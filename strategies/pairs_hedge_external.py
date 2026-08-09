from __future__ import annotations

from polysignal_lab.alpha.types import (
    AlphaDecision,
    MarketView,
    OrderIntent,
    OrderIntentSpec,
    Side,
)


class PairsHedgeExternalAlphaCore:
    """Emit an entry plus a reduce-only hedge on the opposite side.

    Demonstrates the hedge/exit contract: the hedge decision carries
    ``hedge_leg=True`` and an ``order_intent`` with ``reduce_only=True`` so the
    native exit policy treats it as a covering leg rather than a new position.
    """

    def __init__(self, config) -> None:
        self.config = config
        self.name = getattr(config, "name", "pairs_hedge_external")
        self.threshold = float(getattr(config, "params", {}).get("threshold", 0.40))

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        up, down = view.up, view.down
        if up.best_ask is None or down.best_ask is None:
            return []
        side = Side.UP if up.best_ask <= down.best_ask else Side.DOWN
        book = view.book_for(side)
        if book.best_ask >= self.threshold:
            return []
        hedge_side = side.opposite
        hedge_book = view.book_for(hedge_side)
        entry = AlphaDecision(
            strategy=self.name,
            asset=view.asset,
            timeframe=view.timeframe,
            market_id=view.market_id,
            market_slug=view.market_slug,
            condition_id=view.condition_id,
            token_id=book.token_id,
            side=side,
            confidence=0.6,
            entry_reference_price=book.best_ask,
            max_entry_price=book.best_ask,
            seconds_to_close=view.seconds_to_close,
            data_freshness_ms=view.freshness.max_ms,
            reason_codes=("PAIRS_HEDGE_ENTRY",),
            metrics={"threshold": self.threshold},
            order_intent=OrderIntentSpec(intent=OrderIntent.TAKER_IOC, notional=10.0),
        )
        hedge = AlphaDecision(
            strategy=self.name,
            asset=view.asset,
            timeframe=view.timeframe,
            market_id=view.market_id,
            market_slug=view.market_slug,
            condition_id=view.condition_id,
            token_id=hedge_book.token_id,
            side=hedge_side,
            confidence=0.6,
            entry_reference_price=hedge_book.best_ask,
            max_entry_price=hedge_book.best_ask,
            seconds_to_close=view.seconds_to_close,
            data_freshness_ms=view.freshness.max_ms,
            reason_codes=("PAIRS_HEDGE_COVER",),
            metrics={"threshold": self.threshold},
            hedge_leg=True,
            order_intent=OrderIntentSpec(
                intent=OrderIntent.TAKER_IOC, reduce_only=True, notional=10.0
            ),
        )
        return [entry, hedge]
