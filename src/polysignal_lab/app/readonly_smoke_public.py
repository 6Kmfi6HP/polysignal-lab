"""
Input: __future__, __future__.annotations, re, typing, typing.Final, httpx, pydantic, pydantic.JsonValue, pydantic.TypeAdapter, polysignal_lab.app.readonly_smoke_types, polysignal_lab.data.orderbook_payload
Output: make_public_client, check_gamma_events, check_clob_book, check_clob_404, check_binance_spot, public_get, raw_public_get, response_json, surface, gamma_events
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import re
from typing import Final

import httpx
from pydantic import JsonValue, TypeAdapter

from polysignal_lab.app.readonly_smoke_types import (
    JsonObject,
    PublicEndpoint,
    SurfaceEvidence,
    SurfaceOutcome,
    SurfacePayload,
)
from polysignal_lab.config import Settings
from polysignal_lab.data.orderbook_payload import parse_order_book_payload
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.orderbook import OrderBook
from polysignal_lab.domain.spot import SpotPrice
from polysignal_lab.utils import safe_float, utc_now

JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)
INVALID_CLOB_TOKEN_ID: Final = "polysignal-readonly-smoke-invalid-token"
PUBLIC_HEADERS: Final = {
    "Accept": "application/json",
    "User-Agent": "PolySignalLab/1.0 readonly-smoke",
}


def make_public_client() -> httpx.AsyncClient:
    timeout = httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0)
    return httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers=PUBLIC_HEADERS,
    )


async def check_gamma_events(settings: Settings, client: httpx.AsyncClient) -> SurfacePayload:
    endpoint = PublicEndpoint(
        url=f"{settings.data.polymarket.gamma_base_url}/events",
        params={"active": "true", "closed": "false", "limit": "3"},
    )
    result = await public_get(client, endpoint)
    record_count = len(gamma_events(result.payload)) if result.evidence["ok"] else 0
    evidence = result.evidence
    evidence["record_count"] = record_count
    evidence["ok"] = evidence["ok"] and record_count > 0
    if not evidence["ok"] and evidence["detail"] is None:
        evidence["detail"] = "Gamma returned no active event records"
    return SurfacePayload(evidence=evidence, payload=result.payload)


async def check_clob_book(
    settings: Settings,
    client: httpx.AsyncClient,
    markets: list[Market],
) -> SurfacePayload:
    token_id = first_token_id(markets)
    endpoint = PublicEndpoint(url=f"{settings.data.polymarket.clob_base_url}/book", params={})
    if token_id is None:
        return SurfacePayload(
            evidence=surface(
                endpoint,
                SurfaceOutcome(None, False, 0, "No discovered token id for CLOB book check"),
            ),
            payload=None,
        )
    result = await public_get(client, PublicEndpoint(endpoint.url, {"token_id": token_id}))
    book = book_from_payload(result.payload)
    evidence = result.evidence
    evidence["record_count"] = 1 if book is not None else 0
    evidence["ok"] = evidence["ok"] and book is not None
    if not evidence["ok"] and evidence["detail"] is None:
        evidence["detail"] = "CLOB book payload did not parse"
    return SurfacePayload(evidence=evidence, payload=result.payload)


async def check_clob_404(settings: Settings, client: httpx.AsyncClient) -> SurfacePayload:
    endpoint = PublicEndpoint(
        url=f"{settings.data.polymarket.clob_base_url}/book",
        params={"token_id": INVALID_CLOB_TOKEN_ID},
    )
    response = await raw_public_get(client, endpoint)
    evidence = response.evidence
    evidence["ok"] = evidence["status_code"] == 404
    evidence["record_count"] = 0
    if not evidence["ok"] and evidence["detail"] is None:
        evidence["detail"] = "CLOB invalid token did not return 404"
    return response


async def check_binance_spot(settings: Settings, client: httpx.AsyncClient) -> SurfacePayload:
    symbol = settings.data.binance.symbols.get("BTC", "BTCUSDT")
    endpoint = PublicEndpoint(
        url="https://api.binance.com/api/v3/ticker/bookTicker",
        params={"symbol": symbol},
    )
    result = await public_get(client, endpoint)
    spot = spot_from_payload(result.payload, symbol)
    evidence = result.evidence
    evidence["record_count"] = 1 if spot is not None else 0
    evidence["ok"] = evidence["ok"] and spot is not None
    if not evidence["ok"] and evidence["detail"] is None:
        evidence["detail"] = "Binance spot REST payload did not parse"
    return SurfacePayload(evidence=evidence, payload=result.payload)


async def public_get(client: httpx.AsyncClient, endpoint: PublicEndpoint) -> SurfacePayload:
    response = await raw_public_get(client, endpoint)
    status_code = response.evidence["status_code"]
    if status_code is None or status_code >= 400:
        return response
    try:
        payload: JsonValue = JSON_VALUE_ADAPTER.validate_python(response.payload)
    except (TypeError, ValueError) as exc:
        evidence = response.evidence
        evidence["ok"] = False
        evidence["detail"] = f"Invalid JSON payload: {exc}"
        return SurfacePayload(evidence=evidence, payload=None)
    return SurfacePayload(evidence=response.evidence, payload=payload)


async def raw_public_get(client: httpx.AsyncClient, endpoint: PublicEndpoint) -> SurfacePayload:
    try:
        response = await client.get(endpoint.url, params=endpoint.params)
    except httpx.HTTPError as exc:
        return SurfacePayload(
            evidence=surface(endpoint, SurfaceOutcome(None, False, None, f"{exc.__class__.__name__}: {exc}")),
            payload=None,
        )
    status_code = response.status_code
    ok = 200 <= status_code < 300
    payload = response_json(response) if response.content else None
    detail = None if ok else f"HTTP {status_code}"
    return SurfacePayload(
        evidence=surface(endpoint, SurfaceOutcome(status_code, ok, None, detail)),
        payload=payload,
    )


def response_json(response: httpx.Response) -> JsonValue | None:
    try:
        return JSON_VALUE_ADAPTER.validate_python(response.json())
    except (TypeError, ValueError):
        return None


def surface(endpoint: PublicEndpoint, outcome: SurfaceOutcome) -> SurfaceEvidence:
    return {
        "method": "GET",
        "url": endpoint.url,
        "domain": str(httpx.URL(endpoint.url).host or ""),
        "status_code": outcome.status_code,
        "ok": outcome.ok,
        "record_count": outcome.record_count,
        "detail": outcome.detail,
    }


def gamma_events(payload: JsonValue | None) -> list[JsonObject]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        events = payload.get("events") or payload.get("data")
        if isinstance(events, list):
            return [item for item in events if isinstance(item, dict)]
        return [payload]
    return []


def markets_from_gamma(settings: Settings, payload: JsonValue | None) -> list[Market]:
    payloads = flatten_markets(gamma_events(payload))
    markets: list[Market] = []
    for event in payloads:
        match = match_crypto_updown(settings, event)
        if match is None or not allowed_active_market(settings, event):
            continue
        asset, timeframe = match
        try:
            market = Market.from_gamma(event, asset=asset, timeframe=timeframe)
        except (TypeError, ValueError, KeyError):
            continue
        if len(market.outcome_tokens) >= 2:
            markets.append(market)
    return markets or fallback_public_markets(payloads)


def fallback_public_markets(payloads: list[JsonObject]) -> list[Market]:
    for payload in payloads:
        if not fallback_active_market(payload):
            continue
        try:
            market = Market.from_gamma(payload, asset="PUBLIC", timeframe="live")
        except (TypeError, ValueError, KeyError):
            continue
        if len(market.outcome_tokens) >= 2:
            return [market]
    return []


def fallback_active_market(payload: JsonObject) -> bool:
    token_ids = payload.get("clobTokenIds") or payload.get("clob_token_ids") or payload.get("tokenIds")
    if not token_ids:
        return False
    closed = bool(payload.get("closed") or payload.get("archived") or payload.get("resolved"))
    return bool(payload.get("active", not closed)) and not closed


def flatten_markets(payloads: list[JsonObject]) -> list[JsonObject]:
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


def match_crypto_updown(settings: Settings, payload: JsonObject) -> tuple[str, str] | None:
    slug = str(payload.get("slug") or payload.get("eventSlug") or "")
    match = re.match(r"^([a-z0-9]+)-updown-([0-9]+m)-\d+$", slug.lower())
    if match is None:
        return None
    asset = match.group(1).upper()
    timeframe = match.group(2)
    configured_assets = {configured.upper() for configured in settings.markets.assets}
    if asset in configured_assets and timeframe in settings.markets.timeframes:
        return asset, timeframe
    return None


def allowed_active_market(settings: Settings, payload: JsonObject) -> bool:
    closed = bool(payload.get("closed") or payload.get("archived") or payload.get("resolved"))
    active = bool(payload.get("active", not closed))
    if settings.markets.active_only and not active:
        return False
    return closed == settings.markets.closed


def first_token_id(markets: list[Market]) -> str | None:
    for market in markets:
        for token in market.outcome_tokens:
            if token.token_id:
                return token.token_id
    return None


def book_from_payload(payload: JsonValue | None) -> OrderBook | None:
    if not isinstance(payload, dict):
        return None
    try:
        return parse_order_book_payload(payload)
    except (TypeError, ValueError):
        return None


def spot_from_payload(payload: JsonValue | None, symbol: str) -> SpotPrice | None:
    if not isinstance(payload, dict):
        return None
    bid = safe_float(payload.get("bidPrice") or payload.get("b"))
    ask = safe_float(payload.get("askPrice") or payload.get("a"))
    price = safe_float(payload.get("price") or payload.get("lastPrice"))
    if bid is not None and ask is not None:
        price = round((bid + ask) / 2.0, 10)
    if price is None:
        return None
    return SpotPrice(asset=symbol.removesuffix("USDT"), symbol=symbol, price=price, received_at=utc_now())
