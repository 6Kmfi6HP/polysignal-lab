from __future__ import annotations

import logging

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any, Protocol, cast

from polysignal_lab.alpha.types import (
    AlphaCore,
    AlphaDecision,
    MarketView,
    TradingStateView,
)
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.strategy_readiness import StrategyStatus
from polysignal_lab.nautilus_runtime.cache_trading_state import trading_state_from_cache
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicy
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.native_strategy_exit import NativeExitPolicy
from polysignal_lab.nautilus_runtime.strategy.decision_pipeline import DecisionPipeline
from polysignal_lab.nautilus_runtime.strategy.data_boundary import (
    MarketViewClassification,
    MarketViewState,
    classify_market_view,
)
from polysignal_lab.nautilus_runtime.strategy.protocols import _Assembler
from polysignal_lab.nautilus_runtime.strategy.readiness import (
    clear_condition_untradable_state,
    orderbook_readiness_threshold_ms,
    orderbook_trade_threshold_ms,
    stale_orderbook_recovered,
    stale_orderbook_sides,
)
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    MarketSubscriptionState,
    clear_condition_lifecycle_state,
    market_book_generation_ready,
    pending_condition_instrument_ids,
)


logger = logging.getLogger(__name__)


class _EvaluationStrategy(Protocol):
    core: AlphaCore
    policy: DecisionPolicy
    exit_policy: NativeExitPolicy | None
    cache: object | None
    assembler: _Assembler
    registry: MarketCatalog | None
    strategy_name: str
    unsubscribe_exited: bool
    _active_condition_ids: set[str]
    _runtime_readiness_miss_condition_ids: set[str]
    _runtime_readiness_reason_by_condition: dict[str, str]
    _stale_orderbook_recovery_by_condition: dict
    _untradable_quote_sides_by_condition: dict[str, frozenset[Side]]
    _subscription_state: MarketSubscriptionState
    _decision_pipeline: DecisionPipeline

    def _framework_now(self) -> datetime: ...
    def _require_registry(self) -> MarketCatalog | None: ...
    def _require_assembler(self) -> _Assembler: ...
    def _note_runtime_progress(self, phase: str) -> None: ...
    def _note_runtime_readiness(
        self,
        condition_id: str,
        *,
        ready: bool,
        status: StrategyStatus | None = None,
        reason: str | None = None,
    ) -> None: ...
    def _refresh_asset_conditions(self) -> None: ...
    def _unsubscribe_market_conditions(self, condition_ids: Sequence[str]) -> None: ...


def skip_preloaded_condition(
    strategy: _EvaluationStrategy,
    condition_id: str,
    *,
    now: datetime,
) -> bool:
    registry = strategy._require_registry()
    pair = None if registry is None else registry.by_condition(condition_id)
    if pair is None or pair.start_ts is None or now >= pair.start_ts:
        return False
    if condition_id in strategy._runtime_readiness_miss_condition_ids:
        strategy._note_runtime_readiness(condition_id, ready=True)
    return True


def retire_expired_condition(
    strategy: _EvaluationStrategy,
    condition_id: str,
    *,
    now: datetime,
) -> bool:
    registry = strategy._require_registry()
    pair = None if registry is None else registry.by_condition(condition_id)
    end_ts = None if pair is None else getattr(pair, "end_ts", None)
    if end_ts is None or now < end_ts:
        return False
    strategy._active_condition_ids.discard(condition_id)
    _cancel_expired_entry_orders(strategy, condition_id, registry=registry)
    if strategy.unsubscribe_exited:
        clear_condition_lifecycle_state(
            strategy,  # type: ignore[arg-type]
            condition_id,
            clear_history=True,
        )
    else:
        clear_condition_lifecycle_state(
            strategy,  # type: ignore[arg-type]
            condition_id,
            clear_subscribed=False,
        )
    if strategy.unsubscribe_exited:
        strategy._unsubscribe_market_conditions((condition_id,))
    strategy._refresh_asset_conditions()
    strategy._note_runtime_readiness(condition_id, ready=True)
    # Settlement must run even when discovery would otherwise be throttled or
    # when this condition just left the active set.
    from polysignal_lab.nautilus_runtime.strategy import resolution_settlement

    resolution_settlement.resolve_open_positions(
        cast(Any, strategy),
        now=now,
    )
    return True


