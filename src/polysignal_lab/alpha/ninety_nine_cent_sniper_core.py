from __future__ import annotations

from polysignal_lab.alpha.types import (
    AlphaDecision,
    MarketView,
    OrderIntentSpec,
    SideBookView,
)
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.strategy_config import NinetyNineCentSniperConfig


class NinetyNineCentSniperAlphaCore:
    """Snipe near-certain settlement outcomes in the final seconds."""

    name = "ninety_nine_cent_sniper"

    def __init__(self, config: NinetyNineCentSniperConfig) -> None:
        self.config = config

    def reset(self) -> None:
        return None

    @staticmethod
    def _book_mid(book: SideBookView) -> float | None:
        if book.best_bid is not None and book.best_ask is not None:
            return (book.best_bid + book.best_ask) / 2.0
        return None

    def _external_probability(self, view: MarketView, side: Side) -> float | None:
        prob = view.metrics.get("external_probability")
        if prob is not None:
            return float(prob)
        return self._book_mid(view.book_for(side))

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        seconds_to_close = view.seconds_to_close
        if seconds_to_close is None or not self._in_time_window(seconds_to_close):
            return []

        decisions: list[AlphaDecision] = []
        for side in (Side.UP, Side.DOWN):
            decision = self._evaluate_side(view, side, seconds_to_close)
            if decision is not None:
                decisions.append(decision)

        return decisions

    def _in_time_window(self, seconds_to_close: int) -> bool:
        cfg = self.config
        return (
            cfg.min_seconds_before_close
            <= seconds_to_close
            <= cfg.max_seconds_before_close
        )

    def _evaluate_side(
        self, view: MarketView, side: Side, seconds_to_close: int
    ) -> AlphaDecision | None:
        cfg = self.config
        if view.trading.has_market_activity(self.name, view.market_id, side):
            return None
        book = view.book_for(side)
        best_ask = book.best_ask
        if best_ask is None or best_ask > cfg.max_entry_price:
            return None
        prob = self._external_probability(view, side)
        if prob is None or prob < cfg.min_external_probability:
            return None
        if book.best_bid is not None and book.best_bid <= cfg.stop_price:
            return None
        opposite_ask = self._opposite_ask_if_settled(view, side)
        if cfg.require_effectively_settled and opposite_ask is None:
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
            confidence=0.96,
            entry_reference_price=best_ask,
            max_entry_price=min(cfg.max_entry_price, best_ask * 1.01),
            seconds_to_close=seconds_to_close,
            data_freshness_ms=view.freshness.max_ms,
            reason_codes=(
                "NINETY_NINE_SNIPE",
                "EFFECTIVELY_SETTLED",
                "HIGH_PROBABILITY",
                "FOK_EXECUTION",
            ),
            metrics={
                "best_ask": best_ask,
                "best_bid": book.best_bid,
                "midpoint": self._book_mid(book),
                "external_probability": prob,
                "seconds_to_close": seconds_to_close,
                "max_notional": cfg.max_notional_per_trade,
                "stop_price": cfg.stop_price,
                "require_effectively_settled": cfg.require_effectively_settled,
                "opposite_ask": opposite_ask,
                "created_at_for_test": view.created_at,
            },
            order_intent=OrderIntentSpec(
                intent=OrderIntent.TAKER_FOK,
                notional=cfg.max_notional_per_trade,
            ),
        )

    def _opposite_ask_if_settled(self, view: MarketView, side: Side) -> float | None:
        if not self.config.require_effectively_settled:
            return None
        opposite_ask = view.book_for(side.opposite).best_ask
        if opposite_ask is None or opposite_ask > 0.05:
            return None
        return opposite_ask
