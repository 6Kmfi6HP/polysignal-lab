from __future__ import annotations

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.strategies.base import BaseStrategy


class SkewMeanReversionStrategy(BaseStrategy):
    """Signal when one side is excessively cheap vs the other (mean reversion).

    Works across the FULL market lifecycle (not just last seconds).
    Detects when |up_ask - down_ask| exceeds the threshold — the cheaper
    side offers positive expected value assuming the oracle settles near 0.5.

    Key insight: For these 24h Chainlink price markets, both UP and DOWN
    should trade near 0.5 (50/50 oracle). When one side dips significantly
    below, that's the edge.
    """

    name = "skew_mean_reversion"

    def __init__(self, config):
        self.config = config

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        if not self.config.enabled:
            return []
        if snapshot.market.asset not in [a.upper() for a in self.config.assets]:
            return []
        if snapshot.market.timeframe not in self.config.timeframes:
            return []
        if snapshot.up_ask is None or snapshot.down_ask is None:
            return []
        if snapshot.seconds_to_close is None or snapshot.seconds_to_close > self.config.max_seconds_to_close:
            return []

        up_price = snapshot.up_ask
        down_price = snapshot.down_ask
        avg_price = (up_price + down_price) / 2.0
        skew = abs(up_price - down_price)

        # Skew must be significant relative to avg
        if avg_price == 0:
            return []
        skew_ratio = skew / avg_price
        if skew_ratio < self.config.min_skew_ratio:
            return []

        # Which side is cheaper?
        if up_price < down_price:
            side = Side.UP
            cheap_price = up_price
            expensive_price = down_price
        else:
            side = Side.DOWN
            cheap_price = down_price
            expensive_price = up_price

        # Check max entry price filter
        if cheap_price > self.config.max_entry_price:
            return []

        # Check order book spread
        book = snapshot.book_for(side)
        if book and book.spread is not None and book.spread > self.config.max_spread:
            return []

        # Confidence: proportional to skew extremity
        # Baseline 0.55, max ~0.90 when skew_ratio hits max_skew_ratio
        confidence = self.config.base_confidence + min(
            self.config.max_confidence - self.config.base_confidence,
            skew_ratio / self.config.max_skew_ratio * (self.config.max_confidence - self.config.base_confidence),
        )
        confidence = min(self.config.max_confidence, max(self.config.min_confidence, confidence))

        reason_codes = [
            "SKEW_ABOVE_THRESHOLD",
            f"CHEAPER_SIDE_{side.value}",
        ]

        signal = self._candidate(
            snapshot,
            side,
            confidence,
            max_entry_price=self.config.max_entry_price,
            reason_codes=reason_codes,
            metrics={
                "up_price": up_price,
                "down_price": down_price,
                "skew": skew,
                "skew_ratio": skew_ratio,
                "avg_price": avg_price,
                "spread": book.spread if book else None,
            },
        )
        return [signal] if signal else []
