from __future__ import annotations

from polysignal_lab.alpha.types import (
    AlphaDecision,
    MarketView,
    OrderIntent,
    OrderIntentSpec,
    Side,
)


class ExampleExternalAlphaCore:
    """No-rebuild strategy demo.

    The native host passes a config object exposing ``name``, ``assets``,
    ``timeframes`` and ``params`` (the free-form YAML block). This example buys
    the UP token when its best ask is below ``params.threshold`` (default 0.40)
    and the bid/ask spread is tight enough.
    """

    def __init__(self, config) -> None:
        self.config = config
        self.name = getattr(config, "name", "example_external")
        self.threshold = float(getattr(config, "params", {}).get("threshold", 0.40))
        self.max_spread = float(getattr(config, "params", {}).get("max_spread", 0.05))

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        up = view.up
        if up.best_ask is None or up.best_bid is None:
            return []
        if up.best_ask >= self.threshold:
            return []
        if (up.best_ask - up.best_bid) > self.max_spread:
            return []
        return [
            AlphaDecision(
                strategy=self.name,
                asset=view.asset,
                timeframe=view.timeframe,
                market_id=view.market_id,
                market_slug=view.market_slug,
                condition_id=view.condition_id,
                token_id=up.token_id,
                side=Side.UP,
                confidence=0.6,
                entry_reference_price=up.best_ask,
                max_entry_price=up.best_ask,
                seconds_to_close=view.seconds_to_close,
                data_freshness_ms=view.freshness.max_ms,
                reason_codes=("EXTERNAL_EXAMPLE",),
                metrics={"threshold": self.threshold, "ask": up.best_ask},
                order_intent=OrderIntentSpec(
                    intent=OrderIntent.TAKER_IOC,
                    notional=10.0,
                ),
            )
        ]
