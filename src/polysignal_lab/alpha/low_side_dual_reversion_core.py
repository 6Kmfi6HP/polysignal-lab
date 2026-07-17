"""
Input: __future__, __future__.annotations, polysignal_lab.alpha.helpers, polysignal_lab.alpha.helpers.(, polysignal_lab.alpha.types, polysignal_lab.alpha.types.(, polysignal_lab.domain.enums, polysignal_lab.domain.enums.OrderIntent, polysignal_lab.domain.enums.Side
Output: LowSideDualReversionAlphaCore
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""








from __future__ import annotations

from polysignal_lab.alpha.helpers import (
    HedgeDecisionContext,
    HedgeDecisionSpec,
    SIDES,
    OrderDecisionSpec,
    build_order_decision,
    build_hedge_order_decision,
    binary_pair_effective_cost,
    depth_weighted_ask,
    enabled_for_view,
    hedge_context_from_position,
)
from polysignal_lab.alpha.types import (
    AlphaDecision,
    CachedPositionView,
    MarketView,
    OrderIntentSpec,
)
from polysignal_lab.domain.enums import OrderIntent, Side


class LowSideDualReversionAlphaCore:
    name = "low_side_dual_reversion"

    def __init__(self, config) -> None:
        self.config = config

    # -- guard helpers -------------------------------------------------------

    def _validate_inputs(self, view: MarketView) -> bool:
        return enabled_for_view(self.config, view)

    def _active_position(self, view: MarketView) -> CachedPositionView | None:
        return view.trading.unhedged_leg(self.name, view.market_id)

    def _should_skip(self, view: MarketView) -> bool:
        if view.seconds_to_close is None:
            return True
        if view.seconds_to_close <= max(self.config.cancel_before_close_seconds, 60):
            return True
        if view.trading.has_market_activity(self.name, view.market_id):
            return True
        return False

    def _find_best_price(self, view: MarketView) -> float | None:
        best_cost = float("inf")
        best_price: float | None = None
        for bid_price in self.config.bid_prices:
            cost = binary_pair_effective_cost(
                bid_price,
                bid_price,
                fee_rate=self.config.fee_rate,
                slippage_buffer=self.config.slippage_buffer,
            )
            if cost > self.config.pair_cost_cap:
                continue
            up_ask = view.ask_for(Side.UP)
            down_ask = view.ask_for(Side.DOWN)
            if up_ask is not None and bid_price >= up_ask:
                continue
            if down_ask is not None and bid_price >= down_ask:
                continue
            if cost < best_cost:
                best_cost = cost
                best_price = bid_price
        return best_price

    # -- decision helpers ----------------------------------------------------

    def _build_decisions(self, view: MarketView, best_price: float) -> list[AlphaDecision]:
        seconds_to_close = view.seconds_to_close
        if seconds_to_close is None:
            return []
        best_cost = binary_pair_effective_cost(
            best_price,
            best_price,
            fee_rate=self.config.fee_rate,
            slippage_buffer=self.config.slippage_buffer,
        )
        decisions: list[AlphaDecision] = []
        for side in SIDES:
            decision = build_order_decision(
                self.name,
                view,
                side,
                OrderDecisionSpec(
                    confidence=0.60,
                    max_entry_price=best_price,
                    reason_codes=("DUAL_REVERSION_BID", f"PRICE_{best_price}"),
                    metrics={
                        "pair_cost": round(best_cost, 4),
                        "pair_cost_cap": self.config.pair_cost_cap,
                        "bid_price": best_price,
                        "shares": self.config.shares_per_level,
                    },
                    order_intent=OrderIntentSpec(
                        OrderIntent.PASSIVE_GTD,
                        expiry_seconds=min(seconds_to_close - 60, 300),
                        pair_id=f"{view.market_id}:dual",
                    ),
                ),
            )
            if decision:
                decisions.append(decision)
        return decisions

    # -- entry point ---------------------------------------------------------

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        if not self._validate_inputs(view):
            return []
        position = self._active_position(view)
        if position is not None:
            return self._try_hedge(view, position)
        if self._should_skip(view):
            return []
        best_price = self._find_best_price(view)
        return [] if best_price is None else self._build_decisions(view, best_price)

    def _try_hedge(self, view: MarketView, position: CachedPositionView) -> list[AlphaDecision]:
        if view.trading.has_hedge_order(self.name, view.market_id):
            return []
        hedge = hedge_context_from_position(position, view.created_at)
        decisions: list[AlphaDecision] = []

        hedge_book = view.book_for(hedge.hedge_side)
        depth_ask = depth_weighted_ask(hedge_book, self.config.shares_per_level)
        if depth_ask is not None:
            cost = binary_pair_effective_cost(
                hedge.filled_price,
                depth_ask,
                fee_rate=self.config.fee_rate,
                slippage_buffer=self.config.slippage_buffer,
            )
            if cost <= self.config.pair_cost_cap:
                decision = build_hedge_order_decision(
                    HedgeDecisionContext(
                        self.name,
                        view,
                        hedge.hedge_side,
                        hedge.filled_price,
                        hedge.elapsed_seconds,
                    ),
                    HedgeDecisionSpec(
                        confidence=0.70,
                        hedge_price=depth_ask,
                        pair_cost=cost,
                        cap_metric="pair_cost_cap",
                        cap_value=self.config.pair_cost_cap,
                        reason_codes=("DUAL_REVERSION_HEDGE", f"HEDGE_{hedge.hedge_side.value}"),
                        order_intent=OrderIntentSpec(OrderIntent.TAKER_FAK, pair_id=f"{view.market_id}:dual"),
                        hedge_price_metric="hedge_weighted_ask",
                    ),
                )
                if decision:
                    decisions.append(decision)

        if hedge.elapsed_seconds >= self.config.max_unhedged_seconds:
            stop_ask = view.ask_for(hedge.hedge_side)
            if stop_ask is not None:
                cost = binary_pair_effective_cost(
                    hedge.filled_price,
                    stop_ask,
                    fee_rate=self.config.fee_rate,
                    slippage_buffer=self.config.slippage_buffer,
                )
                if cost <= self.config.stop_loss_hedge_cap:
                    decision = build_hedge_order_decision(
                        HedgeDecisionContext(
                            self.name,
                            view,
                            hedge.hedge_side,
                            hedge.filled_price,
                            hedge.elapsed_seconds,
                        ),
                        HedgeDecisionSpec(
                            confidence=0.50,
                            hedge_price=stop_ask,
                            pair_cost=cost,
                            cap_metric="stop_loss_cap",
                            cap_value=self.config.stop_loss_hedge_cap,
                            reason_codes=("DUAL_REVERSION_STOP_LOSS", f"UNHEDGED_{hedge.elapsed_seconds:.0f}s"),
                            order_intent=OrderIntentSpec(OrderIntent.TAKER_FAK, pair_id=f"{view.market_id}:dual"),
                        ),
                    )
                    if decision:
                        decisions.append(decision)
        return decisions


