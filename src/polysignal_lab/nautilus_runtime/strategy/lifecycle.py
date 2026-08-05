from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
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
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.polymarket_clients import (
    polymarket_rtds_data_client_id,
)
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    MarketSubscriptionState,
    force_resubscribe_if_book_stalled,
    force_resubscribe_if_stale_orderbook,
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
    def _note_runtime_progress(self, phase: str) -> None: ...
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


def _global_book_recovery_is_suppressed(
    state: MarketSubscriptionState,
    condition_ids: Sequence[str],
) -> bool:
    # A receipt from one outcome token does not prove that a silent feed has
    # recovered. The timestamp marker is removed only after both sides have
    # receipts newer than the global recovery batch. While it remains active,
    # never-READY conditions retain their abandon clock without adding more
    # per-condition wire churn to the same feed-wide outage.
    once_ready_condition_ids = tuple(
        condition_id
        for condition_id in condition_ids
        if condition_id in state.first_bilateral_book_ever_at_by_condition
    )
    condition_batch_active = bool(once_ready_condition_ids) and all(
        condition_id in state.global_book_recovery_started_at_by_condition
        for condition_id in once_ready_condition_ids
    )
    return state.global_feed_outage_started_at is not None or condition_batch_active


def _condition_has_post_marker_partial_recovery(
    state: MarketSubscriptionState,
    condition_id: str,
) -> bool:
    started_at = state.global_book_recovery_started_at_by_condition.get(condition_id)
    awaiting = state.awaiting_book_sides_by_condition.get(condition_id)
    if started_at is None or awaiting is None or len(awaiting) != 1:
        return False
    receipts = state.last_book_received_at_by_condition.get(condition_id, {})
    return any(
        side not in awaiting
        and (received_at := receipts.get(side)) is not None
        and received_at > started_at
        for side in (Side.UP, Side.DOWN)
    )


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


def _begin_global_book_recovery_if_stalled(
    state: MarketSubscriptionState,
    condition_ids: Sequence[str],
    *,
    now: datetime,
) -> None:
    once_ready_condition_ids = tuple(
        condition_id
        for condition_id in condition_ids
        if condition_id in state.first_bilateral_book_ever_at_by_condition
    )
    if (
        not once_ready_condition_ids
        or not all(
            state.awaiting_book_sides_by_condition.get(condition_id)
            == {Side.UP, Side.DOWN}
            for condition_id in once_ready_condition_ids
        )
    ):
        return
    observed = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    state.global_feed_outage_started_at = (
        state.global_feed_outage_started_at or observed.astimezone(UTC)
    )
    # Keep the original batch boundary for conditions still awaiting recovery
    for condition_id in once_ready_condition_ids:
        state.global_book_recovery_started_at_by_condition.setdefault(
            condition_id,
            observed.astimezone(UTC),
        )


def _recover_book_subscriptions(
    strategy: _LifecycleStrategy,
    condition_ids: Sequence[str],
    *,
    now: datetime,
) -> None:
    state = strategy._subscription_state
    global_book_recovery_suppressed = _global_book_recovery_is_suppressed(
        state,
        condition_ids,
    )
    for condition_id in condition_ids:
        if (
            not global_book_recovery_suppressed
            or _condition_has_post_marker_partial_recovery(state, condition_id)
        ):
            _ = force_resubscribe_if_book_stalled(
                strategy,  # pyright: ignore[reportArgumentType]
                condition_id,
                now=now,
            )
        else:
            _ = force_resubscribe_if_book_stalled(
                strategy,  # pyright: ignore[reportArgumentType]
                condition_id,
                now=now,
                allow_wire_retry=False,
            )
        _ = force_resubscribe_if_stale_orderbook(
            strategy,  # pyright: ignore[reportArgumentType]
            condition_id,
            now=now,
        )
    _begin_global_book_recovery_if_stalled(
        strategy._subscription_state,
        condition_ids,
        now=now,
    )


def on_evaluation_heartbeat(strategy: _LifecycleStrategy, _event: object) -> None:
    strategy._note_runtime_progress("evaluation_heartbeat")
    now = framework_now(strategy)
    active_condition_ids = _active_unexpired_condition_ids(strategy, now=now)
    strategy._subscribe_market_conditions(active_condition_ids)
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
