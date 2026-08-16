from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta
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
    for index in range(count):
        details: dict[str, dict[str, object]] = {
            "cond-1": {
                "subscription_state": "ready",
                "last_book_received_at_by_side": {
                    "UP": book_at,
                    "DOWN": book_at,
                },
                "last_book_at_by_side": {
                    "UP": book_at,
                    "DOWN": book_at,
                },
            }
        }
        path = tmp_path / f"heartbeat-{index}.json"
        path.write_text(json.dumps(_heartbeat(details)), encoding="utf-8")
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
