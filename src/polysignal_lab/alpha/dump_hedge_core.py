"""
Input: __future__, __future__.annotations, collections, collections.defaultdict, collections.deque, datetime, datetime.datetime, datetime.timezone, statistics, statistics.mean
Output: RollingPriceStats, DumpHedgeAlphaCore
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
    enabled_for_view,
    evaluate_from_snapshot_for_test,
    position_hedge_context,
    record_two_leg_fill,
    restore_position_state,
    restore_string_set,
)
from polysignal_lab.alpha.stats import RollingPriceStats
from polysignal_lab.alpha.types import AlphaDecision, AlphaFillEvent, AlphaOrderEvent, MarketView, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent, Side

_FEE_RATE = 0.01
_SLIPPAGE_BUFFER = 0.01


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
        return enabled_for_view(self.config, view)

    def _active_position(self, view: MarketView) -> dict[str, Any] | None:
        position = active_unhedged_position(self._positions, view.market_id)
        return dict(position) if position is not None else None

    def _update_price_stats(self, view: MarketView) -> None:
        for side in SIDES:
            book = view.book_for(side)
            if book.best_ask is not None:
                self._price_stats.push(book.token_id, book.best_ask, size=1.0)
                self._last_price[book.token_id] = book.best_ask

    # -- decision helpers ----------------------------------------------------

    def _evaluate_sides(self, view: MarketView) -> list[AlphaDecision]:
        decisions: list[AlphaDecision] = []
        for side in SIDES:
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
        record_two_leg_fill(
            self._positions,
            self._entered_markets,
            event,
            enter_on_first_fill=False,
        )
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
        hedge = position_hedge_context(position, self._utc_now())
        hedge_ask = view.ask_for(hedge.hedge_side)
        decisions: list[AlphaDecision] = []

        if hedge_ask is not None:
            cost = self._pair_effective_cost(hedge.filled_price, hedge_ask)
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
                        hedge_price=hedge_ask,
                        pair_cost=cost,
                        cap_metric="pair_cost_cap",
                        cap_value=self.config.pair_cost_cap,
                        reason_codes=("DUMP_HEDGE", f"HEDGE_{hedge.hedge_side.value}"),
                        order_intent=OrderIntentSpec(OrderIntent.TAKER_FOK, pair_id=f"{view.market_id}:dump"),
                        hedge_price_metric="hedge_ask",
                    ),
                )
                if decision:
                    decisions.append(decision)

        if hedge.elapsed_seconds >= self.config.stop_loss_max_wait_seconds and hedge_ask is not None:
            cost = self._pair_effective_cost(hedge.filled_price, hedge_ask)
            if cost <= self.config.stop_loss_pair_cap:
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
                        hedge_price=hedge_ask,
                        pair_cost=cost,
                        cap_metric="stop_loss_cap",
                        cap_value=self.config.stop_loss_pair_cap,
                        reason_codes=("DUMP_HEDGE_STOP_LOSS", f"WAITED_{hedge.elapsed_seconds:.0f}s"),
                        order_intent=OrderIntentSpec(OrderIntent.TAKER_FOK, pair_id=f"{view.market_id}:dump"),
                    ),
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

    def save_state(self) -> dict[str, object]:
        from polysignal_lab.alpha.state import json_safe_state

        return json_safe_state({
            "_positions": self._positions,
            "_entered_markets": self._entered_markets,
            "_dump_detected": self._dump_detected,
        })

    def load_state(self, state: dict[str, object]) -> None:
        self._positions = restore_position_state(state.get("_positions", {}) or {})
        self._entered_markets = restore_string_set(state.get("_entered_markets", []) or [])
        self._dump_detected = restore_string_set(state.get("_dump_detected", []) or [])

    def evaluate_view_from_snapshot_for_test(self, snapshot) -> list[AlphaDecision]:
        return evaluate_from_snapshot_for_test(self, snapshot)
