"""
Input: __future__, collections.abc, dataclasses, polysignal_lab.alpha.types, polysignal_lab.nautilus_runtime.decision_policy, polysignal_lab.nautilus_runtime.native_order, polysignal_lab.nautilus_runtime.order_mapping, polysignal_lab.nautilus_runtime.strategy.helpers
Output: DecisionPipelineState, NativeDecisionSink, DecisionPipeline, handle_policy_decision, submit_approved_for_view, should_notify_core_fill, map_approved_to_order_spec
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, cast

from polysignal_lab.alpha.types import AlphaDecision, AlphaFillEvent, MarketView
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import (
    ApprovedDecision,
    BatchArbitrationResult,
    DecisionPolicy,
    RejectedDecision,
)
from polysignal_lab.nautilus_runtime.native_order import OrderSubmittingStrategy, submit_approved_decision
from polysignal_lab.nautilus_runtime.order_mapping import order_spec_from_decision
from polysignal_lab.nautilus_runtime.order_plan import OrderSubmissionPlan
from polysignal_lab.nautilus_runtime.strategy.helpers import _market_view_ready


def should_notify_core_fill(core: object, event: AlphaFillEvent) -> bool:
    checker = getattr(core, "should_notify_fill", None)
    if callable(checker):
        return bool(checker(event))
    return True


def submit_approved_for_view(
    strategy: OrderSubmittingStrategy[object],
    approved: ApprovedDecision,
    *,
    view: MarketView,
    fixed_stake_usdc: float,
    instrument_id_resolver: Callable[[str], object],
    now: Callable[[], datetime] | None = None,
) -> object:
    signal = approved.signal
    book = view.book_for(signal.side)
    return submit_approved_decision(
        strategy,
        approved,
        fixed_stake_usdc=fixed_stake_usdc,
        best_ask=book.best_ask,
        best_bid=getattr(book, "best_bid", None),
        instrument_id_resolver=instrument_id_resolver,
        now=now,
    )


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
        best_bid=getattr(book, "best_bid", None),
    )


@dataclass
class DecisionPipelineState:
    rejected_decisions: deque[RejectedDecision] = field(
        default_factory=lambda: deque(maxlen=1000)
    )


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
        policy: DecisionPolicy | Callable[[], DecisionPolicy],
        *,
        is_active_condition: Callable[[str], bool],
        is_signal_submitted: Callable[[str], bool],
    ) -> None:
        self._policy = policy
        self._is_active_condition = is_active_condition
        self._is_signal_submitted = is_signal_submitted

    def _resolve_policy(self) -> DecisionPolicy:
        if callable(self._policy) and not isinstance(self._policy, DecisionPolicy):
            return cast(DecisionPolicy, self._policy())
        return cast(DecisionPolicy, self._policy)

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
            is_signal_submitted=self._is_signal_submitted,
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
    ) -> BatchArbitrationResult:
        return self._resolve_policy().batch_arbitrate(decisions)

    def record_batch_rejection(
        self,
        rejected: RejectedDecision,
        decision: AlphaDecision,
        *,
        state: DecisionPipelineState,
        sink: NativeDecisionSink,
    ) -> None:
        _record_rejection(rejected, decision, state=state, sink=sink)

    def handle_policy_result(
        self,
        result: ApprovedDecision | RejectedDecision,
        decision: AlphaDecision,
        view: MarketView,
        *,
        state: DecisionPipelineState,
        sink: NativeDecisionSink,
    ) -> None:
        if isinstance(result, RejectedDecision):
            self._on_rejected(result, decision, state=state, sink=sink)
            return
        signal_key = result.signal.dedupe_key
        if self._is_signal_submitted(signal_key):
            self._on_duplicate(
                RejectedDecision(
                    reason_code="DUPLICATE_IN_FLIGHT_SIGNAL",
                    detail={"dedupe_key": signal_key},
                    candidate=result.signal,
                ),
                decision,
                state=state,
                sink=sink,
            )
            return
        try:
            order = sink.submit_order(result, view=view)
        except ValueError as exc:
            self._on_order_mapping_failed(
                RejectedDecision(
                    reason_code="ORDER_MAPPING_FAILED",
                    detail={"error": str(exc)},
                    candidate=result.signal,
                ),
                decision,
                state=state,
                sink=sink,
            )
            return
        self._on_approved(result, decision, order, state=state, sink=sink)

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

    def try_map_approved_spec(
        self,
        approved: ApprovedDecision,
        *,
        decision: AlphaDecision,
        view: MarketView,
        fixed_stake_usdc: float,
        spec_transform: Callable[[OrderSubmissionPlan, AlphaDecision], OrderSubmissionPlan]
        | None = None,
    ) -> OrderSubmissionPlan | RejectedDecision:
        try:
            spec = map_approved_to_order_spec(
                approved,
                view=view,
                fixed_stake_usdc=fixed_stake_usdc,
            )
        except ValueError:
            return RejectedDecision(
                reason_code="ORDER_MAPPING_FAILED",
                detail={"condition_id": decision.condition_id},
                candidate=approved.signal,
            )
        if spec_transform is not None:
            spec = spec_transform(spec, decision)
        return spec


def handle_policy_decision(
    decision: AlphaDecision,
    view: MarketView,
    *,
    policy: DecisionPolicy,
    active_condition_ids: set[str],
    is_signal_submitted: Callable[[str], bool],
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
        if is_signal_submitted(signal_key):
            rejected = RejectedDecision(
                reason_code="DUPLICATE_IN_FLIGHT_SIGNAL",
                detail={"dedupe_key": signal_key},
                candidate=policy_result.signal,
            )
            on_duplicate(rejected, decision)
            return
        try:
            order = submit_approved(policy_result, view)
        except ValueError as exc:
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
