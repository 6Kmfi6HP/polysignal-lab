from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from polysignal_lab.config import (
    HealthAlertConfig,
    HealthConfig,
    Settings,
    StorageConfig,
)
from polysignal_lab.observability.liveness_watchdog import LivenessWatchdog

UTC = timezone.utc
T0 = datetime(2026, 7, 27, 0, 0, 0, tzinfo=UTC)


def _settings(tmp_path: Path, **alert: object) -> Settings:
    return Settings(
        storage=StorageConfig(state_dir=str(tmp_path)),
        health=HealthConfig(
            startup_grace_sec=0,
            alert=HealthAlertConfig(**alert),  # pyright: ignore[reportArgumentType]
        ),
    )


def _write_heartbeat(
    tmp_path: Path, *, updated_at: datetime, readiness_miss_at: datetime | None
) -> None:
    misses = (
        {} if readiness_miss_at is None else {"cond-1": readiness_miss_at.isoformat()}
    )
    payload = {
        "updated_at": updated_at.isoformat(),
        "phase": "readiness_miss" if misses else "readiness_ok",
        "fatal": False,
        "fatal_reason": None,
        # Book data keeps flowing in these cases; the starvation check is
        # exercised separately in test_data_starvation_liveness.py.
        "last_data_at": updated_at.isoformat(),
        "readiness_miss_started_at_by_key": misses,
        "readiness_detail_by_key": {"cond-1": {"asset": "SOL"}} if misses else {},
    }
    (tmp_path / "runtime_heartbeat.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_sustained_readiness_miss_sends_one_alert(tmp_path: Path) -> None:
    """
    The incident in full: readiness stuck, heartbeat still fresh, Docker
    reporting unhealthy — and no notification. One alert must now go out.
    """
    sent: list[str] = []
    clock = {"now": T0}
    watchdog = LivenessWatchdog(
        _settings(tmp_path, min_unhealthy_sec=300, min_consecutive_failures=3),
        sent.append,
        now=lambda: clock["now"],
    )

    for minute in range(20):
        clock["now"] = T0 + timedelta(minutes=minute)
        _write_heartbeat(tmp_path, updated_at=clock["now"], readiness_miss_at=T0)
        _ = watchdog.poll_once()

    assert len(sent) == 1
    assert "cond-1" in sent[0]
    # liveness tolerates the miss for 5 minutes, then the alert gate adds its
    # own window — the page must not arrive before both have elapsed.
    assert watchdog.state.notified is True


def test_healthy_runtime_is_silent(tmp_path: Path) -> None:
    sent: list[str] = []
    clock = {"now": T0}
    watchdog = LivenessWatchdog(
        _settings(tmp_path), sent.append, now=lambda: clock["now"]
    )

    for minute in range(20):
        clock["now"] = T0 + timedelta(minutes=minute)
        _write_heartbeat(tmp_path, updated_at=clock["now"], readiness_miss_at=None)
        _ = watchdog.poll_once()

    assert sent == []


def test_a_failed_alert_is_retried_not_swallowed(tmp_path: Path) -> None:
    """
    Telegram being down must not burn the only page for the episode. Marking
    the alert as delivered before the send succeeds would leave the operator
    with nothing but a later 'recovered' notice for an alert they never got.
    """
    attempts: list[str] = []
    fail_until = {"count": 2}

    def flaky(message: str) -> None:
        attempts.append(message)
        if fail_until["count"] > 0:
            fail_until["count"] -= 1
            raise RuntimeError("telegram down")

    clock = {"now": T0}
    watchdog = LivenessWatchdog(
        _settings(tmp_path, min_unhealthy_sec=0, min_consecutive_failures=1),
        flaky,
        now=lambda: clock["now"],
    )
    # Miss started long enough ago to exhaust liveness.max_readiness_miss_sec.
    miss_started = T0 - timedelta(minutes=30)

    for minute in range(3):
        clock["now"] = T0 + timedelta(minutes=minute)
        _write_heartbeat(
            tmp_path, updated_at=clock["now"], readiness_miss_at=miss_started
        )
        _ = watchdog.poll_once()

    assert len(attempts) == 3  # two failures, then the delivered alert
    assert all("unhealthy" in a for a in attempts)
    assert watchdog.state.notified is True

    # Once delivered, it must not repeat while the failure persists.
    clock["now"] = T0 + timedelta(minutes=4)
    _write_heartbeat(tmp_path, updated_at=clock["now"], readiness_miss_at=miss_started)
    _ = watchdog.poll_once()
    assert len(attempts) == 3


def test_a_failed_recovery_notice_is_retried(tmp_path: Path) -> None:
    """A dropped recovery notice would leave the operator believing it's down."""
    attempts: list[str] = []
    drop_recovery = {"once": True}

    def flaky(message: str) -> None:
        attempts.append(message)
        if "recovered" in message.lower() and drop_recovery["once"]:
            drop_recovery["once"] = False
            raise RuntimeError("telegram down")

    clock = {"now": T0}
    watchdog = LivenessWatchdog(
        _settings(tmp_path, min_unhealthy_sec=0, min_consecutive_failures=1),
        flaky,
        now=lambda: clock["now"],
    )
    _write_heartbeat(
        tmp_path, updated_at=T0, readiness_miss_at=T0 - timedelta(minutes=30)
    )
    _ = watchdog.poll_once()  # alert delivered
    assert watchdog.state.notified is True

    for minute in (1, 2):
        clock["now"] = T0 + timedelta(minutes=minute)
        _write_heartbeat(tmp_path, updated_at=clock["now"], readiness_miss_at=None)
        _ = watchdog.poll_once()

    assert [a for a in attempts if "recovered" in a.lower()] != []
    assert len([a for a in attempts if "recovered" in a.lower()]) == 2
    assert watchdog.state.notified is False


def test_missing_heartbeat_alerts_after_the_grace_window(tmp_path: Path) -> None:
    """A runtime that never wrote a heartbeat is as broken as one that stalled."""
    sent: list[str] = []
    clock = {"now": T0}
    watchdog = LivenessWatchdog(
        _settings(tmp_path, min_unhealthy_sec=60, min_consecutive_failures=2),
        sent.append,
        now=lambda: clock["now"],
    )

    for minute in range(5):
        clock["now"] = T0 + timedelta(minutes=minute)
        _ = watchdog.poll_once()

    assert len(sent) == 1
    assert "heartbeat_missing" in sent[0]


def test_disabled_alerting_never_starts_a_thread(tmp_path: Path) -> None:
    watchdog = LivenessWatchdog(_settings(tmp_path, enabled=False), lambda _m: None)

    watchdog.start()
    try:
        assert watchdog._thread is None
    finally:
        watchdog.stop()
