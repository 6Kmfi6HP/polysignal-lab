from __future__ import annotations

from polysignal_lab.alpha.types import (
    AlphaDecision,
    MarketView,
    OrderIntent,
    OrderIntentSpec,
    Side,
)
from polysignal_lab.nautilus_runtime.strategy_loader import ExternalCoreConfig


class StalenessGuardExternalAlphaCore:
    """Return no decisions when market data is too stale to trust.

    Demonstrates the common guard pattern: bail out entirely when
    ``view.freshness.max_ms`` exceeds ``parameters.max_freshness_ms`` rather than
    acting on stale prices.
    """

    def __init__(self, config: ExternalCoreConfig) -> None:
        self.config = config
        self.name = config.name
        self.max_freshness_ms = int(config.parameters.get("max_freshness_ms", 5000))
        self.threshold = float(config.parameters.get("threshold", 0.45))

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        lag = view.freshness.max_ms
        if lag is None or lag > self.max_freshness_ms:
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
                confidence=0.6,
                entry_reference_price=book.best_ask,
                max_entry_price=book.best_ask,
                seconds_to_close=view.seconds_to_close,
                data_freshness_ms=view.freshness.max_ms,
                reason_codes=("STALENESS_GUARD_OK",),
                metrics={"lag_ms": lag, "max_freshness_ms": self.max_freshness_ms},
                order_intent=OrderIntentSpec(
                    intent=OrderIntent.TAKER_IOC, notional=10.0
                ),
            )
        ]
