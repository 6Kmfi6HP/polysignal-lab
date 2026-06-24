from __future__ import annotations

from pydantic import JsonValue

from polysignal_lab.app.readonly_smoke_public import book_from_payload, spot_from_payload
from polysignal_lab.app.readonly_smoke_types import (
    DashboardEvidence,
    ReadonlySmokeRequest,
    SafetyEvidence,
    SchedulerSnapshotEvidence,
    SurfaceEvidence,
)
from polysignal_lab.app.scheduler import PolySignalScheduler
from polysignal_lab.dashboard.app import create_dashboard_app
from polysignal_lab.data.price_to_beat_provider import PriceToBeatResult, PriceToBeatProvider
from polysignal_lab.domain.market import Market
from polysignal_lab.observability.safety import scan

import httpx


class StaticPriceToBeatProvider(PriceToBeatProvider):
    def __init__(self) -> None:
        return None

    async def get(self, market: Market) -> PriceToBeatResult:
        return PriceToBeatResult(
            value=market.price_to_beat,
            source="gamma_metadata" if market.price_to_beat is not None else "unavailable",
            verified=market.price_to_beat is not None,
        )


async def check_scheduler_snapshot(
    request: ReadonlySmokeRequest,
    markets: list[Market],
    book_payload: JsonValue | None,
    spot_payload: JsonValue | None,
) -> SchedulerSnapshotEvidence:
    if not markets:
        return {
            "created": False,
            "market_count": 0,
            "token_count": 0,
            "snapshot_id": None,
            "detail": "No discovered markets available for scheduler snapshot",
        }
    scheduler = PolySignalScheduler(request.settings, base_dir=request.base_dir)
    await close_scheduler_clients(scheduler)
    try:
        market = markets[0]
        scheduler.ctx.markets.upsert_many([market])
        scheduler.sqlite.upsert_market(market)
        book = book_from_payload(book_payload)
        if book is not None:
            scheduler.ctx.books.update(book)
        spot = spot_from_payload(
            spot_payload,
            request.settings.data.binance.symbols.get(market.asset, f"{market.asset}USDT"),
        )
        if spot is not None:
            scheduler.ctx.spots.update(spot)
        scheduler.snapshot_builder.ptb_provider = StaticPriceToBeatProvider()
        snapshot = await scheduler.snapshot_builder.build(market)
        return {
            "created": True,
            "market_count": len(markets),
            "token_count": len(market.outcome_tokens),
            "snapshot_id": snapshot.snapshot_id,
            "detail": "Public active Gamma fallback market" if market.asset == "PUBLIC" else None,
        }
    finally:
        scheduler.sqlite.close()


async def check_dashboard_reads(request: ReadonlySmokeRequest) -> DashboardEvidence:
    scheduler = PolySignalScheduler(request.settings, base_dir=request.base_dir)
    await close_scheduler_clients(scheduler)
    try:
        dashboard = create_dashboard_app(scheduler.sqlite)
        transport = httpx.ASGITransport(app=dashboard)
        endpoints = ("/health", "/api/overview", "/api/leaderboard", "/")
        async with httpx.AsyncClient(transport=transport, base_url="http://dashboard.local") as client:
            responses = [await client.get(endpoint) for endpoint in endpoints]
        ok = all(response.status_code == 200 for response in responses)
        return {
            "ok": ok,
            "endpoint_count": len(endpoints),
            "detail": None if ok else "At least one dashboard read endpoint failed",
        }
    finally:
        scheduler.sqlite.close()


def check_safety_scan() -> SafetyEvidence:
    findings = scan(".")
    return {
        "ok": not findings,
        "finding_count": len(findings),
        "detail": None if not findings else "; ".join(path for path, _symbol in findings[:5]),
    }


def failure_count(
    surfaces: dict[str, SurfaceEvidence],
    scheduler_snapshot: SchedulerSnapshotEvidence,
    dashboard_reads: DashboardEvidence,
    safety_scan: SafetyEvidence,
) -> int:
    count = sum(1 for surface in surfaces.values() if not surface["ok"])
    if not scheduler_snapshot["created"]:
        count += 1
    if not dashboard_reads["ok"]:
        count += 1
    if not safety_scan["ok"]:
        count += 1
    return count


async def close_scheduler_clients(scheduler: PolySignalScheduler) -> None:
    await scheduler.discovery.client.aclose()
    market_data_client = getattr(scheduler.market_data, "client", None)
    if market_data_client is not None:
        await market_data_client.aclose()
    await scheduler.ptb.client.aclose()
