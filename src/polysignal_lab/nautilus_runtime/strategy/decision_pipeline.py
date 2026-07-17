"""
Input: __future__, collections.abc, dataclasses, polysignal_lab.alpha.types, polysignal_lab.nautilus_runtime.decision_policy, polysignal_lab.nautilus_runtime.native_order
Output: DecisionPipelineState, NativeDecisionSink, DecisionResultHandler, submit_approved_for_view
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from polysignal_lab.alpha.types import AlphaDecision, MarketView
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import (
    ApprovedDecision,
    RejectedDecision,
)
from polysignal_lab.nautilus_runtime.native_order import OrderSubmittingStrategy, submit_approved_decision


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


class DecisionResultHandler:
    def __init__(
        self,
        *,
        is_signal_submitted: Callable[[str], bool],
    ) -> None:
        self._is_signal_submitted = is_signal_submitted

    def handle_result(
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
