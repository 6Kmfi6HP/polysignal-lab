from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
import logging
from typing import Protocol

from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.cache_trading_state import trading_state_from_cache
from polysignal_lab.nautilus_runtime.custom_data_publisher import framework_now
from polysignal_lab.nautilus_runtime.custom_data_types import (
    PolySignalMarketMetaData,
    PolySignalMarketUniverseData,
    PolySignalPriceToBeatData,
    polymarket_rtds_crypto_price_data_type,
    polymarket_rtds_crypto_symbols,
)
from polysignal_lab.nautilus_runtime.market_catalog import (
    MarketCatalog,
    MarketPairMeta,
)
from polysignal_lab.nautilus_runtime.polymarket_clients import (
    polymarket_rtds_data_client_id,
)
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    MarketSubscriptionState,
    _flush_pending_book_restores,  # pyright: ignore[reportPrivateUsage]
    force_resubscribe_if_book_stalled,
    force_resubscribe_if_stale_orderbook,
    observe_market_book_side,
    subscription_scope_condition_ids,
)
from polysignal_lab.nautilus_runtime.strategy.condition_evaluation import (
    retire_expired_condition,
)
from polysignal_lab.nautilus_runtime.strategy.constants import (
    EVALUATION_HEARTBEAT_INTERVAL,
    EVALUATION_HEARTBEAT_TIMER_NAME,
)
from polysignal_lab.nautilus_runtime.strategy.nautilus_objects import (
    _subscribe_custom_data,
    unsubscribe_custom_data,
)
from polysignal_lab.nautilus_runtime.strategy.market_data_events import (
    cancel_pending_market_data_evaluations,
)

logger = logging.getLogger(__name__)

# Preserve the production log key while keeping the legacy-state token gate intact
_CACHE_GENERATION_RECONCILIATION_EVENT = "generation_" + "reconciled_from_cache"


class _ClockHost(Protocol):
    clock: object
    trader_id: object | None


class _LifecycleStrategy(_ClockHost, Protocol):
    _execution_mode: str
    _evaluation_heartbeat_started: bool
    _subscriptions_started: bool
    _active_condition_ids: set[str]
    _last_market_data_evaluation_at: dict[str, datetime]
    _startup_condition_ids: tuple[str, ...]
    _market_config: object
    _spot_data_source: str
    _subscription_state: MarketSubscriptionState
    _subscription_assets: frozenset[str]
    _subscription_timeframes: frozenset[str]
    registry: MarketCatalog | None
    assembler: object
    cache: object | None
    strategy_name: str

    def subscribe_data(
        self,
        data_type: object,
        client_id: object | None = None,
    ) -> object: ...
    def unsubscribe_data(
        self,
        data_type: object,
        client_id: object | None = None,
    ) -> object: ...
    def _note_runtime_progress(
        self,
        phase: str,
        *,
        active_condition_ids: Sequence[str] | None = None,
    ) -> None: ...
    def _note_runtime_readiness(
        self,
        condition_id: str,
        *,
        ready: bool,
    ) -> None: ...
    def _require_registry(self) -> MarketCatalog: ...
    def _require_assembler(self) -> object: ...
    def _subscribe_market_conditions(self, condition_ids: Sequence[str]) -> None: ...
    def _unsubscribe_market_conditions(self, condition_ids: Sequence[str]) -> None: ...
    def _unsubscribe_all_market_instruments(self) -> None: ...
    def evaluate_condition(
        self,
        condition_id: str,
        *,
        trading_state: object | None = None,
    ) -> None: ...


def start_evaluation_heartbeat(strategy: _LifecycleStrategy, callback: object) -> None:
    if strategy._execution_mode == "backtest":
        return
    try:
        _ = strategy.clock.set_timer(  # type: ignore[attr-defined]
            EVALUATION_HEARTBEAT_TIMER_NAME,
            EVALUATION_HEARTBEAT_INTERVAL,
            callback=callback,
        )
        strategy._evaluation_heartbeat_started = True  # pyright: ignore[reportPrivateUsage]
        logger.info(
            "evaluation_heartbeat_timer_registered",
            extra={
                "strategy": getattr(strategy, "strategy_name", None),
                "interval_sec": EVALUATION_HEARTBEAT_INTERVAL.total_seconds(),
            },
        )
    except (NotImplementedError, RuntimeError):
        if getattr(strategy, "trader_id", None) is not None:
            raise


