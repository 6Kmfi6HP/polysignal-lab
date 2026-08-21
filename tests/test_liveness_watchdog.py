from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _pytest.logging import LogCaptureFixture

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
    assert restarts and restarts[0].startswith("fleet_never_ready")


def _write_fleet_heartbeat(
    tmp_path: Path,
    *,
    phase: str,
    replay_unconfirmed: bool,
    replay_started_at: datetime | None = None,
    updated_at: datetime = T0,
) -> None:
    detail: dict[str, object] = {
        "subscription_state": phase,
        "adapter_replay_unconfirmed": replay_unconfirmed,
    }
    if replay_started_at is not None:
        detail["adapter_replay_started_at"] = replay_started_at.isoformat()
    payload = {
        "updated_at": updated_at.isoformat(),
        "phase": "readiness_miss",
        "fatal": False,
        "fatal_reason": None,
        "last_data_at": updated_at.isoformat(),
        # No armed readiness-miss: the fleet-restart path is the one under test.
        # Data stays fresh here; starvation is exercised in test_data_starvation_liveness.py.
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
            updated_at=observed_at,
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
        updated_at=first_expired,
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
        updated_at=late,
    )
    _ = watchdog.poll_once()

    assert restarts and restarts[0].startswith("fleet_never_ready")


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
            tmp_path,
            phase="stale_orderbook",
            replay_unconfirmed=True,
            updated_at=observed_at,
        )
        _ = watchdog.poll_once()

    assert restarts and restarts[0].startswith("fleet_never_ready")


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
            tmp_path,
            phase="stale_orderbook",
            replay_unconfirmed=False,
            updated_at=observed_at,
        )
        _ = watchdog.poll_once()

    assert restarts and restarts[0].startswith("fleet_never_ready")


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
            "updated_at": clock["now"].isoformat(),
            "phase": "readiness_miss",
            "fatal": False,
            "fatal_reason": None,
            "last_data_at": clock["now"].isoformat(),
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
    assert restarts and restarts[0].startswith("fleet_never_ready")


# ── Fleet never-ready state contract (issue69 watchdog) ─────────────────────


def _write_details_heartbeat(
    tmp_path: Path,
    details: Mapping[str, Mapping[str, object]],
    *,
    updated_at: datetime,
) -> None:
    payload = {
        "updated_at": updated_at.isoformat(),
        "phase": "readiness_miss",
        "fatal": False,
        "fatal_reason": None,
        "last_data_at": updated_at.isoformat(),
        "readiness_miss_started_at_by_key": {},
        "readiness_detail_by_key": details,
    }
    (tmp_path / "runtime_heartbeat.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _fleet_watchdog(
    tmp_path: Path, *, restarts: list[str], clock: dict[str, datetime]
) -> LivenessWatchdog:
    return LivenessWatchdog(
        _settings(tmp_path),
        lambda _message: None,
        now=lambda: clock["now"],
        restart=restarts.append,
    )


def test_fleet_never_ready_counts_unsubscribed_metadata_and_intent_states(
    tmp_path: Path,
) -> None:
    """The fleet clock must NOT depend on every stuck condition sharing one
    `subscription_state` string: unsubscribed, metadata pending and unconfirmed
    wire intents all count as no-progress, and a mixed stuck fleet still
    restarts."""
    restarts: list[str] = []
    clock: dict[str, datetime] = {"now": T0}
    watchdog = _fleet_watchdog(tmp_path, restarts=restarts, clock=clock)
    details = {
        "c1": {"subscription_state": "unsubscribed"},
        "c2": {"subscription_state": "pending_metadata"},
        "c3": {"subscription_state": "subscribe_requested"},
        "c4": {"subscription_state": "awaiting_first_book"},
    }
    for delta in (timedelta(0), timedelta(seconds=301)):
        clock["now"] = T0 + delta
        _write_details_heartbeat(tmp_path, details, updated_at=clock["now"])
        _ = watchdog.poll_once()

    assert restarts and restarts[0].startswith("fleet_never_ready")
    reason = json.loads(restarts[0].split(" ", 1)[1])
    buckets = reason["buckets"]
    assert buckets["unsubscribed"] == 1
    assert buckets["metadata_pending"] == 1  # pending_metadata alias
    assert buckets["intent_unconfirmed"] == 1  # subscribe_requested alias
    assert buckets["awaiting_first_book"] == 1
    assert reason["no_progress"] == 4
    assert reason["fleet"] == 4