def _cancel_expired_entry_orders(
    strategy: _EvaluationStrategy,
    condition_id: str,
    *,
    registry: MarketCatalog | None,
) -> None:
    if registry is None or getattr(strategy, "cache", None) is None:
        return
    try:
        trading = trading_state_from_cache(
            getattr(strategy, "cache", None),
            strategy_id=getattr(strategy, "strategy_id", None)
            or getattr(strategy, "id", None),
            registry=registry,
            condition_id=condition_id,
        )
    except (TypeError, ValueError, RuntimeError):
        return
    cancel = getattr(strategy, "cancel_" + "orders", None)
    if not callable(cancel):
        strategy._note_runtime_progress("expired_order_cancel_unavailable")
        return
    client_order_ids = tuple(
        order.client_order_id
        for order in trading.orders
        if not order.reduce_only and (order.is_open or order.is_inflight)
    )
    if not client_order_ids:
        return
    try:
        cancel(client_order_ids)
        strategy._note_runtime_progress("expired_entry_orders_cancelled")
    except (TypeError, ValueError, RuntimeError):
        strategy._note_runtime_progress("expired_order_cancel_failed")


def mark_condition_unready(
    strategy: _EvaluationStrategy,
    condition_id: str,
    *,
    reason: str,
) -> None:
    clear_condition_untradable_state(strategy, condition_id)  # type: ignore[arg-type]
    strategy._runtime_readiness_reason_by_condition[condition_id] = reason
    if reason != "stale_orderbook":
        _ = strategy._stale_orderbook_recovery_by_condition.pop(condition_id, None)
    strategy._note_runtime_progress("readiness_miss")
    strategy._note_runtime_readiness(condition_id, ready=False)


def _missing_quote_depth_reason(classification: MarketViewClassification) -> str:
    sides = ",".join(
        side.value for side in classification.missing_quote_depth_sides
    )
    return f"missing_quote_depth:{sides}"


def _log_market_transition(
    strategy: _EvaluationStrategy,
    condition_id: str,
    market_view: MarketView,
    *,
    event_type: str,
    missing_sides: frozenset[Side],
    now: datetime,
) -> None:
    receipts = strategy._subscription_state.last_book_received_at_by_condition.get(
        condition_id, {}
    )
    logger.info(
        event_type,
        extra={
            "market_detail": {
                "strategy": strategy.strategy_name,
                "condition": condition_id,
                "asset": market_view.asset,
                "timeframe": market_view.timeframe,
                "observed_at": now.isoformat(),
                "missing_sides": sorted(side.value for side in missing_sides),
                "last_book_received_at_by_side": {
                    side.value: (
                        None
                        if (received_at := receipts.get(side)) is None
                        else received_at.isoformat()
                    )
                    for side in (Side.UP, Side.DOWN)
                },
                "freshness_ms_by_side": {
                    side.value: market_view.book_for(side).freshness_ms
                    for side in (Side.UP, Side.DOWN)
                },
            }
        },
    )


def mark_condition_untradable(
    strategy: _EvaluationStrategy,
    condition_id: str,
    market_view: MarketView,
    classification: MarketViewClassification,
    *,
    now: datetime,
) -> None:
    missing_sides = frozenset(classification.missing_quote_depth_sides)
    previous = strategy._untradable_quote_sides_by_condition.get(condition_id)
    strategy._untradable_quote_sides_by_condition[condition_id] = missing_sides
    strategy._note_runtime_readiness(
        condition_id,
        ready=True,
        status="untradable",
        reason=_missing_quote_depth_reason(classification),
    )
    if previous != missing_sides:
        _log_market_transition(
            strategy,
            condition_id,
            market_view,
            event_type="market_untraditable",
            missing_sides=missing_sides,
            now=now,
        )


