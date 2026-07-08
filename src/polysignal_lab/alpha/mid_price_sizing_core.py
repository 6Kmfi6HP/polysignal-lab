"""
Input: __future__, __future__.annotations, statistics, statistics.mean, typing, typing.Any, polysignal_lab.alpha.types, polysignal_lab.alpha.types.AlphaDecision, polysignal_lab.alpha.types.AlphaFillEvent, polysignal_lab.alpha.types.AlphaOrderEvent
Output: MidPriceSizingAlphaCore
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from statistics import mean
from typing import Any

from polysignal_lab.alpha.types import AlphaDecision, AlphaFillEvent, AlphaOrderEvent, MarketView, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent, Side


class MidPriceSizingAlphaCore:
    name = "mid_price_sizing"

    def __init__(self, config) -> None:
        self.config = config
        self._layer_count: dict[str, int] = {}
        self._entry_prices: dict[str, list[float]] = {}

    @staticmethod
    def _pos_key(market_id: str, side: Side) -> str:
        return f"{market_id}:{side.value}"

    def _avg_cost(self, key: str) -> float | None:
        prices = self._entry_prices.get(key, [])
        return mean(prices) if prices else None

    def reset_position(self, market_id: str, side: Side | None = None) -> None:
        if side is not None:
            key = self._pos_key(market_id, side)
            self._layer_count.pop(key, None)
            self._entry_prices.pop(key, None)
            return
        for item in (Side.UP, Side.DOWN):
            key = self._pos_key(market_id, item)
            self._layer_count.pop(key, None)
            self._entry_prices.pop(key, None)

    def on_order_filled(self, event: AlphaFillEvent) -> list[AlphaDecision]:
        key = self._pos_key(event.market_id, event.side)
        self._layer_count[key] = self._layer_count.get(key, 0) + 1
        self._entry_prices.setdefault(key, []).append(event.fill_price)
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
        if not self._regime_gate(view):
            return []
        decisions: list[AlphaDecision] = []
        for side in (Side.UP, Side.DOWN):
            decisions.extend(self._evaluate_side(view, side))
        return decisions

    def _regime_gate(self, view: MarketView) -> bool:
        for side in (Side.UP, Side.DOWN):
            ask = view.ask_for(side)
            if ask is None:
                return False
            if not (self.config.entry_center - self.config.entry_band <= ask <= self.config.entry_center + self.config.entry_band):
                return False
        if view.spot is None or view.spot.price <= 0:
            return False
        if view.seconds_to_close is not None and view.seconds_to_close < 60:
            return False
        return True

    def _evaluate_side(self, view: MarketView, side: Side) -> list[AlphaDecision]:
        key = self._pos_key(view.market_id, side)
        current_layers = self._layer_count.get(key, 0)
        current_avg = self._avg_cost(key)
        book = view.book_for(side)
        ask = book.best_ask
        bid = book.best_bid
        if ask is None or bid is None:
            return []

        if current_layers > 0 and current_avg is not None:
            if bid <= self.config.stop_price:
                return self._close_signal(
                    view,
                    side,
                    ask,
                    bid,
                    current_layers,
                    current_avg,
                    "CLOSE_STOP_LOSS",
                    "stop_price",
                    self.config.stop_price,
                    reason_codes=("STOP_LOSS", f"BID_{bid:.4f}"),
                )
            if bid >= self.config.take_profit_price:
                return self._close_signal(
                    view,
                    side,
                    ask,
                    bid,
                    current_layers,
                    current_avg,
                    "CLOSE_TAKE_PROFIT",
                    "take_profit_price",
                    self.config.take_profit_price,
                    reason_codes=("TAKE_PROFIT", f"BID_{bid:.4f}"),
                )

        if current_layers >= self.config.max_layers:
            return []
        if current_layers == 0:
            return self._evaluate_entry(view, side, ask)
        if current_avg is not None:
            return self._evaluate_addition(view, side, ask, current_layers, current_avg)
        return []

    def _close_signal(
        self,
        view: MarketView,
        side: Side,
        ask: float,
        bid: float,
        current_layers: int,
        current_avg: float,
        action: str,
        threshold_key: str,
        threshold_value: float,
        *,
        reason_codes: tuple[str, ...],
    ) -> list[AlphaDecision]:
        return self._make_signal(
            view,
            side,
            ask,
            confidence=0.30,
            reason_codes=reason_codes,
            metrics={
                "action": action,
                "current_layers": current_layers,
                "avg_cost": current_avg,
                "bid": bid,
                threshold_key: threshold_value,
            },
        )

    def _evaluate_entry(self, view: MarketView, side: Side, ask: float) -> list[AlphaDecision]:
        if ask > self.config.entry_center + self.config.entry_band:
            return []
        return self._make_signal(
            view,
            side,
            ask,
            confidence=0.65,
            reason_codes=("ENTRY", f"LAYER_1_OF_{self.config.max_layers}"),
            metrics={
                "action": "ENTRY",
                "layer": 1,
                "max_layers": self.config.max_layers,
                "base_notional": self.config.base_notional,
                "entry_center": self.config.entry_center,
                "entry_band": self.config.entry_band,
            },
        )

    def _evaluate_addition(self, view: MarketView, side: Side, ask: float, current_layers: int, avg_cost: float) -> list[AlphaDecision]:
        mode = str(getattr(self.config.mode, "value", self.config.mode)).upper()
        setup = self._addition_setup(mode, side, ask, avg_cost)
        if setup is None:
            return []
        action, move_key, move_value, step_key, step_value, multiplier, confidence = setup
        return self._make_signal(
            view,
            side,
            ask,
            confidence=confidence,
            reason_codes=(action, f"LAYER_{current_layers + 1}_OF_{self.config.max_layers}"),
            metrics={
                "action": action,
                move_key: round(move_value, 4),
                step_key: step_value,
                "avg_cost": avg_cost,
                "current_layers": current_layers,
                "layer": current_layers + 1,
                "multiplier": multiplier,
            },
        )

    def _addition_setup(
        self, mode: str, side: Side, ask: float, avg_cost: float
    ) -> tuple[str, str, float, str, float, float, float] | None:
        if mode == "MARTINGALE":
            move = self._adverse_move(side, ask, avg_cost)
            return self._addition_tuple(
                move,
                "MARTINGALE_ADD",
                "adverse_move",
                "adverse_step",
                self.config.adverse_step,
                self.config.martingale_multiplier,
                0.55,
                0.75,
            )
        if mode == "ANTI_MARTINGALE":
            move = self._favorable_move(side, ask, avg_cost)
            return self._addition_tuple(
                move,
                "ANTI_MARTINGALE_ADD",
                "favorable_move",
                "favorable_step",
                self.config.favorable_step,
                self.config.anti_martingale_multiplier,
                0.60,
                0.80,
            )
        return None

    @staticmethod
    def _addition_tuple(
        move: float,
        action: str,
        move_key: str,
        step_key: str,
        step_value: float,
        multiplier: float,
        confidence_base: float,
        confidence_cap: float,
    ) -> tuple[str, str, float, str, float, float, float] | None:
        if move < step_value:
            return None
        confidence = min(
            confidence_cap,
            confidence_base + (move / (step_value * 3)) * 0.20,
        )
        return (
            action,
            move_key,
            move,
            step_key,
            step_value,
            multiplier,
            confidence,
        )

    @staticmethod
    def _adverse_move(side: Side, ask: float, avg_cost: float) -> float:
        if side == Side.UP and ask < avg_cost:
            return avg_cost - ask
        if side == Side.DOWN and ask > avg_cost:
            return ask - avg_cost
        return 0.0

    @staticmethod
    def _favorable_move(side: Side, ask: float, avg_cost: float) -> float:
        if side == Side.UP and ask > avg_cost:
            return ask - avg_cost
        if side == Side.DOWN and ask < avg_cost:
            return avg_cost - ask
        return 0.0

    def _make_signal(self, view: MarketView, side: Side, max_entry_price: float, *, confidence: float, reason_codes: tuple[str, ...], metrics: dict[str, Any]) -> list[AlphaDecision]:
        book = view.book_for(side)
        if book.best_ask is None:
            return []
        mode_value = getattr(self.config.mode, "value", self.config.mode)
        decision = AlphaDecision(
            strategy=self.name,
            asset=view.asset,
            timeframe=view.timeframe,
            market_id=view.market_id,
            market_slug=view.market_slug,
            condition_id=view.condition_id,
            token_id=book.token_id,
            side=side,
            confidence=max(0.0, min(1.0, confidence)),
            entry_reference_price=book.best_ask,
            max_entry_price=min(max_entry_price, self.config.max_price),
            seconds_to_close=view.seconds_to_close,
            data_freshness_ms=view.freshness.max_ms,
            reason_codes=reason_codes,
            metrics={**metrics, "mode": mode_value},
            order_intent=OrderIntentSpec(OrderIntent.TAKER_FAK),
        )
        return [decision]

    def save_state(self) -> dict[str, object]:
        from polysignal_lab.alpha.state import json_safe_state

        return json_safe_state({
            "_layer_count": self._layer_count,
            "_entry_prices": self._entry_prices,
        })

    def load_state(self, state: dict[str, object]) -> None:
        layer_raw = state.get("_layer_count", {}) or {}
        if not isinstance(layer_raw, dict):
            layer_raw = {}
        self._layer_count = {
            str(k): int(v) for k, v in layer_raw.items()
        }
        prices_raw = state.get("_entry_prices", {}) or {}
        if not isinstance(prices_raw, dict):
            prices_raw = {}
        self._entry_prices = {
            str(k): [float(p) for p in v]
            for k, v in prices_raw.items()
        }

    def evaluate_view_from_snapshot_for_test(self, snapshot) -> list[AlphaDecision]:
        from polysignal_lab.alpha.ptb_diff_core import market_view_from_snapshot

        view = market_view_from_snapshot(snapshot)
        return [] if view is None else self.evaluate(view)
