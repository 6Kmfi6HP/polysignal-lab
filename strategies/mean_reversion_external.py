from __future__ import annotations

from polysignal_lab.alpha.types import (
    AlphaDecision,
    MarketView,
    OrderIntent,
    OrderIntentSpec,
    Side,
)


class MeanReversionExternalAlphaCore:
    """Buy the cheaper leg when the pair is mispriced above parity.

    Polymarket binary pairs should sum to ~1.0. When ``up.best_ask +
    down.best_ask > params.inefficiency`` we buy the cheaper side expecting
    mean reversion toward parity.
    """

    def __init__(self, config) -> None:
        self.config = config
        self.name = getattr(config, "name", "mean_reversion_external")
        self.inefficiency = float(getattr(config, "params", {}).get("inefficiency", 1.01))

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        up, down = view.up, view.down
        if up.best_ask is None or down.best_ask is None:
            return []
        pair_cost = up.best_ask + down.best_ask
        if pair_cost <= self.inefficiency:
            return []
        side = Side.UP if up.best_ask <= down.best_ask else Side.DOWN
        book = view.book_for(side)
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
                confidence=0.65,
                entry_reference_price=book.best_ask,
                max_entry_price=book.best_ask,
                seconds_to_close=view.seconds_to_close,
                data_freshness_ms=view.freshness.max_ms,
                reason_codes=("MEAN_REVERSION", "PAIR_INEFFICIENCY"),
                metrics={"pair_cost": pair_cost, "inefficiency": self.inefficiency},
                order_intent=OrderIntentSpec(intent=OrderIntent.TAKER_IOC, notional=10.0),
            )
        ]