def test_fleet_never_ready_mixed_no_progress_does_not_reset_the_clock(
    tmp_path: Path,
) -> None:
    """Regression: the old all-in-one-set check reset the timer whenever the
    fleet's states were NOT all in {awaiting_first_book, stale_orderbook} —
    a mixed stuck fleet (e.g. 1 unsubscribed + 2 stale) never restarted."""
    restarts: list[str] = []
    clock: dict[str, datetime] = {"now": T0}
    watchdog = _fleet_watchdog(tmp_path, restarts=restarts, clock=clock)
    details_a = {
        "c1": {"subscription_state": "awaiting_first_book"},
        "c2": {"subscription_state": "stale_orderbook"},
    }
    details_b = {
        **details_a,
        "c3": {"subscription_state": "unsubscribed"},  # changes the mix only
    }
    for observed_at, details in (
        (T0, details_a),
        (T0 + timedelta(seconds=100), details_b),
        (T0 + timedelta(seconds=301), details_b),
    ):
        clock["now"] = observed_at
        _write_details_heartbeat(tmp_path, details, updated_at=observed_at)
        _ = watchdog.poll_once()

    assert restarts and restarts[0].startswith("fleet_never_ready")


def test_ready_condition_resets_the_fleet_clock(tmp_path: Path) -> None:
    """A condition that actually reached READY is genuine progress: it resets
    the no-progress clock. Only a no-progress bucket mix must not reset it."""
    restarts: list[str] = []
    clock: dict[str, datetime] = {"now": T0}
    watchdog = _fleet_watchdog(tmp_path, restarts=restarts, clock=clock)
    stuck = {"c1": {"subscription_state": "awaiting_first_book"}}

    clock["now"] = T0
    _write_details_heartbeat(tmp_path, stuck, updated_at=T0)
    _ = watchdog.poll_once()  # clock armed at T0

    # c1 becomes ready: progress evidence -> timer reset.
    clock["now"] = T0 + timedelta(seconds=100)
    _write_details_heartbeat(
        tmp_path, {"c1": {"subscription_state": "ready"}}, updated_at=clock["now"]
    )
    _ = watchdog.poll_once()
    assert restarts == []

    # Fleet stuck again from T0+100; less than 300s elapsed since the reset.
    clock["now"] = T0 + timedelta(seconds=301)
    _write_details_heartbeat(tmp_path, stuck, updated_at=clock["now"])
    _ = watchdog.poll_once()
    assert restarts == []

    # Same watchdog instance, same timer: 601s after the reset it fires.
    clock["now"] = T0 + timedelta(seconds=602)
    _write_details_heartbeat(tmp_path, stuck, updated_at=clock["now"])
    _ = watchdog.poll_once()
    assert restarts and restarts[0].startswith("fleet_never_ready")


def test_old_generation_book_evidence_does_not_defer_fleet_restart(
    tmp_path: Path,
) -> None:
    """`first_bilateral_book_ever_at` is old-generation evidence: it must not
    block a restart when the CURRENT generation shows no progress."""
    restarts: list[str] = []
    clock: dict[str, datetime] = {"now": T0}
    watchdog = _fleet_watchdog(tmp_path, restarts=restarts, clock=clock)
    details = {
        "c1": {
            "subscription_state": "stale_orderbook",
            "first_bilateral_book_ever_at": (T0 - timedelta(days=1)).isoformat(),
        }
    }
    for delta in (timedelta(0), timedelta(seconds=301)):
        clock["now"] = T0 + delta
        _write_details_heartbeat(tmp_path, details, updated_at=clock["now"])
        _ = watchdog.poll_once()

    assert restarts and restarts[0].startswith("fleet_never_ready")


def test_fresh_generation_anchor_alone_does_not_defer_fleet_restart(
    tmp_path: Path,
) -> None:
    """A retry-renewable `generation_started_at` is NOT bounded grace evidence
    by itself: only the strategy-side replay boundary (anchored once per
    generation streak) may defer the fleet clock (issue69 B2)."""
    restarts: list[str] = []
    clock: dict[str, datetime] = {"now": T0}
    watchdog = _fleet_watchdog(tmp_path, restarts=restarts, clock=clock)
    detail = {
        "c1": {
            "subscription_state": "awaiting_first_book",
            "generation_started_at": (T0 - timedelta(seconds=30)).isoformat(),
            "adapter_replay_unconfirmed": False,
        }
    }
    for delta in (timedelta(0), timedelta(seconds=301)):
        clock["now"] = T0 + delta
        _write_details_heartbeat(tmp_path, detail, updated_at=clock["now"])
        _ = watchdog.poll_once()

    assert restarts and restarts[0].startswith("fleet_never_ready")


