"""
Input: __future__, __future__.annotations, collections, collections.abc, dataclasses, datetime, typing
Output: DecisionPipeline, SubmittedDecision, NautilusOrderSubmitter, NativeDecisionTelemetry, OrderSubmitter, DecisionTelemetry
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""


from __future__ import annotations

from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from polysignal_lab.alpha.types import AlphaDecision, MarketView
from polysignal_lab.nautilus_runtime.decision_policy import (
    ApprovedDecision,
    BatchArbitrationResult,
    RejectedDecision,
)
from polysignal_lab.nautilus_runtime.native_order import (
    OrderSubmittingStrategy,
    submit_approved_decision,
)


class DecisionPolicyPort(Protocol):
    def batch_arbitrate(
        self, decisions: list[tuple[AlphaDecision, MarketView]]
    ) -> BatchArbitrationResult: ...


class _NativeTelemetryStrategy(Protocol):
    def _record_signal(self, signal: object) -> None: ...
    def _notify_accepted_signal(self, signal: object) -> None: ...
    def _record_decision(self, decision: AlphaDecision, *, accepted: bool) -> None: ...
    def _record_rejected(self, rejected: RejectedDecision) -> None: ...
    def _note_runtime_progress(self, event: str) -> None: ...


class OrderSubmitter(Protocol):
    def submit(self, approved: ApprovedDecision, view: MarketView) -> object: ...


class DecisionTelemetry(Protocol):
    def accepted(self, approved: ApprovedDecision, order: object) -> None: ...
    def rejected(self, rejected: RejectedDecision, decision: AlphaDecision) -> None: ...
    def progress(self, event: str) -> None: ...


@dataclass(slots=True)
class NautilusOrderSubmitter:
    strategy: OrderSubmittingStrategy[object]
    fixed_stake_usdc: float
    instrument_id_resolver: Callable[[str], object]
    now: Callable[[], datetime] | None = None
    use_native_reduce_only: bool = False

    def submit(self, approved: ApprovedDecision, view: MarketView) -> object:
        book = view.book_for(approved.decision.side)
        return submit_approved_decision(
            self.strategy,
            approved,
            fixed_stake_usdc=self.fixed_stake_usdc,
            best_ask=book.best_ask,
            best_bid=getattr(book, "best_bid", None),
            instrument_id_resolver=self.instrument_id_resolver,
            now=self.now,
            view_id=view.view_id,
            use_native_reduce_only=self.use_native_reduce_only,
        )


@dataclass(slots=True)
class NativeDecisionTelemetry:
    strategy: _NativeTelemetryStrategy

    def accepted(self, approved: ApprovedDecision, order: object) -> None:
        _ = order
        self.strategy._record_signal(approved.publish)
        self.strategy._notify_accepted_signal(approved.publish)
        self.strategy._record_decision(approved.decision, accepted=True)

    def rejected(self, rejected: RejectedDecision, decision: AlphaDecision) -> None:
        self.strategy._record_decision(decision, accepted=False)
        self.strategy._record_rejected(rejected)

    def progress(self, event: str) -> None:
        self.strategy._note_runtime_progress(event)


@dataclass(frozen=True, slots=True)
class SubmittedDecision:
    approved: ApprovedDecision
    order: object


@dataclass(slots=True)
class DecisionPipeline:
    policy: DecisionPolicyPort
    submitter: OrderSubmitter
    telemetry: DecisionTelemetry
    rejected_decisions: deque[RejectedDecision] = field(
        default_factory=lambda: deque(maxlen=1000)
    )

    def apply(
        self,
        decisions: Sequence[AlphaDecision],
        view: MarketView,
    ) -> list[SubmittedDecision | RejectedDecision]:
        if not decisions:
            return []
        arbitration = self.policy.batch_arbitrate([(decision, view) for decision in decisions])
        approved_by_id, rejected_by_id = _arbitration_results(arbitration)
        active_dedupe_keys = _active_dedupe_keys(view)
        results: list[SubmittedDecision | RejectedDecision] = []
        for decision in decisions:
            approved = approved_by_id.get(id(decision))
            if approved is None:
                rejected = rejected_by_id.get(id(decision)) or RejectedDecision(
                    reason_code="ARBITRATION_SUPPRESSED",
                    detail={},
                    decision=decision,
                )
                self._reject(rejected, decision)
                results.append(rejected)
                continue
            dedupe_key = approved.decision.dedupe_key()
            if dedupe_key in active_dedupe_keys:
                rejected = RejectedDecision(
                    reason_code="DUPLICATE_IN_FLIGHT_SIGNAL",
                    detail={"dedupe_key": dedupe_key},
                    decision=approved.decision,
                    publish=approved.publish,
                )
                self._reject(rejected, decision)
                results.append(rejected)
                continue
            try:
                order = self.submitter.submit(approved, view)
            except ValueError as exc:
                rejected = RejectedDecision(
                    reason_code="ORDER_MAPPING_FAILED",
                    detail={"error": str(exc)},
                    decision=approved.decision,
                    publish=approved.publish,
                )
                self._reject(rejected, decision)
                results.append(rejected)
                continue
            active_dedupe_keys.add(dedupe_key)
            self.telemetry.accepted(approved, order)
            results.append(SubmittedDecision(approved=approved, order=order))
        return results

    def _reject(self, rejected: RejectedDecision, decision: AlphaDecision) -> None:
        self.rejected_decisions.append(rejected)
        self.telemetry.rejected(rejected, decision)


def _arbitration_results(
    arbitration: BatchArbitrationResult,
) -> tuple[dict[int, ApprovedDecision], dict[int, RejectedDecision]]:
    return (
        {id(approved.decision): approved for approved in arbitration.approvals},
        {id(decision): rejected for decision, rejected in arbitration.rejections},
    )


def _active_dedupe_keys(view: MarketView) -> set[str]:
    return {
        order.dedupe_key
        for order in view.trading.orders
        if order.dedupe_key is not None and (order.is_open or order.is_inflight)
    }
