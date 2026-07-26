from __future__ import annotations

import json
from pathlib import Path

import pytest

from polysignal_lab.config import Settings, StorageConfig
from polysignal_lab.nautilus_runtime import node_probes


@pytest.fixture()
def probe_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Callbacks against tmp state dir, fake clock, and a disk-write counter."""
    settings = Settings(storage=StorageConfig(state_dir=str(tmp_path)))
    clock = {"now": 1000.0}
    monkeypatch.setattr(node_probes, "_monotonic", lambda: clock["now"])
    node_probes._reset_heartbeat_write_gates()

    writes = {"count": 0}
    real_write = node_probes.write_runtime_heartbeat

    def counting_write(path, **kwargs):
        writes["count"] += 1
        return real_write(path, **kwargs)

    monkeypatch.setattr(node_probes, "write_runtime_heartbeat", counting_write)
    note_progress = node_probes._runtime_progress_callback(settings)
    note_readiness = node_probes._runtime_readiness_callback(settings)
    heartbeat_path = tmp_path / "runtime_heartbeat.json"
    return note_progress, note_readiness, heartbeat_path, clock, writes


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _readiness_misses(path: Path) -> dict[str, object]:
    payload = _read(path)
    value = payload["readiness_miss_started_at_by_key"]
    assert isinstance(value, dict)
    return value


def test_progress_burst_is_throttled_to_one_disk_write(probe_env) -> None:
    """
    User symptom: strategy thread spent >85% of its time writing the
    heartbeat JSON on every order-book event, backlogging the data feed
    until readiness never cleared. A burst of progress notes within the
    throttle window must hit disk at most once.
    """
    note_progress, _, heartbeat_path, _, writes = probe_env

    for _ in range(50):
        note_progress("market_data_evaluation")

    assert writes["count"] == 1
    assert _read(heartbeat_path)["phase"] == "market_data_evaluation"


def test_progress_write_resumes_after_interval(probe_env) -> None:
    note_progress, _, _, clock, writes = probe_env

    note_progress("evaluation_heartbeat")
    clock["now"] += node_probes._HEARTBEAT_WRITE_INTERVAL_SEC + 0.1
    note_progress("evaluation_heartbeat")

    assert writes["count"] == 2


def test_new_readiness_miss_bypasses_throttle(probe_env) -> None:
    note_progress, note_readiness, heartbeat_path, _, writes = probe_env

    note_progress("market_data_evaluation")  # consumes the write budget
    note_readiness("cond-1", False, {"asset": "BTC"})

    assert writes["count"] == 2
    assert "cond-1" in _readiness_misses(heartbeat_path)


def test_repeated_readiness_miss_is_throttled(probe_env) -> None:
    _, note_readiness, _, _, writes = probe_env

    note_readiness("cond-1", False, {"asset": "BTC"})
    for _ in range(50):
        note_readiness("cond-1", False, {"asset": "BTC"})

    assert writes["count"] == 1


def test_readiness_clear_bypasses_throttle(probe_env) -> None:
    _, note_readiness, heartbeat_path, _, writes = probe_env

    note_readiness("cond-1", False, {"asset": "BTC"})
    note_readiness("cond-1", True, {"asset": "BTC"})

    assert writes["count"] == 2
    assert "cond-1" not in _readiness_misses(heartbeat_path)


def test_startup_phase_bypasses_throttle_and_resets_tracking(probe_env) -> None:
    note_progress, note_readiness, heartbeat_path, _, writes = probe_env

    note_readiness("cond-1", False, {"asset": "BTC"})
    note_progress("start")
    # After a start, the same key missing again is a new miss and must write.
    note_readiness("cond-1", False, {"asset": "BTC"})

    assert writes["count"] == 3
    assert "cond-1" in _readiness_misses(heartbeat_path)


def test_fatal_bypasses_throttle(probe_env, tmp_path: Path) -> None:
    note_progress, _, heartbeat_path, _, writes = probe_env

    note_progress("market_data_evaluation")
    node_probes._write_runtime_heartbeat_best_effort(
        heartbeat_path,
        phase="fatal",
        fatal=True,
        fatal_reason="boom",
    )

    assert writes["count"] == 2
    assert _read(heartbeat_path)["fatal"] is True
