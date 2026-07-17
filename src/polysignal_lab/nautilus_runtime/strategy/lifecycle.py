"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Sequence, datetime, datetime.UTC, datetime.datetime, typing, typing.Protocol, polysignal_lab.nautilus_runtime.custom_data_types
Output: framework_now, start_evaluation_heartbeat, stop_evaluation_heartbeat, on_strategy_start, on_evaluation_heartbeat, _LifecycleStrategy
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol

from polysignal_lab.nautilus_runtime.custom_data_types import (
    PolySignalMarketMetaData,
    PolySignalMarketUniverseData,
    PolySignalPriceToBeatData,
    polymarket_rtds_crypto_price_type,
)
from polysignal_lab.nautilus_runtime.strategy.condition_evaluation import (
    retire_expired_condition,
)
from polysignal_lab.nautilus_runtime.strategy.helpers import (
    EVALUATION_HEARTBEAT_INTERVAL,
    EVALUATION_HEARTBEAT_TIMER_NAME,
    _subscribe_custom_data,
)


class _LifecycleStrategy(Protocol):
    _execution_mode: str
    _active_condition_ids: set[str]
    _last_market_data_evaluation_at: dict[str, datetime]
    _startup_condition_ids: tuple[str, ...]
    assembler: object
    cache: object | None
    clock: object
    trader_id: object | None

    def _note_runtime_progress(self, phase: str) -> None: ...
    def _require_registry(self) -> object: ...
    def _require_assembler(self) -> object: ...
    def _subscribe_market_conditions(self, condition_ids: Sequence[str]) -> None: ...
    def evaluate_condition(self, condition_id: str) -> None: ...


def framework_now(strategy: _LifecycleStrategy) -> datetime:
    try:
        timestamp_ns = getattr(strategy.clock, "timestamp_ns", None)
        if callable(timestamp_ns):
            value = int(timestamp_ns())
            if value >= 0:
                return datetime.fromtimestamp(value / 1_000_000_000, UTC)
    except (NotImplementedError, RuntimeError, AttributeError):
        pass
    if getattr(strategy, "trader_id", None) is None:
        return datetime(1970, 1, 1, tzinfo=UTC)
    raise RuntimeError("Nautilus framework clock timestamp_ns is unavailable")


def start_evaluation_heartbeat(strategy: _LifecycleStrategy, callback: object) -> None:
    if strategy._execution_mode == "backtest":
        return
    try:
        _ = strategy.clock.set_timer(  # type: ignore[attr-defined]
            EVALUATION_HEARTBEAT_TIMER_NAME,
            EVALUATION_HEARTBEAT_INTERVAL,
            callback=callback,
        )
    except (NotImplementedError, RuntimeError):
        if getattr(strategy, "trader_id", None) is not None:
            raise


def stop_evaluation_heartbeat(strategy: _LifecycleStrategy) -> None:
    if strategy._execution_mode == "backtest":
        return
    try:
        _ = strategy.clock.cancel_timer(EVALUATION_HEARTBEAT_TIMER_NAME)  # type: ignore[attr-defined]
    except (NotImplementedError, RuntimeError):
        if getattr(strategy, "trader_id", None) is not None:
            raise


def on_strategy_start(strategy: _LifecycleStrategy, heartbeat_callback: object) -> None:
    strategy._note_runtime_progress("start")
    _ = strategy._require_registry()
    _ = strategy._require_assembler()
    assembler = strategy.assembler
    bind_cache = getattr(assembler, "bind_cache", None)
    if callable(bind_cache) and not bool(getattr(assembler, "is_bound", False)):
        bind_cache(strategy.cache)
    strategy._subscribe_market_conditions(strategy._startup_condition_ids)
    _subscribe_custom_data(strategy, polymarket_rtds_crypto_price_type())  # type: ignore[arg-type]
    _subscribe_custom_data(strategy, PolySignalPriceToBeatData)  # type: ignore[arg-type]
    # Meta/universe still accepted for catalog keys + active-set updates;
    # Gamma discovery worker is deleted (official InstrumentProvider owns load).
    _subscribe_custom_data(strategy, PolySignalMarketMetaData)  # type: ignore[arg-type]
    _subscribe_custom_data(strategy, PolySignalMarketUniverseData)  # type: ignore[arg-type]
    start_evaluation_heartbeat(strategy, heartbeat_callback)


def on_evaluation_heartbeat(strategy: _LifecycleStrategy, _event: object) -> None:
    strategy._note_runtime_progress("evaluation_heartbeat")
    now = framework_now(strategy)
    for condition_id in tuple(sorted(strategy._active_condition_ids)):
        if retire_expired_condition(strategy, condition_id, now=now):  # type: ignore[arg-type]
            continue
        last_eval = strategy._last_market_data_evaluation_at.get(condition_id)
        if last_eval is not None and now - last_eval < EVALUATION_HEARTBEAT_INTERVAL:
            continue
        strategy.evaluate_condition(condition_id)