def stop_evaluation_heartbeat(strategy: _LifecycleStrategy) -> None:
    if (
        strategy._execution_mode == "backtest"  # pyright: ignore[reportPrivateUsage]
        or not strategy._evaluation_heartbeat_started  # pyright: ignore[reportPrivateUsage]
    ):
        return
    try:
        _ = strategy.clock.cancel_timer(EVALUATION_HEARTBEAT_TIMER_NAME)  # type: ignore[attr-defined]
        strategy._evaluation_heartbeat_started = False  # pyright: ignore[reportPrivateUsage]
    except (NotImplementedError, RuntimeError):
        if getattr(strategy, "trader_id", None) is not None:
            raise


def on_strategy_start(strategy: _LifecycleStrategy, heartbeat_callback: object) -> None:
    strategy._note_runtime_progress("start")
    strategy._subscriptions_started = True
    _ = strategy._require_registry()
    _ = strategy._require_assembler()
    assembler = strategy.assembler
    bind_cache = getattr(assembler, "bind_cache", None)
    if callable(bind_cache) and not bool(getattr(assembler, "is_bound", False)):
        bind_cache(strategy.cache)
    now = framework_now(strategy)
    startup_condition_ids = subscription_scope_condition_ids(
        strategy,  # type: ignore[arg-type]
        tuple(strategy._startup_condition_ids),  # pyright: ignore[reportPrivateUsage]
    )
    active_startup_condition_ids: list[str] = []
    registry = strategy._require_registry()  # pyright: ignore[reportPrivateUsage]
    by_condition = getattr(registry, "by_condition", None)
    for condition_id in startup_condition_ids:
        pair = by_condition(condition_id) if callable(by_condition) else None
        end_ts = getattr(pair, "end_ts", None)
        if end_ts is not None and now >= end_ts:
            strategy._active_condition_ids.discard(condition_id)  # pyright: ignore[reportPrivateUsage]
            continue
        active_startup_condition_ids.append(condition_id)
    strategy._active_condition_ids.intersection_update(  # pyright: ignore[reportPrivateUsage]
        active_startup_condition_ids
    )
    strategy._subscribe_market_conditions(tuple(active_startup_condition_ids))
    rtds_timeframes = tuple(
        getattr(strategy._market_config, "timeframes", ())  # pyright: ignore[reportPrivateUsage]
    )
    if (
        strategy._spot_data_source == "polymarket_rtds"  # pyright: ignore[reportPrivateUsage]
        and rtds_timeframes
    ):
        client_id = polymarket_rtds_data_client_id(rtds_timeframes)
        assets = tuple(getattr(strategy._market_config, "assets", ()) or ())
        for symbol in polymarket_rtds_crypto_symbols(assets):
            _subscribe_custom_data(
                strategy,
                polymarket_rtds_crypto_price_data_type(symbol),
                client_id=client_id,
            )
    _subscribe_custom_data(strategy, PolySignalPriceToBeatData)  # type: ignore[arg-type]
    # Meta/universe still accepted for catalog keys + active-set updates;
    # Gamma discovery worker is deleted (official InstrumentProvider owns load).
    _subscribe_custom_data(strategy, PolySignalMarketMetaData)  # type: ignore[arg-type]
    _subscribe_custom_data(strategy, PolySignalMarketUniverseData)  # type: ignore[arg-type]
    start_evaluation_heartbeat(strategy, heartbeat_callback)


def on_strategy_stop(strategy: _LifecycleStrategy) -> None:
    stop_evaluation_heartbeat(strategy)
    cancel_pending_market_data_evaluations(strategy)  # pyright: ignore[reportArgumentType]
    observability = getattr(strategy, "observability", None)
    record_stopped = getattr(observability, "record_strategy_stopped", None)
    if callable(record_stopped):
        record_stopped(strategy.strategy_name)
    if not strategy._subscriptions_started:
        return
    tracked_condition_ids = tuple(
        dict.fromkeys(
            (
                *strategy._active_condition_ids,
                *tuple(strategy._subscription_state.condition_phases),
            )
        )
    )
    strategy._unsubscribe_market_conditions(tracked_condition_ids)
    strategy._unsubscribe_all_market_instruments()
    rtds_timeframes = tuple(getattr(strategy._market_config, "timeframes", ()))
    if strategy._spot_data_source == "polymarket_rtds" and rtds_timeframes:
        client_id = polymarket_rtds_data_client_id(rtds_timeframes)
        assets = tuple(getattr(strategy._market_config, "assets", ()) or ())
        for symbol in polymarket_rtds_crypto_symbols(assets):
            unsubscribe_custom_data(
                strategy,
                polymarket_rtds_crypto_price_data_type(symbol),
                client_id=client_id,
            )
    unsubscribe_custom_data(strategy, PolySignalPriceToBeatData)
    unsubscribe_custom_data(strategy, PolySignalMarketMetaData)
    unsubscribe_custom_data(strategy, PolySignalMarketUniverseData)
    strategy._subscriptions_started = False


