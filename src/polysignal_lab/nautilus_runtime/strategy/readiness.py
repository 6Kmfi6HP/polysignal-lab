from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from polysignal_lab.alpha.types import MarketView
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.strategy_readiness import StrategyStatus
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    ConditionSubscriptionPhase,
    MarketSubscriptionState,
    condition_phase,
    pending_condition_instrument_ids,
)


class _ReadinessStrategy(Protocol):
    registry: MarketCatalog | None
    policy: object
    strategy_name: str
    _subscription_state: MarketSubscriptionState
    _runtime_readiness_miss_condition_ids: set[str]
    _runtime_readiness_reason_by_condition: dict[str, str]
    _stale_orderbook_recovery_by_condition: dict[str, dict[Side, float]]
    _untradable_quote_sides_by_condition: dict[str, frozenset[Side]]
    progress_callback: Callable[[str], None] | None
    readiness_callback: Callable[[str, bool, dict[str, object]], None] | None

    def _framework_now(self) -> datetime: ...
    def _require_registry(self) -> MarketCatalog | None: ...


class _UntradableStateOwner(Protocol):
    _untradable_quote_sides_by_condition: dict[str, frozenset[Side]]


def note_runtime_progress(strategy: _ReadinessStrategy, phase: str) -> None:
    callback = strategy.progress_callback
    if callback is None:
        return
    callback(phase)


def note_runtime_readiness(
    strategy: _ReadinessStrategy,
    condition_id: str,
    *,
    ready: bool,
    status: StrategyStatus | None = None,
    reason: str | None = None,
) -> None:
    if ready:
        _ = strategy._runtime_readiness_miss_condition_ids.discard(condition_id)
        _ = strategy._runtime_readiness_reason_by_condition.pop(condition_id, None)
        _ = strategy._stale_orderbook_recovery_by_condition.pop(condition_id, None)
    else:
        strategy._runtime_readiness_miss_condition_ids.add(condition_id)
    _record_strategy_readiness(
        strategy,
        condition_id,
        ready=ready,
        status=status,
        reason=reason,
    )


def _record_strategy_readiness(
    strategy: _ReadinessStrategy,
    condition_id: str,
    *,
    ready: bool,
    status: StrategyStatus | None,
    reason: str | None,
) -> None:
    observability = getattr(strategy, "observability", None)
    record_status = getattr(observability, "record_strategy_status", None)
    record_status_value = getattr(observability, "record_strategy_status_value", None)
    callback = strategy.readiness_callback
    if callback is None and not callable(record_status) and not callable(
        record_status_value
    ):
        return
    now = strategy._framework_now()
    detail = readiness_detail(strategy, condition_id, now=now)
    asset = detail.get("asset")
    timeframe = detail.get("timeframe")
    if isinstance(asset, str) and isinstance(timeframe, str):
        state = detail.get("subscription_state")
        effective_status, effective_reason, explicit_status = _effective_status(
            strategy,
            asset,
            timeframe,
            ready=ready,
            status=status,
            reason=reason,
            readiness_state=state,
        )
        if explicit_status and callable(record_status_value):
            record_status_value(
                strategy=strategy.strategy_name,
                asset=asset,
                timeframe=timeframe,
                status=effective_status,
                reason=effective_reason,
            )
        elif callable(record_status):
            record_status(
                strategy=strategy.strategy_name,
                asset=asset,
                timeframe=timeframe,
                ready=ready,
                reason=effective_reason,
            )
    if callback is not None:
        callback(condition_id, ready, detail)


def _strategy_status_reason(
    ready: bool,
    state: object,
    reason: str | None,
) -> str | None:
    if reason is not None:
        return reason
    return None if ready else str(state or "missing_data")


def _effective_status(
    strategy: _ReadinessStrategy,
    asset: str,
    timeframe: str,
    *,
    ready: bool,
    status: StrategyStatus | None,
    reason: str | None,
    readiness_state: object,
) -> tuple[StrategyStatus, str | None, bool]:
    readiness_miss_reason = (
        _readiness_miss_reason_for_market(strategy, asset, timeframe)
        if ready
        else None
    )
    if readiness_miss_reason is not None:
        return "missing_data", readiness_miss_reason, True
    untradable_reason = (
        _untradable_reason_for_market(strategy, asset, timeframe)
        if ready and status in {None, "untradable"}
        else None
    )
    if untradable_reason is not None:
        return "untradable", untradable_reason, True
    effective_status: StrategyStatus = status or (
        "active" if ready else "missing_data"
    )
    return (
        effective_status,
        _strategy_status_reason(ready, readiness_state, reason),
        status is not None,
    )


