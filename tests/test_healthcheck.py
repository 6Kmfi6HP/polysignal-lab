"""
Input: __future__, __future__.annotations, concurrent.futures, concurrent.futures.ThreadPoolExecutor, json, datetime, datetime.UTC, datetime.datetime, datetime.timedelta, pathlib
Output: test_liveness_passes_for_fresh_heartbeat, test_liveness_fails_for_stale_heartbeat, test_liveness_fails_for_fatal_heartbeat, test_liveness_fails_for_missing_heartbeat, test_liveness_allows_missing_heartbeat_during_startup_grace, test_liveness_fails_for_missing_heartbeat_after_startup_grace, test_liveness_allows_stale_heartbeat_during_startup_grace, test_liveness_fails_for_corrupt_heartbeat, test_liveness_fails_for_malformed_heartbeat_timestamp, test_liveness_fails_for_wrong_heartbeat_field_types
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
import threading

import pytest

from polysignal_lab.observability.health import ComponentHealth, HealthSnapshot
from polysignal_lab.observability.runtime_health import (
    RestartGateResult,
    evaluate_liveness,
    evaluate_restart_gate,
    read_runtime_heartbeat,
    write_runtime_heartbeat,
)


def _dt(second: int) -> datetime:
    return datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC) + timedelta(seconds=second)


def test_liveness_passes_for_fresh_heartbeat(tmp_path) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    write_runtime_heartbeat(path, phase="running", now=_dt(0))

    result = evaluate_liveness(path, max_age_sec=120, now=_dt(30))

    assert result.ok is True
    assert result.reason is None
    assert result.heartbeat_age_sec == 30


def test_liveness_fails_for_stale_heartbeat(tmp_path) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    write_runtime_heartbeat(path, phase="running", now=_dt(0))

    result = evaluate_liveness(path, max_age_sec=120, now=_dt(121))

    assert result.ok is False
    assert result.reason == "heartbeat_stale"
    assert result.heartbeat_age_sec == 121


def test_liveness_fails_for_fatal_heartbeat(tmp_path) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    write_runtime_heartbeat(
        path,
        phase="fatal",
        fatal=True,
        fatal_reason="LiveNode.run returned unexpectedly",
        now=_dt(0),
    )

    result = evaluate_liveness(path, max_age_sec=120, now=_dt(1))

    assert result.ok is False
    assert result.reason == "fatal"
    assert result.fatal_reason == "LiveNode.run returned unexpectedly"


def test_liveness_fails_for_missing_heartbeat(tmp_path) -> None:
    result = evaluate_liveness(
        tmp_path / "runtime_heartbeat.json",
        max_age_sec=120,
        now=_dt(0),
    )

    assert result.ok is False
    assert result.reason == "heartbeat_missing"

def test_liveness_allows_missing_heartbeat_during_startup_grace(tmp_path) -> None:
    result = evaluate_liveness(
        tmp_path / "runtime_heartbeat.json",
        max_age_sec=120,
        startup_started_at=_dt(0),
        startup_grace_sec=60,
        now=_dt(59),
    )

    assert result.ok is True
    assert result.reason is None


def test_liveness_fails_for_missing_heartbeat_after_startup_grace(tmp_path) -> None:
    result = evaluate_liveness(
        tmp_path / "runtime_heartbeat.json",
        max_age_sec=120,
        startup_started_at=_dt(0),
        startup_grace_sec=60,
        now=_dt(61),
    )

    assert result.ok is False
    assert result.reason == "heartbeat_missing"


def test_liveness_allows_stale_heartbeat_during_startup_grace(tmp_path) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    write_runtime_heartbeat(path, phase="starting", now=_dt(0))

    result = evaluate_liveness(
        path,
        max_age_sec=10,
        startup_started_at=_dt(0),
        startup_grace_sec=60,
        now=_dt(30),
    )

    assert result.ok is True
    assert result.heartbeat_age_sec == 30


def test_liveness_fails_for_corrupt_heartbeat(tmp_path) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    path.write_text("not-json", encoding="utf-8")

    result = evaluate_liveness(
        path,
        max_age_sec=120,
        startup_started_at=_dt(0),
        startup_grace_sec=60,
        now=_dt(30),
    )

    assert result.ok is False
    assert result.reason == "heartbeat_unreadable"


def test_liveness_fails_for_malformed_heartbeat_timestamp(tmp_path) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    path.write_text(
        json.dumps(
            {
                "updated_at": "not-a-timestamp",
                "phase": "running",
                "fatal": False,
                "fatal_reason": None,
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_liveness(path, max_age_sec=120, now=_dt(0))

    assert result.ok is False
    assert result.reason == "heartbeat_unreadable"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "updated_at": 0,
            "phase": "running",
            "fatal": False,
            "fatal_reason": None,
        },
        {
            "updated_at": "2026-06-30T12:00:00+00:00",
            "phase": 0,
            "fatal": False,
            "fatal_reason": None,
        },
        {
            "updated_at": "2026-06-30T12:00:00+00:00",
            "phase": "running",
            "fatal": "false",
            "fatal_reason": None,
        },
        {
            "updated_at": "2026-06-30T12:00:00+00:00",
            "phase": "running",
            "fatal": False,
            "fatal_reason": 0,
        },
    ],
)
def test_liveness_fails_for_wrong_heartbeat_field_types(tmp_path, payload) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = evaluate_liveness(path, max_age_sec=120, now=_dt(0))

    assert result.ok is False
    assert result.reason == "heartbeat_unreadable"


def test_read_runtime_heartbeat_round_trips(tmp_path) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    written = write_runtime_heartbeat(path, phase="running", now=_dt(0))

    read = read_runtime_heartbeat(path)

    assert read == written
    assert read.updated_at == "2026-06-30T12:00:00+00:00"
    assert read.phase == "running"
    assert read.fatal is False


def test_read_runtime_heartbeat_supports_legacy_readiness_miss_payload(tmp_path) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    started_at = _dt(0).isoformat()
    path.write_text(
        json.dumps(
            {
                "updated_at": started_at,
                "phase": "readiness_miss",
                "fatal": False,
                "fatal_reason": None,
                "phase_started_at": started_at,
            }
        ),
        encoding="utf-8",
    )

    heartbeat = read_runtime_heartbeat(path)

    assert tuple(heartbeat.readiness_miss_started_at_by_key.values()) == (
        started_at,
    )


def test_liveness_rejects_invalid_readiness_miss_timestamp(tmp_path) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    path.write_text(
        json.dumps(
            {
                "updated_at": _dt(0).isoformat(),
                "phase": "readiness_miss",
                "readiness_miss_started_at_by_key": {
                    "condition-a": "not-a-timestamp"
                },
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_liveness(
        path,
        max_age_sec=120,
        max_readiness_miss_sec=300,
        now=_dt(1),
    )

    assert result.ok is False
    assert result.reason == "heartbeat_unreadable"


def test_write_runtime_heartbeat_uses_independent_temp_files_for_concurrent_writes(
    monkeypatch,
    tmp_path,
) -> None:
    original_write_text = Path.write_text
    barrier = threading.Barrier(2)
    path = tmp_path / "runtime_heartbeat.json"

    def synchronized_tmp_write(self, *args, **kwargs):
        result = original_write_text(self, *args, **kwargs)
        if "runtime_heartbeat" in self.name and self.name.endswith(".tmp"):
            barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(Path, "write_text", synchronized_tmp_write)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(write_runtime_heartbeat, path, phase=f"phase-{index}")
            for index in range(2)
        ]
        for future in futures:
            future.result()

    assert read_runtime_heartbeat(path).phase in {"phase-0", "phase-1"}

def _snapshot(*components: ComponentHealth) -> HealthSnapshot:
    status = "ok"
    if any(component.status == "down" for component in components):
        status = "down"
    elif any(component.status == "degraded" for component in components):
        status = "degraded"
    return HealthSnapshot(
        status=status,
        generated_at="2026-06-30T12:00:00+00:00",
        components=list(components),
    )


def test_restart_gate_ignores_noncritical_down_component() -> None:
    result = evaluate_restart_gate(
        _snapshot(ComponentHealth(name="telegram", status="down")),
        critical_components=("runtime", "scheduler", "sqlite"),
        critical_down_sec=300,
        min_consecutive_failures=5,
        now=_dt(0),
    )

    assert result.restart_recommended is False
    assert result.critical_down_components == ()
    assert result.consecutive_failures == 0


def test_restart_gate_waits_for_duration_and_count() -> None:
    first = evaluate_restart_gate(
        _snapshot(ComponentHealth(name="runtime", status="down")),
        critical_components=("runtime",),
        critical_down_sec=300,
        min_consecutive_failures=5,
        now=_dt(0),
    )
    second = evaluate_restart_gate(
        _snapshot(ComponentHealth(name="runtime", status="down")),
        critical_components=("runtime",),
        critical_down_sec=300,
        min_consecutive_failures=5,
        previous=first,
        now=_dt(30),
    )

    assert first.restart_recommended is False
    assert first.first_down_at == "2026-06-30T12:00:00+00:00"
    assert first.consecutive_failures == 1
    assert second.restart_recommended is False
    assert second.down_duration_sec == 30
    assert second.consecutive_failures == 2


def test_restart_gate_recommends_after_sustained_critical_down() -> None:
    previous = RestartGateResult(
        restart_recommended=False,
        critical_down_components=("runtime",),
        first_down_at="2026-06-30T12:00:00+00:00",
        consecutive_failures=4,
    )

    result = evaluate_restart_gate(
        _snapshot(ComponentHealth(name="runtime", status="down")),
        critical_components=("runtime",),
        critical_down_sec=300,
        min_consecutive_failures=5,
        previous=previous,
        now=_dt(59) + timedelta(seconds=241),
    )

    assert result.restart_recommended is True
    assert result.reason == "critical_components_down"
    assert result.critical_down_components == ("runtime",)
    assert result.down_duration_sec == 300
    assert result.consecutive_failures == 5


def test_restart_gate_resets_after_recovery() -> None:
    previous = RestartGateResult(
        restart_recommended=False,
        critical_down_components=("runtime",),
        first_down_at="2026-06-30T12:00:00+00:00",
        consecutive_failures=4,
    )

    result = evaluate_restart_gate(
        _snapshot(ComponentHealth(name="runtime", status="ok")),
        critical_components=("runtime",),
        critical_down_sec=300,
        min_consecutive_failures=5,
        previous=previous,
        now=_dt(59),
    )

    assert result.restart_recommended is False
    assert result.critical_down_components == ()
    assert result.first_down_at is None
    assert result.down_duration_sec == 0
    assert result.consecutive_failures == 0


def test_healthcheck_cli_liveness_returns_zero_for_fresh_heartbeat(tmp_path) -> None:
    from polysignal_lab.healthcheck import main

    state_dir = tmp_path / "state"
    config = tmp_path / "settings.yaml"
    config.write_text(
        "\n".join(
            [
                "storage:",
                f"  state_dir: {state_dir.as_posix()}",
                "health:",
                "  liveness:",
                "    heartbeat_max_age_sec: 120",
            ]
        ),
        encoding="utf-8",
    )
    write_runtime_heartbeat(
        state_dir / "runtime_heartbeat.json",
        phase="running",
    )

    assert main(["liveness", "--config", str(config)]) == 0


def test_healthcheck_cli_liveness_returns_one_for_missing_heartbeat_without_startup_marker(
    tmp_path,
    capsys,
) -> None:
    from polysignal_lab.healthcheck import main

    state_dir = tmp_path / "state"
    config = tmp_path / "settings.yaml"
    config.write_text(
        "\n".join(
            [
                "storage:",
                f"  state_dir: {state_dir.as_posix()}",
                "health:",
                "  startup_grace_sec: 60",
                "  liveness:",
                "    heartbeat_max_age_sec: 120",
            ]
        ),
        encoding="utf-8",
    )

    assert main(["liveness", "--config", str(config)]) == 1
    assert "liveness failed:" in capsys.readouterr().out
    assert not (state_dir / "runtime_startup.json").exists()


def test_healthcheck_cli_liveness_returns_zero_for_missing_heartbeat_with_fresh_startup_marker(tmp_path) -> None:
    from polysignal_lab.healthcheck import main

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config = tmp_path / "settings.yaml"
    config.write_text(
        "\n".join(
            [
                "storage:",
                f"  state_dir: {state_dir.as_posix()}",
                "health:",
                "  startup_grace_sec: 60",
                "  liveness:",
                "    heartbeat_max_age_sec: 120",
            ]
        ),
        encoding="utf-8",
    )
    (state_dir / "runtime_startup.json").write_text(
        json.dumps({"started_at": datetime.now(UTC).isoformat()}),
        encoding="utf-8",
    )

    assert main(["liveness", "--config", str(config)]) == 0


def test_healthcheck_cli_liveness_returns_one_for_missing_heartbeat_with_expired_startup_marker(
    tmp_path,
    capsys,
) -> None:
    from polysignal_lab.healthcheck import main

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config = tmp_path / "settings.yaml"
    config.write_text(
        "\n".join(
            [
                "storage:",
                f"  state_dir: {state_dir.as_posix()}",
                "health:",
                "  startup_grace_sec: 60",
                "  liveness:",
                "    heartbeat_max_age_sec: 120",
            ]
        ),
        encoding="utf-8",
    )
    (state_dir / "runtime_startup.json").write_text(
        json.dumps(
            {
                "started_at": (
                    datetime.now(UTC) - timedelta(seconds=61)
                ).isoformat()
            }
        ),
        encoding="utf-8",
    )

    assert main(["liveness", "--config", str(config)]) == 1
    assert "liveness failed:" in capsys.readouterr().out


def test_docker_compose_main_healthcheck_uses_liveness_cli() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "polysignal_lab.healthcheck" in compose
    assert "liveness" in compose
    assert "sqlite3.connect" not in compose
    assert "start_period: 180s" in compose