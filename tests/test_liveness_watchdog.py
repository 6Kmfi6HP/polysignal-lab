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


def test_fleet_never_ready_requests_one_supervised_restart(tmp_path: Path) -> None:
    restarts: list[str] = []
    clock = {"now": T0}
    watchdog = LivenessWatchdog(
        _settings(tmp_path),
        lambda _message: None,
        now=lambda: clock["now"],
        restart=restarts.append,
    )

    for observed_at, phase in (
        (T0, "awaiting_first_book"),
        (T0 + timedelta(seconds=301), "stale_orderbook"),
    ):
        clock["now"] = observed_at
        _write_heartbeat(tmp_path, updated_at=observed_at, readiness_miss_at=None)
        payload_path = tmp_path / "runtime_heartbeat.json"
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        payload["readiness_detail_by_key"] = {"cond-1": {"subscription_state": phase}}
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        _ = watchdog.poll_once()

    _ = watchdog.poll_once()
    assert restarts == ["fleet_never_ready"]


def _write_fleet_heartbeat(
    tmp_path: Path,
    *,
    phase: str,
    replay_unconfirmed: bool,
    replay_started_at: datetime | None = None,
) -> None:
    detail: dict[str, object] = {
        "subscription_state": phase,
        "adapter_replay_unconfirmed": replay_unconfirmed,
    }
    if replay_started_at is not None:
        detail["adapter_replay_started_at"] = replay_started_at.isoformat()
    payload = {
        "updated_at": T0.isoformat(),
        "phase": "readiness_miss",
        "fatal": False,
        "fatal_reason": None,
        "last_data_at": T0.isoformat(),
        # No armed readiness-miss: the fleet-restart path is the one under test.
        "readiness_miss_started_at_by_key": {},
        "readiness_detail_by_key": {"cond-1": detail},
    }
    (tmp_path / "runtime_heartbeat.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_fleet_never_ready_defers_restart_while_replay_within_grace(
    tmp_path: Path,
) -> None:
    """A recent adapter replay defers the fleet restart, but only for a bounded
    window: while the marker is inside the grace period the fleet clock stays
    reset, and once it ages past the grace period the supervised restart fires
    after the gate threshold."""
    restarts: list[str] = []
    clock = {"now": T0}
    watchdog = LivenessWatchdog(
        _settings(tmp_path),
        lambda _message: None,
        now=lambda: clock["now"],
        restart=restarts.append,
    )

    replay_started = T0 - timedelta(seconds=60)  # inside the 240s grace
    # Two polls inside the grace window: the fleet clock is reset each time, so
    # even a long bookless spell does not accumulate a supervised restart.
    for observed_at in (T0, T0 + timedelta(seconds=100)):
        clock["now"] = observed_at
        _write_fleet_heartbeat(
            tmp_path,
            phase="stale_orderbook",
            replay_unconfirmed=True,
            replay_started_at=replay_started,
        )
        _ = watchdog.poll_once()

    assert restarts == []

    # Past the grace window (marker fixed at T0-60s, grace expires at T0+180)
    # the fleet clock starts accruing; after the gate threshold it restarts.
    first_expired = T0 + timedelta(seconds=250)
    clock["now"] = first_expired
    _write_fleet_heartbeat(
        tmp_path,
        phase="stale_orderbook",
        replay_unconfirmed=True,
        replay_started_at=replay_started,
    )
    _ = watchdog.poll_once()
    assert restarts == []

    late = T0 + timedelta(seconds=551)
    clock["now"] = late
    _write_fleet_heartbeat(
        tmp_path,
        phase="stale_orderbook",
        replay_unconfirmed=True,
        replay_started_at=replay_started,
    )
    _ = watchdog.poll_once()

    assert restarts == ["fleet_never_ready"]


def test_fleet_never_ready_restarts_when_replay_marker_has_no_anchor(
    tmp_path: Path,
) -> None:
    """A replay marker without a usable timestamp grants no exemption (B2)."""
    restarts: list[str] = []
    clock = {"now": T0}
    watchdog = LivenessWatchdog(
        _settings(tmp_path),
        lambda _message: None,
        now=lambda: clock["now"],
        restart=restarts.append,
    )

    for observed_at in (T0, T0 + timedelta(seconds=301)):
        clock["now"] = observed_at
        _write_fleet_heartbeat(
            tmp_path, phase="stale_orderbook", replay_unconfirmed=True
        )
        _ = watchdog.poll_once()

    assert restarts == ["fleet_never_ready"]


