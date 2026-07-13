"""
Input: __future__, json, datetime, pathlib, httpx, polysignal_lab.app.readonly_smoke_public, polysignal_lab.app.readonly_smoke_types, polysignal_lab.data.polymarket_market_discovery
Output: collect_readonly_smoke, write_evidence
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from polysignal_lab.app.readonly_smoke_public import (
    check_binance_spot,
    check_clob_404,
    check_clob_book,
    check_gamma_events,
    make_public_client,
)
from polysignal_lab.app.readonly_smoke_types import (
    ReadonlySmokeEvidence,
    ReadonlySmokeRequest,
)
from polysignal_lab.data.polymarket_market_discovery import MarketDiscovery


async def _check_dashboard_reads_retired(request: object) -> dict[str, object]:
    _ = request
    return {
        "status": "not_run",
        "ok": True,
        "endpoint_count": 0,
        "detail": "Dashboard smoke retired; use Nautilus runtime probes",
    }


async def _check_health_snapshot_retired(request: object) -> dict[str, object]:
    _ = request
    return {
        "status": "not_run",
        "generated_at": None,
        "components": [],
    }


async def _check_scheduler_snapshot_retired(
    request: object, markets: list[object], book_payload: object, spot_payload: object,
) -> dict[str, object]:
    _ = request
    _ = markets
    _ = book_payload
    _ = spot_payload
    return {
        "status": "not_run",
        "created": False,
        "market_count": 0,
        "token_count": 0,
        "snapshot_id": None,
        "detail": "Scheduler smoke retired; use Nautilus runtime probes",
    }


def _check_safety_scan_retired() -> dict[str, object]:
    return {
        "status": "not_run",
        "ok": True,
        "finding_count": 0,
        "detail": "Safety smoke retired; use the dedicated Nautilus safety scan",
    }


def _failure_count_retired(
    surfaces: dict[str, object],
    scheduler_snapshot: dict[str, object],
    health_snapshot: dict[str, object],
    dashboard_reads: dict[str, object],
    safety_scan: dict[str, object],
) -> int:
    return sum(
        1 for surface in surfaces.values() if not surface.get("ok")
    ) + (0 if health_snapshot.get("status") != "down" else 1)


check_dashboard_reads = _check_dashboard_reads_retired
check_health_snapshot = _check_health_snapshot_retired
check_scheduler_snapshot = _check_scheduler_snapshot_retired
check_safety_scan = _check_safety_scan_retired
failure_count = _failure_count_retired

__all__ = ["ReadonlySmokeRequest", "collect_readonly_smoke"]


async def collect_readonly_smoke(
    request: ReadonlySmokeRequest,
    client: httpx.AsyncClient | None = None,
) -> ReadonlySmokeEvidence:
    active_client = client or make_public_client()
    owns_client = client is None
    try:
        gamma = await check_gamma_events(request.settings, active_client)
        rotation = request.settings.runtime.nautilus.market_rotation
        markets = []
        if gamma.evidence["ok"]:
            try:
                markets = await MarketDiscovery(
                    request.settings.data.polymarket,
                    request.settings.markets,
                    client=active_client,
                ).discover(
                    include_next_periods=rotation.include_next_periods,
                    stale_grace_sec=rotation.stale_grace_sec,
                    max_event_pages=1,
                )
            except (httpx.HTTPError, TypeError, ValueError):
                pass
        clob_book = await check_clob_book(request.settings, active_client, markets)
        clob_404 = await check_clob_404(request.settings, active_client)
        binance = await check_binance_spot(request.settings, active_client)
        scheduler_snapshot = await check_scheduler_snapshot(
            request,
            markets,
            clob_book.payload,
            binance.payload,
        )
        health_snapshot = await check_health_snapshot(request)
        dashboard_reads = await check_dashboard_reads(request)
        safety_scan = check_safety_scan()
        surfaces = {
            "gamma_active_events": gamma.evidence,
            "clob_book": clob_book.evidence,
            "clob_404": clob_404.evidence,
            "binance_spot_rest": binance.evidence,
        }
        failures = failure_count(
            surfaces,
            scheduler_snapshot,
            health_snapshot,
            dashboard_reads,
            safety_scan,
        )
        evidence: ReadonlySmokeEvidence = {
            "recorded_at": datetime.now(UTC).isoformat(),
            "mode": "smoke",
            "bounded": True,
            "once": True,
            "network_calls": True,
            "authenticated_endpoints": False,
            "trading_actions": False,
            "config_path": str(request.config_path),
            "app_name": request.settings.app.name,
            "dashboard_read_only": request.settings.dashboard.read_only,
            "public_surfaces_checked": list(surfaces),
            "passed": failures == 0,
            "failure_count": failures,
            "surfaces": surfaces,
            "scheduler_snapshot": scheduler_snapshot,
            "health_snapshot": health_snapshot,
            "dashboard_reads": dashboard_reads,
            "safety_scan": safety_scan,
        }
        write_evidence(request.evidence_path, evidence)
        return evidence
    finally:
        if owns_client:
            await active_client.aclose()


def write_evidence(path: Path | None, evidence: ReadonlySmokeEvidence) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
