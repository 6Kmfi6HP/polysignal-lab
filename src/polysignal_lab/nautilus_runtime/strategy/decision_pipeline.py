"""
Input: __future__, collections.abc, dataclasses, polysignal_lab.alpha.types, polysignal_lab.nautilus_runtime.decision_policy, polysignal_lab.nautilus_runtime.order_mapping, polysignal_lab.nautilus_runtime.strategy.helpers
Output: DecisionPipelineState, NativeDecisionSink, DecisionPipeline, handle_policy_decision, map_approved_to_order_spec
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, cast

from polysignal_lab.alpha.types import AlphaDecision, MarketView
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import (
    ApprovedDecision,
    DecisionPolicyActor,
    RejectedDecision,
)
from polysignal_lab.nautilus_runtime.order_plan import OrderSubmissionPlan
from polysignal_lab.nautilus_runtime.order_mapping import order_spec_from_decision
from polysignal_lab.nautilus_runtime.strategy.helpers import _market_view_ready


def map_approved_to_order_spec(
    approved: ApprovedDecision,
    *,
    view: MarketView,
    fixed_stake_usdc: float,
) -> OrderSubmissionPlan:
    signal = approved.signal
    book = view.book_for(signal.side)
    return order_spec_from_decision(
        approved,
        fixed_stake_usdc=fixed_stake_usdc,
        best_ask=book.best_ask,
    )


@dataclass
class DecisionPipelineState:
    submitted_signal_keys: set[str] = field(default_factory=set)
    rejected_decisions: deque[RejectedDecision] = field(
        default_factory=lambda: deque(maxlen=1000)
    )
    submitted_orders: deque[object] = field(default_factory=lambda: deque(maxlen=1000))


class NativeDecisionSink(Protocol):
    def submit_order(self, approved: ApprovedDecision, *, view: MarketView) -> object: ...
    def remember_metrics(self, order: object, approved: ApprovedDecision) -> None: ...
    def record_signal(self, signal: SignalCandidate) -> None: ...
    def notify_accepted(self, signal: SignalCandidate) -> None: ...
    def record_decision(self, decision: AlphaDecision, *, accepted: bool) -> None: ...
    def record_rejected(self, rejected: RejectedDecision) -> None: ...
    def note_progress(self, event: str) -> None: ...


def _record_rejection(
    rejected: RejectedDecision,
    decision: AlphaDecision,
    *,
    state: DecisionPipelineState,
    sink: NativeDecisionSink,
) -> None:
    state.rejected_decisions.append(rejected)
    sink.record_decision(decision, accepted=False)
    sink.record_rejected(rejected)


@dataclass(slots=True)
class NativeDecisionSinkImpl:
    submit_order_fn: Callable[[ApprovedDecision, MarketView], object]
    remember_metrics_fn: Callable[[object, ApprovedDecision], None]
    record_signal_fn: Callable[[SignalCandidate], None]
    notify_accepted_fn: Callable[[SignalCandidate], None]
    record_decision_fn: Callable[[AlphaDecision, bool], None]
    record_rejected_fn: Callable[[RejectedDecision], None]
    note_progress_fn: Callable[[str], None] | None = None

    def submit_order(self, approved: ApprovedDecision, *, view: MarketView) -> object:
        return self.submit_order_fn(approved, view)

    def remember_metrics(self, order: object, approved: ApprovedDecision) -> None:
        self.remember_metrics_fn(order, approved)

    def record_signal(self, signal: SignalCandidate) -> None:
        self.record_signal_fn(signal)

    def notify_accepted(self, signal: SignalCandidate) -> None:
        self.notify_accepted_fn(signal)

    def record_decision(self, decision: AlphaDecision, *, accepted: bool) -> None:
        self.record_decision_fn(decision, accepted)

    def record_rejected(self, rejected: RejectedDecision) -> None:
        self.record_rejected_fn(rejected)

    def note_progress(self, event: str) -> None:
        if self.note_progress_fn is not None:
            self.note_progress_fn(event)


class DecisionPipeline:
    def __init__(
        self,
        policy: DecisionPolicyActor | Callable[[], DecisionPolicyActor],
        *,
        is_active_condition: Callable[[str], bool],
    ) -> None:
        self._policy = policy
        self._is_active_condition = is_active_condition

    def _resolve_policy(self) -> DecisionPolicyActor:
        if callable(self._policy) and not isinstance(self._policy, DecisionPolicyActor):
            return cast(DecisionPolicyActor, self._policy())
        return cast(DecisionPolicyActor, self._policy)

    def handle_decision(
        self,
        decision: AlphaDecision,
        view: MarketView,
        *,
        state: DecisionPipelineState,
        sink: NativeDecisionSink,
    ) -> None:
        handle_policy_decision(
            decision,
            view,
            policy=self._resolve_policy(),
            active_condition_ids={
                condition_id
                for condition_id in (decision.condition_id,)
                if self._is_active_condition(condition_id)
            },
            submitted_signal_keys=state.submitted_signal_keys,
            submit_approved=lambda approved, market_view: sink.submit_order(
                approved, view=market_view
            ),
            on_duplicate=lambda rejected, original: self._on_duplicate(
                rejected, original, state=state, sink=sink
            ),
            on_order_mapping_failed=lambda rejected, original: self._on_order_mapping_failed(
                rejected, original, state=state, sink=sink
            ),
            on_approved=lambda approved, original, order: self._on_approved(
                approved, original, order, state=state, sink=sink
            ),
            on_rejected=lambda rejected, original: self._on_rejected(
                rejected, original, state=state, sink=sink
            ),
            market_view_ready=_market_view_ready,
            note_progress=sink.note_progress,
        )

    def try_batch_arbitrate(
        self,
        decisions: list[tuple[AlphaDecision, MarketView]],
    ) -> list[AlphaDecision]:
        """Batch-arbitrate multiple (decision, view) pairs against each other.

        This lets ``suppress_ambiguous`` detect opposite-side conflicts within
        a single evaluation epoch.  Survivors still need individual
        ``handle_decision()`` calls for gate/consensus evaluation.
        """
        if not decisions:
            return []
        policy = self._resolve_policy()
        survivors = policy.batch_arbitrate(decisions)
        return survivors

    @staticmethod
    def _on_duplicate(
        rejected: RejectedDecision,
        decision: AlphaDecision,
        *,
        state: DecisionPipelineState,
        sink: NativeDecisionSink,
    ) -> None:
        _record_rejection(rejected, decision, state=state, sink=sink)

    @staticmethod
    def _on_order_mapping_failed(
        rejected: RejectedDecision,
        decision: AlphaDecision,
        *,
        state: DecisionPipelineState,
        sink: NativeDecisionSink,
    ) -> None:
        _record_rejection(rejected, decision, state=state, sink=sink)

    @staticmethod
    def _on_approved(
        approved: ApprovedDecision,
        decision: AlphaDecision,
        order: object,
        *,
        state: DecisionPipelineState,
        sink: NativeDecisionSink,
    ) -> None:
        sink.remember_metrics(order, approved)
        state.submitted_orders.append(order)
        sink.record_signal(approved.signal)
        sink.notify_accepted(approved.signal)
        sink.record_decision(decision, accepted=True)

    @staticmethod
    def _on_rejected(
        rejected: RejectedDecision,
        decision: AlphaDecision,
        *,
        state: DecisionPipelineState,
        sink: NativeDecisionSink,
    ) -> None:
        _record_rejection(rejected, decision, state=state, sink=sink)


def handle_policy_decision(
    decision: AlphaDecision,
    view: MarketView,
    *,
    policy: DecisionPolicyActor,
    active_condition_ids: set[str],
    submitted_signal_keys: set[str],
    submit_approved: Callable[[ApprovedDecision, MarketView], object],
    on_duplicate: Callable[[RejectedDecision, AlphaDecision], None],
    on_order_mapping_failed: Callable[[RejectedDecision, AlphaDecision], None],
    on_approved: Callable[[ApprovedDecision, AlphaDecision, object], None],
    on_rejected: Callable[[RejectedDecision, AlphaDecision], None],
    market_view_ready: Callable[[MarketView], bool] = _market_view_ready,
    note_progress: Callable[[str], None] | None = None,
) -> None:
    if not market_view_ready(view):
        if note_progress is not None:
            note_progress("readiness_miss")
        return
    if decision.condition_id not in active_condition_ids:
        return
    policy_result = policy.decide(decision, view)
    if isinstance(policy_result, ApprovedDecision):
        signal_key = policy_result.signal.dedupe_key
        if signal_key in submitted_signal_keys:
            rejected = RejectedDecision(
                reason_code="DUPLICATE_IN_FLIGHT_SIGNAL",
                detail={"dedupe_key": signal_key},
                candidate=policy_result.signal,
            )
            on_duplicate(rejected, decision)
            return
        submitted_signal_keys.add(signal_key)
        try:
            order = submit_approved(policy_result, view)
        except ValueError as exc:
            submitted_signal_keys.discard(signal_key)
            rejected = RejectedDecision(
                reason_code="ORDER_MAPPING_FAILED",
                detail={"error": str(exc)},
                candidate=policy_result.signal,
            )
            on_order_mapping_failed(rejected, decision)
            return
        on_approved(policy_result, decision, order)
        return
    on_rejected(cast(RejectedDecision, policy_result), decision)