def _readiness_miss_reason_for_market(
    strategy: _ReadinessStrategy,
    asset: str,
    timeframe: str,
) -> str | None:
    registry = strategy._require_registry()
    for condition_id in sorted(strategy._runtime_readiness_miss_condition_ids):
        pair = None if registry is None else registry.by_condition(condition_id)
        if pair is None or pair.asset != asset or pair.timeframe != timeframe:
            continue
        return strategy._runtime_readiness_reason_by_condition.get(
            condition_id, "missing_data"
        )
    return None


def _untradable_reason_for_market(
    strategy: _ReadinessStrategy,
    asset: str,
    timeframe: str,
) -> str | None:
    registry = strategy._require_registry()
    missing_sides: set[Side] = set()
    for condition_id, sides in strategy._untradable_quote_sides_by_condition.items():
        pair = None if registry is None else registry.by_condition(condition_id)
        if pair is None or pair.asset != asset or pair.timeframe != timeframe:
            continue
        missing_sides.update(sides)
    if not missing_sides:
        return None
    ordered_sides = (side.value for side in (Side.UP, Side.DOWN) if side in missing_sides)
    return f"missing_quote_depth:{','.join(ordered_sides)}"


def book_readiness_detail(
    state: MarketSubscriptionState,
    condition_id: str,
    *,
    now: datetime,
) -> tuple[
    dict[str, str | None],
    dict[str, str | None],
    dict[str, int | None],
    int | None,
]:
    last_books = state.last_book_at_by_condition.get(condition_id, {})
    last_receipts = state.last_book_received_at_by_condition.get(condition_id, {})
    last_book_at_by_side: dict[str, str | None] = {}
    last_received_at_by_side: dict[str, str | None] = {}
    freshness_ms_by_side: dict[str, int | None] = {}
    for side in (Side.UP, Side.DOWN):
        book_at = last_books.get(side)
        received_at = last_receipts.get(side)
        last_book_at_by_side[side.value] = (
            None if book_at is None else book_at.isoformat()
        )
        last_received_at_by_side[side.value] = (
            None if received_at is None else received_at.isoformat()
        )
        freshness_ms_by_side[side.value] = (
            None
            if received_at is None
            else max(0, int((now - received_at).total_seconds() * 1000))
        )
    freshness_values = [
        value for value in freshness_ms_by_side.values() if value is not None
    ]
    return (
        last_book_at_by_side,
        last_received_at_by_side,
        freshness_ms_by_side,
        max(freshness_values) if freshness_values else None,
    )


def subscription_readiness_state(
    strategy: _ReadinessStrategy,
    condition_id: str,
    *,
    preloaded: bool,
) -> str:
    """Derive the readiness string purely from the single condition phase plus
    the orthogonal markers (_stale_orderbook_recovery, reason dict).

    The phase is the source of truth for condition-level lifecycle; the
    pending_instrument_ids / awaiting-book-sides bookkeeping it shadows is
    maintained by the subscription transition functions in subscriptions.py.
    """
    phase = condition_phase(strategy, condition_id)
    if preloaded:
        return "preloaded"
    if phase is ConditionSubscriptionPhase.PENDING_METADATA:
        return "pending_metadata"
    if phase is ConditionSubscriptionPhase.PENDING_INSTRUMENT:
        return "awaiting_instrument"
    if condition_id in strategy._stale_orderbook_recovery_by_condition:
        return "stale_orderbook"
    if phase is ConditionSubscriptionPhase.AWAITING_FIRST_BOOK:
        return "awaiting_first_book"
    reasons = getattr(strategy, "_runtime_readiness_reason_by_condition", {})
    if reason := reasons.get(condition_id):
        return reason
    if phase is not ConditionSubscriptionPhase.UNSUBSCRIBED:
        return "subscribe_requested"
    return "unsubscribed"


