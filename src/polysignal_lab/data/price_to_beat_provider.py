"""
Input: __future__, __future__.annotations, re, dataclasses, dataclasses.dataclass, pydantic, polysignal_lab.data.anchor_price_service, polysignal_lab.domain.market
Output: PriceToBeatResult, PriceToBeatProvider
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import JsonValue

from polysignal_lab.data.anchor_price_service import AnchorPriceStore
from polysignal_lab.domain.market import Market
from polysignal_lab.utils import safe_float

@dataclass(frozen=True)
class PriceToBeatResult:
    value: float | None
    source: str
    verified: bool
    reason: str | None = None
    anchor_source: str | None = None
    anchor_lag_ms: int | None = None
    from_anchor_service: bool = False


class PriceToBeatProvider:
    """PTB provider for crypto Up/Down markets.

    Sources are limited to project market metadata, the persisted anchor service,
    and a non-authoritative text fallback.
    """

    def __init__(self, *, anchor_store: AnchorPriceStore | None = None):
        self.anchor_store = anchor_store

    async def get(self, market: Market) -> PriceToBeatResult:
        result = self._resolve_non_api_sources(market)
        if result is not None:
            return result
        return self._apply_text_fallback(market)

    def get_sync(self, market: Market) -> PriceToBeatResult:
        result = self._resolve_non_api_sources(market)
        if result is not None:
            return result
        return self._apply_text_fallback(market)

    def _resolve_non_api_sources(self, market: Market) -> PriceToBeatResult | None:
        """Check anchor, metadata, and raw payload (Sources 1-2). Returns result or None."""
        if self.anchor_store is not None:
            anchor = self.anchor_store.get_verified_anchor_price(
                market.asset, market.timeframe, market.market_slug
            )
            if anchor is not None and anchor.price is not None:
                return PriceToBeatResult(
                    value=anchor.price,
                    source=f"anchor_service:{anchor.source}",
                    verified=True,
                    anchor_source=anchor.source,
                    anchor_lag_ms=anchor.lag_ms,
                    from_anchor_service=True,
                )

        # Source 1: Direct metadata field
        if market.price_to_beat is not None:
            return PriceToBeatResult(value=market.price_to_beat, source="market_metadata", verified=True)

        # Source 2: Raw payload extraction
        raw_value = self._extract_from_raw(market.raw)
        if raw_value is not None:
            return PriceToBeatResult(value=raw_value, source="market_raw", verified=True)

        return None

    def _apply_text_fallback(self, market: Market) -> PriceToBeatResult:
        """Source 4: text pattern extraction fallback."""
        text_value = self._extract_from_text(" ".join(filter(None, [market.question, market.market_slug])))
        if text_value is not None:
            return PriceToBeatResult(value=text_value, source="text_pattern", verified=False)
        return PriceToBeatResult(value=None, source="unavailable", verified=False, reason="PTB_UNAVAILABLE")


    def _extract_from_raw(self, raw: dict[str, JsonValue]) -> float | None:
        for key in ["priceToBeat", "price_to_beat", "priceToBeatValue", "strikePrice", "targetPrice"]:
            value = safe_float(raw.get(key))
            if value is not None:
                return value
        for container_key in ["metadata", "custom", "data"]:
            nested = raw.get(container_key)
            if isinstance(nested, dict):
                value = self._extract_from_raw(nested)
                if value is not None:
                    return value
        return None

    def _extract_from_text(self, text: str) -> float | None:
        patterns = [
            r"price\s*to\s*beat\s*[:$ ]+([0-9][0-9,]*(?:\.[0-9]+)?)",
            r"above\s*\$?([0-9][0-9,]*(?:\.[0-9]+)?)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I)
            if match:
                return safe_float(match.group(1).replace(",", ""))
        return None
