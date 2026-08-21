from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from polysignal_lab.observability.runtime_health import (
    evaluate_liveness,
    read_runtime_heartbeat,
    write_runtime_heartbeat,
)

UTC = timezone.utc
T0 = datetime(2026, 7, 27, 0, 0, 0, tzinfo=UTC)

STARVATION_SEC = 600


def _detail(book_at: datetime | None) -> dict[str, object]:
    stamp = None if book_at is None else book_at.isoformat()
    return {
        "asset": "BTC",
        "subscription_state": "ready" if book_at else "awaiting_first_book",
        "last_book_at_by_side": {"UP": stamp, "DOWN": stamp},
    }


def _liveness(path: Path, now: datetime):
    return evaluate_liveness(
        path,
        max_age_sec=120,
        startup_started_at=T0 - timedelta(hours=1),
        startup_grace_sec=180,
        max_readiness_miss_sec=300,
        max_data_starvation_sec=STARVATION_SEC,
        now=now,
    )


def test_book_arrival_is_recorded_as_last_data_at(tmp_path: Path) -> None:
    path = tmp_path / "hb.json"

    _ = write_runtime_heartbeat(
        path,
        phase="readiness_ok",
        readiness_key="cond-1",
        readiness_ok=False,
        readiness_detail=_detail(T0),
        now=T0,
    )

    assert read_runtime_heartbeat(path).last_data_at == T0.isoformat()


def test_last_data_at_survives_market_rotation(tmp_path: Path) -> None:
    """
    The whole reason the six-day outage stayed invisible: rotation resets the
    per-condition readiness state every cycle, so nothing ever accumulated.
    The data clock must be monotonic across rotations.
    """
    path = tmp_path / "hb.json"
    _ = write_runtime_heartbeat(
        path,
        phase="readiness_ok",
        readiness_key="cond-1",
        readiness_ok=False,
        readiness_detail=_detail(T0),
        now=T0,
    )

    # A new rotation cycle: fresh condition, never received a book.
    for cycle in range(1, 5):
        write_runtime_heartbeat(
            path,
            phase="readiness_miss",
            readiness_key=f"cond-{cycle}",
            readiness_ok=False,
            readiness_detail=_detail(None),
            now=T0 + timedelta(minutes=15 * cycle),
        )

    assert read_runtime_heartbeat(path).last_data_at == T0.isoformat()


def test_starved_runtime_fails_liveness(tmp_path: Path) -> None:
    """
    The real incident: heartbeat fresh, readiness churning, zero market data
    for days, and every health signal reporting fine.
    """
    path = tmp_path / "hb.json"
    _ = write_runtime_heartbeat(
        path,
        phase="readiness_ok",
        readiness_key="cond-1",
        readiness_ok=False,
        readiness_detail=_detail(T0),
        now=T0,
    )
    last_write = T0
    for cycle in range(1, 40):
        last_write = T0 + timedelta(minutes=15 * cycle)
        write_runtime_heartbeat(
            path,
            phase="readiness_miss",
            readiness_key=f"cond-{cycle}",
            readiness_ok=False,
            readiness_detail=_detail(None),
            now=last_write,
        )

    # The heartbeat is one second old — exactly the state that reported
    # healthy throughout the outage.
    result = _liveness(path, last_write + timedelta(seconds=1))

    assert result.ok is False
    assert result.reason == "data_starvation"


def test_flowing_data_keeps_liveness_ok(tmp_path: Path) -> None:
    path = tmp_path / "hb.json"
    now = T0
    for cycle in range(20):
        now = T0 + timedelta(minutes=5 * cycle)
        write_runtime_heartbeat(
            path,
            phase="readiness_ok",
            readiness_key="cond-1",
            readiness_ok=True,
            readiness_detail=_detail(now),
            now=now,
        )

    assert _liveness(path, now + timedelta(seconds=30)).ok is True


