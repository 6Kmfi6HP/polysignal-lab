from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from polysignal_lab.alpha.types import AlphaDecision, AlphaFillEvent, MarketGroupView, MarketView, OrderIntentSpec, SideBookView
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
        self._active_baskets: dict[str, dict[str, Any]] = {}

    def register_relation(self, relation_id: str, rel_type: RelationType, condition_ids: list[str], sides: list[Side]) -> None:
        if len(condition_ids) != len(sides):
            raise ValueError(f"condition_ids ({len(condition_ids)}) and sides ({len(sides)}) must have same length")
        rel = MarketRelation(relation_id=relation_id, rel_type=rel_type, condition_ids=list(condition_ids), sides=list(sides))
        idx = len(self._relations)
        self._relations.append(rel)
        for condition_id in condition_ids:
            self._market_to_relations.setdefault(condition_id, []).append(idx)

    def on_order_filled(self, event: AlphaFillEvent) -> list[AlphaDecision]:
        self.on_notify_fill(event.market_id, event.side, event.fill_price, event.shares)
        return []

    def on_notify_fill(self, market_id: str, side: Side, fill_price: float, shares: float) -> None:
        for basket in self._active_baskets.values():
            if market_id in basket.get("markets", set()):
                basket.setdefault("fills", {})[market_id] = {
                    "side": side,
                    "fill_price": fill_price,
                    "shares": shares,
                }
                return

    def on_leg_failure(self, pair_id: str, market_id: str, side: Side) -> None:
        basket = self._active_baskets.setdefault(pair_id, {"fills": {}, "markets": set()})
        basket["failed"] = True
        basket["failed_leg"] = {"market_id": market_id, "side": side}

    def _pair_effective_cost(self, *leg_prices: float) -> float:
        return sum(leg_prices) + len(leg_prices) * self.config.fee_rate

    def _executable_buy_price(self, book: SideBookView, shares: int) -> float | None:
        return book.best_ask

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        if not self.config.enabled:
            return []
        if view.asset not in [asset.upper() for asset in self.config.assets]:
            return []
        if view.timeframe not in self.config.timeframes:
            return []
        rel_indices = self._market_to_relations.get(view.condition_id, [])
        decisions: list[AlphaDecision] = []
        for idx in rel_indices:
            decisions.extend(self._evaluate_relation(view, self._relations[idx], view.condition_id))
        return decisions

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
            exec_price = self._executable_buy_price(view.book_for(rel.sides[leg_index]), self.config.min_depth_shares)
            if exec_price is None:
                return []
            leg_exec_prices.append(exec_price)

        cost = self._pair_effective_cost(*leg_exec_prices)
        if cost >= 1.0 - self.config.min_edge:
            return []

        relation_code = "EXHAUSTIVE_MUTUALLY_EXCLUSIVE" if rel.rel_type == RelationType.EXHAUSTIVE_MUTUALLY_EXCLUSIVE else "INCLUSION"
        confidence = min(0.90, 0.60 + (1.0 - cost) * 2.0)
        basket = self._active_baskets.setdefault(rel.relation_id, {"fills": {}, "markets": set(), "failed": False})
        basket["markets"].update(item.market_id for item in views)

        decisions: list[AlphaDecision] = []
        n_legs = len(views)
        leg_price_map = {condition_id: round(price, 4) for condition_id, price in zip(rel.condition_ids, leg_exec_prices, strict=True)}
        for leg_index, view in enumerate(views):
            decisions.append(
                self._decision(
                    view,
                    rel.sides[leg_index],
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
                    pair_id=rel.relation_id,
                )
            )
        return decisions

    def _evaluate_relation(self, view: MarketView, rel: MarketRelation, triggered_condition_id: str) -> list[AlphaDecision]:
        try:
            leg_index = rel.condition_ids.index(triggered_condition_id)
        except ValueError:
            return []
        target_side = rel.sides[leg_index]
        target_book = view.book_for(target_side)
        if target_book.best_ask is None:
            return []
        exec_price = self._executable_buy_price(target_book, self.config.min_depth_shares)
        if exec_price is None:
            return []

        cost_valid = False
        reason_codes: tuple[str, ...] = ()
        metrics: dict[str, Any] = {}
        if rel.rel_type == RelationType.EXHAUSTIVE_MUTUALLY_EXCLUSIVE:
            n_legs = len(rel.condition_ids)
            threshold = (1.0 - self.config.min_edge) / n_legs
            if exec_price <= threshold:
                cost = sum(exec_price for _ in range(n_legs)) + n_legs * self.config.fee_rate
                if cost < 1.0:
                    cost_valid = True
                    reason_codes = ("EXHAUSTIVE_MUTUALLY_EXCLUSIVE", f"COST_{cost:.4f}", f"THRESHOLD_{threshold:.4f}", f"LEG_{leg_index}_OF_{n_legs}")
                    metrics = {
                        "relation_id": rel.relation_id,
                        "relation_type": rel.rel_type.value,
                        "leg_index": leg_index,
                        "n_legs": n_legs,
                        "estimated_pair_cost": round(cost, 4),
                        "min_edge": self.config.min_edge,
                        "leg_exec_price": exec_price,
                        "threshold": round(threshold, 4),
                    }
        elif rel.rel_type == RelationType.INCLUSION and len(rel.condition_ids) >= 2:
            if exec_price <= (1.0 - self.config.min_edge) * 0.5:
                est_cost = 2.0 * exec_price + 2.0 * self.config.fee_rate
                if est_cost < 1.0:
                    cost_valid = True
                    role = "INCLUSION_A" if leg_index == 0 else "INCLUSION_B"
                    reason_codes = (f"INCLUSION_{'A' if leg_index == 0 else 'B'}", f"COST_{est_cost:.4f}")
                    metrics = {
                        "relation_id": rel.relation_id,
                        "relation_type": rel.rel_type.value,
                        "leg_index": leg_index,
                        "estimated_pair_cost": round(est_cost, 4),
                        "min_edge": self.config.min_edge,
                        "leg_exec_price": exec_price,
                        "role": role,
                    }
        if not cost_valid:
            return []

        confidence = min(0.90, 0.60 + (1.0 - metrics.get("estimated_pair_cost", 1.0)) * 2.0)
        basket = self._active_baskets.setdefault(rel.relation_id, {"fills": {}, "markets": set(), "failed": False})
        basket["markets"].add(view.market_id)
        return [
            self._decision(
                view,
                target_side,
                confidence=confidence,
                max_entry_price=exec_price,
                reason_codes=reason_codes,
                metrics=metrics,
                pair_id=rel.relation_id,
            )
        ]

    def _decision(self, view: MarketView, side: Side, *, confidence: float, max_entry_price: float, reason_codes: tuple[str, ...], metrics: dict[str, Any], pair_id: str) -> AlphaDecision:
        book = view.book_for(side)
        return AlphaDecision(
            strategy=self.name,
            asset=view.asset,
            timeframe=view.timeframe,
            market_id=view.market_id,
            market_slug=view.market_slug,
            condition_id=view.condition_id,
            token_id=book.token_id,
            side=side,
            confidence=confidence,
            entry_reference_price=book.best_ask or max_entry_price,
            max_entry_price=max_entry_price,
            seconds_to_close=view.seconds_to_close,
            data_freshness_ms=view.freshness.max_ms,
            reason_codes=reason_codes,
            metrics=metrics,
            order_intent=OrderIntentSpec(OrderIntent.TAKER_FOK, pair_id=pair_id),
        )

    def evaluate_view_from_snapshot_for_test(self, snapshot) -> list[AlphaDecision]:
        from polysignal_lab.alpha.ptb_diff_core import market_view_from_snapshot

        view = market_view_from_snapshot(snapshot)
        return [] if view is None else self.evaluate(view)
