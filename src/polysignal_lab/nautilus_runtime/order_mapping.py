"""
Input: __future__, __future__.annotations, polysignal_lab.alpha.types, polysignal_lab.alpha.types.AlphaDecision, polysignal_lab.alpha.types.NautilusOrderSpec, polysignal_lab.domain.signal, polysignal_lab.domain.signal.SignalCandidate, polysignal_lab.nautilus_runtime.decision_policy, polysignal_lab.nautilus_runtime.decision_policy.ApprovedDecision, polysignal_lab.nautilus_runtime.order_plan
Output: order_spec_from_decision
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from polysignal_lab.alpha.types import AlphaDecision
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import ApprovedDecision
from polysignal_lab.nautilus_runtime.order_plan import OrderSubmissionPlan, build_order_spec


def order_spec_from_decision(
    decision: ApprovedDecision | AlphaDecision | SignalCandidate,
    fixed_stake_usdc: float,
    best_ask: float | None = None,
    best_bid: float | None = None,
) -> OrderSubmissionPlan:
    return build_order_spec(
        _decision_source(decision),
        fixed_stake_usdc=fixed_stake_usdc,
        best_ask=best_ask,
        best_bid=best_bid,
    )


def _decision_source(
    decision: ApprovedDecision | AlphaDecision | SignalCandidate,
) -> AlphaDecision | SignalCandidate:
    if isinstance(decision, ApprovedDecision):
        return decision.signal
    return decision
