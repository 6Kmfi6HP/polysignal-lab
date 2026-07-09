"""
Input: __future__, __future__.annotations, json, re, datetime, datetime.timedelta, typing, typing.Final, typing.Protocol, httpx, pydantic
Output: MarketDiscovery
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import Final, Protocol

import httpx
from pydantic import JsonValue, TypeAdapter

from polysignal_lab.config import MarketConfig, PolymarketDataConfig
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.utils import utc_now

JsonObject = dict[str, JsonValue]
GAMMA_PAGE_LIMIT: Final = 200
JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


class _JsonResponse(Protocol):
    def raise_for_status(self) -> None: ...

    def json(self) -> JsonValue: ...


class _AsyncJsonClient(Protocol):
    async def get(self, url: str, *, params: dict[str, str] | None = None) -> _JsonResponse: ...


class _HttpxJsonResponse:
    def __init__(self, response: httpx.Response) -> None:
        self._response: httpx.Response = response

    def raise_for_status(self) -> None:
        _ = self._response.raise_for_status()

    def json(self) -> JsonValue:
        return JSON_VALUE_ADAPTER.validate_python(self._response.json())


class _HttpxAsyncJsonClient:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient = httpx.AsyncClient(timeout=15.0)

    async def get(self, url: str, *, params: dict[str, str] | None = None) -> _JsonResponse:
        return _HttpxJsonResponse(await self._client.get(url, params=params))


class MarketDiscovery:
    def __init__(
        self,
        config: PolymarketDataConfig,
        market_config: MarketConfig,
        client: _AsyncJsonClient | None = None,
    ):
        self.config: PolymarketDataConfig = config
        self.market_config: MarketConfig = market_config
        self.client: _AsyncJsonClient = client or _HttpxAsyncJsonClient()

    def replace_client(self, client: _AsyncJsonClient | None = None) -> _AsyncJsonClient:
        self.client = client or _HttpxAsyncJsonClient()
        return self.client

    async def discover(
        self,
        *,
        include_next_periods: int = 0,
        stale_grace_sec: int = 0,
    ) -> list[Market]:
        payloads = await self._fetch_gamma_events()
        payloads.extend(
            await self._fetch_current_slot_payloads(
                include_next_periods=include_next_periods,
                stale_grace_sec=stale_grace_sec,
            )
        )
        return self._markets_from_payloads(
            payloads,
            include_next_periods=include_next_periods,
            stale_grace_sec=stale_grace_sec,
        )

    def discover_sync(
        self,
        *,
        include_next_periods: int = 0,
        stale_grace_sec: int = 0,
    ) -> list[Market]:
        with httpx.Client(timeout=15.0) as client:
            payloads = self._fetch_gamma_events_sync(client)
            payloads.extend(
                self._fetch_current_slot_payloads_sync(
                    client,
                    include_next_periods=include_next_periods,
                    stale_grace_sec=stale_grace_sec,
                )
            )
        return self._markets_from_payloads(
            payloads,
            include_next_periods=include_next_periods,
            stale_grace_sec=stale_grace_sec,
        )

    def _parse_response(self, response: _JsonResponse) -> JsonValue:
        response.raise_for_status()
        return JSON_VALUE_ADAPTER.validate_python(response.json())

    async def _request_async(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
    ) -> JsonValue:
        response = await self.client.get(url, params=params)
        return self._parse_response(response)

    def _request_sync(
        self,
        url: str,
        *,
        sync_client: httpx.Client,
        params: dict[str, str] | None = None,
    ) -> JsonValue:
        return self._parse_response(_HttpxJsonResponse(sync_client.get(url, params=params)))

    def _markets_from_payloads(
        self,
        payloads: list[JsonObject],
        *,
        include_next_periods: int = 0,
        stale_grace_sec: int = 0,
    ) -> list[Market]:
        candidates = self._flatten_markets(payloads)
        markets: list[Market] = []
        seen: set[str] = set()
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
            if not self._is_allowed_window(
                market,
                include_next_periods=include_next_periods,
                stale_grace_sec=stale_grace_sec,
            ):
                continue
            if len(market.outcome_tokens) >= 2:
                key = market.condition_id or market.market_id or market.market_slug
                if key in seen:
                    continue
                seen.add(key)
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


    def _fetch_gamma_events_sync(self, client: httpx.Client) -> list[JsonObject]:
        events: list[JsonObject] = []
        offset = 0
        while True:
            page = self._fetch_gamma_events_page_sync(client, offset)
            events.extend(page)
            if len(page) < GAMMA_PAGE_LIMIT:
                return events
            offset += GAMMA_PAGE_LIMIT

    def _fetch_gamma_events_page_sync(self, client: httpx.Client, offset: int) -> list[JsonObject]:
        params = {
            "active": str(self.market_config.active_only).lower(),
            "closed": str(self.market_config.closed).lower(),
            "order": "startDate",
            "ascending": "false",
            "limit": str(GAMMA_PAGE_LIMIT),
            "offset": str(offset),
        }
        payload = self._request_sync(
            f"{self.config.gamma_base_url}/events",
            params=params,
            sync_client=client,
        )
        return _gamma_events_from_json(payload)

    async def _fetch_gamma_events_page(self, offset: int) -> list[JsonObject]:
        params = {
            "active": str(self.market_config.active_only).lower(),
            "closed": str(self.market_config.closed).lower(),
            "order": "startDate",
            "ascending": "false",
            "limit": str(GAMMA_PAGE_LIMIT),
            "offset": str(offset),
        }
        payload = await self._request_async(
            f"{self.config.gamma_base_url}/events",
            params=params,
        )
        return _gamma_events_from_json(payload)

    async def _fetch_current_slot_payloads(
        self,
        *,
        include_next_periods: int = 0,
        stale_grace_sec: int = 0,
    ) -> list[JsonObject]:
        if not (self.market_config.active_only and not self.market_config.closed):
            return []
        payloads: list[JsonObject] = []
        for slug in self._current_slot_slugs(
            include_next_periods=include_next_periods,
            stale_grace_sec=stale_grace_sec,
        ):
            payload = await self._fetch_gamma_event_by_slug(slug)
            if payload is None:
                payload = await self._fetch_gamma_market_by_slug(slug)
            if payload is not None:
                payloads.append(payload)
        return payloads

    def _fetch_current_slot_payloads_sync(
        self,
        client: httpx.Client,
        *,
        include_next_periods: int = 0,
        stale_grace_sec: int = 0,
    ) -> list[JsonObject]:
        if not (self.market_config.active_only and not self.market_config.closed):
            return []
        payloads: list[JsonObject] = []
        for slug in self._current_slot_slugs(
            include_next_periods=include_next_periods,
            stale_grace_sec=stale_grace_sec,
        ):
            payload = self._fetch_gamma_event_by_slug_sync(client, slug)
            if payload is None:
                payload = self._fetch_gamma_market_by_slug_sync(client, slug)
            if payload is not None:
                payloads.append(payload)
        return payloads


    def _current_slot_slugs(
        self,
        *,
        include_next_periods: int = 0,
        stale_grace_sec: int = 0,
    ) -> list[str]:
        now_ts = int(utc_now().timestamp())
        next_periods = max(int(include_next_periods), 0)
        grace_sec = max(int(stale_grace_sec), 0)
        slugs: list[str] = []
        for asset in self.market_config.assets:
            asset_slug = str(asset).strip().lower()
            if not asset_slug:
                continue
            for timeframe in self.market_config.timeframes:
                timeframe_slug = str(timeframe).strip().lower()
                seconds = _timeframe_seconds(timeframe_slug)
                if seconds is None:
                    continue
                current_slot_base = now_ts // seconds * seconds
                bases: list[int] = []
                if grace_sec > 0 and now_ts - current_slot_base < grace_sec:
                    bases.append(current_slot_base - seconds)
                bases.extend(
                    current_slot_base + offset * seconds
                    for offset in range(next_periods + 1)
                )
                for slot_base in bases:
                    slugs.append(f"{asset_slug}-updown-{timeframe_slug}-{slot_base}")
        return slugs

    async def _fetch_gamma_event_by_slug(self, slug: str) -> JsonObject | None:
        return await self._fetch_gamma_slug_payload(f"{self.config.gamma_base_url}/events/slug/{slug}")

    async def _fetch_gamma_market_by_slug(self, slug: str) -> JsonObject | None:
        try:
            payload = await self._request_async(
                f"{self.config.gamma_base_url}/markets",
                params={"slug": slug},
            )
        except (httpx.HTTPError, TypeError, ValueError):
            return None
        payloads = _gamma_events_from_json(payload)
        return payloads[0] if payloads else None

    async def _fetch_gamma_slug_payload(self, url: str) -> JsonObject | None:
        try:
            payload = await self._request_async(url)
        except (httpx.HTTPError, TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def _fetch_gamma_event_by_slug_sync(self, client: httpx.Client, slug: str) -> JsonObject | None:
        return self._fetch_gamma_slug_payload_sync(client, f"{self.config.gamma_base_url}/events/slug/{slug}")

    def _fetch_gamma_market_by_slug_sync(self, client: httpx.Client, slug: str) -> JsonObject | None:
        try:
            payload = self._request_sync(
                f"{self.config.gamma_base_url}/markets",
                params={"slug": slug},
                sync_client=client,
            )
        except (httpx.HTTPError, TypeError, ValueError):
            return None
        payloads = _gamma_events_from_json(payload)
        return payloads[0] if payloads else None

    def _fetch_gamma_slug_payload_sync(self, client: httpx.Client, url: str) -> JsonObject | None:
        try:
            payload = self._request_sync(url, sync_client=client)
        except (httpx.HTTPError, TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def _flatten_markets(self, payloads: list[JsonObject]) -> list[JsonObject]:
        out: list[JsonObject] = []
        for event in payloads:
            event_markets = event.get("markets")
            if isinstance(event_markets, list) and event_markets:
                for market in event_markets:
                    if isinstance(market, dict):
                        merged = {**event, **market}
                        _ = merged.setdefault("eventSlug", event.get("slug"))
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

    def _is_allowed_window(
        self,
        market: Market,
        *,
        include_next_periods: int = 0,
        stale_grace_sec: int = 0,
    ) -> bool:
        if not (self.market_config.active_only and not self.market_config.closed):
            return True
        if market.start_ts is None or market.end_ts is None:
            return True
        now = utc_now()
        grace_window = timedelta(seconds=max(int(stale_grace_sec), 0))
        future_seconds = max(int(include_next_periods), 0) * (
            _timeframe_seconds(market.timeframe) or 0
        )
        future_window = timedelta(seconds=future_seconds)
        return market.start_ts <= now + future_window and market.end_ts >= now - grace_window

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
            decoded = JSON_VALUE_ADAPTER.validate_python(json.loads(raw))
        except json.JSONDecodeError:
            return []
        return decoded if isinstance(decoded, list) else []
    return []


def _timeframe_seconds(timeframe: str) -> int | None:
    match = re.fullmatch(r"([1-9]\d*)m", timeframe)
    if match is None:
        return None
    return int(match.group(1)) * 60
