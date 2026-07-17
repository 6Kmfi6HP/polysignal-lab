"""
Input: __future__, __future__.annotations, datetime, datetime.datetime, datetime.timezone, typing, typing.Any, polysignal_lab.alpha.types, polysignal_lab.alpha.types.AlphaDecision, polysignal_lab.alpha.types.AlphaFillEvent
Output: PreOrderMarketAlphaCore
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""






from __future__ import annotations

from datetime import datetime
from typing import Any

from polysignal_lab.alpha.helpers import (
    HedgeDecisionContext,
    HedgeDecisionSpec,
    SIDES,
    OrderDecisionSpec,
    build_order_decision,
    build_hedge_order_decision,
    binary_pair_effective_cost,
    enabled_for_view,
)
from polysignal_lab.alpha.types import (
    AlphaDecision,
    CachedPositionView,
    MarketView,
    OrderIntentSpec,
)
from polysignal_lab.domain.enums import OrderIntent, Side


class PreOrderMarketAlphaCore:
    name = "pre_order_market"

    def __init__(self, config) -> None:
        self.config = config

    def _now_from(self, view: MarketView) -> datetime:
        """Return the logical clock time from the view."""
        return view.created_at

    def _has_started(self, view: MarketView) -> bool:
        return view.start_ts is None or self._now_from(view) >= view.start_ts

    def _is_in_pre_order_window(self, view: MarketView) -> bool:
        if view.start_ts is None:
            return False
        now_ts = self._now_from(view).timestamp()
        return view.start_ts.timestamp() - self.config.seconds_before_open <= now_ts < view.start_ts.timestamp() + self.config.seconds_after_open_expiry

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        if not enabled_for_view(self.config, view):
            return []

        position = view.trading.unhedged_leg(self.name, view.market_id)
        if position is not None:
            return self._reconcile_after_open(view, position)
        if not self._is_in_pre_order_window(view):
            return []
        if view.trading.has_market_activity(self.name, view.market_id):
            return []
        if view.start_ts is None:
            return []

        decisions: list[AlphaDecision] = []
        now = self._now_from(view)
        for price, shares in self.config.ladder:
            for side in SIDES:
                ask = view.ask_for(side)
                if ask is not None and price >= ask:
                    continue
                cost = binary_pair_effective_cost(price, price)
                decision = self._decision(
                    view,
                    side,
                    confidence=0.55,
                    max_entry_price=price,
                    reason_codes=("PRE_ORDER_BID", f"PRICE_{price}"),
                    metrics={
                        "pair_cost": round(cost, 4),
                        "expiry_after_open": round(self.config.seconds_after_open_expiry),
                        "pre_order_shares": shares,
                        "expiry_ts": view.start_ts.timestamp() + self.config.seconds_after_open_expiry,
                    },
                    order_intent=OrderIntentSpec(
                        OrderIntent.PASSIVE_GTD,
                        expiry_seconds=max(1, int(view.start_ts.timestamp() + self.config.seconds_after_open_expiry - now.timestamp())),
                        pair_id=f"{view.market_id}:pre",
                    ),
                )
                if decision:
                    decisions.append(decision)
        return decisions

    def _reconcile_after_open(self, view: MarketView, position: CachedPositionView) -> list[AlphaDecision]:
        if view.trading.has_hedge_order(self.name, view.market_id):
            return []
        hedge_side = position.side.opposite
        filled_price = position.avg_entry_price
        hedge_ask = view.ask_for(hedge_side)
        if hedge_ask is None:
            return []
        cost = binary_pair_effective_cost(filled_price, hedge_ask)
        if cost > self.config.reconcile_max_pair_cost:
            return []
        decision = build_hedge_order_decision(
            HedgeDecisionContext(self.name, view, hedge_side, filled_price, 0.0),
            HedgeDecisionSpec(
                confidence=0.55,
                hedge_price=hedge_ask,
                pair_cost=cost,
                cap_metric="reconcile_max_pair_cost",
                cap_value=self.config.reconcile_max_pair_cost,
                reason_codes=("PRE_ORDER_RECONCILE", f"HEDGE_{hedge_side.value}"),
                order_intent=OrderIntentSpec(OrderIntent.TAKER_FAK, pair_id=f"{view.market_id}:pre"),
                hedge_price_metric="hedge_ask",
            ),
        )
        return [decision] if decision else []

    def _decision(self, view: MarketView, side: Side, *, confidence: float, max_entry_price: float, reason_codes: tuple[str, ...], metrics: dict[str, Any], order_intent: OrderIntentSpec, hedge_leg: bool = False) -> AlphaDecision | None:
        return build_order_decision(
            self.name,
            view,
            side,
            OrderDecisionSpec(
                confidence=confidence,
                max_entry_price=max_entry_price,
                reason_codes=reason_codes,
                metrics=metrics,
                order_intent=order_intent,
                hedge_leg=hedge_leg,
            ),
        )
