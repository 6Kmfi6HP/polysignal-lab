"""
Input: __future__, __future__.annotations, datetime, datetime.datetime, datetime.timezone, typing, typing.Any, polysignal_lab.alpha.types, polysignal_lab.alpha.types.AlphaDecision, polysignal_lab.alpha.types.AlphaFillEvent
Output: LowSideDualReversionAlphaCore
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from polysignal_lab.alpha.types import AlphaDecision, AlphaFillEvent, AlphaOrderEvent, MarketView, OrderIntentSpec, SideBookView
from polysignal_lab.domain.enums import OrderIntent, Side


class LowSideDualReversionAlphaCore:
    name = "low_side_dual_reversion"

    def __init__(self, config) -> None:
        self.config = config
        self._entered_markets: set[str] = set()
        self._positions: dict[str, dict[str, Any]] = {}

    def _pair_effective_cost(self, leg1_price: float, leg2_price: float) -> float:
        return leg1_price + leg2_price + 2.0 * self.config.fee_rate + self.config.slippage_buffer

    def _depth_weighted_ask(self, book: SideBookView, shares: int) -> float | None:
        if shares <= 0 or not book.ask_levels:
            return None
        remaining = float(shares)
        total_cost = 0.0
        for price, size in sorted(book.ask_levels, key=lambda level: level[0]):
            take = min(remaining, size)
            total_cost += take * price
            remaining -= take
            if remaining <= 0:
                break
        if remaining > 0:
            return None
        return total_cost / shares

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    def on_order_filled(self, event: AlphaFillEvent) -> list[AlphaDecision]:
        if event.market_id in self._positions:
            self._positions[event.market_id]["hedged"] = True
            self._entered_markets.add(event.market_id)
            return []
        self._positions[event.market_id] = {
            "side": event.side,
            "entry_price": event.fill_price,
            "filled_at": event.ts_event,
            "hedged": False,
        }
        self._entered_markets.add(event.market_id)
        return []

    def on_order_submitted(self, event: AlphaOrderEvent) -> None: pass
    def on_order_accepted(self, event: AlphaOrderEvent) -> None: pass
    def on_order_rejected(self, event: AlphaOrderEvent) -> None: pass
    def on_order_canceled(self, event: AlphaOrderEvent) -> None: pass
    def on_order_expired(self, event: AlphaOrderEvent) -> None: pass

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        if not self.config.enabled:
            return []
        if view.asset not in [asset.upper() for asset in self.config.assets]:
            return []
        if view.timeframe not in self.config.timeframes:
            return []

        position = self._positions.get(view.market_id)
        if position and not position.get("hedged", False):
            return self._try_hedge(view, position)
        if view.seconds_to_close is None:
            return []
        if view.seconds_to_close <= max(self.config.cancel_before_close_seconds, 60):
            return []
        if view.market_id in self._entered_markets:
            return []

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
        if best_price is None:
            return []

        decisions: list[AlphaDecision] = []
        for side in (Side.UP, Side.DOWN):
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
                    expiry_seconds=min(view.seconds_to_close - 60, 300),
                    pair_id=f"{view.market_id}:dual",
                ),
            )
            if decision:
                decisions.append(decision)
        return decisions

    def _try_hedge(self, view: MarketView, position: dict[str, Any]) -> list[AlphaDecision]:
        filled_side: Side = position["side"]
        hedge_side = filled_side.opposite
        filled_price = float(position["entry_price"])
        elapsed = (self._utc_now() - position["filled_at"]).total_seconds()
        decisions: list[AlphaDecision] = []

        hedge_book = view.book_for(hedge_side)
        depth_ask = self._depth_weighted_ask(hedge_book, self.config.shares_per_level)
        if depth_ask is not None:
            cost = self._pair_effective_cost(filled_price, depth_ask)
            if cost <= self.config.pair_cost_cap:
                decision = self._decision(
                    view,
                    hedge_side,
                    confidence=0.70,
                    max_entry_price=depth_ask,
                    reason_codes=("DUAL_REVERSION_HEDGE", f"HEDGE_{hedge_side.value}"),
                    metrics={
                        "pair_cost": round(cost, 4),
                        "pair_cost_cap": self.config.pair_cost_cap,
                        "filled_leg_price": filled_price,
                        "hedge_weighted_ask": depth_ask,
                        "elapsed_seconds": round(elapsed, 2),
                    },
                    order_intent=OrderIntentSpec(OrderIntent.TAKER_FAK, pair_id=f"{view.market_id}:dual"),
                    hedge_leg=True,
                )
                if decision:
                    decisions.append(decision)

        if elapsed >= self.config.max_unhedged_seconds:
            stop_ask = view.ask_for(hedge_side)
            if stop_ask is not None:
                cost = self._pair_effective_cost(filled_price, stop_ask)
                if cost <= self.config.stop_loss_hedge_cap:
                    decision = self._decision(
                        view,
                        hedge_side,
                        confidence=0.50,
                        max_entry_price=stop_ask,
                        reason_codes=("DUAL_REVERSION_STOP_LOSS", f"UNHEDGED_{elapsed:.0f}s"),
                        metrics={
                            "pair_cost": round(cost, 4),
                            "stop_loss_cap": self.config.stop_loss_hedge_cap,
                            "filled_leg_price": filled_price,
                            "elapsed_seconds": round(elapsed, 2),
                        },
                        order_intent=OrderIntentSpec(OrderIntent.TAKER_FAK, pair_id=f"{view.market_id}:dual"),
                        hedge_leg=True,
                    )
                    if decision:
                        decisions.append(decision)
        return decisions

    def _decision(self, view: MarketView, side: Side, *, confidence: float, max_entry_price: float, reason_codes: tuple[str, ...], metrics: dict[str, Any], order_intent: OrderIntentSpec, hedge_leg: bool = False) -> AlphaDecision | None:
        book = view.book_for(side)
        if book.best_ask is None:
            return None
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
            entry_reference_price=book.best_ask,
            max_entry_price=max_entry_price,
            seconds_to_close=view.seconds_to_close,
            data_freshness_ms=view.freshness.max_ms,
            reason_codes=reason_codes,
            metrics=metrics,
            order_intent=order_intent,
            hedge_leg=hedge_leg,
        )

    def evaluate_view_from_snapshot_for_test(self, snapshot) -> list[AlphaDecision]:
        from polysignal_lab.alpha.ptb_diff_core import market_view_from_snapshot

        view = market_view_from_snapshot(snapshot)
        return [] if view is None else self.evaluate(view)
