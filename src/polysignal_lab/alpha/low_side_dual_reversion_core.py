"""
Input: __future__, __future__.annotations, datetime, datetime.datetime, datetime.timezone, typing, typing.Any, polysignal_lab.alpha.types, polysignal_lab.alpha.types.AlphaDecision, polysignal_lab.alpha.types.AlphaFillEvent
Output: LowSideDualReversionAlphaCore
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from polysignal_lab.alpha.helpers import (
    HedgeDecisionContext,
    HedgeDecisionSpec,
    SIDES,
    OrderDecisionSpec,
    active_unhedged_position,
    build_order_decision,
    build_hedge_order_decision,
    depth_weighted_ask,
    enabled_for_view,
    evaluate_from_snapshot_for_test,
    position_hedge_context,
    record_two_leg_fill,
)
from polysignal_lab.alpha.types import AlphaDecision, AlphaFillEvent, AlphaOrderEvent, MarketView, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent, Side


class LowSideDualReversionAlphaCore:
    name = "low_side_dual_reversion"

    def __init__(self, config) -> None:
        self.config = config
        self._entered_markets: set[str] = set()
        self._positions: dict[str, dict[str, Any]] = {}

    def _pair_effective_cost(self, leg1_price: float, leg2_price: float) -> float:
        return leg1_price + leg2_price + 2.0 * self.config.fee_rate + self.config.slippage_buffer

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    def _now_from(self, view: MarketView) -> datetime:
        """Return the logical clock time from the view."""
        return view.created_at

    def on_order_filled(self, event: AlphaFillEvent) -> list[AlphaDecision]:
        record_two_leg_fill(
            self._positions,
            self._entered_markets,
            event,
            enter_on_first_fill=True,
        )
        return []

    def on_order_submitted(self, event: AlphaOrderEvent) -> None: pass
    def on_order_accepted(self, event: AlphaOrderEvent) -> None: pass
    def on_order_rejected(self, event: AlphaOrderEvent) -> None: pass
    def on_order_canceled(self, event: AlphaOrderEvent) -> None: pass
    def on_order_expired(self, event: AlphaOrderEvent) -> None: pass

    # -- guard helpers -------------------------------------------------------

    def _validate_inputs(self, view: MarketView) -> bool:
        return enabled_for_view(self.config, view)

    def _active_position(self, view: MarketView) -> dict[str, Any] | None:
        position = active_unhedged_position(self._positions, view.market_id)
        return dict(position) if position is not None else None

    def _should_skip(self, view: MarketView) -> bool:
        if view.seconds_to_close is None:
            return True
        if view.seconds_to_close <= max(self.config.cancel_before_close_seconds, 60):
            return True
        if view.market_id in self._entered_markets:
            return True
        return False

    def _find_best_price(self, view: MarketView) -> float | None:
        best_cost = float("inf")
        best_price: float | None = None
        for bid_price in self.config.bid_prices:
            cost = self._pair_effective_cost(bid_price, bid_price)
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
        best_cost = self._pair_effective_cost(best_price, best_price)
        decisions: list[AlphaDecision] = []
        for side in SIDES:
            decision = self._decision(
                view,
                side,
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
            )
            if decision:
                decisions.append(decision)
        return decisions

    # -- entry point ---------------------------------------------------------

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        if not self._validate_inputs(view):
            return []
        pos = self._active_position(view)
        if pos is not None:
            return self._try_hedge(view, pos)
        if self._should_skip(view):
            return []
        best_price = self._find_best_price(view)
        return [] if best_price is None else self._build_decisions(view, best_price)

    def _try_hedge(self, view: MarketView, position: dict[str, Any]) -> list[AlphaDecision]:
        hedge = position_hedge_context(position, self._now_from(view))
        decisions: list[AlphaDecision] = []

        hedge_book = view.book_for(hedge.hedge_side)
        depth_ask = depth_weighted_ask(hedge_book, self.config.shares_per_level)
        if depth_ask is not None:
            cost = self._pair_effective_cost(hedge.filled_price, depth_ask)
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
                cost = self._pair_effective_cost(hedge.filled_price, stop_ask)
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

    def evaluate_view_from_snapshot_for_test(self, snapshot) -> list[AlphaDecision]:
        return evaluate_from_snapshot_for_test(self, snapshot)
