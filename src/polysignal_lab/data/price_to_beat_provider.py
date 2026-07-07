"""
Input: __future__, __future__.annotations, re, dataclasses, dataclasses.dataclass, typing, typing.Any, typing.Protocol, httpx, polysignal_lab.domain.market
Output: _CryptoPriceResponse, _CryptoPriceClient, PriceToBeatResult, PriceToBeatProvider
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from polysignal_lab.domain.market import Market
from polysignal_lab.utils import safe_float


class _CryptoPriceResponse(Protocol):
    status_code: int

    def json(self) -> Any: ...


class _CryptoPriceClient(Protocol):
    async def get(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> _CryptoPriceResponse: ...


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

    Sources:
      1. market.price_to_beat from Gamma metadata if present.
      2. Raw Gamma payload extraction.
      3. Optional Polymarket web crypto-price API.
      4. Text pattern extraction fallback.

    The crypto-price endpoint is a Polymarket web frontend endpoint protected by
    Cloudflare in server/container environments. It is opt-in so startup does
    not flood logs with 403 responses when the endpoint blocks non-browser HTTP.
    """

    CRYPTO_PRICE_API = "https://polymarket.com/api/crypto/crypto-price"

    def __init__(
        self,
        client: _CryptoPriceClient | None = None,
        *,
        use_crypto_price_api: bool = False,
        anchor_store: Any | None = None,
    ):
        self.client = client or httpx.AsyncClient(timeout=10.0)
        self.use_crypto_price_api = use_crypto_price_api
        self.anchor_store = anchor_store

    async def get(self, market: Market) -> PriceToBeatResult:
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

        # Source 3: Optional Polymarket web crypto-price API.
        if self.use_crypto_price_api:
            ptb = await self._fetch_crypto_price_api(market)
            if ptb is not None:
                return PriceToBeatResult(value=ptb, source="crypto_price_api", verified=True)

        # Source 4: Text pattern
        text_value = self._extract_from_text(" ".join(filter(None, [market.question, market.market_slug])))
        if text_value is not None:
            return PriceToBeatResult(value=text_value, source="text_pattern", verified=False)

        return PriceToBeatResult(value=None, source="unavailable", verified=False, reason="PTB_UNAVAILABLE")

    def get_sync(self, market: Market) -> PriceToBeatResult:
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

        # Source 3: Optional Polymarket web crypto-price API.
        if self.use_crypto_price_api:
            ptb = self._fetch_crypto_price_api_sync(market)
            if ptb is not None:
                return PriceToBeatResult(value=ptb, source="crypto_price_api", verified=True)

        # Source 4: Text pattern
        text_value = self._extract_from_text(" ".join(filter(None, [market.question, market.market_slug])))
        if text_value is not None:
            return PriceToBeatResult(value=text_value, source="text_pattern", verified=False)

        return PriceToBeatResult(value=None, source="unavailable", verified=False, reason="PTB_UNAVAILABLE")


    async def _fetch_crypto_price_api(self, market: Market) -> float | None:
        """Fetch PTB from Polymarket's web crypto-price API.

        GET https://polymarket.com/api/crypto/crypto-price
          ?symbol={asset}&eventStartTime={ISO}&variant={fifteen}&endDate={ISO}
        Reference PTB bot uses "fifteen" for both 5m and 15m windows.
        """
        event_start_time = market.raw.get("eventStartTime") or market.raw.get("event_start_time")
        end_date = market.raw.get("endDate") or market.raw.get("end_date")
        if not isinstance(end_date, str) and market.end_ts:
            end_date = market.end_ts.strftime("%Y-%m-%dT%H:%M:%SZ")

        if event_start_time is None or end_date is None:
            return None

        # Normalize eventStartTime to ISO format
        if isinstance(event_start_time, str):
            start_str = event_start_time.replace(" ", "T")
            if "+" in start_str:
                start_str = start_str.split("+")[0] + "Z"
            elif not start_str.endswith("Z"):
                start_str += "Z"
        else:
            return None

        params = {
            "symbol": market.asset.upper(),
            "eventStartTime": start_str,
            "variant": self._variant_for(market.timeframe),
            "endDate": str(end_date),
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://polymarket.com/",
        }
        try:
            resp = await self.client.get(self.CRYPTO_PRICE_API, params=params, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                # Response format: {"openPrice": 12345.67, "closePrice": ..., "completed": bool}
                price = data.get("openPrice")
                if price is None:
                    price = data.get("closePrice")
                if price is not None:
                    return safe_float(price)
            return None
        except Exception:
            return None

    def _fetch_crypto_price_api_sync(self, market: Market) -> float | None:
        event_start_time = market.raw.get("eventStartTime") or market.raw.get("event_start_time")
        end_date = market.raw.get("endDate") or market.raw.get("end_date")
        if not isinstance(end_date, str) and market.end_ts:
            end_date = market.end_ts.strftime("%Y-%m-%dT%H:%M:%SZ")

        if event_start_time is None or end_date is None:
            return None

        if isinstance(event_start_time, str):
            start_str = event_start_time.replace(" ", "T")
            if "+" in start_str:
                start_str = start_str.split("+")[0] + "Z"
            elif not start_str.endswith("Z"):
                start_str += "Z"
        else:
            return None

        params = {
            "symbol": market.asset.upper(),
            "eventStartTime": start_str,
            "variant": self._variant_for(market.timeframe),
            "endDate": str(end_date),
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://polymarket.com/",
        }
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(self.CRYPTO_PRICE_API, params=params, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                price = data.get("openPrice")
                if price is None:
                    price = data.get("closePrice")
                if price is not None:
                    return safe_float(price)
            return None
        except Exception:
            return None

    def _variant_for(self, timeframe: str) -> str:
        return "fifteen"

    def _extract_from_raw(self, raw: dict[str, Any]) -> float | None:
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
