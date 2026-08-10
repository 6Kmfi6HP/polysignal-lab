from __future__ import annotations

from polysignal_lab.alpha.types import (
    AlphaDecision,
    MarketView,
    OrderIntent,
    OrderIntentSpec,
    Side,
)
from polysignal_lab.nautilus_runtime.strategy_loader import ExternalCoreConfig


class SpotConfirmedExternalAlphaCore:
    """Only trade when a spot price confirms the view is tradable.

    Requires ``view.spot`` to be present and inside ``parameters.price_band``; this
    exercises the spot-data branch that some native strategies depend on.
    """

    def __init__(self, config: ExternalCoreConfig) -> None:
        self.config = config
        self.name = config.name
        band = config.parameters.get("price_band", [0.0, 1.0])
        self.low, self.high = float(band[0]), float(band[1])
        self.threshold = float(config.parameters.get("threshold", 0.45))

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        spot = view.spot
        if spot is None:
            return []
        if not (self.low <= spot.price <= self.high):
            return []
        if view.up.best_ask is not None and view.up.best_ask < self.threshold:
            side, book = Side.UP, view.up
        elif view.down.best_ask is not None and view.down.best_ask < self.threshold:
            side, book = Side.DOWN, view.down
        else:
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
                confidence=0.62,
                entry_reference_price=book.best_ask,
                max_entry_price=book.best_ask,
                seconds_to_close=view.seconds_to_close,
                data_freshness_ms=view.freshness.max_ms,
                reason_codes=("SPOT_CONFIRMED",),
                metrics={"spot_price": spot.price, "threshold": self.threshold},
                order_intent=OrderIntentSpec(
                    intent=OrderIntent.TAKER_IOC, notional=10.0
                ),
            )
        ]
