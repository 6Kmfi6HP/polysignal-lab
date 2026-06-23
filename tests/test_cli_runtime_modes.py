from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from polysignal_lab.app import main as app_main
from polysignal_lab.app.readonly_smoke_types import ReadonlySmokeEvidence, ReadonlySmokeRequest


def test_cli_help_lists_supported_runtime_modes_without_removed_alias() -> None:
    # Given: the installed module CLI is available.
    command = [sys.executable, "-m", "polysignal_lab.app.main", "--help"]

    # When: help is requested through the public CLI surface.
    result = subprocess.run(command, capture_output=True, check=True, text=True)

    # Then: help lists stable supported modes and excludes removed aliases.
    assert "--mode {scheduler,dashboard,smoke}" in result.stdout
    assert "--once" in result.stdout
    assert "--real-readonly-smoke" in result.stdout
    assert "polysignal-demo" not in result.stdout
    assert "demo" not in result.stdout


def test_dashboard_compatibility_alias_resolves_to_dashboard() -> None:
    # Given: callers still use the historical dashboard flag.
    argv = ["--dashboard"]

    # When: CLI options are parsed.
    options = app_main.parse_cli(argv)

    # Then: the flag resolves to the explicit dashboard mode.
    assert options.mode is app_main.RuntimeMode.DASHBOARD


def test_once_readonly_smoke_writes_bounded_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: the bounded smoke mode is requested with an evidence destination.
    evidence_path = tmp_path / "smoke.json"
    argv = ["--once", "--real-readonly-smoke", "--evidence", str(evidence_path)]
    payload: ReadonlySmokeEvidence = {
        "recorded_at": "2026-06-22T00:00:00+00:00",
        "mode": "smoke",
        "bounded": True,
        "once": True,
        "network_calls": True,
        "authenticated_endpoints": False,
        "trading_actions": False,
        "config_path": "config/signal_bot.yaml",
        "app_name": "PolySignal Lab",
        "dashboard_read_only": True,
        "public_surfaces_checked": ["gamma_active_events"],
        "passed": True,
        "failure_count": 0,
        "surfaces": {},
        "scheduler_snapshot": {
            "created": True,
            "market_count": 1,
            "token_count": 2,
            "snapshot_id": "snap-test",
            "detail": None,
        },
        "dashboard_reads": {"ok": True, "endpoint_count": 4, "detail": None},
        "safety_scan": {"ok": True, "finding_count": 0, "detail": None},
    }

    async def fake_collect(request: ReadonlySmokeRequest) -> ReadonlySmokeEvidence:
        if request.evidence_path is not None:
            request.evidence_path.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    monkeypatch.setattr(app_main, "collect_readonly_smoke", fake_collect)

    # When: the public CLI is invoked.
    exit_code = app_main.main(argv)

    # Then: it exits successfully and records public read-only smoke evidence.
    recorded = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert recorded["mode"] == "smoke"
    assert recorded["bounded"] is True
    assert recorded["network_calls"] is True
    assert recorded["authenticated_endpoints"] is False
    assert recorded["trading_actions"] is False
