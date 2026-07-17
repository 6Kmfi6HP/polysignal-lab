"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Sequence, dataclasses, dataclasses.replace, datetime, datetime.datetime, typing, typing.Protocol
Output: skip_preloaded_condition, retire_expired_condition, mark_condition_unready, evaluate_condition, evaluate_ready_condition, apply_decision_batch, evaluate_decisions, handle_decision, _EvaluationStrategy
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from typing import Protocol, cast

from polysignal_lab.alpha.types import AlphaCore, AlphaDecision, MarketView
from polysignal_lab.nautilus_runtime.cache_trading_state import trading_state_from_cache
from polysignal_lab.nautilus_runtime.decision_policy import (
    DecisionPolicy,
    RejectedDecision,
)
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.native_strategy_exit import NativeExitPolicy
from polysignal_lab.nautilus_runtime.strategy.decision_pipeline import (
    DecisionPipelineState,
    DecisionResultHandler,
    NativeDecisionSink,
)
from polysignal_lab.nautilus_runtime.strategy.helpers import _Assembler, _market_view_ready
from polysignal_lab.nautilus_runtime.strategy.readiness import (
    orderbook_readiness_threshold_ms,
    orderbook_trade_threshold_ms,
    stale_orderbook_recovered,
    stale_orderbook_sides,
)
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    market_book_generation_ready,
    retire_market_book_generation,
)


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
    _stale_orderbook_recovery_by_condition: dict
    _subscription_state: object
    _pipeline_state: DecisionPipelineState
    _decision_result_handler: DecisionResultHandler
    _decision_sink: NativeDecisionSink

    def _framework_now(self) -> datetime: ...
    def _require_registry(self) -> MarketCatalog | None: ...
    def _require_assembler(self) -> _Assembler: ...
    def _note_runtime_progress(self, phase: str) -> None: ...
    def _note_runtime_readiness(self, condition_id: str, *, ready: bool) -> None: ...
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
    strategy._subscription_state.pending_metadata_condition_ids.discard(condition_id)  # type: ignore[attr-defined]
    retire_market_book_generation(strategy, condition_id)  # type: ignore[arg-type]
    if strategy.unsubscribe_exited:
        strategy._unsubscribe_market_conditions((condition_id,))
    strategy._refresh_asset_conditions()
    strategy._note_runtime_readiness(condition_id, ready=True)
    return True


def mark_condition_unready(strategy: _EvaluationStrategy, condition_id: str) -> None:
    strategy._note_runtime_progress("readiness_miss")
    strategy._note_runtime_readiness(condition_id, ready=False)


def evaluate_condition(
    strategy: _EvaluationStrategy,
    condition_id: str,
    *,
    created_at: datetime | None = None,
) -> None:
    if condition_id not in strategy._active_condition_ids:
        return
    now = created_at or strategy._framework_now()
    if retire_expired_condition(strategy, condition_id, now=now):
        return
    if skip_preloaded_condition(strategy, condition_id, now=now):
        return
    if not market_book_generation_ready(strategy, condition_id):  # type: ignore[arg-type]
        mark_condition_unready(strategy, condition_id)
        return
    view = strategy._require_assembler().build(condition_id, created_at=now)
    if view is None or not _market_view_ready(view):
        mark_condition_unready(strategy, condition_id)
        return
    market_view = cast(MarketView, view)
    if isinstance(view, MarketView):
        market_view = replace(
            view,
            trading=trading_state_from_cache(
                strategy.cache,
                strategy_id=getattr(strategy, "strategy_id", None)
                or getattr(strategy, "id", None),
                registry=strategy._require_registry(),
                condition_id=market_view.condition_id,
            ),
        )
    stale_sides = stale_orderbook_sides(
        market_view,
        threshold_ms=orderbook_readiness_threshold_ms(strategy),  # type: ignore[arg-type]
    )
    if stale_sides is not None:
        strategy._stale_orderbook_recovery_by_condition[condition_id] = stale_sides
        mark_condition_unready(strategy, condition_id)
        return
    evaluate_ready_condition(
        strategy,
        condition_id,
        market_view,
        now=now,
    )


def evaluate_ready_condition(
    strategy: _EvaluationStrategy,
    condition_id: str,
    market_view: MarketView,
    *,
    now: datetime,
) -> None:
    readiness_confirmed = False
    if condition_id in strategy._stale_orderbook_recovery_by_condition:
        if not stale_orderbook_recovered(strategy, condition_id, market_view):  # type: ignore[arg-type]
            strategy._note_runtime_progress("readiness_miss")
            strategy._note_runtime_readiness(condition_id, ready=False)
            return
        strategy._note_runtime_readiness(condition_id, ready=True)
        readiness_confirmed = True
    elif condition_id in strategy._runtime_readiness_miss_condition_ids:
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
    apply_decision_batch(strategy, decisions, market_view)
    if (
        not readiness_confirmed
        and condition_id not in strategy._runtime_readiness_miss_condition_ids
    ):
        strategy._note_runtime_readiness(condition_id, ready=True)


def apply_decision_batch(
    strategy: _EvaluationStrategy,
    decisions: Sequence[AlphaDecision],
    view: MarketView,
) -> None:
    """Evaluate decisions through the strategy-owned DecisionPolicy (no Actor bus)."""
    if not decisions:
        return
    pairs = [(decision, view) for decision in decisions]
    arbitration = strategy.policy.batch_arbitrate(list(pairs))
    survivor_ids = {id(decision) for decision in arbitration}
    rejected_by_id = {
        id(decision): rejected for decision, rejected in arbitration.rejections
    }
    for decision in decisions:
        if id(decision) not in survivor_ids:
            rejected = rejected_by_id.get(id(decision)) or RejectedDecision(
                reason_code="ARBITRATION_SUPPRESSED",
                detail={},
            )
            strategy._decision_result_handler.handle_result(
                rejected,
                decision,
                view,
                state=strategy._pipeline_state,
                sink=strategy._decision_sink,
            )
            continue
        policy_result = strategy.policy.decide(decision, view)
        strategy._decision_result_handler.handle_result(
            policy_result,
            decision,
            view,
            state=strategy._pipeline_state,
            sink=strategy._decision_sink,
        )


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
    apply_decision_batch(strategy, (decision,), view)


__all__ = [
    "apply_decision_batch",
    "evaluate_condition",
    "evaluate_decisions",
    "evaluate_ready_condition",
    "handle_decision",
    "mark_condition_unready",
    "retire_expired_condition",
    "skip_preloaded_condition",
]
