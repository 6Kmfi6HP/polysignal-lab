from __future__ import annotations

from polysignal_lab.alpha.cross_market_core import CrossMarketAlphaCore, MarketRelation, RelationType
from polysignal_lab.alpha.ptb_diff_core import decision_to_signal, market_view_from_snapshot
from polysignal_lab.alpha.types import AlphaFillEvent, MarketGroupView
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.domain.snapshot_batch import CrossMarketEvaluationContext
from polysignal_lab.strategies.base import BaseStrategy
from polysignal_lab.strategies.config import CrossMarketBotConfig
from polysignal_lab.utils import utc_now


class CrossMarketBotStrategy(BaseStrategy):
    name = "cross_market_bot"

    def __init__(self, config: CrossMarketBotConfig):
        self.config = config
        self.core = CrossMarketAlphaCore(config)

    def register_relation(self, relation_id: str, rel_type: RelationType, condition_ids: list[str], sides: list[Side]) -> None:
        self.core.register_relation(relation_id, rel_type, condition_ids, sides)

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        view = market_view_from_snapshot(snapshot)
        if view is None:
            return []
        return [
            decision_to_signal(decision, snapshot.snapshot_id, self.freshness_policy)
            for decision in self.core.evaluate(view)
        ]

    def evaluate_group(self, context: CrossMarketEvaluationContext) -> list[SignalCandidate]:
        group = self._group_view(context)
        if group is None:
            return []
        return [
            decision_to_signal(decision, context.batch.batch_id, self.freshness_policy)
            for decision in self.core.evaluate_group(group)
        ]

    def notify_fill(self, market_id: str, side: Side, fill_price: float, shares: float) -> None:
        self.core.on_order_filled(
            AlphaFillEvent(
                strategy=self.name,
                market_id=market_id,
                condition_id="",
                token_id="",
                side=side,
                order_id=f"{self.name}:{market_id}:{side.value}",
                client_order_id=None,
                reason=None,
                ts_event=utc_now(),
                metrics={},
                fill_price=fill_price,
                shares=shares,
                liquidity_side=None,
            )
        )

    def notify_leg_failure(self, pair_id: str, market_id: str, side: Side) -> None:
        self.core.on_leg_failure(pair_id, market_id, side)

    def _group_view(self, context: CrossMarketEvaluationContext) -> MarketGroupView | None:
        views = {}
        for condition_id, snapshot in context.snapshots_by_condition_id.items():
            view = market_view_from_snapshot(snapshot)
            if view is None:
                return None
            views[condition_id] = view
        return MarketGroupView(
            group_id=context.batch.batch_id,
            relation_id=context.relation_id,
            created_at=context.batch.as_of,
            views_by_condition_id=views,
            max_source_skew_ms=context.batch.max_source_skew_ms,
            metrics={},
        )

    @property
    def _relations(self):
        return self.core._relations

    @_relations.setter
    def _relations(self, value):
        self.core._relations = value

    @property
    def _market_to_relations(self):
        return self.core._market_to_relations

    @_market_to_relations.setter
    def _market_to_relations(self, value):
        self.core._market_to_relations = value

    @property
    def _active_baskets(self):
        return self.core._active_baskets

    @_active_baskets.setter
    def _active_baskets(self, value):
        self.core._active_baskets = value
