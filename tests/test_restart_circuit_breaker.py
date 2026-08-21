"""Regression tests for the restart circuit breaker (issue69 death-spiral breaker).

Live evidence (2026-08-16/17): Docker ``restart: unless-stopped`` combined with a
persistent data_starvation or readiness_miss created an infinite restart loop.
The in-process ``_restart_requested`` latch only prevents multiple restarts within
a single process lifetime; it has no memory across container restarts, so the
supervisor kept restarting the same wedged runtime forever.

The fix persists supervised-restart timestamps to ``runtime_restart_history.json``
in the state directory. Once ``max_restarts_in_window`` restarts land inside the
rolling ``restart_circuit_breaker_window_sec`` window, the breaker opens: further
restart requests are suppressed and an error is logged so the operator intervenes
instead of the container spinning.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from _pytest.logging import LogCaptureFixture

from polysignal_lab.config import (
    HealthConfig,
    HealthRestartGateConfig,
    Settings,
    StorageConfig,
)
from polysignal_lab.observability.liveness_watchdog import LivenessWatchdog

UTC = timezone.utc
T0 = datetime(2026, 8, 17, 0, 0, 0, tzinfo=UTC)

# Suppress unused-import: pytest provides the tmp_path/caplog fixtures.
_ = pytest


def _settings(
    tmp_path: Path,
    *,
    max_restarts: int = 3,
    window_sec: int = 600,
) -> Settings:
    return Settings(
        storage=StorageConfig(state_dir=str(tmp_path)),
        health=HealthConfig(
            startup_grace_sec=0,
            restart_gate=HealthRestartGateConfig(
                enabled=True,
                critical_down_sec=300,
                max_restarts_in_window=max_restarts,
                restart_circuit_breaker_window_sec=window_sec,
            ),
        ),
    )


def _write_starved_heartbeat(tmp_path: Path, *, now: datetime) -> None:
    """Heartbeat where last_data_at is old enough to trigger data_starvation."""
    payload = {
        "updated_at": now.isoformat(),
        "phase": "data_starvation",
        "fatal": False,
        "fatal_reason": None,
        "last_data_at": (now - timedelta(seconds=301)).isoformat(),
        "readiness_miss_started_at_by_key": {},
        "readiness_detail_by_key": {},
    }
    (tmp_path / "runtime_heartbeat.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _seed_restart_history(tmp_path: Path, timestamps: list[datetime]) -> None:
    (tmp_path / "runtime_restart_history.json").write_text(
        json.dumps([ts.isoformat() for ts in timestamps]),
        encoding="utf-8",
    )


def test_circuit_breaker_opens_after_max_restarts_in_window(
    tmp_path: Path, caplog: LogCaptureFixture
) -> None:
    """After max_restarts_in_window supervised restarts within the rolling
    window, the breaker opens and suppresses further restart requests."""
    restarts: list[str] = []
    _write_starved_heartbeat(tmp_path, now=T0)
    # Seed 3 prior restarts within the 600s window — at the limit.
    _seed_restart_history(
        tmp_path,
        [
            T0 - timedelta(seconds=300),
            T0 - timedelta(seconds=200),
            T0 - timedelta(seconds=100),
        ],
    )
    watchdog = LivenessWatchdog(
        _settings(tmp_path, max_restarts=3, window_sec=600),
        lambda _message: None,
        now=lambda: T0,
        restart=restarts.append,
    )

    with caplog.at_level(
        logging.ERROR, logger="polysignal_lab.observability.liveness_watchdog"
    ):
        _ = watchdog.poll_once()
        _ = watchdog.poll_once()

    # The breaker is open: no restart issued.
    assert restarts == []
    assert any(
        "restart_circuit_breaker_open" in record.getMessage()
        for record in caplog.records
    )


def test_breaker_open_episode_does_not_append_history_per_poll(
    tmp_path: Path, caplog: LogCaptureFixture
) -> None:
    """I1 regression: while the breaker is open and the fault persists, each
    poll_once must NOT append a fresh restart timestamp.

    Live evidence 2026-08-18: runtime_restart_history.json grew one entry per
    30s poll while the breaker was open (recent_count 37 -> 38), so the 1800s
    rolling window was continuously refreshed and the breaker could never
    cool down — supervised restarts were suppressed forever.
    """
    restarts: list[str] = []
    _write_starved_heartbeat(tmp_path, now=T0)
    # 3 prior restarts inside the 600s window — the breaker is already open.
    _seed_restart_history(
        tmp_path,
        [
            T0 - timedelta(seconds=300),
            T0 - timedelta(seconds=200),
            T0 - timedelta(seconds=100),
        ],
    )
    watchdog = LivenessWatchdog(
        _settings(tmp_path, max_restarts=3, window_sec=600),
        lambda _message: None,
        now=lambda: T0,
        restart=restarts.append,
    )

    with caplog.at_level(
        logging.ERROR, logger="polysignal_lab.observability.liveness_watchdog"
    ):
        for _ in range(3):
            _ = watchdog.poll_once()

    # No restart fires and the persisted history does not grow per poll.
    assert restarts == []
    history = json.loads(
        (tmp_path / "runtime_restart_history.json").read_text(encoding="utf-8")
    )
    assert len(history) == 3


def test_circuit_breaker_closed_when_restarts_below_threshold(
    tmp_path: Path,
) -> None:
    """With fewer restarts than the limit, the breaker stays closed and each
    supervised restart fires and is counted on fire (I1 cooldown vortex
    fix: a restart that does not fire must not enter the window — a
    "future" timestamp would re-extend the cooldown forever)."""
    restarts: list[str] = []
    _write_starved_heartbeat(tmp_path, now=T0)
    _seed_restart_history(
        tmp_path,
        [T0 - timedelta(seconds=100)],
    )
    watchdog = LivenessWatchdog(
        _settings(tmp_path, max_restarts=3, window_sec=600),
        lambda _message: None,
        now=lambda: T0,
        restart=restarts.append,
    )

    # Poll 1 fires and counts the restart; poll 2 is a no-op because the
    # in-flight latch is set after the fire (the real restart replaces the
    # process; the latch only guards the same instance).
    _ = watchdog.poll_once()
    _ = watchdog.poll_once()

    assert restarts == ["data_starvation"]
    history = json.loads(
        (tmp_path / "runtime_restart_history.json").read_text(encoding="utf-8")
    )
    assert len(history) == 2


def test_circuit_breaker_resets_after_window_expires(tmp_path: Path) -> None:
    """Old restarts outside the rolling window are pruned; the breaker closes
    and a new restart can fire."""
    restarts: list[str] = []
    _write_starved_heartbeat(tmp_path, now=T0)
    # 3 restarts, but all older than the 600s window.
    _seed_restart_history(
        tmp_path,
        [
            T0 - timedelta(seconds=700),
            T0 - timedelta(seconds=750),
            T0 - timedelta(seconds=800),
        ],
    )
    watchdog = LivenessWatchdog(
        _settings(tmp_path, max_restarts=3, window_sec=600),
        lambda _message: None,
        now=lambda: T0,
        restart=restarts.append,
    )

    _ = watchdog.poll_once()
    _ = watchdog.poll_once()

    assert restarts == ["data_starvation"]


def test_breaker_recovers_after_window_cooldown_same_instance(
    tmp_path: Path,
) -> None:
    """Same watchdog instance: breaker opens, window cools down, restart fires again.

    Regression for the issue69 latch lock: the breaker-open branch must NOT set
    ``_restart_requested``, otherwise the watchdog is permanently disarmed
    within the same process even after the rolling window expires and the
    breaker closes.  The latch is reserved for an in-flight restart in the
    normal (non-breaker) branch; breaker suppression is ``_circuit_breaker_open``'s
    own responsibility and auto-clears when old timestamps are pruned.

    Also covers the I1 cooldown-vortex fix: a suppressed attempt (breaker
    open) never enters the window, so when the window cools the SAME watchdog
    instance fires again instead of re-extending the cooldown forever.
    """
    restarts: list[str] = []
    window_sec = 1800
    clock: dict[str, datetime] = {"now": T0}

    # Seed 3 prior restarts inside the 1800s window — the breaker is open.
    _seed_restart_history(
        tmp_path,
        [T0 - timedelta(seconds=300), T0 - timedelta(seconds=200),
         T0 - timedelta(seconds=100)],
    )
    watchdog = LivenessWatchdog(
        _settings(tmp_path, max_restarts=3, window_sec=window_sec),
        lambda _message: None,
        now=lambda: clock["now"],
        restart=restarts.append,
    )

    # Poll 1 at T0: breaker open — restart suppressed, nothing appended.
    _write_starved_heartbeat(tmp_path, now=T0)
    _ = watchdog.poll_once()
    assert restarts == []

    # Advance past the breaker window.  The open state is self-clearing: old
    # timestamps age out, the breaker closes, and the SAME watchdog instance
    # fires a restart (counted once, on fire).
    clock["now"] = T0 + timedelta(seconds=window_sec + 1)
    _write_starved_heartbeat(tmp_path, now=clock["now"])
    _ = watchdog.poll_once()

    assert restarts == ["data_starvation"]


def test_circuit_breaker_persists_restart_timestamp(
    tmp_path: Path,
) -> None:
    """A supervised restart that fires (breaker closed) appends its timestamp
    to the persisted history so the next process can see it."""
    restarts: list[str] = []
    _write_starved_heartbeat(tmp_path, now=T0)
    watchdog = LivenessWatchdog(
        _settings(tmp_path, max_restarts=3, window_sec=600),
        lambda _message: None,
        now=lambda: T0,
        restart=restarts.append,
    )

    _ = watchdog.poll_once()
    _ = watchdog.poll_once()

    assert restarts == ["data_starvation"]
    history_path = tmp_path / "runtime_restart_history.json"
    assert history_path.exists()
    history = json.loads(history_path.read_text(encoding="utf-8"))
    assert any(T0.isoformat() in ts for ts in history)
