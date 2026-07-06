from __future__ import annotations

from polysignal_lab.alpha.types import AlphaDecision, NautilusOrderSpec
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import ApprovedDecision
from polysignal_lab.nautilus_runtime.order_plan import build_order_spec


def order_spec_from_decision(
    decision: ApprovedDecision | AlphaDecision | SignalCandidate,
    fixed_stake_usdc: float,
    best_ask: float | None = None,
) -> NautilusOrderSpec:
    return build_order_spec(
        _decision_source(decision),
        fixed_stake_usdc=fixed_stake_usdc,
        best_ask=best_ask,
    )


def _decision_source(
    decision: ApprovedDecision | AlphaDecision | SignalCandidate,
) -> AlphaDecision | SignalCandidate:
    if isinstance(decision, ApprovedDecision):
        return decision.signal
    return decision
