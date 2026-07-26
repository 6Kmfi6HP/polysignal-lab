from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from polysignal_lab.app import main as app_main
from polysignal_lab.app.readonly_smoke_types import (
    ReadonlySmokeEvidence,
    ReadonlySmokeRequest,
)


class _FakeSettings:
    def __init__(self) -> None:
        self.runtime = SimpleNamespace(nautilus=SimpleNamespace())

    def validate_runtime_environment(self) -> None:
        return None


def _worktree_env() -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": str(Path.cwd() / "src"),
    }


def test_cli_help_lists_supported_runtime_modes_without_removed_alias() -> None:
    command = [sys.executable, "-m", "polysignal_lab.app.main", "--help"]

    result = subprocess.run(
        command, capture_output=True, check=True, text=True, env=_worktree_env()
    )

    assert "--mode {dashboard,smoke,nautilus,sandbox,live,backtest}" in result.stdout
    assert "--once" in result.stdout
    assert "--real-readonly-smoke" in result.stdout
    assert "--dashboard" not in result.stdout
    assert "scheduler" not in result.stdout
    assert "--allow-legacy-scheduler" not in result.stdout
    assert "polysignal-demo" not in result.stdout
    assert "demo" not in result.stdout


def test_main_uses_config_default_nautilus_runtime_when_no_mode_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    fake_settings = _FakeSettings()
    fake_module = ModuleType("polysignal_lab.nautilus_runtime.node")
    setattr(
        fake_module,
        "run_nautilus_cli",
        lambda settings: calls.append("nautilus"),
    )

    monkeypatch.setattr(app_main, "load_settings", lambda path: fake_settings)
    monkeypatch.setitem(
        sys.modules, "polysignal_lab.nautilus_runtime.node", fake_module
    )

    exit_code = app_main.main([])

    assert exit_code == 0
    assert calls == ["nautilus"]


def test_main_uses_nautilus_when_no_mode_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    fake_settings = _FakeSettings()
    fake_module = ModuleType("polysignal_lab.nautilus_runtime.node")
    setattr(
        fake_module,
        "run_nautilus_cli",
        lambda settings: calls.append("nautilus"),
    )

    monkeypatch.setattr(app_main, "load_settings", lambda path: fake_settings)
    monkeypatch.setitem(
        sys.modules, "polysignal_lab.nautilus_runtime.node", fake_module
    )

    exit_code = app_main.main([])

    assert exit_code == 0
    assert calls == ["nautilus"]


@pytest.mark.parametrize("mode", ["sandbox", "live", "backtest"])
def test_main_selects_explicit_nautilus_trading_mode(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    fake_settings = _FakeSettings()
    fake_module = ModuleType("polysignal_lab.nautilus_runtime.node")
    setattr(
        fake_module,
        "run_nautilus_cli",
        lambda settings: calls.append(settings.runtime.nautilus.execution_mode),
    )

    monkeypatch.setattr(app_main, "load_settings", lambda path: fake_settings)
    monkeypatch.setitem(
        sys.modules, "polysignal_lab.nautilus_runtime.node", fake_module
    )

    exit_code = app_main.main(["--mode", mode])

    assert exit_code == 0
    assert calls == [mode]


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

    result = subprocess.run(
        command, capture_output=True, check=True, text=True, env=_worktree_env()
    )

    assert result.stdout.strip() == "False"


def test_scheduler_mode_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        app_main.parse_cli(["--mode", "scheduler"])

    assert (
        "invalid choice" in capsys.readouterr().err.lower()
        or "scheduler" in capsys.readouterr().err
    )


def test_dashboard_flag_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        app_main.parse_cli(["--dashboard"])

    assert (
        "unrecognized arguments" in capsys.readouterr().err.lower()
        or "dashboard" in capsys.readouterr().err
    )


@pytest.mark.parametrize("flag", ["--once", "--real-readonly-smoke"])
def test_smoke_flags_require_explicit_smoke_mode(
    flag: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        app_main.parse_cli([flag])

    assert "require the explicit 'smoke' mode" in capsys.readouterr().err


def test_explicit_smoke_writes_bounded_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path = tmp_path / "smoke.json"
    argv = ["--mode", "smoke", "--evidence", str(evidence_path)]
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
            "status": "created",
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
        "dashboard_reads": {
            "status": "ok",
            "ok": True,
            "endpoint_count": 4,
            "detail": None,
        },
        "safety_scan": {"status": "ok", "ok": True, "finding_count": 0, "detail": None},
    }

    async def fake_collect(request: ReadonlySmokeRequest) -> ReadonlySmokeEvidence:
        if request.evidence_path is not None:
            request.evidence_path.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    monkeypatch.setattr(app_main, "_collect_readonly_smoke", fake_collect)

    exit_code = app_main.main(argv)

    recorded = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert recorded["mode"] == "smoke"
    assert recorded["bounded"] is True
    assert recorded["network_calls"] is True
    assert recorded["authenticated_endpoints"] is False
    assert recorded["trading_actions"] is False
    assert recorded["health_snapshot"]["status"] == "degraded"
