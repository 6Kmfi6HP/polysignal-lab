"""
Input: __future__, __future__.annotations, json, pathlib, pathlib.Path, httpx, pytest, pydantic, pydantic.JsonValue, polysignal_lab.app
Output: test_fake_public_api_outage_degrades_without_unhandled_exception, test_health_snapshot_syncs_before_client_cleanup, test_failure_count_counts_only_down_health_snapshot
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import json

from pathlib import Path

import httpx
import pytest
from pydantic import JsonValue

from polysignal_lab.app.readonly_smoke import (
    ReadonlySmokeRequest,
    collect_readonly_smoke,
    failure_count,
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
    assert evidence["scheduler_snapshot"]["created"] is False
    assert evidence["health_snapshot"]["status"] in {"unknown", "ok", "degraded"}
    assert evidence["dashboard_reads"]["ok"] is False
    assert evidence["safety_scan"]["ok"] is True
    written_evidence = json.loads(request.evidence_path.read_text(encoding="utf-8"))
    assert written_evidence["health_snapshot"] == evidence["health_snapshot"]
    assert all("authorization" not in {key.lower() for key in item.headers} for item in requests)


async def test_health_snapshot_syncs_before_client_cleanup(
    tmp_path: Path,
) -> None:
    request = ReadonlySmokeRequest(
        settings=Settings(),
        config_path=Path("config/signal_bot.yaml"),
        evidence_path=None,
        base_dir=tmp_path / "runtime",
    )

    evidence = await collect_readonly_smoke(request, httpx.AsyncClient())

    assert evidence["health_snapshot"]["status"] in {"unknown", "ok", "degraded"}


def test_failure_count_counts_only_down_health_snapshot() -> None:
    surfaces = {
        "gamma_active_events": {
            "method": "GET",
            "url": "https://gamma-api.polymarket.com/events",
            "domain": "gamma-api.polymarket.com",
            "status_code": 200,
            "ok": True,
            "record_count": 1,
            "detail": None,
        }
    }
    scheduler_snapshot = {
        "created": True,
        "market_count": 1,
        "token_count": 2,
        "snapshot_id": "snapshot-1",
        "detail": None,
    }
    dashboard_reads = {"ok": True, "endpoint_count": 4, "detail": None}
    safety_scan = {"ok": True, "finding_count": 0, "detail": None}

    degraded_failures = failure_count(
        surfaces,
        scheduler_snapshot,
        {"status": "degraded", "generated_at": "2026-06-24T00:00:00Z", "components": []},
        dashboard_reads,
        safety_scan,
    )
    down_failures = failure_count(
        surfaces,
        scheduler_snapshot,
        {"status": "down", "generated_at": "2026-06-24T00:00:00Z", "components": []},
        dashboard_reads,
        safety_scan,
    )

    assert degraded_failures == 0
    assert down_failures == 1
