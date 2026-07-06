from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from polysignal_lab.app import main as app_main
from polysignal_lab.app.readonly_smoke_types import ReadonlySmokeEvidence, ReadonlySmokeRequest


class _FakeSettings:
    def __init__(self, engine: str) -> None:
        self.runtime = SimpleNamespace(engine=engine)

    def validate_runtime_environment(self) -> None:
        return None

def _worktree_env() -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": str(Path.cwd() / "src"),
    }



def test_cli_help_lists_supported_runtime_modes_without_removed_alias() -> None:
    # Given: the installed module CLI is available.
    command = [sys.executable, "-m", "polysignal_lab.app.main", "--help"]

    # When: help is requested through the public CLI surface.
    result = subprocess.run(command, capture_output=True, check=True, text=True, env=_worktree_env())

    # Then: help lists stable supported modes and excludes removed aliases.
    assert "--mode {scheduler,dashboard,smoke,nautilus}" in result.stdout
    assert "--once" in result.stdout
    assert "--real-readonly-smoke" in result.stdout
    assert "--allow-legacy-scheduler" not in result.stdout
    assert "polysignal-demo" not in result.stdout
    assert "demo" not in result.stdout


def test_dashboard_compatibility_alias_resolves_to_dashboard() -> None:
    # Given: callers still use the historical dashboard flag.
    argv = ["--dashboard"]

    # When: CLI options are parsed.
    options = app_main.parse_cli(argv)

    # Then: the flag resolves to the explicit dashboard mode.
    assert options.mode is app_main.RuntimeMode.DASHBOARD


def test_main_uses_config_default_nautilus_runtime_when_no_mode_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: no explicit runtime selector and the loaded settings default to Nautilus.
    calls: list[str] = []
    fake_settings = _FakeSettings("nautilus")
    fake_module = ModuleType("polysignal_lab.nautilus_runtime.node")
    setattr(
        fake_module,
        "run_nautilus_cli",
        lambda settings: calls.append(f"nautilus:{settings.runtime.engine}"),
    )

    monkeypatch.setattr(app_main, "load_settings", lambda path: fake_settings)
    monkeypatch.setattr(app_main, "run_scheduler_cli", lambda settings: calls.append("scheduler"))
    monkeypatch.setitem(sys.modules, "polysignal_lab.nautilus_runtime.node", fake_module)

    # When: the main entry runs without command or --mode.
    exit_code = app_main.main([])

    # Then: it follows the configured Nautilus default instead of the legacy scheduler default.
    assert exit_code == 0
    assert calls == ["nautilus:nautilus"]

def test_main_uses_nautilus_when_legacy_config_is_default_without_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    fake_settings = _FakeSettings("legacy")
    fake_module = ModuleType("polysignal_lab.nautilus_runtime.node")
    setattr(
        fake_module,
        "run_nautilus_cli",
        lambda settings: calls.append(f"nautilus:{settings.runtime.engine}"),
    )

    monkeypatch.setattr(app_main, "load_settings", lambda path: fake_settings)
    monkeypatch.setattr(app_main, "run_scheduler_cli", lambda settings: calls.append("scheduler"))
    monkeypatch.setitem(sys.modules, "polysignal_lab.nautilus_runtime.node", fake_module)

    exit_code = app_main.main([])

    assert exit_code == 0
    assert calls == ["nautilus:legacy"]


def test_main_import_does_not_load_legacy_scheduler_stack() -> None:
    command = [
        sys.executable,
        "-c",
        (
            "import sys; "
            "import polysignal_lab.app.main; "
            "print('polysignal_lab.app.scheduler' in sys.modules)"
        ),
    ]

    result = subprocess.run(command, capture_output=True, check=True, text=True, env=_worktree_env())

    assert result.stdout.strip() == "False"


def test_explicit_legacy_scheduler_requires_hidden_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    fake_settings = _FakeSettings("nautilus")

    monkeypatch.setattr(app_main, "load_settings", lambda path: fake_settings)
    monkeypatch.setattr(app_main, "run_scheduler_cli", lambda settings: calls.append("scheduler"))

    exit_code = app_main.main(["--mode", "scheduler", "--allow-legacy-scheduler"])

    assert exit_code == 0
    assert calls == ["scheduler"]


def test_main_scheduler_mode_without_once_aliases_to_nautilus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the caller requests scheduler mode without --once.
    calls: list[str] = []
    fake_settings = _FakeSettings("nautilus")
    fake_module = ModuleType("polysignal_lab.nautilus_runtime.node")
    setattr(fake_module, "run_nautilus_cli", lambda settings: calls.append("nautilus"))

    monkeypatch.setattr(app_main, "load_settings", lambda path: fake_settings)
    monkeypatch.setattr(app_main, "run_scheduler_cli", lambda settings: calls.append("scheduler"))
    monkeypatch.setitem(sys.modules, "polysignal_lab.nautilus_runtime.node", fake_module)

    # When: scheduler mode is provided without --once.
    exit_code = app_main.main(["--mode", "scheduler"])

    # Then: the legacy scheduler selector aliases to Nautilus instead of the scheduler CLI.
    assert exit_code == 0
    assert calls == ["nautilus"]


def test_main_scheduler_mode_with_once_runs_readonly_smoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: scheduler mode is requested with bounded --once smoke.
    calls: list[str] = []
    fake_settings = _FakeSettings("nautilus")
    fake_module = ModuleType("polysignal_lab.nautilus_runtime.node")
    setattr(fake_module, "run_nautilus_cli", lambda settings: calls.append("nautilus"))

    def fake_readonly_smoke(settings: object, options: object) -> None:
        calls.append("readonly_smoke")

    monkeypatch.setattr(app_main, "load_settings", lambda path: fake_settings)
    monkeypatch.setattr(app_main, "run_scheduler_cli", lambda settings: calls.append("scheduler"))
    monkeypatch.setattr(app_main, "run_readonly_smoke", fake_readonly_smoke)
    monkeypatch.setitem(sys.modules, "polysignal_lab.nautilus_runtime.node", fake_module)

    # When: scheduler mode is combined with --once.
    exit_code = app_main.main(["--mode", "scheduler", "--once"])

    # Then: bounded read-only smoke runs instead of Nautilus or the scheduler CLI.
    assert exit_code == 0
    assert calls == ["readonly_smoke"]


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
        "health_snapshot": {
            "status": "degraded",
            "generated_at": "2026-06-24T00:00:00Z",
            "components": [
                {
                    "name": "binance_ws",
                    "status": "degraded",
                    "last_success_at": None,
                    "last_error_at": "2026-06-24T00:00:00Z",
                    "last_error": "bounded smoke uses REST fallback",
                    "metrics": {},
                }
            ],
        },
        "dashboard_reads": {"ok": True, "endpoint_count": 4, "detail": None},
        "safety_scan": {"ok": True, "finding_count": 0, "detail": None},
    }

    async def fake_collect(request: ReadonlySmokeRequest) -> ReadonlySmokeEvidence:
        if request.evidence_path is not None:
            request.evidence_path.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    monkeypatch.setattr(app_main, "_collect_readonly_smoke", fake_collect)

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
    assert recorded["health_snapshot"]["status"] == "degraded"