def clear_condition_untradable_state(
    strategy: _UntradableStateOwner,
    condition_id: str,
) -> None:
    states = getattr(strategy, "_untradable_quote_sides_by_condition", None)
    if states is not None:
        _ = states.pop(condition_id, None)


def subscription_timing_detail(
    state: MarketSubscriptionState,
    condition_id: str,
    *,
    now: datetime,
) -> dict[str, object]:
    intent_at = state.subscribe_intent_started_at_by_condition.get(condition_id)
    generation_at = state.book_generation_started_at_by_condition.get(condition_id)
    first_book_at = state.first_bilateral_book_at_by_condition.get(condition_id)

    def age_ms(started_at: datetime | None) -> int | None:
        if started_at is None:
            return None
        return max(0, int((now - started_at).total_seconds() * 1000))

    return {
        "subscribe_intent_started_at": (
            None if intent_at is None else intent_at.isoformat()
        ),
        "subscribe_intent_age_ms": age_ms(intent_at),
        "generation_started_at": (
            None if generation_at is None else generation_at.isoformat()
        ),
        "generation_age_ms": age_ms(generation_at),
        "first_bilateral_book_at": (
            None if first_book_at is None else first_book_at.isoformat()
        ),
        "first_bilateral_book_latency_ms": (
            state.first_bilateral_book_latency_ms_by_condition.get(condition_id)
        ),
    }


def readiness_detail(
    strategy: _ReadinessStrategy,
    condition_id: str,
    *,
    now: datetime,
) -> dict[str, object]:
    state = strategy._subscription_state
    registry = strategy._require_registry()
    pair = None if registry is None else registry.by_condition(condition_id)
    pending_sides = state.awaiting_book_sides_by_condition.get(condition_id, set())
    pending_instrument_ids = pending_condition_instrument_ids(
        strategy,  # type: ignore[arg-type]
        condition_id,
    )
    (
        last_books,
        last_receipts,
        freshness_by_side,
        max_freshness_ms,
    ) = book_readiness_detail(state, condition_id, now=now)
    state_name = subscription_readiness_state(
        strategy,
        condition_id,
        preloaded=bool(
            pair is not None and pair.start_ts is not None and now < pair.start_ts
        ),
    )
    return {
        "condition_id": condition_id,
        "market_id": None if pair is None else pair.market_id,
        "asset": None if pair is None else pair.asset,
        "timeframe": None if pair is None else pair.timeframe,
        "subscription_state": state_name,
        "subscribe_requested": condition_phase(
            strategy, condition_id
        )
        is not ConditionSubscriptionPhase.UNSUBSCRIBED,
        **subscription_timing_detail(state, condition_id, now=now),
        "pending_instrument_ids": list(pending_instrument_ids),
        "awaiting_book_sides": sorted(side.value for side in pending_sides),
        "last_book_at_by_side": last_books,
        "last_book_received_at_by_side": last_receipts,
        "freshness_ms_by_side": freshness_by_side,
        "max_freshness_ms": max_freshness_ms,
    }


def stale_orderbook_recovered(
    strategy: _ReadinessStrategy,
    condition_id: str,
    view: MarketView,
) -> bool:
    recovery = strategy._stale_orderbook_recovery_by_condition.get(condition_id)
    if recovery is None:
        return True
    return all(
        (freshness_ms := view.book_for(side).freshness_ms) is not None
        and freshness_ms <= threshold_ms
        for side, threshold_ms in recovery.items()
    )


def orderbook_readiness_threshold_ms(strategy: _ReadinessStrategy) -> float:
    return float(strategy.policy.orderbook_readiness_threshold_ms())  # type: ignore[attr-defined]


def orderbook_trade_threshold_ms(strategy: _ReadinessStrategy) -> float:
    return float(
        strategy.policy.orderbook_trade_threshold_ms(strategy.strategy_name)  # type: ignore[attr-defined]
    )


def stale_orderbook_sides(
    view: MarketView,
    *,
    threshold_ms: float,
) -> dict[Side, float] | None:
    stale_sides: dict[Side, float] | None = None
    for side in (Side.UP, Side.DOWN):
        freshness_ms = view.book_for(side).freshness_ms
        if freshness_ms is not None and freshness_ms <= threshold_ms:
            continue
        if stale_sides is None:
            stale_sides = {}
        stale_sides[side] = threshold_ms
    return stale_sides
