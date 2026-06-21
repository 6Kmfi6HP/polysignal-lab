from __future__ import annotations

import re
from typing import Any

import httpx

from polysignal_lab.config import MarketConfig, PolymarketDataConfig
from polysignal_lab.domain.enums import MarketStatus, Side
from polysignal_lab.domain.market import Market, OutcomeToken


class MarketDiscovery:
    def __init__(self, config: PolymarketDataConfig, market_config: MarketConfig, client: httpx.AsyncClient | None = None):
        self.config = config
        self.market_config = market_config
        self.client = client or httpx.AsyncClient(timeout=15.0)

    async def discover(self) -> list[Market]:
        payloads = await self._fetch_gamma_events()
        candidates = self._flatten_markets(payloads)
        markets: list[Market] = []
        for payload in candidates:
            match = self._match_crypto_updown(payload)
            if not match:
                continue
            asset, timeframe = match
            try:
                market = Market.from_gamma(payload, asset=asset, timeframe=timeframe)
            except Exception:
                continue
            if len(market.outcome_tokens) < 2:
                inferred = self._infer_tokens(payload, market.market_id)
                if inferred:
                    market.outcome_tokens = inferred
            if len(market.outcome_tokens) >= 2:
                markets.append(market)
        return markets

    async def _fetch_gamma_events(self) -> list[dict[str, Any]]:
        params = {
            "active": str(self.market_config.active_only).lower(),
            "closed": str(self.market_config.closed).lower(),
            "order": "startDate",
            "ascending": "false",
            "limit": "200",
            "offset": "0",
        }
        response = await self.client.get(f"{self.config.gamma_base_url}/events", params=params)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("events") or data.get("data") or [data]
        return []

    def _flatten_markets(self, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for event in payloads:
            event_markets = event.get("markets") or []
            if event_markets:
                for market in event_markets:
                    merged = {**event, **market}
                    merged.setdefault("eventSlug", event.get("slug"))
                    out.append(merged)
            else:
                out.append(event)
        return out

    def _match_crypto_updown(self, payload: dict[str, Any]) -> tuple[str, str] | None:
        slug = str(payload.get("slug") or payload.get("eventSlug") or "")
        import re
        # Match patterns like: btc-updown-5m-1234567890 or eth-updown-15m-1234567890
        m = re.match(r"^(btc|eth|sol|xrp|doge|bnb|hype)-updown-(5m|15m)-\d+$", slug.lower())
        if m:
            asset = m.group(1).upper()
            timeframe = m.group(2)
            if asset in [a.upper() for a in self.market_config.assets] and timeframe in self.market_config.timeframes:
                return asset, timeframe
        return None

    def _infer_tokens(self, payload: dict[str, Any], market_id: str) -> list[OutcomeToken]:
        tokens = []
        clob_tokens = payload.get("clobTokenIds") or payload.get("tokenIds") or []
        if isinstance(clob_tokens, str):
            import json
            try:
                clob_tokens = json.loads(clob_tokens)
            except Exception:
                return []
        if len(clob_tokens) >= 2:
            tokens.append(OutcomeToken(token_id=str(clob_tokens[0]), side=Side.UP, outcome_name="Up", market_id=market_id))
            tokens.append(OutcomeToken(token_id=str(clob_tokens[1]), side=Side.DOWN, outcome_name="Down", market_id=market_id))
        return tokens
