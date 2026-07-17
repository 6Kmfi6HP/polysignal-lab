"""
Input: __future__, __future__.annotations, typing, typing.Final, httpx, pydantic, pydantic.JsonValue, pydantic.TypeAdapter, polysignal_lab.app.readonly_smoke_types, polysignal_lab.app.readonly_smoke_types.(
Output: make_public_client, check_gamma_events, check_clob_book, check_clob_404, check_binance_spot, public_get, raw_public_get, response_json, surface, first_token_id
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""









from __future__ import annotations

from typing import Final

import httpx
from pydantic import JsonValue, TypeAdapter

from polysignal_lab.app.readonly_smoke_types import (
    PublicEndpoint,
    SurfaceEvidence,
    SurfaceOutcome,
    SurfacePayload,
)
from polysignal_lab.config import Settings
from polysignal_lab.data.market_discovery_helpers import (
    gamma_events_from_json,
    gamma_events_query_params,
)
from polysignal_lab.domain.market import Market
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
        params=gamma_events_query_params(settings.markets, 0),
    )
    result = await public_get(client, endpoint)
    record_count = len(gamma_events_from_json(result.payload)) if result.evidence["ok"] else 0
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
    book_ok = clob_book_payload_ok(result.payload)
    evidence = result.evidence
    evidence["record_count"] = 1 if book_ok else 0
    evidence["ok"] = evidence["ok"] and book_ok
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


def first_token_id(markets: list[Market]) -> str | None:
    for market in markets:
        for token in market.outcome_tokens:
            if token.token_id:
                return token.token_id
    return None


def clob_book_payload_ok(payload: JsonValue | None) -> bool:
    """Minimal HTTP probe: accept a CLOB book-shaped JSON object."""
    if not isinstance(payload, dict):
        return False
    bids = payload.get("bids")
    asks = payload.get("asks")
    if not isinstance(bids, list) or not isinstance(asks, list):
        return False
    token = payload.get("asset_id") or payload.get("token_id") or payload.get("assetId")
    if token in (None, ""):
        return False
    return True


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
