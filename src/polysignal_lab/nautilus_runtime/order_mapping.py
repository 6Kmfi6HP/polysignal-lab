"""
Input: __future__, __future__.annotations, polysignal_lab.alpha.types, polysignal_lab.nautilus_runtime.order_plan
Output: order_spec_from_decision
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""


from __future__ import annotations

from polysignal_lab.alpha.types import AlphaDecision
from polysignal_lab.nautilus_runtime.order_plan import OrderSubmissionPlan, build_order_spec


def order_spec_from_decision(
    decision: AlphaDecision,
    fixed_stake_usdc: float,
    best_ask: float | None = None,
    best_bid: float | None = None,
    *,
    view_id: str = "",
) -> OrderSubmissionPlan:
    """Build Nautilus OrderFactory parameters from the trading intent SoT."""
    return build_order_spec(
        decision,
        fixed_stake_usdc=fixed_stake_usdc,
        best_ask=best_ask,
        best_bid=best_bid,
        view_id=view_id,
    )
