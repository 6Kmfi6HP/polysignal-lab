from __future__ import annotations

from polysignal_lab.alpha.types import (
    AlphaDecision,
    MarketView,
    OrderIntent,
    OrderIntentSpec,
    Side,
)
from polysignal_lab.nautilus_runtime.strategy_loader import ExternalCoreConfig


class MomentumBreakoutExternalAlphaCore:
    """Buy the cheaper side when its ask is below a threshold.

    Functional-test stand-in for a momentum/breakout alpha: it compares the UP
    and DOWN books, selects the cheaper side, and emits a TAKER_IOC entry when
    the selected ask is under ``params.threshold`` and the spread is tight.
    """

    def __init__(self, config: ExternalCoreConfig) -> None:
        self.config = config
        self.name = config.name
        self.threshold = float(config.params.get("threshold", 0.45))
        self.max_spread = float(config.params.get("max_spread", 0.03))

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        up, down = view.up, view.down
        if up.best_ask is None or down.best_ask is None:
            return []
        side = Side.UP if up.best_ask <= down.best_ask else Side.DOWN
        book = view.book_for(side)
        spread = (book.best_ask - book.best_bid) if book.best_bid is not None else None
        if book.best_ask >= self.threshold:
            return []
        if spread is None or spread > self.max_spread:
            return []
        return [
            AlphaDecision(
                strategy=self.name,
                asset=view.asset,
                timeframe=view.timeframe,
                market_id=view.market_id,
                market_slug=view.market_slug,
                condition_id=view.condition_id,
                token_id=book.token_id,
                side=side,
                confidence=0.7,
                entry_reference_price=book.best_ask,
                max_entry_price=book.best_ask,
                seconds_to_close=view.seconds_to_close,
                data_freshness_ms=view.freshness.max_ms,
                reason_codes=("MOMENTUM_BREAKOUT", "CHEAP_SIDE"),
                metrics={"threshold": self.threshold, "ask": book.best_ask},
                order_intent=OrderIntentSpec(intent=OrderIntent.TAKER_IOC, notional=10.0),
            )
        ]
