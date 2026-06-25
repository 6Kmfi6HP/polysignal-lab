from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from polysignal_lab.alpha.types import AlphaDecision, AlphaFillEvent, AlphaOrderEvent, MarketView, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent, Side

_FEE_RATE = 0.01
_SLIPPAGE_BUFFER = 0.01


class PreOrderMarketAlphaCore:
    name = "pre_order_market"

    def __init__(self, config) -> None:
        self.config = config
        self._pre_ordered: set[str] = set()
        self._entered_markets: set[str] = set()
        self._positions: dict[str, dict[str, Any]] = {}
        self._reconciled: set[str] = set()

    @staticmethod
    def _pair_effective_cost(leg1_price: float, leg2_price: float) -> float:
        return leg1_price + leg2_price + 2.0 * _FEE_RATE + _SLIPPAGE_BUFFER

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    def _has_started(self, view: MarketView) -> bool:
        return view.start_ts is None or self._utc_now() >= view.start_ts

    def _is_in_pre_order_window(self, view: MarketView) -> bool:
        if view.start_ts is None:
            return False
        now_ts = self._utc_now().timestamp()
        return view.start_ts.timestamp() - self.config.seconds_before_open <= now_ts < view.start_ts.timestamp() + self.config.seconds_after_open_expiry

    def on_order_submitted(self, event: AlphaOrderEvent) -> None:
        self._pre_ordered.add(event.market_id)

    def on_order_accepted(self, event: AlphaOrderEvent) -> None:
        self.on_order_submitted(event)

    def on_order_rejected(self, event: AlphaOrderEvent) -> None:
        self._pre_ordered.discard(event.market_id)

    def on_order_canceled(self, event: AlphaOrderEvent) -> None:
        self._pre_ordered.discard(event.market_id)

    def on_order_expired(self, event: AlphaOrderEvent) -> None:
        self._pre_ordered.discard(event.market_id)

    def on_order_filled(self, event: AlphaFillEvent) -> list[AlphaDecision]:
        self._pre_ordered.add(event.market_id)
        position = self._positions.get(event.market_id)
        if position is not None:
            if position["side"] != event.side:
                position["hedged"] = True
                self._entered_markets.add(event.market_id)
            else:
                position["entry_price"] = (position["entry_price"] + event.fill_price) / 2.0
            return []
        self._positions[event.market_id] = {
            "side": event.side,
            "entry_price": event.fill_price,
            "filled_at": event.ts_event,
            "hedged": False,
        }
        self._entered_markets.add(event.market_id)
        return []

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        if not self.config.enabled:
            return []
        if view.asset not in [asset.upper() for asset in self.config.assets]:
            return []
        if view.timeframe not in self.config.timeframes:
            return []

        position = self._positions.get(view.market_id)
        if position and not position.get("hedged", False):
            return self._reconcile_after_open(view, position)
        if view.market_id in self._entered_markets:
            return []
        if not self._is_in_pre_order_window(view):
            return []
        if view.market_id in self._pre_ordered:
            return []
        if view.start_ts is None:
            return []

        decisions: list[AlphaDecision] = []
        now = self._utc_now()
        for price, shares in self.config.ladder:
            for side in (Side.UP, Side.DOWN):
                ask = view.ask_for(side)
                if ask is not None and price >= ask:
                    continue
                cost = self._pair_effective_cost(price, price)
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

    def _reconcile_after_open(self, view: MarketView, position: dict[str, Any]) -> list[AlphaDecision]:
        if view.market_id in self._reconciled:
            return []
        filled_side: Side = position["side"]
        hedge_side = filled_side.opposite
        filled_price = float(position["entry_price"])
        hedge_ask = view.ask_for(hedge_side)
        if hedge_ask is None:
            return []
        cost = self._pair_effective_cost(filled_price, hedge_ask)
        if cost > self.config.reconcile_max_pair_cost:
            self._reconciled.add(view.market_id)
            return []
        self._reconciled.add(view.market_id)
        decision = self._decision(
            view,
            hedge_side,
            confidence=0.55,
            max_entry_price=hedge_ask,
            reason_codes=("PRE_ORDER_RECONCILE", f"HEDGE_{hedge_side.value}"),
            metrics={
                "pair_cost": round(cost, 4),
                "reconcile_max_pair_cost": self.config.reconcile_max_pair_cost,
                "filled_leg_price": filled_price,
                "hedge_ask": hedge_ask,
            },
            order_intent=OrderIntentSpec(OrderIntent.TAKER_FAK, pair_id=f"{view.market_id}:pre"),
            hedge_leg=True,
        )
        return [decision] if decision else []

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
