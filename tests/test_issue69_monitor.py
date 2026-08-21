from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

def _load_monitor() -> ModuleType:
    path = Path(__file__).parents[1] / "scripts" / "monitor_issue69_reconnect.py"
    spec = importlib.util.spec_from_file_location("issue69_monitor", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("monitor_issue69_reconnect.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MONITOR = _load_monitor()


def _heartbeat(details: dict[str, dict[str, object]]) -> dict[str, object]:
    return {
        "updated_at": "2026-08-16T06:00:00+00:00",
        "phase": "readiness_ok",
        "fatal": False,
        "fatal_reason": None,
        "last_data_at": "2026-08-16T06:00:00+00:00",
        "readiness_miss_started_at_by_key": {},
        "readiness_detail_by_key": details,
    }


def _log(reconnects: int) -> str:
    lines: list[str] = []
    start = datetime(2026, 8, 16, 5, 0, 0)
    for index in range(reconnects):
        at = start + timedelta(minutes=5 * index)
        lines.append(
            f"{at.isoformat()}Z [INFO] ... {index} ... "
            "Polymarket WebSocket reconnected "
            "Resubscribing to 8 market assets after reconnect"
        )
    return "\n".join(lines)


def _cycle_heartbeats(tmp_path: Path, count: int, book_at: str) -> list[Path]:
    paths: list[Path] = []
    start = datetime(2026, 8, 16, 5, 0, 4, tzinfo=timezone.utc)
    for index in range(count):
        # Realistic recovered heartbeat: conditions that reached READY have
        # their detail popped from readiness_detail_by_key; the global
        # last_data_at clock holds the recovery evidence. Each snapshot's
        # last_data must fall inside ITS cycle window (reconnect, next].
        payload = _heartbeat({})
        window_book = (
            start + timedelta(minutes=5 * index + 1)
        ).isoformat()
        payload["last_data_at"] = window_book
        path = tmp_path / f"heartbeat-{index}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths.append(path)
    return paths


def test_five_cycles_pass_with_bilateral_books(tmp_path: Path) -> None:
    book_at = "2026-08-16T05:21:00Z"
    heartbeats = _cycle_heartbeats(tmp_path, 5, book_at)
    summary = MONITOR.assess_cycles(
        heartbeats[0],
        _log(5),
        cycles_required=5,
        heartbeat_files=heartbeats,
    )
    assert summary["status"] == "passed"
    assert summary["cycles_observed"] == 5


def test_five_cycles_fail_when_replay_never_confirm(tmp_path: Path) -> None:
    details: dict[str, dict[str, object]] = {
        "cond-1": {
            "subscription_state": "awaiting_first_book",
            "adapter_replay_unconfirmed": True,
            "last_book_received_at_by_side": {},
            "last_book_at_by_side": {},
        }
    }
    heartbeat = tmp_path / "runtime_heartbeat.json"
    heartbeat.write_text(json.dumps(_heartbeat(details)), encoding="utf-8")
    summary = MONITOR.assess_cycles(
        heartbeat, _log(5), cycles_required=5, heartbeat_files=[heartbeat] * 5
    )
    assert summary["status"] == "failed"


def test_five_cycles_fail_when_one_side_missing(tmp_path: Path) -> None:
    details: dict[str, dict[str, object]] = {
        "cond-1": {
            "subscription_state": "stale_orderbook",
            "last_book_received_at_by_side": {
                "UP": "2026-08-16T05:21:00Z",
                "DOWN": None,
            },
            "last_book_at_by_side": {
                "UP": "2026-08-16T05:21:00Z",
                "DOWN": None,
            },
        }
    }
    heartbeat = tmp_path / "runtime_heartbeat.json"
    heartbeat.write_text(json.dumps(_heartbeat(details)), encoding="utf-8")
    summary = MONITOR.assess_cycles(
        heartbeat, _log(5), cycles_required=5, heartbeat_files=[heartbeat] * 5
    )
    assert summary["status"] == "failed"


# ------------------------------------------------------------------- B4 formats


def _jsonl_line(at: str, message: str) -> str:
    return json.dumps(
        {
            "timestamp": at,
            "level": "INFO",
            "component": "PolymarketDataClient",
            "message": message,
        }
    )


def test_reconnect_times_parses_jsonl_sink() -> None:
    """B4: production JSONL lines (leading ``{``) must yield reconnect times."""
    lines = "\n".join(
        [
            _jsonl_line("2026-08-16T05:00:03+0700", "transport error: Invalid close code: 1013"),
            _jsonl_line("2026-08-16T05:00:04+0700", "Polymarket WS reconnected"),
            _jsonl_line("2026-08-16T05:00:05+0700", "Resubscribing to 16 market assets after reconnect"),
        ]
    )
    times = MONITOR._reconnect_times(lines)
    # The transport-error line is not a reconnect marker; the reconnect and
    # resubscribe lines coalesce into a single boundary.
    assert len(times) == 1
    # +0700 offset normalizes to UTC: 05:00:04+07:00 == 04:00:04-07:00? No: ==
    # 05:00:04 - 07:00 == 2026-08-15T22:00:04Z.
    assert times[0] == datetime(2026, 8, 15, 22, 0, 4, tzinfo=timezone.utc)


def test_reconnect_times_parses_human_asctime_sink() -> None:
    """B4: `%(asctime)s` "YYYY-MM-DD HH:MM:SS,mmm" lines parse as UTC."""
    log = (
        "2026-08-16 05:00:03,500 INFO  nautilus_polymarket: transport error: Invalid close code: 1013\n"
        "2026-08-16 05:00:04,500 INFO  nautilus_polymarket: Polymarket WebSocket reconnected\n"
    )
    times = MONITOR._reconnect_times(log)
    assert len(times) == 1
    assert times[0] == datetime(2026, 8, 16, 5, 0, 4, tzinfo=timezone.utc)


def test_reconnect_times_matches_issue_reconnect_string() -> None:
    log = (
        "2026-08-16T05:00:00Z [INFO] Polymarket WS reconnected\n"
        "2026-08-16T05:05:00Z [INFO] Polymarket WS reconnected\n"
    )
    times = MONITOR._reconnect_times(log)
    assert len(times) == 2


def test_books_after_reconnect_compares_offsets_correctly() -> None:
    """B4: a +0700 JSONL reconnect must compare against a UTC heartbeat book."""
    reconnect_at = datetime(2026, 8, 16, 5, 0, 4, tzinfo=timezone.utc)
    cycle = {
        "reconnect_at": reconnect_at.isoformat(),
        "heartbeat": {
            "conditions": {
                "cond-1": {
                    "last_book_at_by_side": {
                        "UP": "2026-08-16T05:21:00+00:00",
                        "DOWN": "2026-08-16T05:21:00+00:00",
                    }
                }
            }
        },
    }
    assert MONITOR._books_after_reconnect(cycle) is True


def test_missing_log_file_yields_actionable_diagnostic(tmp_path: Path, capsys) -> None:
    code = MONITOR.main(
        [
            "--state-dir",
            str(tmp_path),
            "--log",
            str(tmp_path / "no-such-runtime.log"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "log file not found" in captured.err


def test_assess_cycles_reports_snapshot_auth(tmp_path: Path) -> None:
    """B4: the summary discloses whether per-cycle proof was used."""
    heartbeats = _cycle_heartbeats(tmp_path, 5, "2026-08-16T05:21:00Z")
    with_snapshots = MONITOR.assess_cycles(
        heartbeats[0], _log(5), cycles_required=5, heartbeat_files=heartbeats
    )
    assert with_snapshots["heartbeat_snapshots_supplied"] == len(heartbeats)
    assert with_snapshots["per_cycle_heartbeat_snapshots"] is True
    without = MONITOR.assess_cycles(
        heartbeats[0], _log(5), cycles_required=5, heartbeat_files=None
    )
    assert without["heartbeat_snapshots_supplied"] == 0
    assert without["per_cycle_heartbeat_snapshots"] is False


def _rust_jsonl_line(timestamp: str, message: str) -> str:
    """Mirror the real Nautilus Rust JSONL schema seen in logs/runtime."""
    return json.dumps(
        {
            "color": "31;1",
            "component": "nautilus_polymarket::websocket::client",
            "level": "INFO",
            "message": message,
            "timestamp": timestamp,
            "trader_id": "PolySignal-Nautilus-001",
        }
    )


def test_reconnect_times_parses_real_rust_jsonl_schema() -> None:
    """B4: the actual Nautilus Rust JSONL lines (nanosecond Z timestamps)."""
    lines = "\n".join(
        [
            _rust_jsonl_line(
                "2026-08-16T12:00:51.264130577Z",
                "Polymarket WebSocket reconnected",
            ),
            _rust_jsonl_line(
                "2026-08-16T12:00:51.264143127Z",
                "Polymarket WS reconnected",
            ),
        ]
    )
    times = MONITOR._reconnect_times(lines)
    # Both marker lines are ~12us apart -> one coalesced boundary.
    assert len(times) == 1
    assert times[0] == datetime(2026, 8, 16, 12, 0, 51, 264130, tzinfo=timezone.utc)


def test_main_discovers_rust_log_directory(tmp_path, capsys) -> None:
    """B4: --log pointing at a logs dir picks the newest Nautilus Rust JSONL,
    not the marker-free polysignal_lab.jsonl."""
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "polysignal_lab.jsonl").write_text(
        _jsonl_line("2026-08-16T05:00:04Z", "unrelated python line") + "\n",
        encoding="utf-8",
    )
    (logs / "PolySignal-Nautilus-001_2026-08-16_000000-000_x.jsonl").write_text(
        _rust_jsonl_line("2026-08-16T05:00:04Z", "Polymarket WebSocket reconnected")
        + "\n",
        encoding="utf-8",
    )
    # A heartbeat so assess_cycles can read it; data flowed after the reconnect.
    recovered = _heartbeat({})
    recovered["last_data_at"] = "2026-08-16T05:21:00+00:00"
    (tmp_path / "runtime_heartbeat.json").write_text(
        json.dumps(recovered), encoding="utf-8"
    )
    code = MONITOR.main(["--state-dir", str(tmp_path), "--log", str(logs), "--json"])
    captured = capsys.readouterr()
    assert "log file not found" not in captured.err
    assert "no reconnect/resubscribe markers found" not in captured.err
    # The single reconnect was found and assessed (fewer than the 5 required
    # cycles -> failed/exit 1), proving the Rust log was the one read.
    summary = json.loads(captured.out)
    assert summary["reconnect_count"] == 1
    assert summary["cycles_observed"] == 1
    assert code == 1


def test_assess_cycles_fails_closed_on_missing_heartbeat(tmp_path: Path) -> None:
    """B4/G1: a missing heartbeat is reported as heartbeat_unavailable, not a crash."""
    missing = tmp_path / "no-heartbeat.json"
    summary = MONITOR.assess_cycles(missing, _log(5), cycles_required=5)
    assert summary["status"] == "failed"
    assert summary["exit_code"] == 1
    for cycle in summary["cycles"]:
        assert cycle["heartbeat"]["status"] == "heartbeat_unavailable"


def test_books_after_reconnect_naive_vs_aware_no_type_error() -> None:
    """B4/G2: naive reconnect times compared against aware book timestamps."""
    cycle = {
        "reconnect_at": "2026-08-16T05:00:04",  # naive -> treated as UTC by _to_utc
        "heartbeat": {
            "conditions": {
                "cond-1": {
                    "last_book_at_by_side": {
                        "UP": "2026-08-16T05:21:00+00:00",
                        "DOWN": "2026-08-16T05:21:00+00:00",
                    }
                }
            }
        },
    }
    assert MONITOR._books_after_reconnect(cycle) is True


def test_recovered_heartbeat_with_stale_last_data_fails(tmp_path: Path) -> None:
    """B4: a fresh heartbeat whose last_data_at predates the reconnect cannot
    certify recovery — data stopped before the boundary."""
    stale = _heartbeat({})
    stale["last_data_at"] = "2026-08-16T04:59:00+00:00"  # before every reconnect
    (tmp_path / "runtime_heartbeat.json").write_text(
        json.dumps(stale), encoding="utf-8"
    )
    summary = MONITOR.assess_cycles(
        tmp_path / "runtime_heartbeat.json",
        _log(5),
        cycles_required=5,
        heartbeat_files=None,
    )
    assert summary["status"] == "failed"

    # And the precise signal: last book before reconnect -> not recovered.
    cycle = {
        "reconnect_at": "2026-08-16T05:00:04+00:00",
        "end_at": "2026-08-16T05:05:04+00:00",
        "last_data_at": "2026-08-16T04:59:00+00:00",
        "heartbeat": {"conditions": {}, "status": "ok"},
    }
    assert MONITOR._books_after_reconnect(cycle) is False


def test_reconnect_times_ignores_rtds_keepalive_reconnects() -> None:
    """B4: only the data-feed (WS) reconnect marks a cycle boundary, not the
    separate RTDS keepalive feed."""
    log = (
        "2026-08-16T05:00:04Z [INFO] Polymarket RTDS reconnected\n"
        "2026-08-16T05:05:04Z [INFO] Polymarket WebSocket reconnected\n"
    )
    times = MONITOR._reconnect_times(log)
    assert len(times) == 1
    assert times[0] == datetime(2026, 8, 16, 5, 5, 4, tzinfo=timezone.utc)


def test_reconnect_times_handles_prefixed_human_lines() -> None:
    """B4: `docker compose logs` prefixes (``container | ``) must not drop
    human markers."""
    log = (
        "polysignal-lab | 2026-08-16 05:00:04,500 INFO nautilus_polymarket: "
        "Polymarket WebSocket reconnected\n"
    )
    times = MONITOR._reconnect_times(log)
    assert len(times) == 1


def test_missing_heartbeat_path_no_traceback(tmp_path: Path, capsys) -> None:
    """B4: a missing heartbeat with a valid marker log fails cleanly, no traceback."""
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "PolySignal-Nautilus-001_2026-08-16_000000-000_x.jsonl").write_text(
        _rust_jsonl_line("2026-08-16T05:00:04Z", "Polymarket WebSocket reconnected")
        + "\n",
        encoding="utf-8",
    )
    missing_state = tmp_path / "no-such-state"
    code = MONITOR.main(
        ["--state-dir", str(missing_state), "--log", str(logs), "--json"]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "Traceback" not in captured.err
    assert "log file not found" not in captured.err


def test_assess_heartbeat_counts_armed_miss_without_replay() -> None:
    """A once-READY stuck condition (readiness miss armed, no replay marker) is
    reported unrecovered — the exact post-grace issue shape."""
    heartbeat = {
        "updated_at": "2026-08-16T06:00:00+00:00",
        "phase": "readiness_miss",
        "fatal": False,
        "last_data_at": "2026-08-16T06:00:00+00:00",
        "readiness_miss_started_at_by_key": {"cond-1": "2026-08-16T05:30:00+00:00"},
        "readiness_detail_by_key": {
            "cond-1": {
                "subscription_state": "stale_orderbook",
                "first_bilateral_book_ever_at": "2026-08-16T04:00:00+00:00",
                "last_book_received_at_by_side": {},
                "last_book_at_by_side": {},
            }
        },
    }
    summary = MONITOR.assess_heartbeat(heartbeat)
    assert summary["status"] == "unrecovered"
    assert summary["unrecovered"] == ["cond-1"]


def test_single_late_book_does_not_prove_early_cycles() -> None:
    """B4: a single post-hoc book must not certify every earlier cycle.
    The verdict-real defect: _books_after_reconnect had no upper bound, so a
    last_data_at after ALL reconnects vacuously passed all 5 cycles."""
    # Cycle 1 window is (05:00, 05:05]; a book at 05:21 is outside it.
    cycle1 = {
        "reconnect_at": "2026-08-16T05:00:04+00:00",
        "end_at": "2026-08-16T05:05:04+00:00",
        "last_data_at": "2026-08-16T05:21:00+00:00",
        "heartbeat": {"conditions": {}, "status": "ok", "exit_code": 0},
    }
    assert MONITOR._books_after_reconnect(cycle1) is False

    # Cycle 5 is (05:20, 05:25]; the same late book now proves that cycle.
    cycle5 = {
        "reconnect_at": "2026-08-16T05:20:04+00:00",
        "end_at": "2026-08-16T05:25:04+00:00",
        "last_data_at": "2026-08-16T05:21:00+00:00",
        "heartbeat": {"conditions": {}, "status": "ok", "exit_code": 0},
    }
    assert MONITOR._books_after_reconnect(cycle5) is True


def test_single_current_heartbeat_cannot_pass_all_5_cycles(
    tmp_path: Path,
) -> None:
    """End-to-end: with ONE current heartbeat (no snapshots), a late last_data_at
    can only certify the final cycle — the earlier cycles must fail."""
    book_at = "2026-08-16T05:21:00Z"
    hb = _cycle_heartbeats(tmp_path, 1, book_at)[0]
    summary = MONITOR.assess_cycles(hb, _log(5), cycles_required=5)
    assert summary["status"] == "failed"  # 1 book cannot prove 5 cycles
    assert summary["cycles_observed"] == 5
    assert not all(MONITOR._books_after_reconnect(c) for c in summary["cycles"])


def test_assess_heartbeat_counts_replay_timeout_as_unrecovered() -> None:
    """A stuck condition whose replay marker is stale (explicit timeout with
    recovery attempts) must be reported unrecovered, not replay_unconfirmed."""
    heartbeat = {
        "updated_at": "2026-08-16T06:00:00+00:00",
        "phase": "readiness_miss",
        "fatal": False,
        "last_data_at": "2026-08-16T06:00:00+00:00",
        "readiness_miss_started_at_by_key": {},
        "readiness_detail_by_key": {
            "cond-1": {
                "subscription_state": "awaiting_first_book",
                "adapter_replay_unconfirmed": True,
                "adapter_replay_timeout": True,
                "recovery_attempt_count": 3,
                "last_book_received_at_by_side": {},
                "last_book_at_by_side": {},
            }
        },
    }
    summary = MONITOR.assess_heartbeat(heartbeat)
    assert summary["status"] == "unrecovered"
    assert summary["unrecovered"] == ["cond-1"]
    assert summary["replay_unconfirmed"] == []


def test_transport_errors_counts_ws_close_codes() -> None:
    """B4 monitor should expose transport-level close/restore evidence so a
    failing restore loop is not hidden behind a generic status string."""
    lines = "\n".join(
        [
            "code=1013 slow consumer",
            "code=1008 invalid subscription payload",
            "code=1000 all subscribed assets resolved",
        ]
    )
    assert MONITOR._transport_errors(lines) == {
        "1000": 1,
        "1001": 0,
        "1008": 1,
        "1013": 1,
    }
