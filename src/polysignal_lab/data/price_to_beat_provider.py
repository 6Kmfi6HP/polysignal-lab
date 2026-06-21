from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

from polysignal_lab.domain.market import Market
from polysignal_lab.utils import safe_float


@dataclass(frozen=True)
class PriceToBeatResult:
    value: float | None
    source: str
    verified: bool
    reason: str | None = None


class PriceToBeatProvider:
    """PTB provider — mirrors PolyBullLabs PTB bot's approach.

    Sources (in order):
      1. market.price_to_beat (from Gamma metadata if present)
      2. Polymarket crypto-price API (https://polymarket.com/api/crypto/crypto-price)
         using eventStartTime + endDate from Gamma, with variant=fifteen
      3. Raw payload extraction
      4. Text pattern extraction (fallback)
    """

    CRYPTO_PRICE_API = "https://polymarket.com/api/crypto/crypto-price"
    PTB_VARIANT = "fifteen"

    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client or httpx.AsyncClient(timeout=10.0)

    async def get(self, market: Market) -> PriceToBeatResult:
        # Source 1: Direct metadata field
        if market.price_to_beat is not None:
            return PriceToBeatResult(value=market.price_to_beat, source="market_metadata", verified=True)

        # Source 2: Polymarket crypto-price API (most reliable for these markets)
        ptb = await self._fetch_crypto_price_api(market)
        if ptb is not None:
            return PriceToBeatResult(value=ptb, source="crypto_price_api", verified=True)

        # Source 3: Raw payload extraction
        raw_value = self._extract_from_raw(market.raw)
        if raw_value is not None:
            return PriceToBeatResult(value=raw_value, source="market_raw", verified=True)

        # Source 4: Text pattern
        text_value = self._extract_from_text(" ".join(filter(None, [market.question, market.market_slug])))
        if text_value is not None:
            return PriceToBeatResult(value=text_value, source="text_pattern", verified=False)

        return PriceToBeatResult(value=None, source="unavailable", verified=False, reason="PTB_UNAVAILABLE")

    async def _fetch_crypto_price_api(self, market: Market) -> float | None:
        """Fetch PTB from Polymarket's crypto-price API.

        Mirrors PTB bot's get_crypto_price_api():
          GET https://polymarket.com/api/crypto/crypto-price
            ?symbol=BTC&eventStartTime={ISO}&variant=fifteen&endDate={ISO}
        """
        event_start_time = market.raw.get("eventStartTime") or market.raw.get("event_start_time")
        end_date = None
        if market.end_ts:
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
            from polysignal_lab.utils import parse_dt
            parsed = parse_dt(event_start_time)
            if parsed is None:
                return None
            start_str = parsed.strftime("%Y-%m-%dT%H:%M:%SZ")

        params = {
            "symbol": "BTC",
            "eventStartTime": start_str,
            "variant": self.PTB_VARIANT,
            "endDate": end_date,
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
                if price is not None:
                    return safe_float(price)
            return None
        except Exception:
            return None

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
