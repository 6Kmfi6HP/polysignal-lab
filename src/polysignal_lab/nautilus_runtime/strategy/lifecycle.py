from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
import logging
import os
from typing import Any, Protocol, cast

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market
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
    polymarket_data_client_id,
    polymarket_rtds_data_client_id,
)
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    MarketSubscriptionState,
    _flush_pending_book_restores,  # pyright: ignore[reportPrivateUsage]
    force_resubscribe_if_book_stalled,
    force_resubscribe_if_stale_orderbook,
    force_resubscribe_if_stale_receipt,
    observe_market_book_side,
    _subscribe_suppressed,  # pyright: ignore[reportPrivateUsage]
    _ready_receipt_stalled,  # pyright: ignore[reportPrivateUsage]
    pending_condition_instrument_ids,
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
    def request_instruments(
        self,
        venue: object,
        client_id: object | None = None,
    ) -> object: ...
    def subscribe_instruments(
        self,
        venue: object,
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
    def _refresh_asset_conditions(self) -> None: ...
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
        _ = force_resubscribe_if_stale_receipt(
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
_ADAPTER_REFRESH_INTERVAL = timedelta(seconds=300)
# Once a condition's recovery marker has already consumed dispatch attempts and
# remains no-book/stale, re-drive the adapter instrument load every two minutes
# instead of every five. This is not a per-condition wire retry; it is the same
# non-destructive venue/client instrument load, so the process-global single-
# flight gate still bounds it. Only explicit recovery attempts/cached generation
# timeouts drive the shorter cadence.
_ADAPTER_REFRESH_TIMEOUT_INTERVAL = timedelta(seconds=120)
# Per-data-client adapter refresh gate bucketed by ``client_id`` (one client per
# timeframe). Every strategy shares one Polymarket data client per timeframe, so
# a fleet-wide refresh burst is still bounded to one load per window, but 5m and
# 15m each get their own bucket: a 15m rotation must never be suppressed because
# the 5m client refreshed moments ago, and vice versa. A failed refresh does not
# consume its bucket so the next heartbeat can retry immediately. The dispatch
# itself is non-destructive (see _refresh_venue_instrument_subscriptions): it
# never unsubscribes the shared venue/client instrument topic.
_ADAPTER_REFRESH_AT_BY_CLIENT: dict[str, datetime] = {}


def _discover_in_scope_markets(
    registry: MarketCatalog,
    assets: frozenset[str],
    timeframes: frozenset[str],
) -> list[Market]:
    """Gamma discovery → registry updates → in-scope markets."""
    from polysignal_lab.config import load_settings
    from polysignal_lab.data.polymarket_market_discovery import MarketDiscovery

    settings = load_settings()
    markets = MarketDiscovery(
        settings.data.polymarket,
        settings.markets,
    ).discover_sync(include_next_periods=1, max_event_pages=2)
    in_scope: list[Market] = []
    for market in markets:
        asset = str(getattr(market, "asset", "")).upper()
        timeframe = str(getattr(market, "timeframe", "")).lower()
        if asset not in assets or timeframe not in timeframes:
            continue
        # Always (re-)register: Gamma may return an updated end_ts for a known
        # condition (e.g. the market just closed). Without re-registration the
        # registry keeps the stale end_ts from the initial registration, so
        # retire_expired_condition can never fire and the condition stays in
        # the active set forever (issue69 signal stall).
        try:
            registry.register(MarketPairMeta.from_market(market))
        except (ValueError, TypeError):
            continue
        # Collect every in-scope market, not just newly registered ones: the
        # strategy's startup condition set is empty (registration delegates the
        # active set to universe events, and the rotation actor's timers do not
        # fire under poll()), so without this the fleet never subscribes.
        in_scope.append(market)
    return in_scope


def _discover_new_conditions(
    registry: MarketCatalog,
    assets: frozenset[str],
    timeframes: frozenset[str],
) -> list[str]:
    """Compatibility wrapper: Gamma discovery → new condition ids."""
    return [
        market.condition_id
        for market in _discover_in_scope_markets(registry, assets, timeframes)
    ]


def _polymarket_venue() -> object | None:
    from polysignal_lab.nautilus_runtime.optional_imports import load_nautilus_module

    venue_cls = getattr(
        load_nautilus_module("nautilus_trader.core.nautilus_pyo3"),
        "Venue",
        None,
    )
    return None if venue_cls is None else venue_cls.from_str("POLYMARKET")


def _pending_instrument_count(strategy: _LifecycleStrategy) -> int:
    """Count unresolved instruments across active conditions."""
    return sum(
        len(pending_condition_instrument_ids(strategy, condition_id))
        for condition_id in strategy._active_condition_ids
    )


def _request_instrument_refresh(
    strategy: _LifecycleStrategy,
    *,
    now: datetime | None = None,
) -> int:
    """Re-drive each due data client's instrument load for POLYMARKET.

    issue69: the adapter only loads startup ``load_ids``, so slot instruments
    that rotate in later never load and their wire subscriptions never land.
    The gate is bucketed per data client (client_id == timeframe) and a failed
    dispatch does not consume its bucket. Returns clients refreshed.
    """
    request = getattr(strategy, "request_instruments", None)
    venue = _polymarket_venue()
    if not callable(request) or venue is None:
        return 0
    current = now if now is not None else framework_now(strategy)
    return sum(
        _refresh_due_instrument_client(
            strategy,
            venue,
            timeframe=timeframe,
            current=current,
        )
        for timeframe in getattr(strategy, "_subscription_timeframes", frozenset())
    )


def _refresh_due_instrument_client(
    strategy: _LifecycleStrategy,
    venue: object,
    *,
    timeframe: str,
    current: datetime,
) -> bool:
    """Refresh one client when its per-client throttle allows."""
    client_id = polymarket_data_client_id(timeframe)
    client_key = str(client_id)
    last_refresh = _ADAPTER_REFRESH_AT_BY_CLIENT.get(client_key)
    if (
        last_refresh is not None
        and current - last_refresh < _ADAPTER_REFRESH_INTERVAL
    ):
        return False
    pending = _pending_instrument_count(strategy)
    if not _refresh_venue_instrument_subscriptions(
        strategy, venue, timeframe=timeframe, client_id=client_id
    ):
        logger.info(
            "adapter_instrument_refresh_failed",
            extra={
                "client_id": client_key,
                "timeframe": timeframe,
                "pending_instrument_count": pending,
                "last_request_at": (
                    None
                    if _ADAPTER_REFRESH_AT_BY_CLIENT.get(client_key) is None
                    else _ADAPTER_REFRESH_AT_BY_CLIENT[client_key].isoformat()
                ),
            },
        )
        return False
    _ADAPTER_REFRESH_AT_BY_CLIENT[client_key] = current
    strategy._last_adapter_refresh_at = current  # pyright: ignore[reportAttributeAccessIssue]
    logger.info(
        "adapter_instrument_refresh_requested",
        extra={
            "client_id": client_key,
            "timeframe": timeframe,
            "pending_instrument_count": pending,
        },
    )
    return True


def _refresh_venue_instrument_subscriptions(
    strategy: _LifecycleStrategy,
    venue: object,
    *,
    timeframe: str,
    client_id: object,
) -> bool:
    """Non-destructive per-client instrument refresh (issue69 shared client).

    The Polymarket data client for a timeframe is shared by every strategy
    and by the MarketRotationActor, so a venue/client-wide
    ``unsubscribe_instruments`` dispatched from one strategy would decrement
    the shared instrument-topic refcount and, once the last subscriber
    leaves, tear down instrument delivery for the whole fleet (and reset the
    adapter's load state). The refresh is therefore strictly additive: it
    (re-)affirms the strategy's venue instrument subscription (idempotent,
    refcounted) and re-drives the provider load with ``request_instruments``
    so instruments that rotated in beyond the startup ``load_ids`` load and
    their wire subscriptions land. Nothing here removes a shared
    subscription, and per-instrument teardown stays on the strategy's own
    instrument keys.
    """
    subscribe = getattr(strategy, "subscribe_instruments", None)
    request = getattr(strategy, "request_instruments", None)
    if callable(subscribe):
        try:
            _ = subscribe(venue, client_id=client_id)
        except Exception:
            logger.debug(
                "instrument subscription refresh failed for %s",
                timeframe,
                exc_info=True,
            )
    if not callable(request):
        return False
    try:
        _ = request(venue, client_id=client_id)
    except Exception:
        logger.debug("instrument refresh failed for %s", timeframe, exc_info=True)
        return False
    return True


def _discover_and_subscribe_new_markets(
    strategy: _LifecycleStrategy,
    *,
    now: datetime,
) -> None:
    """Discover current markets, subscribe new conditions, backfill resolution."""
    if os.environ.get("POLYSIGNAL_MARKET_DISCOVERY") != "1":
        return
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
        markets = _discover_in_scope_markets(registry, assets, timeframes)
    except Exception:
        logger.warning(
            "market_discovery_error",
            extra={
                "strategy": getattr(strategy, "strategy_name", None),
            },
            exc_info=True,
        )
        return
    new_conditions = [market.condition_id for market in markets]
    if not new_conditions:
        _log_market_discovery_empty(strategy)
        return
    attached = _attach_discovered_conditions(strategy, new_conditions, now=now)
    _log_market_discovery_run(
        strategy,
        attached,
        new_conditions,
        assets,
        timeframes,
    )


def _log_market_discovery_empty(strategy: _LifecycleStrategy) -> None:
    logger.info(
        "market_discovery_empty",
        extra={"strategy": getattr(strategy, "strategy_name", None)},
    )


def _log_market_discovery_run(
    strategy: _LifecycleStrategy,
    attached: int,
    new_conditions: Sequence[str],
    assets: frozenset[str],
    timeframes: frozenset[str],
) -> None:
    logger.info(
        "market_discovery_run strategy=%s new=%d candidates=%d conditions=%s assets=%s tfs=%s",
        getattr(strategy, "strategy_name", None),
        attached,
        len(new_conditions),
        new_conditions[:5],
        sorted(assets),
        sorted(timeframes),
    )


def _attach_discovered_conditions(
    strategy: _LifecycleStrategy,
    new_conditions: Sequence[str],
    *,
    now: datetime,
) -> int:
    """Attach only conditions missing from the active set.

    Discovery may return all in-scope markets for metadata refresh, but active
    conditions are already wired; re-subscribing them every 30s adds adapter
    request pressure and can contribute to slow-consumer closes.
    """
    # A no-book-abandoned condition stays suppressed for _NO_BOOK_SUPPRESS_SEC:
    # discovery still refreshes its registry metadata (so end_ts/retire stay
    # correct) but must NOT re-add it to the active set — adding it while the
    # suppression marker is fresh would recreate the active-but-unsubscribed
    # wedge where the heartbeat re-subscribes nothing and readiness misses
    # forever. Once the window elapses _subscribe_suppressed() drops the
    # marker and the same discovery round attaches it normally.
    suppressed = tuple(
        condition_id
        for condition_id in new_conditions
        if _subscribe_suppressed(strategy, condition_id, now=now)
    )
    attach_candidates = tuple(
        condition_id
        for condition_id in new_conditions
        if condition_id not in suppressed
    )
    subscribe_conditions = tuple(
        condition_id
        for condition_id in attach_candidates
        if condition_id not in strategy._active_condition_ids
    )
    strategy._active_condition_ids.update(attach_candidates)
    strategy._refresh_asset_conditions()
    if subscribe_conditions:
        strategy._subscribe_market_conditions(subscribe_conditions)
        # New slots rotate in beyond the startup load_ids; drive the adapter
        # instrument load so their wire subscriptions actually land. The
        # per-client gate bounds a fleet-wide refresh burst to one load per
        # data client per window.
        _request_instrument_refresh(strategy)
    if suppressed:
        _log_attach_suppressed(strategy, suppressed)
    return len(subscribe_conditions)


def _log_attach_suppressed(
    strategy: _LifecycleStrategy,
    suppressed: tuple[str, ...],
) -> None:
    logger.info(
        "discovery_attach_suppressed",
        extra={
            "strategy": getattr(strategy, "strategy_name", None),
            "suppressed_count": len(suppressed),
            "condition_ids": list(suppressed),
        },
    )


def _data_stall_refresh_due(strategy: _LifecycleStrategy, *, now: datetime) -> bool:
    """True when a book-stall is detected and the adapter refresh is not
    throttled: some condition is awaiting its first book or under stale-book
    recovery while the venue silently stopped pushing — the reconnect restore
    list carries resolved markets, so only re-driving the adapter instrument
    load rebuilds the wire subscriptions for the current window set.
    """
    state = getattr(strategy, "_subscription_state", None)
    if state is None:
        return False
    awaiting = getattr(state, "awaiting_book_sides_by_condition", None)
    stale = getattr(strategy, "_stale_orderbook_recovery_by_condition", None)
    if not awaiting and not stale:
        return False
    timed_out = any(
        state.book_recovery_attempt_count_by_condition.get(condition_id, 0) > 0
        and state.adapter_replay_started_at_by_condition.get(condition_id) is not None
        for condition_id in set(awaiting or ()) | set(stale or ())
    )
    refresh_interval = (
        _ADAPTER_REFRESH_TIMEOUT_INTERVAL
        if timed_out
        else _ADAPTER_REFRESH_INTERVAL
    )
    for timeframe in getattr(strategy, "_subscription_timeframes", frozenset()):
        client_key = str(polymarket_data_client_id(timeframe))
        last_refresh = _ADAPTER_REFRESH_AT_BY_CLIENT.get(client_key)
        if (
            last_refresh is None
            or now - last_refresh >= refresh_interval
        ):
            # At least one data client is due for a fresh load.
            return True
    return False


def _ready_condition_stalled(
    strategy: _LifecycleStrategy,
    condition_id: str,
    *,
    now: datetime,
) -> bool:
    return _ready_receipt_stalled(
        strategy,  # pyright: ignore[reportArgumentType]
        condition_id,
        now=now,
    )


def _reconcile_open_positions(
    strategy: _LifecycleStrategy,
    *,
    now: datetime,
) -> None:
    # Local import avoids the native_strategy <-> lifecycle <-> strategy
    # package import cycle on basedpyright's symbol map.
    from polysignal_lab.nautilus_runtime.strategy import resolution_settlement

    resolution_settlement.resolve_open_positions(
        cast(Any, strategy),
        now=now,
    )


def on_evaluation_heartbeat(strategy: _LifecycleStrategy, _event: object) -> None:
    now = framework_now(strategy)
    active_condition_ids = _active_unexpired_condition_ids(strategy, now=now)
    if not active_condition_ids:
        logger.info(
            "evaluation_heartbeat_no_active_conditions",
            extra={"strategy": getattr(strategy, "strategy_name", None)},
        )
    strategy._note_runtime_progress(
        "evaluation_heartbeat",
        active_condition_ids=active_condition_ids,
    )
    # Self-sufficient market rotation first: nautilus 1.231 actor timers do not
    # fire under poll(), so without this the active set never gains new windows.
    _discover_and_subscribe_new_markets(strategy, now=now)
    # Resolution reporting is final source of truth and must not depend on
    # active discovery: closed markets are no longer active and historical
    # condition ids may already be absent from the registry.
    _reconcile_open_positions(strategy, now=now)
    # Phase 2 of any deferred refresh: restore drains from a prior turn so the
    # DataEngine had a chance to tear down the old wire subscription before the
    # re-subscribe is enqueued (issue69: same-turn drain+restore is a wire
    # no-op; splitting the turns makes Polymarket re-push the initial snapshot).
    _flush_pending_book_restores(strategy, now=now)  # pyright: ignore[reportArgumentType]
    strategy._subscribe_market_conditions(active_condition_ids)
    _reconcile_awaiting_books_from_cache(strategy, active_condition_ids, now=now)
    if _data_stall_refresh_due(strategy, now=now):
        # Venue silently stopped pushing (reconnect restore list carries
        # resolved markets); re-drive the adapter instrument load to rebuild
        # the wire subscriptions from the current window set.
        _ = _request_instrument_refresh(strategy, now=now)
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
