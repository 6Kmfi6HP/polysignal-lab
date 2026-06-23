from __future__ import annotations

from pathlib import Path

import httpx
from pydantic import JsonValue

from polysignal_lab.app.readonly_smoke import (
    ReadonlySmokeRequest,
    collect_readonly_smoke,
)
from polysignal_lab.config import Settings


def _gamma_payload() -> list[dict[str, JsonValue]]:
    return [
        {
            "id": "event-1",
            "slug": "btc-updown-5m-1710000000",
            "title": "Bitcoin Up or Down - 5m",
            "active": True,
            "closed": False,
            "markets": [
                {
                    "id": "market-1",
                    "conditionId": "0xcondition",
                    "slug": "btc-updown-5m-1710000000",
                    "question": "Bitcoin Up or Down - 5m",
                    "active": True,
                    "closed": False,
                    "priceToBeat": "100.00",
                    "outcomes": '["Up", "Down"]',
                    "clobTokenIds": '["token-up", "token-down"]',
                }
            ],
        }
    ]


def _book_payload(token_id: str) -> dict[str, JsonValue]:
    return {
        "market": "0xcondition",
        "asset_id": token_id,
        "bids": [{"price": "0.40", "size": "12"}],
        "asks": [{"price": "0.52", "size": "8"}],
        "last_trade_price": "0.49",
    }


async def test_fake_public_api_outage_degrades_without_unhandled_exception(
    tmp_path: Path,
) -> None:
    # Given: Gamma, CLOB, Binance, scheduler, dashboard, and safety are checked
    # through public read-only HTTP shapes, with Binance degraded.
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        host = request.url.host
        path = request.url.path
        token_id = request.url.params.get("token_id")
        if host == "gamma-api.polymarket.com" and path == "/events":
            return httpx.Response(200, json=_gamma_payload(), request=request)
        if host == "clob.polymarket.com" and path == "/book" and token_id in {"token-up", "token-down"}:
            return httpx.Response(200, json=_book_payload(token_id), request=request)
        if host == "clob.polymarket.com" and path == "/book":
            return httpx.Response(404, json={"error": "not found"}, request=request)
        if host == "api.binance.com" and path == "/api/v3/ticker/bookTicker":
            return httpx.Response(503, json={"msg": "maintenance"}, request=request)
        return httpx.Response(500, json={"error": "unexpected"}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = Settings()
    request = ReadonlySmokeRequest(
        settings=settings,
        config_path=Path("config/signal_bot.yaml"),
        evidence_path=tmp_path / "smoke.json",
        base_dir=tmp_path / "runtime",
    )

    # When: the bounded smoke collector runs.
    evidence = await collect_readonly_smoke(request, client)

    # Then: it records real-surface status without auth headers or a crash.
    assert evidence["bounded"] is True
    assert evidence["authenticated_endpoints"] is False
    assert evidence["trading_actions"] is False
    assert evidence["passed"] is False
    assert evidence["failure_count"] == 1
    assert evidence["surfaces"]["gamma_active_events"]["record_count"] == 1
    assert evidence["surfaces"]["clob_book"]["status_code"] == 200
    assert evidence["surfaces"]["clob_404"]["status_code"] == 404
    assert evidence["surfaces"]["binance_spot_rest"]["ok"] is False
    assert evidence["scheduler_snapshot"]["created"] is True
    assert evidence["dashboard_reads"]["ok"] is True
    assert evidence["safety_scan"]["ok"] is True
    assert request.evidence_path.read_text(encoding="utf-8")
    assert all("authorization" not in {key.lower() for key in item.headers} for item in requests)
