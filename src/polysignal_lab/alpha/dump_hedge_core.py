"""
Input: __future__, __future__.annotations, collections, collections.defaultdict, collections.deque, datetime, datetime.datetime, datetime.timezone, statistics, statistics.mean
Output: RollingPriceStats, DumpHedgeAlphaCore
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
from statistics import mean, pstdev
from typing import Any

from polysignal_lab.alpha.types import AlphaDecision, AlphaFillEvent, AlphaOrderEvent, MarketView, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent, Side

_FEE_RATE = 0.01
_SLIPPAGE_BUFFER = 0.01


class RollingPriceStats:
    def __init__(self, window_size: int = 16) -> None:
        self.values: dict[str, deque[tuple[float, float]]] = defaultdict(lambda: deque(maxlen=window_size))

    def push(self, key: str, price: float, size: float = 1.0) -> None:
        self.values[key].append((price, max(size, 1e-9)))

    def stats(self, key: str) -> dict[str, float | None]:
        vals = list(self.values[key])
        if not vals:
            return {"vwap": None, "momentum": None, "z_score": None, "count": 0}
        total_size = sum(size for _, size in vals)
        prices = [price for price, _ in vals]
        vwap = sum(price * size for price, size in vals) / total_size if total_size else mean(prices)
        momentum = vals[-1][0] - vals[0][0] if len(vals) > 1 else 0.0
        stdev = pstdev(prices) if len(prices) > 1 else 0.0
        z_score = (prices[-1] - mean(prices)) / stdev if stdev > 0 else 0.0
        return {"vwap": vwap, "momentum": momentum, "z_score": z_score, "count": len(vals)}


class DumpHedgeAlphaCore:
    name = "dump_hedge"

    def __init__(self, config) -> None:
        self.config = config
        self._price_stats = RollingPriceStats(window_size=16)
        self._entered_markets: set[str] = set()
        self._positions: dict[str, dict[str, Any]] = {}
        self._dump_detected: set[str] = set()
        self._last_price: dict[str, float] = {}

    @staticmethod
    def _pair_effective_cost(leg1_price: float, leg2_price: float) -> float:
        return leg1_price + leg2_price + 2.0 * _FEE_RATE + _SLIPPAGE_BUFFER

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    # -- guard helpers -------------------------------------------------------

    def _validate_inputs(self, view: MarketView) -> bool:
        if not self.config.enabled:
            return False
        if view.asset not in [asset.upper() for asset in self.config.assets]:
            return False
        if view.timeframe not in self.config.timeframes:
            return False
        return True

    def _active_position(self, view: MarketView) -> dict[str, Any] | None:
        position = self._positions.get(view.market_id)
        if position and not position.get("hedged", False):
            return position
        return None

    def _update_price_stats(self, view: MarketView) -> None:
        for side in (Side.UP, Side.DOWN):
            book = view.book_for(side)
            if book.best_ask is not None:
                self._price_stats.push(book.token_id, book.best_ask, size=1.0)
                self._last_price[book.token_id] = book.best_ask

    # -- decision helpers ----------------------------------------------------

    def _evaluate_sides(self, view: MarketView) -> list[AlphaDecision]:
        decisions: list[AlphaDecision] = []
        for side in (Side.UP, Side.DOWN):
            book = view.book_for(side)
            stats = self._price_stats.stats(book.token_id)
            if stats["count"] < 2:
                continue
            vwap = stats["vwap"]
            current_ask = book.best_ask
            if vwap is None or current_ask is None or vwap == 0:
                continue
            drop_ratio = (vwap - current_ask) / vwap
            if drop_ratio >= self.config.move_threshold:
                decision = self._decision(
                    view,
                    side,
                    confidence=0.75,
                    max_entry_price=current_ask,
                    reason_codes=("DUMP_DETECTED", f"DROP_{drop_ratio:.1%}", f"SIDE_{side.value}"),
                    metrics={
                        "vwap": round(vwap, 4),
                        "current_ask": round(current_ask, 4),
                        "drop_ratio": round(drop_ratio, 4),
                        "move_threshold": self.config.move_threshold,
                        "shares": self.config.leg_shares,
                    },
                    order_intent=OrderIntentSpec(OrderIntent.TAKER_FAK, pair_id=f"{view.market_id}:dump"),
                )
                if decision:
                    decisions.append(decision)
        return decisions

    # -- guard helpers (cont.) -----------------------------------------------

    def _is_in_detection_window(self, view: MarketView) -> bool:
        if view.start_ts is None:
            return False
        elapsed = (self._utc_now() - view.start_ts).total_seconds()
        return 0 <= elapsed <= self.config.detection_window_minutes * 60.0

    def on_order_accepted(self, event: AlphaOrderEvent) -> None:
        self._dump_detected.add(event.market_id)

    def on_order_submitted(self, event: AlphaOrderEvent) -> None:
        self.on_order_accepted(event)

    def on_order_rejected(self, event: AlphaOrderEvent) -> None:
        self._dump_detected.discard(event.market_id)

    def on_order_canceled(self, event: AlphaOrderEvent) -> None:
        self._dump_detected.discard(event.market_id)

    def on_order_expired(self, event: AlphaOrderEvent) -> None:
        self._dump_detected.discard(event.market_id)

    def on_order_filled(self, event: AlphaFillEvent) -> list[AlphaDecision]:
        self._dump_detected.add(event.market_id)
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
        return []

    def on_leg_failure(self, pair_id: str, market_id: str, side: Side) -> None:
        self._positions.pop(market_id, None)
        self._dump_detected.discard(market_id)

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        if not self._validate_inputs(view):
            return []
        pos = self._active_position(view)
        if pos is not None:
            return self._try_hedge_or_stop(view, pos)
        if view.market_id in self._entered_markets:
            return []
        self._update_price_stats(view)
        if not self._is_in_detection_window(view) or view.market_id in self._dump_detected:
            return []
        return self._evaluate_sides(view)

    def _try_hedge_or_stop(self, view: MarketView, position: dict[str, Any]) -> list[AlphaDecision]:
        now = self._utc_now()
        filled_side: Side = position["side"]
        hedge_side = filled_side.opposite
        filled_price = float(position["entry_price"])
        elapsed = (now - position["filled_at"]).total_seconds()
        hedge_ask = view.ask_for(hedge_side)
        decisions: list[AlphaDecision] = []

        if hedge_ask is not None:
            cost = self._pair_effective_cost(filled_price, hedge_ask)
            if cost <= self.config.pair_cost_cap:
                decision = self._decision(
                    view,
                    hedge_side,
                    confidence=0.70,
                    max_entry_price=hedge_ask,
                    reason_codes=("DUMP_HEDGE", f"HEDGE_{hedge_side.value}"),
                    metrics={
                        "pair_cost": round(cost, 4),
                        "pair_cost_cap": self.config.pair_cost_cap,
                        "filled_leg_price": filled_price,
                        "hedge_ask": hedge_ask,
                        "elapsed_seconds": round(elapsed, 2),
                    },
                    order_intent=OrderIntentSpec(OrderIntent.TAKER_FOK, pair_id=f"{view.market_id}:dump"),
                    hedge_leg=True,
                )
                if decision:
                    decisions.append(decision)

        if elapsed >= self.config.stop_loss_max_wait_seconds and hedge_ask is not None:
            cost = self._pair_effective_cost(filled_price, hedge_ask)
            if cost <= self.config.stop_loss_pair_cap:
                decision = self._decision(
                    view,
                    hedge_side,
                    confidence=0.50,
                    max_entry_price=hedge_ask,
                    reason_codes=("DUMP_HEDGE_STOP_LOSS", f"WAITED_{elapsed:.0f}s"),
                    metrics={
                        "pair_cost": round(cost, 4),
                        "stop_loss_cap": self.config.stop_loss_pair_cap,
                        "filled_leg_price": filled_price,
                        "elapsed_seconds": round(elapsed, 2),
                    },
                    order_intent=OrderIntentSpec(OrderIntent.TAKER_FOK, pair_id=f"{view.market_id}:dump"),
                    hedge_leg=True,
                )
                if decision:
                    decisions.append(decision)
        return decisions

    def _decision(
        self,
        view: MarketView,
        side: Side,
        *,
        confidence: float,
        max_entry_price: float,
        reason_codes: tuple[str, ...],
        metrics: dict[str, Any],
        order_intent: OrderIntentSpec,
        hedge_leg: bool = False,
    ) -> AlphaDecision | None:
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

    def save_state(self) -> dict[str, object]:
        from polysignal_lab.alpha.state import json_safe_state

        return json_safe_state({
            "_positions": self._positions,
            "_entered_markets": self._entered_markets,
            "_dump_detected": self._dump_detected,
        })

    def load_state(self, state: dict[str, object]) -> None:
        from polysignal_lab.alpha.state import restore_utc_datetime
        from polysignal_lab.domain.enums import Side

        positions_raw = state.get("_positions", {}) or {}
        self._positions = {}
        for mid, pos in positions_raw.items():
            self._positions[str(mid)] = {
                "side": Side(pos["side"]),
                "entry_price": float(pos["entry_price"]),
                "filled_at": restore_utc_datetime(pos["filled_at"]),
                "hedged": bool(pos["hedged"]),
            }
        self._entered_markets = set(state.get("_entered_markets", []) or [])
        self._dump_detected = set(state.get("_dump_detected", []) or [])

    def evaluate_view_from_snapshot_for_test(self, snapshot) -> list[AlphaDecision]:
        from polysignal_lab.alpha.ptb_diff_core import market_view_from_snapshot

        view = market_view_from_snapshot(snapshot)
        return [] if view is None else self.evaluate(view)
