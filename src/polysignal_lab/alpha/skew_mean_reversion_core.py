"""Pure alpha core for the skew mean-reversion strategy.

Extracted verbatim from ``strategies/skew_mean_reversion.py``: the decision
logic in ``evaluate`` is moved, not rewritten. No scheduler, Nautilus, Telegram,
SQLite, wallet, or snapshot machinery.
"""

from __future__ import annotations

from polysignal_lab.alpha.types import AlphaDecision, MarketView
from polysignal_lab.domain.enums import Side


class SkewMeanReversionAlphaCore:
    """Signal when one side is excessively cheap vs the other (mean reversion)."""

    name = "skew_mean_reversion"

    def __init__(self, config) -> None:
        self.config = config

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        cfg = self.config
        if not getattr(cfg, "enabled", True):
            return []
        if view.asset not in [a.upper() for a in cfg.assets]:
            return []
        if view.timeframe not in cfg.timeframes:
            return []
        if view.up.best_ask is None or view.down.best_ask is None:
            return []
        if view.seconds_to_close is None or view.seconds_to_close > cfg.max_seconds_to_close:
            return []

        up_price = view.up.best_ask
        down_price = view.down.best_ask
        avg_price = (up_price + down_price) / 2.0
        skew = abs(up_price - down_price)

        # Skew must be significant relative to avg
        if avg_price == 0:
            return []
        skew_ratio = skew / avg_price
        if skew_ratio < cfg.min_skew_ratio:
            return []

        # Which side is cheaper?
        if up_price < down_price:
            side = Side.UP
            cheap_price = up_price
        else:
            side = Side.DOWN
            cheap_price = down_price

        # Check max entry price filter
        if cheap_price > cfg.max_entry_price:
            return []

        # Check order book spread
        book = view.book_for(side)
        if book.spread is not None and book.spread > cfg.max_spread:
            return []

        # Confidence: proportional to skew extremity
        confidence = cfg.base_confidence + min(
            cfg.max_confidence - cfg.base_confidence,
            skew_ratio / cfg.max_skew_ratio * (cfg.max_confidence - cfg.base_confidence),
        )
        confidence = min(cfg.max_confidence, max(cfg.min_confidence, confidence))

        reason_codes = (
            "SKEW_ABOVE_THRESHOLD",
            f"CHEAPER_SIDE_{side.value}",
        )
        metrics = {
            "up_price": up_price,
            "down_price": down_price,
            "skew": skew,
            "skew_ratio": skew_ratio,
            "avg_price": avg_price,
            "spread": book.spread,
            "created_at_for_test": view.created_at,
        }

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
                confidence=confidence,
                entry_reference_price=book.best_ask,
                max_entry_price=cfg.max_entry_price,
                seconds_to_close=view.seconds_to_close,
                data_freshness_ms=view.freshness.max_ms,
                reason_codes=reason_codes,
                metrics=metrics,
            )
        ]