def test_starvation_is_not_reported_inside_startup_grace(tmp_path: Path) -> None:
    """A runtime that has not yet received its first book is still booting."""
    path = tmp_path / "hb.json"
    _ = write_runtime_heartbeat(path, phase="starting", now=T0)

    result = evaluate_liveness(
        path,
        max_age_sec=120,
        startup_started_at=T0,
        startup_grace_sec=180,
        max_readiness_miss_sec=300,
        max_data_starvation_sec=STARVATION_SEC,
        now=T0 + timedelta(seconds=60),
    )

    assert result.ok is True


def test_starvation_check_is_off_when_unconfigured(tmp_path: Path) -> None:
    """Callers that pass no threshold keep the previous liveness semantics."""
    path = tmp_path / "hb.json"
    _ = write_runtime_heartbeat(
        path,
        phase="readiness_miss",
        readiness_key="cond-1",
        readiness_ok=False,
        readiness_detail=_detail(None),
        now=T0,
    )

    result = evaluate_liveness(
        path,
        max_age_sec=120,
        startup_started_at=T0 - timedelta(hours=1),
        startup_grace_sec=180,
        now=T0 + timedelta(seconds=30),
    )

    assert result.ok is True


def test_fresh_heartbeat_with_stale_data_is_data_starvation_not_heartbeat_stale(
    tmp_path: Path,
) -> None:
    """Fresh heartbeat, stale market data: the reason must be
    data_starvation (market data health), never heartbeat_stale — a healthy
    process can still be data-starved (the six-day outage shape)."""
    path = tmp_path / "hb.json"
    _ = write_runtime_heartbeat(
        path,
        phase="readiness_miss",
        readiness_key="cond-1",
        readiness_ok=False,
        readiness_detail=_detail(T0 - timedelta(seconds=601)),
        now=T0,
    )

    result = evaluate_liveness(
        path,
        max_age_sec=120,
        startup_started_at=T0 - timedelta(hours=1),
        startup_grace_sec=180,
        max_readiness_miss_sec=300,
        max_data_starvation_sec=STARVATION_SEC,
        now=T0 + timedelta(seconds=1),
    )

    assert result.ok is False
    assert result.reason == "data_starvation"


def test_stale_heartbeat_with_fresh_data_is_heartbeat_stale_not_data_starvation(
    tmp_path: Path,
) -> None:
    """Fresh market data, stale process heartbeat: heartbeat_stale only. A
    heartbeat file age must never be blamed on market-data starvation, and
    vice versa."""
    path = tmp_path / "hb.json"
    _ = write_runtime_heartbeat(
        path,
        phase="readiness_ok",
        readiness_key="cond-1",
        readiness_ok=True,
        readiness_detail=_detail(T0),
        now=T0,
    )

    result = evaluate_liveness(
        path,
        max_age_sec=120,
        startup_started_at=T0 - timedelta(hours=1),
        startup_grace_sec=180,
        max_readiness_miss_sec=300,
        max_data_starvation_sec=STARVATION_SEC,
        now=T0 + timedelta(seconds=300),
    )

    assert result.ok is False
    assert result.reason == "heartbeat_stale"


def test_stale_heartbeat_and_stale_data_reports_data_starvation(
    tmp_path: Path,
) -> None:
    """Both broken: the market-data reason wins (starved runtimes must be
    supervised by their data clock even when the heartbeat writer is also
    wedged — previously the stale branch returned first and the supervisor
    stayed silent)."""
    path = tmp_path / "hb.json"
    _ = write_runtime_heartbeat(
        path,
        phase="readiness_ok",
        readiness_key="cond-1",
        readiness_ok=True,
        readiness_detail=_detail(T0 - timedelta(seconds=601)),
        now=T0,
    )

    result = evaluate_liveness(
        path,
        max_age_sec=120,
        startup_started_at=T0 - timedelta(hours=1),
        startup_grace_sec=180,
        max_readiness_miss_sec=300,
        max_data_starvation_sec=STARVATION_SEC,
        now=T0 + timedelta(seconds=300),
    )

    assert result.ok is False
    assert result.reason == "data_starvation"
