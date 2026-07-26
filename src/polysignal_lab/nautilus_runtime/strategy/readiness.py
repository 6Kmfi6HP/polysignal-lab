from __future__ import annotations

from datetime import datetime
from typing import Protocol

from polysignal_lab.alpha.types import MarketView
from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    MarketSubscriptionState,
)


class _ReadinessStrategy(Protocol):
    registry: MarketCatalog | None
    policy: object
    strategy_name: str
    _subscription_state: MarketSubscriptionState
    _runtime_readiness_miss_condition_ids: set[str]
    _stale_orderbook_recovery_by_condition: dict[str, dict[Side, float]]
    progress_callback: object | None
    readiness_callback: object | None

    def _framework_now(self) -> datetime: ...
    def _require_registry(self) -> MarketCatalog | None: ...


def note_runtime_progress(strategy: _ReadinessStrategy, phase: str) -> None:
    callback = strategy.progress_callback
    if callback is None:
        return
    callback(phase)  # type: ignore[operator]


def note_runtime_readiness(
    strategy: _ReadinessStrategy,
    condition_id: str,
    *,
    ready: bool,
) -> None:
    if ready:
        _ = strategy._runtime_readiness_miss_condition_ids.discard(condition_id)
        _ = strategy._stale_orderbook_recovery_by_condition.pop(condition_id, None)
    else:
        strategy._runtime_readiness_miss_condition_ids.add(condition_id)
    callback = strategy.readiness_callback
    if callback is None:
        return
    now = strategy._framework_now()
    detail = readiness_detail(strategy, condition_id, now=now)
    callback(condition_id, ready, detail)  # type: ignore[operator]


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
    pending_sides: set[Side],
) -> str:
    state = strategy._subscription_state
    if preloaded:
        return "preloaded"
    if condition_id in state.pending_metadata_condition_ids:
        return "pending_metadata"
    if condition_id in strategy._stale_orderbook_recovery_by_condition:
        return "stale_orderbook"
    if pending_sides:
        return "awaiting_first_book"
    if condition_id in state.subscribe_intent_condition_ids:
        return "subscribe_requested"
    return "unsubscribed"


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
        pending_sides=pending_sides,
    )
    generation_started_at = state.book_generation_started_at_by_condition.get(
        condition_id
    )
    return {
        "condition_id": condition_id,
        "market_id": None if pair is None else pair.market_id,
        "asset": None if pair is None else pair.asset,
        "timeframe": None if pair is None else pair.timeframe,
        "subscription_state": state_name,
        "subscribe_requested": condition_id in state.subscribe_intent_condition_ids,
        "generation_started_at": (
            None if generation_started_at is None else generation_started_at.isoformat()
        ),
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
