#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


SIDES = ("UP", "DOWN")
Detail = dict[str, Any]
CYCLES_REQUIRED = 5
RECONNECT_MARKER = "Polymarket WebSocket reconnected"
RESUBSCRIBE_MARKER = "Resubscribing to"


def _read_heartbeat(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("runtime heartbeat must be a JSON object")
    return payload


def _conditions(heartbeat: dict[str, Any]) -> dict[str, Detail]:
    raw = heartbeat.get("readiness_detail_by_key", {})
    return {
        str(condition_id): detail
        for condition_id, detail in raw.items()
        if isinstance(detail, dict)
    }


def assess_heartbeat(heartbeat: dict[str, Any]) -> dict[str, Any]:
    details = _conditions(heartbeat)
    misses = heartbeat.get("readiness_miss_started_at_by_key", {})
    misses = misses if isinstance(misses, dict) else {}

    replay_unconfirmed: list[str] = []
    unrecovered: list[str] = []
    for condition_id, detail in details.items():
        state = detail.get("subscription_state")
        received_raw = detail.get("last_book_received_at_by_side", {})
        book_raw = detail.get("last_book_at_by_side", {})
        received: dict[Any, Any] = received_raw if isinstance(received_raw, dict) else {}
        book_at: dict[Any, Any] = book_raw if isinstance(book_raw, dict) else {}
        missing_sides = [
            side
            for side in SIDES
            if not received.get(side) or not book_at.get(side)
        ]
        replay = state == "adapter_replay_unconfirmed" or bool(
            detail.get("adapter_replay_unconfirmed")
        )
        readiness_miss = bool(misses.get(condition_id)) and not replay
        if replay:
            replay_unconfirmed.append(condition_id)
        elif missing_sides or readiness_miss:
            unrecovered.append(condition_id)

    if unrecovered:
        status = "unrecovered"
        exit_code = 1
    elif replay_unconfirmed:
        status = "replay_unconfirmed"
        exit_code = 0
    else:
        status = "ok"
        exit_code = 0
    return {
        "status": status,
        "exit_code": exit_code,
        "active_conditions": len(details),
        "replay_unconfirmed": replay_unconfirmed,
        "replay_unconfirmed_count": len(replay_unconfirmed),
        "unrecovered": unrecovered,
        "unrecovered_count": len(unrecovered),
        "conditions": details,
    }


def _reconnect_times(log_text: str) -> list[datetime]:
    times: list[datetime] = []
    for line in log_text.splitlines():
        if RECONNECT_MARKER in line or RESUBSCRIBE_MARKER in line:
            timestamp = line.split(" ", 1)[0]
            try:
                times.append(datetime.fromisoformat(timestamp.replace("Z", "+00:00")))
            except ValueError:
                continue
    seen: set[datetime] = set()
    unique: list[datetime] = []
    for value in times:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def _books_after_reconnect(cycle: dict[str, Any]) -> bool:
    heartbeat_summary = cycle.get("heartbeat")
    if not isinstance(heartbeat_summary, dict):
        return False
    heartbeat = heartbeat_summary.get("conditions")
    if not isinstance(heartbeat, dict) or not heartbeat:
        return False
    reconnect_at = str(cycle.get("reconnect_at", ""))
    if not reconnect_at:
        return False
    try:
        reconnect_dt = datetime.fromisoformat(reconnect_at)
    except ValueError:
        return False
    for detail in heartbeat.values():
        if not isinstance(detail, dict):
            return False
        book_at = detail.get("last_book_at_by_side")
        if not isinstance(book_at, dict):
            return False
        for side in SIDES:
            raw = book_at.get(side)
            if not isinstance(raw, str):
                return False
            try:
                book_dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return False
            if book_dt <= reconnect_dt:
                return False
    return True


def assess_cycles(
    heartbeat_path: Path,
    log_text: str,
    *,
    cycles_required: int = CYCLES_REQUIRED,
    heartbeat_files: list[Path] | None = None,
) -> dict[str, Any]:
    reconnects = _reconnect_times(log_text)
    if not reconnects:
        return {
            "status": "no_reconnects",
            "exit_code": 1,
            "cycles_observed": 0,
            "cycles_required": cycles_required,
            "reconnect_count": 0,
        }

    # A cycle starts at a reconnect and ends at the next reconnect. We require
    # at least cycles_required reconnect boundaries, then check the heartbeat
    # state at each boundary window.
    observed: list[dict[str, Any]] = []
    for index, reconnect_at in enumerate(reconnects[:cycles_required]):
        next_at = (
            reconnects[index + 1]
            if index + 1 < len(reconnects)
            else reconnect_at + timedelta(minutes=5)
        )
        if (next_at - reconnect_at).total_seconds() < 30:
            continue
        cycle_heartbeat_path = (
            heartbeat_files[index]
            if heartbeat_files is not None and index < len(heartbeat_files)
            else heartbeat_path
        )
        observed.append(
            {
                "cycle": index + 1,
                "reconnect_at": reconnect_at.isoformat(),
                "end_at": next_at.isoformat(),
                "heartbeat": assess_heartbeat(_read_heartbeat(cycle_heartbeat_path)),
            }
        )

    heartbeat_statuses = [
        str(cycle["heartbeat"]["status"])
        for cycle in observed
        if isinstance(cycle.get("heartbeat"), dict)
    ]
    passed = (
        len(observed) >= cycles_required
        and all(status == "ok" for status in heartbeat_statuses)
        and all(_books_after_reconnect(cycle) for cycle in observed)
    )
    return {
        "status": "passed" if passed else "failed",
        "exit_code": 0 if passed else 1,
        "cycles_observed": len(observed),
        "cycles_required": cycles_required,
        "reconnect_count": len(reconnects),
        "cycles": observed,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify five market cycles recover after Polymarket reconnect."
    )
    parser.add_argument("--state-dir", default="state")
    parser.add_argument("--heartbeat", default="runtime_heartbeat.json")
    parser.add_argument("--log", default="runtime.log")
    parser.add_argument("--cycles", type=int, default=CYCLES_REQUIRED)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    heartbeat_path = Path(args.state_dir) / args.heartbeat
    log_text = Path(args.log).read_text(encoding="utf-8", errors="replace")
    summary = assess_cycles(
        heartbeat_path,
        log_text,
        cycles_required=args.cycles,
    )
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    else:
        print(
            f"{summary['status']}: "
            f"{summary.get('cycles_observed', 0)}/{summary.get('cycles_required', 0)} "
            "reconnect cycles checked"
        )
    exit_code = summary.get("exit_code", 1)
    return exit_code if isinstance(exit_code, int) else 1


if __name__ == "__main__":
    raise SystemExit(main())
