"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Callable, collections.abc.Mapping, collections.abc.Sequence, typing, typing.cast, nautilus_trader.config, nautilus_trader.config.StrategyConfig, nautilus_trader.trading.strategy, nautilus_trader.trading.strategy.Strategy, polysignal_lab.alpha.cross_market_core, polysignal_lab.alpha.cross_market_core.CrossMarketAlphaCore, polysignal_lab.alpha.types, polysignal_lab.alpha.types.(, polysignal_lab.domain.enums, polysignal_lab.nautilus_bridge.state, polysignal_lab.nautilus_bridge.state.decode_state, polysignal_lab.nautilus_bridge.state.encode_state
Output: CrossMarketNautilusStrategy
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from nautilus_trader.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy

from polysignal_lab.alpha.cross_market_core import CrossMarketAlphaCore
from polysignal_lab.alpha.types import AlphaDecision, MarketGroupView, MarketView
from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_bridge.state import save_strategy_state, load_strategy_state
from polysignal_lab.nautilus_runtime.decision_policy import (
    ApprovedDecision,
    DecisionPolicyActor,
    RejectedDecision,
)
from polysignal_lab.nautilus_runtime.order_mapping import order_spec_from_decision
from polysignal_lab.nautilus_runtime.order_plan import NautilusOrderSpec


class CrossMarketNautilusStrategy(Strategy):
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
        config: StrategyConfig | None = None,
    ) -> None:
        Strategy.__init__(self, config=config or StrategyConfig())

        self.core: CrossMarketAlphaCore = core
        self.assembler: MarketViewAssembler | None = assembler
        self.condition_ids: tuple[str, ...] = tuple(condition_ids)
        self.strategy_name: str = strategy_name
        self.policy: DecisionPolicyActor = policy or DecisionPolicyActor()
        self.submitter: Callable[[NautilusOrderSpec], object] | None = submitter
        self.fixed_stake_usdc: float = fixed_stake_usdc
        self.submitted_specs: list[NautilusOrderSpec] = []
        self.rejected_decisions: list[RejectedDecision] = []

    def on_save(self) -> dict[str, bytes]:
        return save_strategy_state(self.strategy_name, self.core)

    def on_load(self, state: Mapping[str, bytes]) -> None:
        load_strategy_state(self.strategy_name, self.core, state)

    def evaluate_group(self, group: MarketGroupView) -> list[NautilusOrderSpec]:
        """Evaluate a pre-assembled MarketGroupView and submit approved orders."""
        decisions = self.core.evaluate_group(group)
        submitted: list[NautilusOrderSpec] = []
        for decision in decisions:
            view = group.views_by_condition_id.get(decision.condition_id)
            if view is None:
                continue
            policy_result = self.policy.decide(decision, view)
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
            spec = order_spec_from_decision(
                approved,
                fixed_stake_usdc=self.fixed_stake_usdc,
                best_ask=best_ask,
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

        spec = _with_decision_pair_id(spec, decision)

        self.submitted_specs.append(spec)
        if self.submitter is not None:
            _ = self.submitter(spec)
        return [spec]


def _with_decision_pair_id(
    spec: NautilusOrderSpec,
    decision: AlphaDecision,
) -> NautilusOrderSpec:
    pair_id = getattr(getattr(decision, "order_intent", None), "pair_id", None)
    if not pair_id:
        return spec
    return NautilusOrderSpec(
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
