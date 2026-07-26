from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

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
    assembler: object
    cache: object | None

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
    startup_condition_ids = tuple(strategy._startup_condition_ids)  # pyright: ignore[reportPrivateUsage]
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
    if not strategy._subscriptions_started:
        return
    tracked_condition_ids = tuple(
        dict.fromkeys(
            (
                *strategy._startup_condition_ids,
                *strategy._active_condition_ids,
                *strategy._subscription_state.subscribe_intent_condition_ids,
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


def on_evaluation_heartbeat(strategy: _LifecycleStrategy, _event: object) -> None:
    strategy._note_runtime_progress("evaluation_heartbeat")
    now = framework_now(strategy)
    registry = strategy._require_registry()
    trading_state = trading_state_from_cache(
        strategy.cache,
        strategy_id=getattr(strategy, "strategy_id", None)
        or getattr(strategy, "id", None),
        registry=registry,
    )
    for condition_id in tuple(sorted(strategy._active_condition_ids)):
        if retire_expired_condition(strategy, condition_id, now=now):  # type: ignore[arg-type]
            continue
        last_eval = strategy._last_market_data_evaluation_at.get(condition_id)
        if last_eval is not None and now - last_eval < EVALUATION_HEARTBEAT_INTERVAL:
            continue
        strategy.evaluate_condition(condition_id, trading_state=trading_state)