def test_fleet_restart_reason_carries_structured_evidence(tmp_path: Path) -> None:
    """The restart reason is not just `fleet_never_ready`: it carries state
    buckets, oldest wait age, generation epoch, transport states and in-flight
    counts — without any credential material."""
    restarts: list[str] = []
    clock: dict[str, datetime] = {"now": T0}
    watchdog = _fleet_watchdog(tmp_path, restarts=restarts, clock=clock)
    details = {
        "c1": {
            "subscription_state": "awaiting_first_book",
            "subscribe_requested": True,
            "total_stall_started_at": (T0 - timedelta(seconds=5000)).isoformat(),
            "generation_started_at": (T0 - timedelta(seconds=30)).isoformat(),
        },
        "c2": {
            "subscription_state": "transport_disconnected",
            "transport_state": "transport_disconnected",
            "awaiting_book_sides": ["UP", "DOWN"],
        },
        "c3": {
            "subscription_state": "unsubscribed",
            "connection_epoch": 7,
        },
    }
    for delta in (timedelta(0), timedelta(seconds=301)):
        clock["now"] = T0 + delta
        _write_details_heartbeat(tmp_path, details, updated_at=clock["now"])
        _ = watchdog.poll_once()

    assert restarts and restarts[0].startswith("fleet_never_ready ")
    reason = json.loads(restarts[0].split(" ", 1)[1])
    buckets = reason["buckets"]
    assert buckets["awaiting_first_book"] == 1
    assert buckets["transport_disconnected"] == 1
    assert buckets["unsubscribed"] == 1
    assert reason["no_progress"] == 3
    assert reason["fleet"] == 3
    assert reason["oldest_wait_age_sec"] >= 4999
    assert reason["generation_started_iso"] is not None
    assert reason["transport_states"] == ["transport_disconnected"]
    assert reason["connection_epoch"] == [7]
    assert reason["in_flight"] == 2  # c1 subscribe_requested + c2 awaiting sides


# ── Mixed fleet: one READY must not clear still-stalled evidence ────────────


def test_mixed_fleet_one_ready_condition_keeps_stalled_evidence(
    tmp_path: Path,
) -> None:
    """Regression (issue69): a single READY condition among stuck conditions
    must NOT erase the fleet clock accrued on the stalled ones. READY proves
    progress for that condition only — it is not evidence the rest of the
    fleet recovered. The clock keeps accruing and fires the supervised
    restart with the stalled evidence intact."""
    restarts: list[str] = []
    clock: dict[str, datetime] = {"now": T0}
    watchdog = _fleet_watchdog(tmp_path, restarts=restarts, clock=clock)

    # T0: the whole fleet is stuck — the fleet clock arms.
    clock["now"] = T0
    _write_details_heartbeat(
        tmp_path,
        {
            "c0": {"subscription_state": "awaiting_first_book"},
            "c1": {"subscription_state": "awaiting_first_book"},
        },
        updated_at=T0,
    )
    _ = watchdog.poll_once()

    # T0+100: c0 becomes READY while c1 stays stale. READY must NOT reset
    # the clock: c1's stalled evidence is still accruing.
    clock["now"] = T0 + timedelta(seconds=100)
    _write_details_heartbeat(
        tmp_path,
        {
            "c0": {"subscription_state": "ready"},
            "c1": {"subscription_state": "stale_orderbook"},
        },
        updated_at=clock["now"],
    )
    _ = watchdog.poll_once()
    assert restarts == []

    # T0+301: one stalled condition has now been evidence-armed for 301s;
    # the supervised restart fires even though c0 is READY and data flows.
    clock["now"] = T0 + timedelta(seconds=301)
    _write_details_heartbeat(
        tmp_path,
        {
            "c0": {"subscription_state": "ready"},
            "c1": {"subscription_state": "stale_orderbook"},
        },
        updated_at=clock["now"],
    )
    _ = watchdog.poll_once()
    assert restarts and restarts[0].startswith("fleet_never_ready")
    reason = json.loads(restarts[0].split(" ", 1)[1])
    assert reason["no_progress"] == 1  # stalled count, not ready count
    assert reason["fleet"] == 2
    assert reason["buckets"]["stale_orderbook"] == 1
    assert reason["buckets"]["ready"] == 1  # READY visible in evidence