def test_fleet_never_ready_still_requests_restart_without_replay_unconfirmed(
    tmp_path: Path,
) -> None:
    restarts: list[str] = []
    clock = {"now": T0}
    watchdog = LivenessWatchdog(
        _settings(tmp_path),
        lambda _message: None,
        now=lambda: clock["now"],
        restart=restarts.append,
    )

    for observed_at in (T0, T0 + timedelta(seconds=301)):
        clock["now"] = observed_at
        _write_fleet_heartbeat(
            tmp_path, phase="stale_orderbook", replay_unconfirmed=False
        )
        _ = watchdog.poll_once()

    assert restarts == ["fleet_never_ready"]


def test_readiness_miss_requests_one_supervised_restart(tmp_path: Path) -> None:
    restarts: list[str] = []
    _write_heartbeat(
        tmp_path,
        updated_at=T0,
        readiness_miss_at=T0 - timedelta(seconds=301),
    )
    watchdog = LivenessWatchdog(
        _settings(tmp_path),
        lambda _message: None,
        now=lambda: T0,
        restart=restarts.append,
    )

    _ = watchdog.poll_once()
    _ = watchdog.poll_once()

    assert restarts == ["readiness_miss"]


def test_data_starvation_requests_one_supervised_restart(tmp_path: Path) -> None:
    restarts: list[str] = []
    _write_heartbeat(tmp_path, updated_at=T0, readiness_miss_at=None)
    payload_path = tmp_path / "runtime_heartbeat.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["last_data_at"] = (T0 - timedelta(seconds=301)).isoformat()
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    watchdog = LivenessWatchdog(
        _settings(tmp_path),
        lambda _message: None,
        now=lambda: T0,
        restart=restarts.append,
    )

    _ = watchdog.poll_once()
    _ = watchdog.poll_once()

    assert restarts == ["data_starvation"]


def test_disabled_alerting_never_starts_a_thread(tmp_path: Path) -> None:
    watchdog = LivenessWatchdog(_settings(tmp_path, enabled=False), lambda _m: None)

    watchdog.start()
    try:
        assert watchdog._thread is None
    finally:
        watchdog.stop()


def test_fleet_rotating_grace_does_not_escape_supervision(tmp_path: Path) -> None:
    """A fleet cannot defer the supervised restart by keeping ANY one condition
    inside its grace window: the skip requires every bookless condition to be
    within its own bounded window. One expired marker resumes the fleet clock."""
    restarts: list[str] = []
    clock = {"now": T0}
    watchdog = LivenessWatchdog(
        _settings(tmp_path),
        lambda _message: None,
        now=lambda: clock["now"],
        restart=restarts.append,
    )

    def write_fleet() -> None:
        payload = {
            "updated_at": T0.isoformat(),
            "phase": "readiness_miss",
            "fatal": False,
            "fatal_reason": None,
            "last_data_at": T0.isoformat(),
            "readiness_miss_started_at_by_key": {},
            "readiness_detail_by_key": {
                # c1 is still inside its 240s grace; c2's grace expired long ago.
                "c1": {
                    "subscription_state": "stale_orderbook",
                    "adapter_replay_unconfirmed": True,
                    "adapter_replay_started_at": (
                        T0 - timedelta(seconds=60)
                    ).isoformat(),
                },
                "c2": {
                    "subscription_state": "stale_orderbook",
                    "adapter_replay_unconfirmed": True,
                    "adapter_replay_started_at": (
                        T0 - timedelta(seconds=400)
                    ).isoformat(),
                },
            },
        }
        (tmp_path / "runtime_heartbeat.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    # At T0 c1 is in-grace but c2 is not: the all-in-grace skip does NOT fire,
    # so the fleet clock starts accruing from the first poll.
    clock["now"] = T0
    write_fleet()
    _ = watchdog.poll_once()
    assert restarts == []

    # Past the gate threshold the fleet restart fires despite c1 still being
    # (hypothetically) within its own grace: one expired condition is enough.
    clock["now"] = T0 + timedelta(seconds=301)
    write_fleet()
    _ = watchdog.poll_once()
    assert restarts == ["fleet_never_ready"]
