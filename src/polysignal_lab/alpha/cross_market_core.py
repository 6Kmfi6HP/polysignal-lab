"""
Input: __future__, __future__.annotations, dataclasses, dataclasses.dataclass, enum, enum.StrEnum, polysignal_lab.alpha.helpers, polysignal_lab.alpha.helpers.(, polysignal_lab.alpha.types, polysignal_lab.alpha.types.AlphaDecision
Output: RelationType, MarketRelation, CrossMarketAlphaCore
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""









from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from polysignal_lab.alpha.helpers import (
    OrderDecisionSpec,
    build_order_decision,
    depth_weighted_ask,
)
from polysignal_lab.alpha.types import AlphaDecision, MarketGroupView, MarketView, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent, Side


class RelationType(StrEnum):
    EXHAUSTIVE_MUTUALLY_EXCLUSIVE = "EXHAUSTIVE_MUTUALLY_EXCLUSIVE"
    INCLUSION = "INCLUSION"


@dataclass
class MarketRelation:
    relation_id: str
    rel_type: RelationType
    condition_ids: list[str]
    sides: list[Side]


class CrossMarketAlphaCore:
    name = "cross_market_bot"

    def __init__(self, config) -> None:
        self.config = config
        self._relations: list[MarketRelation] = []
        self._market_to_relations: dict[str, list[int]] = {}

    def register_relation(self, relation_id: str, rel_type: RelationType, condition_ids: list[str], sides: list[Side]) -> None:
        if len(condition_ids) != len(sides):
            raise ValueError(f"condition_ids ({len(condition_ids)}) and sides ({len(sides)}) must have same length")
        rel = MarketRelation(relation_id=relation_id, rel_type=rel_type, condition_ids=list(condition_ids), sides=list(sides))
        idx = len(self._relations)
        self._relations.append(rel)
        for condition_id in condition_ids:
            self._market_to_relations.setdefault(condition_id, []).append(idx)

    def _pair_effective_cost(self, *leg_prices: float) -> float:
        return sum(leg_prices) + len(leg_prices) * self.config.fee_rate

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        """Cross-market requires evaluate_group; single-market leg fabrication removed."""
        _ = view
        return []

    def evaluate_group(self, view: MarketGroupView) -> list[AlphaDecision]:
        if not self.config.enabled:
            return []
        candidates: list[AlphaDecision] = []
        for rel in self._relations:
            if view.relation_id != "all_markets" and rel.relation_id != view.relation_id:
                continue
            if not all(condition_id in view.views_by_condition_id for condition_id in rel.condition_ids):
                continue
            candidates.extend(self._evaluate_relation_group(view, rel))
        return candidates

    def _evaluate_relation_group(self, group: MarketGroupView, rel: MarketRelation) -> list[AlphaDecision]:
        views = [group.views_by_condition_id[condition_id] for condition_id in rel.condition_ids]
        enabled_assets = {asset.upper() for asset in self.config.assets}
        if any(view.asset not in enabled_assets for view in views):
            return []
        if any(view.timeframe not in self.config.timeframes for view in views):
            return []

        leg_exec_prices: list[float] = []
        for leg_index, view in enumerate(views):
            exec_price = depth_weighted_ask(view.book_for(rel.sides[leg_index]), self.config.min_depth_shares)
            if exec_price is None:
                return []
            leg_exec_prices.append(exec_price)

        cost = self._pair_effective_cost(*leg_exec_prices)
        if cost >= 1.0 - self.config.min_edge:
            return []

        relation_code = "EXHAUSTIVE_MUTUALLY_EXCLUSIVE" if rel.rel_type == RelationType.EXHAUSTIVE_MUTUALLY_EXCLUSIVE else "INCLUSION"
        confidence = min(0.90, 0.60 + (1.0 - cost) * 2.0)
        decisions: list[AlphaDecision] = []
        n_legs = len(views)
        leg_price_map = {condition_id: round(price, 4) for condition_id, price in zip(rel.condition_ids, leg_exec_prices, strict=True)}
        for leg_index, view in enumerate(views):
            decision = build_order_decision(
                self.name,
                view,
                rel.sides[leg_index],
                OrderDecisionSpec(
                    confidence=confidence,
                    max_entry_price=leg_exec_prices[leg_index],
                    reason_codes=(relation_code, f"COST_{cost:.4f}", f"LEG_{leg_index}_OF_{n_legs}"),
                    metrics={
                        "relation_id": rel.relation_id,
                        "relation_type": rel.rel_type.value,
                        "leg_index": leg_index,
                        "n_legs": n_legs,
                        "estimated_pair_cost": round(cost, 4),
                        "min_edge": self.config.min_edge,
                        "leg_exec_price": leg_exec_prices[leg_index],
                        "leg_exec_prices": leg_price_map,
                    },
                    order_intent=OrderIntentSpec(OrderIntent.TAKER_FOK, pair_id=rel.relation_id),
                    fallback_to_max_entry=True,
                ),
            )
            if decision is not None:
                decisions.append(decision)
        return decisions