def _with_trading_state(
    strategy: _EvaluationStrategy,
    view: MarketView,
    trading_state: object | None,
) -> MarketView | None:
    registry = strategy._require_registry()
    if registry is None:
        return None
    trading = (
        trading_state.for_condition(view.condition_id)
        if isinstance(trading_state, TradingStateView)
        else trading_state_from_cache(
            strategy.cache,
            strategy_id=getattr(strategy, "strategy_id", None)
            or getattr(strategy, "id", None),
            registry=registry,
            condition_id=view.condition_id,
        )
    )
    return replace(view, trading=trading)


def _classified_market_view(
    strategy: _EvaluationStrategy,
    condition_id: str,
    *,
    now: datetime,
    trading_state: object | None,
) -> tuple[MarketView, MarketViewClassification] | None:
    view = strategy._require_assembler().build(condition_id, created_at=now)
    classification = classify_market_view(view)
    if classification.state is MarketViewState.INVALID:
        mark_condition_unready(
            strategy,
            condition_id,
            reason="missing_market_view",
        )
        return None
    market_view = cast(MarketView, view)
    if not isinstance(view, MarketView):
        return market_view, classification
    resolved_view = _with_trading_state(strategy, view, trading_state)
    if resolved_view is None:
        mark_condition_unready(
            strategy,
            condition_id,
            reason="missing_market_view",
        )
        return None
    return resolved_view, classification


def _market_view_blocks_evaluation(
    strategy: _EvaluationStrategy,
    condition_id: str,
    market_view: MarketView,
    classification: MarketViewClassification,
    *,
    now: datetime,
) -> bool:
    stale_sides = stale_orderbook_sides(
        market_view,
        threshold_ms=orderbook_readiness_threshold_ms(strategy),  # type: ignore[arg-type]
    )
    if stale_sides is not None:
        strategy._stale_orderbook_recovery_by_condition[condition_id] = stale_sides
        mark_condition_unready(
            strategy,
            condition_id,
            reason="stale_orderbook",
        )
        return True
    if classification.state is not MarketViewState.UNTRADABLE:
        return False
    mark_condition_untradable(
        strategy,
        condition_id,
        market_view,
        classification,
        now=now,
    )
    return True


def _book_generation_wait_reason(
    strategy: _EvaluationStrategy,
    condition_id: str,
) -> str:
    pending = pending_condition_instrument_ids(  # type: ignore[arg-type]
        strategy,
        condition_id,
    )
    return "awaiting_instrument" if pending else "awaiting_first_book"


def evaluate_condition(
    strategy: _EvaluationStrategy,
    condition_id: str,
    *,
    created_at: datetime | None = None,
    trading_state: object | None = None,
) -> None:
    if condition_id not in strategy._active_condition_ids:
        return
    now = created_at or strategy._framework_now()
    if retire_expired_condition(strategy, condition_id, now=now):
        return
    if skip_preloaded_condition(strategy, condition_id, now=now):
        return
    if not market_book_generation_ready(strategy, condition_id):  # type: ignore[arg-type]
        mark_condition_unready(
            strategy,
            condition_id,
            reason=_book_generation_wait_reason(strategy, condition_id),
        )
        return
    classified = _classified_market_view(
        strategy,
        condition_id,
        now=now,
        trading_state=trading_state,
    )
    if classified is None:
        return
    market_view, classification = classified
    if _market_view_blocks_evaluation(
        strategy,
        condition_id,
        market_view,
        classification,
        now=now,
    ):
        return
    evaluate_ready_condition(
        strategy,
        condition_id,
        market_view,
        now=now,
    )


