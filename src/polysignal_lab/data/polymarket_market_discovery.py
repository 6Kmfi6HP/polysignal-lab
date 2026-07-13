"""
Input: __future__, typing, httpx, pydantic, polysignal_lab.config, polysignal_lab.data.market_discovery_helpers, polysignal_lab.domain.market, polysignal_lab.utils
Output: MarketDiscovery
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from typing import Final, Protocol

import httpx
from pydantic import JsonValue, TypeAdapter

from polysignal_lab.config import MarketConfig, PolymarketDataConfig
from polysignal_lab.data.market_discovery_helpers import (
    build_current_slot_slugs,
    gamma_events_from_json,
    gamma_events_query_params,
    paginate_gamma_events,
    parse_gamma_markets,
    paginate_gamma_events_async,
)
from polysignal_lab.domain.market import Market
from polysignal_lab.utils import utc_now

JsonObject = dict[str, JsonValue]
GAMMA_PAGE_LIMIT: Final = 200
JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


class _JsonResponse(Protocol):
    def raise_for_status(self) -> object: ...

    def json(self) -> object: ...


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
        max_event_pages: int | None = None,
    ) -> list[Market]:
        payloads = await self._fetch_gamma_events(max_pages=max_event_pages)
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
        max_event_pages: int | None = None,
    ) -> list[Market]:
        with httpx.Client(timeout=15.0) as client:
            payloads = self._fetch_gamma_events_sync(
                client,
                max_pages=max_event_pages,
            )
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
        _ = response.raise_for_status()
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
        return parse_gamma_markets(
            payloads,
            self.market_config,
            include_next_periods=include_next_periods,
            stale_grace_sec=stale_grace_sec,
            now=utc_now(),
        )

    async def _fetch_gamma_events(
        self,
        *,
        max_pages: int | None = None,
    ) -> list[JsonObject]:
        return await paginate_gamma_events_async(
            self._fetch_gamma_events_page,
            max_pages=max_pages,
        )

    def _fetch_gamma_events_sync(
        self,
        client: httpx.Client,
        *,
        max_pages: int | None = None,
    ) -> list[JsonObject]:
        return paginate_gamma_events(
            lambda offset: self._fetch_gamma_events_page_sync(client, offset),
            max_pages=max_pages,
        )

    def _fetch_gamma_events_page_sync(self, client: httpx.Client, offset: int) -> list[JsonObject]:
        params = gamma_events_query_params(self.market_config, offset)
        payload = self._request_sync(
            f"{self.config.gamma_base_url}/events",
            params=params,
            sync_client=client,
        )
        return gamma_events_from_json(payload)

    async def _fetch_gamma_events_page(self, offset: int) -> list[JsonObject]:
        params = gamma_events_query_params(self.market_config, offset)
        payload = await self._request_async(
            f"{self.config.gamma_base_url}/events",
            params=params,
        )
        return gamma_events_from_json(payload)

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
        return build_current_slot_slugs(
            assets=list(self.market_config.assets),
            timeframes=list(self.market_config.timeframes),
            now_ts=int(utc_now().timestamp()),
            include_next_periods=include_next_periods,
            stale_grace_sec=stale_grace_sec,
        )

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
        payloads = gamma_events_from_json(payload)
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
        payloads = gamma_events_from_json(payload)
        return payloads[0] if payloads else None

    def _fetch_gamma_slug_payload_sync(self, client: httpx.Client, url: str) -> JsonObject | None:
        try:
            payload = self._request_sync(url, sync_client=client)
        except (httpx.HTTPError, TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None
