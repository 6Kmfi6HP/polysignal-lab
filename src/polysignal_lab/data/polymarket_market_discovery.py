from __future__ import annotations

import json
import re
from typing import Final

import httpx
from pydantic import JsonValue, TypeAdapter

from polysignal_lab.config import MarketConfig, PolymarketDataConfig
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market, OutcomeToken

JsonObject = dict[str, JsonValue]
GAMMA_PAGE_LIMIT: Final = 200
JSON_VALUE_ADAPTER: Final = TypeAdapter(JsonValue)


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
            if match is None or not self._is_allowed_active_market(payload):
                continue
            asset, timeframe = match
            try:
                market = Market.from_gamma(payload, asset=asset, timeframe=timeframe)
            except (KeyError, TypeError, ValueError):
                continue
            if len(market.outcome_tokens) < 2:
                inferred = self._infer_tokens(payload, market.market_id)
                if inferred:
                    market.outcome_tokens = inferred
            if len(market.outcome_tokens) >= 2:
                markets.append(market)
        return markets

    async def _fetch_gamma_events(self) -> list[JsonObject]:
        events: list[JsonObject] = []
        offset = 0
        while True:
            page = await self._fetch_gamma_events_page(offset)
            events.extend(page)
            if len(page) < GAMMA_PAGE_LIMIT:
                return events
            offset += GAMMA_PAGE_LIMIT

    async def _fetch_gamma_events_page(self, offset: int) -> list[JsonObject]:
        params = {
            "active": str(self.market_config.active_only).lower(),
            "closed": str(self.market_config.closed).lower(),
            "order": "startDate",
            "ascending": "false",
            "limit": str(GAMMA_PAGE_LIMIT),
            "offset": str(offset),
        }
        response = await self.client.get(f"{self.config.gamma_base_url}/events", params=params)
        response.raise_for_status()
        return _gamma_events_from_json(JSON_VALUE_ADAPTER.validate_python(response.json()))

    def _flatten_markets(self, payloads: list[JsonObject]) -> list[JsonObject]:
        out: list[JsonObject] = []
        for event in payloads:
            event_markets = event.get("markets")
            if isinstance(event_markets, list) and event_markets:
                for market in event_markets:
                    if isinstance(market, dict):
                        merged = {**event, **market}
                        merged.setdefault("eventSlug", event.get("slug"))
                        out.append(merged)
            else:
                out.append(event)
        return out

    def _match_crypto_updown(self, payload: JsonObject) -> tuple[str, str] | None:
        slug = str(payload.get("slug") or payload.get("eventSlug") or "")
        match = re.match(r"^([a-z0-9]+)-updown-([0-9]+m)-\d+$", slug.lower())
        if match is None:
            return None
        asset = match.group(1).upper()
        timeframe = match.group(2)
        if asset in {configured.upper() for configured in self.market_config.assets} and timeframe in self.market_config.timeframes:
            return asset, timeframe
        return None

    def _is_allowed_active_market(self, payload: JsonObject) -> bool:
        closed = bool(payload.get("closed") or payload.get("archived") or payload.get("resolved"))
        active = bool(payload.get("active", not closed))
        if self.market_config.active_only and not active:
            return False
        return closed == self.market_config.closed

    def _infer_tokens(self, payload: JsonObject, market_id: str) -> list[OutcomeToken]:
        token_ids = _json_list(payload.get("clobTokenIds") or payload.get("clob_token_ids") or payload.get("tokenIds"))
        if len(token_ids) < 2:
            return []
        return [
            OutcomeToken(token_id=str(token_ids[0]), side=Side.UP, outcome_name="Up", market_id=market_id),
            OutcomeToken(token_id=str(token_ids[1]), side=Side.DOWN, outcome_name="Down", market_id=market_id),
        ]


def _gamma_events_from_json(payload: JsonValue) -> list[JsonObject]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("events", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    return []


def _json_list(raw: JsonValue | None) -> list[JsonValue]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return decoded if isinstance(decoded, list) else []
    return []
