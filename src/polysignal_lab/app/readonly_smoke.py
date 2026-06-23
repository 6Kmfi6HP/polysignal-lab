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
    markets_from_gamma,
)
from polysignal_lab.app.readonly_smoke_runtime import (
    check_dashboard_reads,
    check_safety_scan,
    check_scheduler_snapshot,
    failure_count,
)
from polysignal_lab.app.readonly_smoke_types import (
    ReadonlySmokeEvidence,
    ReadonlySmokeRequest,
)

__all__ = ["ReadonlySmokeRequest", "collect_readonly_smoke"]


async def collect_readonly_smoke(
    request: ReadonlySmokeRequest,
    client: httpx.AsyncClient | None = None,
) -> ReadonlySmokeEvidence:
    active_client = client or make_public_client()
    owns_client = client is None
    try:
        gamma = await check_gamma_events(request.settings, active_client)
        markets = markets_from_gamma(request.settings, gamma.payload)
        clob_book = await check_clob_book(request.settings, active_client, markets)
        clob_404 = await check_clob_404(request.settings, active_client)
        binance = await check_binance_spot(request.settings, active_client)
        scheduler_snapshot = await check_scheduler_snapshot(
            request,
            markets,
            clob_book.payload,
            binance.payload,
        )
        dashboard_reads = await check_dashboard_reads(request)
        safety_scan = check_safety_scan()
        surfaces = {
            "gamma_active_events": gamma.evidence,
            "clob_book": clob_book.evidence,
            "clob_404": clob_404.evidence,
            "binance_spot_rest": binance.evidence,
        }
        failures = failure_count(surfaces, scheduler_snapshot, dashboard_reads, safety_scan)
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