def test_mixed_fleet_stuck_becomes_ready_then_stalls_again(
    tmp_path: Path,
) -> None:
    """A previously stalled condition turning READY resets nothing while other
    conditions remain stalled; when the last stalled condition also recovers,
    the fleet clock resets (full fleet readiness is the only reset)."""
    restarts: list[str] = []
    clock: dict[str, datetime] = {"now": T0}
    watchdog = _fleet_watchdog(tmp_path, restarts=restarts, clock=clock)

    clock["now"] = T0
    _write_details_heartbeat(
        tmp_path,
        {"c1": {"subscription_state": "pending_metadata"}},
        updated_at=T0,
    )
    _ = watchdog.poll_once()  # clock armed at T0

    # The only condition has recovered: full readiness resets the fleet clock.
    clock["now"] = T0 + timedelta(seconds=100)
    _write_details_heartbeat(
        tmp_path, {"c1": {"subscription_state": "ready"}}, updated_at=clock["now"]
    )
    _ = watchdog.poll_once()
    assert restarts == []

    # Full fleet stuck again: the clock re-arms at T0+100, not at T0.
    clock["now"] = T0 + timedelta(seconds=201)
    _write_details_heartbeat(
        tmp_path,
        {"c1": {"subscription_state": "awaiting_first_book"}},
        updated_at=clock["now"],
    )
    _ = watchdog.poll_once()
    assert restarts == []

    clock["now"] = T0 + timedelta(seconds=502)
    _write_details_heartbeat(
        tmp_path,
        {"c1": {"subscription_state": "awaiting_first_book"}},
        updated_at=clock["now"],
    )
    _ = watchdog.poll_once()
    assert restarts and restarts[0].startswith("fleet_never_ready")


# ── Old-generation heartbeat evidence ───────────────────────────────────────


def _write_foreign_pid_heartbeat(tmp_path: Path, *, now: datetime) -> None:
    payload = {
        "updated_at": now.isoformat(),
        "phase": "data_starvation",
        "fatal": False,
        "fatal_reason": None,
        "last_data_at": (now - timedelta(seconds=3600)).isoformat(),
        "readiness_miss_started_at_by_key": {"cond-1": (now).isoformat()},
        "readiness_detail_by_key": {
            "cond-1": {"subscription_state": "stale_orderbook"}
        },
        # Written by a PREVIOUS boot's process — never evidence for this one.
        "pid": 424242,
        "boot_id": "boot-dead",
    }
    (tmp_path / "runtime_heartbeat.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_old_generation_heartbeat_never_triggers_watchdog_restart(
    tmp_path: Path,
) -> None:
    """issue69 stale-heartbeat loop: a previous boot's heartbeat file (old
    pid) must never age-kill or data-starve the current process. The in-process
    watchdog ignores foreign files entirely — no restart, no fleet clock."""
    restarts: list[str] = []
    clock: dict[str, datetime] = {"now": T0}
    watchdog = LivenessWatchdog(
        _settings(tmp_path),
        lambda _message: None,
        now=lambda: clock["now"],
        restart=restarts.append,
    )

    for delta in (timedelta(0), timedelta(seconds=301), timedelta(seconds=3600)):
        clock["now"] = T0 + delta
        _write_heartbeat(tmp_path, updated_at=clock["now"], readiness_miss_at=None)
        _write_foreign_pid_heartbeat(tmp_path, now=clock["now"])
        _ = watchdog.poll_once()

    assert restarts == []


def test_own_pid_starved_heartbeat_still_restarts(tmp_path: Path) -> None:
    """The pid guard only filters FOREIGN files; the current process's own
    starved heartbeat must still trigger the supervised restart."""
    restarts: list[str] = []
    _write_heartbeat(tmp_path, updated_at=T0, readiness_miss_at=None)
    payload_path = tmp_path / "runtime_heartbeat.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["last_data_at"] = (T0 - timedelta(seconds=301)).isoformat()
    payload["pid"] = 123456  # matches the watchdog's process in this test
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    watchdog = LivenessWatchdog(
        _settings(tmp_path),
        lambda _message: None,
        now=lambda: T0,
        restart=restarts.append,
        current_pid=123456,
    )

    _ = watchdog.poll_once()
    _ = watchdog.poll_once()

    assert restarts == ["data_starvation"]