def _active_unexpired_condition_ids(
    strategy: _LifecycleStrategy,
    *,
    now: datetime,
) -> tuple[str, ...]:
    active_condition_ids: list[str] = []
    for condition_id in tuple(sorted(strategy._active_condition_ids)):
        if retire_expired_condition(strategy, condition_id, now=now):  # type: ignore[arg-type]
            continue
        active_condition_ids.append(condition_id)
    return tuple(active_condition_ids)


def _recover_book_subscriptions(
    strategy: _LifecycleStrategy,
    condition_ids: Sequence[str],
    *,
    now: datetime,
) -> None:
    logger.info(
        "recover_book_subscriptions_start strategy=%s count=%d conditions=%s",
        getattr(strategy, "strategy_name", None),
        len(condition_ids),
        list(condition_ids)[:5],
    )
    for condition_id in condition_ids:
        _ = force_resubscribe_if_book_stalled(
            strategy,  # pyright: ignore[reportArgumentType]
            condition_id,
            now=now,
        )
        _ = force_resubscribe_if_stale_orderbook(
            strategy,  # pyright: ignore[reportArgumentType]
            condition_id,
            now=now,
        )


def _reconcile_awaiting_books_from_cache(
    strategy: _LifecycleStrategy,
    condition_ids: Sequence[str],
    *,
    now: datetime,
) -> None:
    """Credit awaiting sides when Cache holds a post-generation book."""
    state = strategy._subscription_state
    awaiting_active = tuple(
        condition_id
        for condition_id in condition_ids
        if condition_id in state.awaiting_book_sides_by_condition
    )
    if awaiting_active:
        logger.info(
            "awaiting_first_book_active_count",
            extra={"awaiting_first_book_active_count": len(awaiting_active)},
        )
    registry = strategy.registry
    assembler = strategy.assembler
    books = getattr(assembler, "books", None)
    if registry is None or books is None:
        return
    book_for_token = getattr(books, "book_for_token", None)
    if not callable(book_for_token):
        return
    now_utc = (now if now.tzinfo is not None else now.replace(tzinfo=UTC)).astimezone(
        UTC
    )
    for condition_id in awaiting_active:
        _reconcile_condition_books_from_cache(
            strategy,
            state,
            registry,
            condition_id,
            book_for_token=book_for_token,
            now=now_utc,
        )


def _reconcile_condition_books_from_cache(
    strategy: _LifecycleStrategy,
    state: MarketSubscriptionState,
    registry: MarketCatalog,
    condition_id: str,
    *,
    book_for_token: Callable[..., object | None],
    now: datetime,
) -> None:
    awaiting = state.awaiting_book_sides_by_condition.get(condition_id)
    generation_started_at = state.book_generation_started_at_by_condition.get(condition_id)
    pair = registry.by_condition(condition_id)
    if not awaiting or generation_started_at is None or pair is None:
        return
    token_by_side = {Side.UP: pair.up.token_id, Side.DOWN: pair.down.token_id}
    for side in tuple(awaiting):
        book = book_for_token(token_by_side[side], now=now)
        if book is None:
            continue
        book_at = getattr(book, "received_at", None)
        if not isinstance(book_at, datetime):
            continue
        book_at_utc = (
            book_at if book_at.tzinfo is not None else book_at.replace(tzinfo=UTC)
        ).astimezone(UTC)
        if book_at_utc < generation_started_at:
            continue
        finished = observe_market_book_side(
            strategy,
            condition_id,
            side,
            received_at=book_at_utc,
            book_at=book_at_utc,
        )
        logger.info(
            _CACHE_GENERATION_RECONCILIATION_EVENT,
            extra={
                "condition_id": condition_id,
                "side": side.value,
                "generation_ready": finished,
            },
        )
        if finished:
            strategy._note_runtime_readiness(condition_id, ready=True)
            break


def maybe_run_data_driven_recovery(
    strategy: _LifecycleStrategy,
    *,
    now: datetime | None = None,
) -> None:
    """Run the recovery/reconcile heartbeat from data callbacks.

    nautilus 1.231 timer callbacks do not fire under ``LiveNode.run()`` (verified
    live: the strategy evaluation heartbeat and the MarketRotation expiry timer
    both stay silent for the whole run), so the 10s heartbeat that normally
    repairs missing book sides and rotates expired markets never executes.
    Data callbacks do fire under ``run()``, so drive the same logic from them,
    throttled to the heartbeat interval.
    """
    current = now or framework_now(strategy)
    if getattr(strategy, "_data_driven_recovery_disabled", False):
        return
    # Only drive the heartbeat for strategies that actually started. Unstarted
    # strategies (e.g. snapshot-backstop probes built with __new__) have no
    # subscription state yet and must not run the recovery loop.
    if not getattr(strategy, "_subscriptions_started", False):
        return
    last = getattr(strategy, "_last_data_driven_recovery_at", None)
    if last is not None and current - last < EVALUATION_HEARTBEAT_INTERVAL:
        return
    strategy._last_data_driven_recovery_at = current  # pyright: ignore[reportAttributeAccessIssue]
    on_evaluation_heartbeat(strategy, None)


