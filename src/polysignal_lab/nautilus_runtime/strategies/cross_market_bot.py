from __future__ import annotations

from collections.abc import Callable, Sequence

from polysignal_lab.alpha.cross_market_core import CrossMarketAlphaCore
from polysignal_lab.alpha.types import (
    AlphaDecision,
    MarketGroupView,
    MarketView,
    NautilusOrderSpec,
)
from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.decision_policy import (
    ApprovedDecision,
    DecisionPolicyActor,
    RejectedDecision,
)
from polysignal_lab.nautilus_runtime.order_mapping import order_spec_from_decision


class CrossMarketNautilusStrategy:
    """Nautilus wrapper for cross-market alpha strategies.

    Unlike single-market wrappers that evaluate one condition_id at a time,
    this wrapper receives a pre-assembled MarketGroupView containing multiple
    related condition views and evaluates them as a basket through
    CrossMarketAlphaCore.evaluate_group().
    """

    def __init__(
        self,
        *,
        core: CrossMarketAlphaCore,
        assembler: MarketViewAssembler | None = None,
        condition_ids: Sequence[str],
        strategy_name: str,
        policy: DecisionPolicyActor | None = None,
        submitter: Callable[[NautilusOrderSpec], object] | None = None,
        fixed_stake_usdc: float = 10.0,
    ) -> None:
        self.core = core
        self.assembler = assembler
        self.condition_ids = tuple(condition_ids)
        self.strategy_name = strategy_name
        self.policy = policy or DecisionPolicyActor()
        self.submitter = submitter
        self.fixed_stake_usdc = fixed_stake_usdc
        self.submitted_specs: list[NautilusOrderSpec] = []
        self.rejected_decisions: list[RejectedDecision] = []

    def evaluate_group(self, group: MarketGroupView) -> list[NautilusOrderSpec]:
        """Evaluate a pre-assembled MarketGroupView and submit approved orders."""
        decisions = self.core.evaluate_group(group)
        submitted: list[NautilusOrderSpec] = []
        for decision in decisions:
            view = group.views_by_condition_id.get(decision.condition_id)
            if view is None:
                continue
            policy_result = self.policy.evaluate(decision, view)
            if isinstance(policy_result, ApprovedDecision):
                specs = self._submit_approved(
                    policy_result, decision=decision, view=view
                )
                submitted.extend(specs)
            else:
                self.rejected_decisions.append(policy_result)
        return submitted

    def on_leg_failure(self, pair_id: str, market_id: str, side: Side) -> None:
        """Propagate leg failure to the core basket state."""
        self.core.on_leg_failure(pair_id, market_id, side)

    def _submit_approved(
        self,
        approved: ApprovedDecision,
        *,
        decision: AlphaDecision,
        view: MarketView,
    ) -> list[NautilusOrderSpec]:
        """Map an approved decision to order specs with basket pair tags."""
        book = view.book_for(approved.signal.side)
        best_ask = book.best_ask
        try:
            available = (
                sum(
                    float(size)
                    for price, size in book.ask_levels
                    if float(price) <= float(approved.signal.max_entry_price)
                )
                if book.ask_levels and approved.signal.max_entry_price is not None
                else None
            )
            spec = order_spec_from_decision(
                approved,
                fixed_stake_usdc=self.fixed_stake_usdc,
                best_ask=best_ask,
                available_shares=available,
            )
        except ValueError:
            self.rejected_decisions.append(
                RejectedDecision(
                    reason_code="ORDER_MAPPING_FAILED",
                    detail={"condition_id": decision.condition_id},
                    candidate=approved.signal,
                )
            )
            return []

        # Preserve pair_id from the decision's order_intent
        pair_id = getattr(
            getattr(decision, "order_intent", None), "pair_id", None
        )
        if pair_id:
            spec = NautilusOrderSpec(
                instrument_id=spec.instrument_id,
                side=spec.side,
                price=spec.price,
                quantity=spec.quantity,
                intent=spec.intent,
                expiry_seconds=spec.expiry_seconds,
                pair_id=spec.pair_id or pair_id,
                reduce_only=spec.reduce_only,
                hedge_leg=spec.hedge_leg,
                tags={**spec.tags, "pair_id": pair_id},
            )

        self.submitted_specs.append(spec)
        if self.submitter is not None:
            self.submitter(spec)
        return [spec]