def _cancel_pending_recovery_if_cleared(
    strategy: _EvaluationStrategy,
    condition_id: str,
) -> None:
    """Drop a trailing recovery alert after any path clears miss/untradable state.

    Market-data events already cancel before evaluating. Direct callers such as
    RTDS spot and price-to-beat updates do not, so a pending 500 ms alert would
    otherwise re-evaluate the same recovered observation.
    """
    if (
        condition_id in strategy._runtime_readiness_miss_condition_ids
        or condition_id in strategy._untradable_quote_sides_by_condition
    ):
        return
    cancel = getattr(strategy, "_cancel_market_data_recovery_evaluation", None)
    if callable(cancel):
        cancel(condition_id)


def evaluate_ready_condition(
    strategy: _EvaluationStrategy,
    condition_id: str,
    market_view: MarketView,
    *,
    now: datetime,
) -> None:
    readiness_confirmed = _restore_tradable_state(
        strategy,
        condition_id,
        market_view,
        now=now,
    )
    if not readiness_confirmed and condition_id in strategy._stale_orderbook_recovery_by_condition:
        if not stale_orderbook_recovered(strategy, condition_id, market_view):  # type: ignore[arg-type]
            strategy._note_runtime_progress("readiness_miss")
            strategy._note_runtime_readiness(condition_id, ready=False)
            return
        strategy._note_runtime_readiness(condition_id, ready=True)
        readiness_confirmed = True
    elif not readiness_confirmed and condition_id in strategy._runtime_readiness_miss_condition_ids:
        strategy._note_runtime_readiness(condition_id, ready=True)
        readiness_confirmed = True
    evaluate_core = (
        stale_orderbook_sides(
            market_view,
            threshold_ms=orderbook_trade_threshold_ms(strategy),  # type: ignore[arg-type]
        )
        is None
    )
    decisions = evaluate_decisions(
        strategy,
        market_view,
        now=now,
        evaluate_core=evaluate_core,
    )
    _ = strategy._decision_pipeline.apply(decisions, market_view)
    if (
        not readiness_confirmed
        and condition_id not in strategy._runtime_readiness_miss_condition_ids
    ):
        strategy._note_runtime_readiness(condition_id, ready=True)
    _cancel_pending_recovery_if_cleared(strategy, condition_id)


def _restore_tradable_state(
    strategy: _EvaluationStrategy,
    condition_id: str,
    market_view: MarketView,
    *,
    now: datetime,
) -> bool:
    missing_sides = strategy._untradable_quote_sides_by_condition.pop(
        condition_id, None
    )
    if missing_sides is None:
        return False
    _log_market_transition(
        strategy,
        condition_id,
        market_view,
        event_type="market_tradable",
        missing_sides=missing_sides,
        now=now,
    )
    strategy._note_runtime_readiness(condition_id, ready=True)
    return True


def evaluate_decisions(
    strategy: _EvaluationStrategy,
    market_view: MarketView,
    *,
    now: datetime,
    evaluate_core: bool = True,
) -> tuple[AlphaDecision, ...]:
    if strategy.exit_policy is None:
        return tuple(strategy.core.evaluate(market_view)) if evaluate_core else ()
    try:
        cache = strategy.cache
    except (AttributeError, RuntimeError):
        cache = None
    try:
        decisions = strategy.exit_policy.decisions(
            cache=cache,
            strategy_id=getattr(strategy, "strategy_id", None)
            or getattr(strategy, "id", None),
            registry=strategy._require_registry(),
            view=market_view,
            now=now,
            trading=market_view.trading,
        )
    except (TypeError, ValueError, RuntimeError):
        strategy._note_runtime_progress("native_exit_failed")
        return tuple(strategy.core.evaluate(market_view)) if evaluate_core else ()
    if decisions:
        strategy._note_runtime_progress("native_exit")
        return decisions
    return tuple(strategy.core.evaluate(market_view)) if evaluate_core else ()


def handle_decision(
    strategy: _EvaluationStrategy,
    decision: AlphaDecision,
    view: MarketView,
) -> None:
    _ = strategy._decision_pipeline.apply((decision,), view)


__all__ = [
    "evaluate_condition",
    "evaluate_decisions",
    "evaluate_ready_condition",
    "handle_decision",
    "mark_condition_unready",
    "retire_expired_condition",
    "skip_preloaded_condition",
]