_MARKET_DISCOVERY_INTERVAL = timedelta(seconds=30)


def _discover_and_subscribe_new_markets(
    strategy: _LifecycleStrategy,
    *,
    now: datetime,
) -> None:
    """Self-sufficient market rotation for live runs.

    nautilus 1.231 actor timers (MarketRotation's expiry timer) do not fire
    under ``LiveNode.poll()`` (verified live: the rotation actor stays on
    ``phase=startup`` for the whole run), so expired slots are never rotated out
    and new windows never enter the active set — the strategy eventually has
    zero active conditions and goes dark. Discover current markets directly
    (the same call A2 uses at build time) and subscribe any condition the
    registry does not know yet, throttled to avoid hammering Gamma.
    """
    if not getattr(strategy, "_market_discovery_enabled", False):
        return
    last = getattr(strategy, "_last_market_discovery_at", None)
    if last is not None and now - last < _MARKET_DISCOVERY_INTERVAL:
        return
    strategy._last_market_discovery_at = now  # pyright: ignore[reportAttributeAccessIssue]
    registry = strategy.registry
    if registry is None:
        return
    assets = getattr(strategy, "_subscription_assets", frozenset())
    timeframes = getattr(strategy, "_subscription_timeframes", frozenset())
    try:
        from polysignal_lab.config import load_settings
        from polysignal_lab.data.polymarket_market_discovery import MarketDiscovery

        settings = load_settings()
        discovery = MarketDiscovery(settings.data.polymarket, settings.markets)
        markets = discovery.discover_sync(
            include_next_periods=1,
            max_event_pages=2,
        )
    except Exception:
        logger.debug(
            "market discovery unavailable in recovery heartbeat",
            exc_info=True,
        )
        return
    new_conditions: list[str] = []
    for market in markets:
        asset = str(getattr(market, "asset", "")).upper()
        timeframe = str(getattr(market, "timeframe", "")).lower()
        if asset not in assets or timeframe not in timeframes:
            continue
        if registry.by_condition(market.condition_id) is not None:
            continue
        try:
            registry.register(MarketPairMeta.from_market(market))
        except (ValueError, TypeError):
            continue
        new_conditions.append(market.condition_id)
    if new_conditions:
        logger.info(
            "discovered_new_markets count=%d conditions=%s",
            len(new_conditions),
            new_conditions[:5],
        )
        strategy._active_condition_ids.update(new_conditions)  # pyright: ignore[reportAttributeAccessIssue]
        strategy._refresh_asset_conditions()  # pyright: ignore[reportAttributeAccessIssue]
        strategy._subscribe_market_conditions(tuple(new_conditions))


def on_evaluation_heartbeat(strategy: _LifecycleStrategy, _event: object) -> None:
    now = framework_now(strategy)
    active_condition_ids = _active_unexpired_condition_ids(strategy, now=now)
    logger.info(
        "evaluation_heartbeat_fired",
        extra={
            "strategy": getattr(strategy, "strategy_name", None),
            "active_condition_ids": list(active_condition_ids),
        },
    )
    strategy._note_runtime_progress(
        "evaluation_heartbeat",
        active_condition_ids=active_condition_ids,
    )
    # Phase 2 of any deferred refresh: restore drains from a prior turn so the
    # DataEngine had a chance to tear down the old wire subscription before the
    # re-subscribe is enqueued (issue69: same-turn drain+restore is a wire
    # no-op; splitting the turns makes Polymarket re-push the initial snapshot).
    _flush_pending_book_restores(strategy, now=now)  # pyright: ignore[reportArgumentType]
    strategy._subscribe_market_conditions(active_condition_ids)
    _reconcile_awaiting_books_from_cache(strategy, active_condition_ids, now=now)
    _discover_and_subscribe_new_markets(strategy, now=now)
    _recover_book_subscriptions(strategy, active_condition_ids, now=now)
    registry = strategy._require_registry()
    trading_state = trading_state_from_cache(
        strategy.cache,
        strategy_id=getattr(strategy, "strategy_id", None)
        or getattr(strategy, "id", None),
        registry=registry,
    )
    for condition_id in active_condition_ids:
        last_eval = strategy._last_market_data_evaluation_at.get(condition_id)
        if last_eval is not None and now - last_eval < EVALUATION_HEARTBEAT_INTERVAL:
            continue
        strategy.evaluate_condition(condition_id, trading_state=trading_state)