def test_foreign_pid_heartbeat_ignored_for_liveness_alert(
    tmp_path: Path,
) -> None:
    """The alert path also ignores a foreign heartbeat: no unhealthy alert is
    sent for another process's file and no recovery page follows."""
    sent: list[str] = []
    clock: dict[str, datetime] = {"now": T0}
    watchdog = LivenessWatchdog(
        _settings(tmp_path, min_unhealthy_sec=0, min_consecutive_failures=1),
        sent.append,
        now=lambda: clock["now"],
    )

    _write_foreign_pid_heartbeat(tmp_path, now=T0)
    for _ in range(3):
        _ = watchdog.poll_once()

    assert sent == []


# ── Stop-intent callback safety and duplicate requests ──────────────────────


def test_duplicate_restart_requests_fire_one_stop_intent(tmp_path: Path) -> None:
    """The latch + circuit bookkeeping must collapse any number of polls in
    the same episode into exactly ONE restart callback and ONE history entry:
    a duplicate stop intent would otherwise reboot the process twice for one
    stuck episode."""
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

    for _ in range(5):
        _ = watchdog.poll_once()

    assert restarts == ["readiness_miss"]
    history_path = tmp_path / "runtime_restart_history.json"
    history = json.loads(history_path.read_text(encoding="utf-8"))
    assert len(history) == 1


def test_restart_callback_exception_is_logged_and_not_retried(
    tmp_path: Path,
    caplog: LogCaptureFixture,
) -> None:
    """A raising stop-intent callback must not tear down the poll loop nor
    loop: the latch is already set before the callback runs, so the next
    polls keep the episode armed-down (no duplicate stop requests)."""
    called: list[str] = []

    def exploding(reason: str) -> None:
        called.append(reason)
        raise RuntimeError("stop transport exploded")

    _write_heartbeat(
        tmp_path,
        updated_at=T0,
        readiness_miss_at=T0 - timedelta(seconds=301),
    )
    watchdog = LivenessWatchdog(
        _settings(tmp_path),
        lambda _message: None,
        now=lambda: T0,
        restart=exploding,
    )

    with caplog.at_level(
        logging.ERROR, logger="polysignal_lab.observability.liveness_watchdog"
    ):
        for _ in range(3):
            _ = watchdog.poll_once()

    assert called == ["readiness_miss"]  # exactly one callback attempt
    assert any(
        "restart_callback_failed" in record.getMessage() for record in caplog.records
    )
    assert watchdog.state is not None  # poll loop survived the callback raise


def test_cross_thread_stop_intent_runs_on_watchdog_thread(tmp_path: Path) -> None:
    """The supervised restart is issued from the watchdog's own thread, not
    from the Nautilus event loop: the callback only ever receives a thread-
    safe stop intent (request_process_stop in node.py) and must never touch
    the unsendable PyO3 node from another thread."""
    import threading as _threading

    fired = _threading.Event()
    thread_names: list[str] = []
    main_thread = _threading.current_thread().name

    def on_restart(reason: str) -> None:
        thread_names.append(_threading.current_thread().name)
        fired.set()

    _write_heartbeat(
        tmp_path,
        updated_at=T0,
        readiness_miss_at=T0 - timedelta(seconds=301),
    )
    from polysignal_lab.config import HealthRestartGateConfig

    watchdog = LivenessWatchdog(
        Settings(
            storage=StorageConfig(state_dir=str(tmp_path)),
            health=HealthConfig(
                startup_grace_sec=0,
                alert=HealthAlertConfig(
                    enabled=True,
                    poll_interval_sec=1,
                    min_unhealthy_sec=0,
                    min_consecutive_failures=1,
                ),
                # 1s critical window: the aged miss/starvation evidence fires
                # the restart intent almost immediately, in real time.
                restart_gate=HealthRestartGateConfig(enabled=True, critical_down_sec=1),
            ),
        ),
        lambda _message: None,
        now=lambda: datetime.now(UTC),
        restart=on_restart,
    )
    watchdog.start()
    try:
        assert fired.wait(timeout=5.0), "restart callback never fired"
    finally:
        watchdog.stop()

    assert thread_names and thread_names[0] == "polysignal-liveness-watchdog"
    assert thread_names[0] != main_thread
    assert watchdog._thread is None  # stop() joined the thread cleanly
