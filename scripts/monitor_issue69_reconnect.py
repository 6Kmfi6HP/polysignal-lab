#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SIDES = ("UP", "DOWN")
Detail = dict[str, Any]
CYCLES_REQUIRED = 5
RECONNECT_MARKER = "Polymarket WebSocket reconnected"
RESUBSCRIBE_MARKER = "Resubscribing to"
# A single reconnect logs both the reconnect and the resubscribe lines; collapse
# markers that land within this window into one cycle boundary.
COALESCE_SEC = 15.0
# Human sink: `%(asctime)s %(levelname)s ...` where asctime is
# "2026-08-16 11:50:03,500", plus the JSONL ISO "2026-08-16T05:00:00Z" form.
# Search semantics (not anchored) so `docker compose logs` prefix output
# ("container | " before the timestamp) still yields the boundary time.
_HUMAN_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})")
# Data-feed (WS) reconnect only; `Polymarket RTDS reconnected` is the separate
# RTDS keepalive feed and must not become a spurious cycle boundary.
_RECONNECT_WS_RE = re.compile(
    r"Polymarket\s+(?:WS|WebSocket)\s+reconnect",
    re.IGNORECASE,
)


def _to_utc(value: datetime) -> datetime:
    """Normalize naive (Docker-human) and offset (JSONL) timestamps to UTC."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_reconnect_line(line: str) -> bool:
    """Match the data-feed reconnect markers (WS/WebSocket + resubscribe)."""
    if RECONNECT_MARKER in line or RESUBSCRIBE_MARKER in line:
        return True
    return _RECONNECT_WS_RE.search(line) is not None


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
        received_raw = detail.get("last_book_received_at_by_side", {})
        book_raw = detail.get("last_book_at_by_side", {})
        received: dict[Any, Any] = received_raw if isinstance(received_raw, dict) else {}
        book_at: dict[Any, Any] = book_raw if isinstance(book_raw, dict) else {}
        missing_sides = [
            side
            for side in SIDES
            if not received.get(side) or not book_at.get(side)
        ]
        # subscription_readiness_state never emits an "adapter_replay_unconfirmed"
        # state name; the unconfirmed signal is the detail field only.
        replay = bool(detail.get("adapter_replay_unconfirmed"))
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


def _parse_log_timestamp(line: str) -> datetime | None:
    """Extract a UTC-aware timestamp from a JSONL or human log line."""
    stripped = line.lstrip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except ValueError:
            return None
        if not isinstance(payload, dict):
            return None
        timestamp = payload.get("timestamp")
        if not isinstance(timestamp, str):
            return None
        try:
            return _to_utc(datetime.fromisoformat(timestamp))
        except ValueError:
            return None
    match = _HUMAN_TS_RE.search(stripped)
    if match is None:
        return None
    try:
        return _to_utc(
            datetime.strptime(
                f"{match.group(1)} {match.group(2)}",
                "%Y-%m-%d %H:%M:%S",
            )
        )
    except ValueError:
        return None


def _reconnect_times(log_text: str) -> list[datetime]:
    times: list[datetime] = []
    for line in log_text.splitlines():
        if not _is_reconnect_line(line):
            continue
        timestamp = _parse_log_timestamp(line)
        if timestamp is None:
            continue
        if times and 0 <= (timestamp - times[-1]).total_seconds() < COALESCE_SEC:
            # Same reconnect's second marker line; keep the first boundary.
            continue
        times.append(timestamp)
    return times


def _read_log(path: Path) -> str:
    """Read a log file, transparently decompressing rotated ``.gz`` backups."""
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    return path.read_text(encoding="utf-8", errors="replace")


def _candidate_log_files(path: Path) -> list[Path]:
    parent = path.parent
    if not parent.exists():
        return []
    return sorted(
        candidate
        for candidate in parent.iterdir()
        if candidate.is_file()
        and (candidate.suffix in {".jsonl", ".log", ".gz"} or ".jsonl" in candidate.name)
    )


def _discover_rust_log(directory: Path) -> Path | None:
    """Newest Nautilus Rust JSONL in a logs directory.

    The reconnect markers are emitted by the Rust Polymarket adapter into files
    named ``PolySignal-Nautilus-<trader>_<ts>_<instance>.jsonl``, not the Python
    ``polysignal_lab.jsonl`` sink.
    """
    candidates = sorted(
        directory.glob("PolySignal-Nautilus-*.jsonl"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0]
    fallback = sorted(
        (
            path
            for path in directory.glob("*.jsonl")
            if "polysignal_lab" not in path.name
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return fallback[0] if fallback else None


def _log_has_markers(log_text: str) -> bool:
    return any(_is_reconnect_line(line) for line in log_text.splitlines())


def _books_after_reconnect(cycle: dict[str, Any]) -> bool:
    """Prove data flowed inside this cycle's own window.

    Each cycle is a reconnect boundary; with per-cycle heartbeat snapshots the
    proof must fall inside ``(reconnect_at, end_at]`` — otherwise a single late
    book (or a post-hoc ``last_data_at``) would certify every earlier cycle,
    which is a vacuous pass. The runtime pops a recovered condition's detail
    from ``readiness_detail_by_key`` the moment it reaches READY, so a healthy
    heartbeat carries per-condition book timestamps ONLY for bookless
    conditions; the global ``last_data_at`` clock is the recovery evidence and
    is bounded by the cycle end the same way.
    """
    reconnect_at = str(cycle.get("reconnect_at", ""))
    if not reconnect_at:
        return False
    try:
        reconnect_dt = _to_utc(datetime.fromisoformat(reconnect_at))
    except ValueError:
        return False
    end_at = cycle.get("end_at")
    end_dt = None
    if isinstance(end_at, str):
        try:
            end_dt = _to_utc(datetime.fromisoformat(end_at.replace("Z", "+00:00")))
        except ValueError:
            end_dt = None

    def within_window(value: datetime) -> bool:
        if value <= reconnect_dt:
            return False
        if end_dt is not None and value > end_dt:
            return False
        return True

    last_data_at = cycle.get("last_data_at")
    if isinstance(last_data_at, str):
        try:
            if within_window(
                _to_utc(datetime.fromisoformat(last_data_at.replace("Z", "+00:00")))
            ):
                return True
        except ValueError:
            pass
    heartbeat_summary = cycle.get("heartbeat")
    if not isinstance(heartbeat_summary, dict):
        return False
    heartbeat = heartbeat_summary.get("conditions")
    if not isinstance(heartbeat, dict) or not heartbeat:
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
                book_dt = _to_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
            except ValueError:
                return False
            if not within_window(book_dt):
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
            "heartbeat_snapshots_supplied": (len(heartbeat_files) if heartbeat_files else 0),
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
        try:
            raw_heartbeat = _read_heartbeat(cycle_heartbeat_path)
            last_data_at = raw_heartbeat.get("last_data_at")
            heartbeat = assess_heartbeat(raw_heartbeat)
        except (OSError, ValueError, TypeError):
            # A missing/corrupt heartbeat cannot prove recovery for this cycle:
            # fail closed (exit 1), never crash the verification run.
            last_data_at = None
            heartbeat = {
                "status": "heartbeat_unavailable",
                "exit_code": 1,
                "active_conditions": 0,
                "replay_unconfirmed": [],
                "replay_unconfirmed_count": 0,
                "unrecovered": [],
                "unrecovered_count": 0,
                "conditions": {},
            }
        observed.append(
            {
                "cycle": index + 1,
                "reconnect_at": reconnect_at.isoformat(),
                "end_at": next_at.isoformat(),
                "last_data_at": last_data_at,
                "heartbeat": heartbeat,
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
        "heartbeat_snapshots_supplied": (len(heartbeat_files) if heartbeat_files else 0),
        "per_cycle_heartbeat_snapshots": bool(heartbeat_files),
        "cycles": observed,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify five market cycles recover after Polymarket reconnect."
    )
    parser.add_argument("--state-dir", default="state")
    parser.add_argument("--heartbeat", default="runtime_heartbeat.json")
    parser.add_argument(
        "--log",
        default="logs/runtime",
        help=(
            "Nautilus adapter log file (JSONL or plain text from `docker logs`), "
            "or a directory to auto-pick the newest PolySignal-Nautilus-*.jsonl "
            "from. The reconnect markers are Rust-adapter lines, so the Python "
            "polysignal_lab.jsonl will NOT contain them."
        ),
    )
    parser.add_argument(
        "--snapshots",
        nargs="*",
        default=None,
        help=(
            "optional per-cycle runtime heartbeat snapshot files, one per "
            "reconnect boundary (oldest first). Without them every cycle is "
            "checked against the single current --heartbeat."
        ),
    )
    parser.add_argument("--cycles", type=int, default=CYCLES_REQUIRED)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    heartbeat_path = Path(args.state_dir) / args.heartbeat
    log_path = Path(args.log)
    if log_path.is_dir():
        discovered = _discover_rust_log(log_path)
        if discovered is None:
            print(
                f"no Nautilus log files found in {log_path}; "
                "point --log at a *.jsonl file or `docker logs` output",
                file=sys.stderr,
            )
            return 1
        log_path = discovered
    if not log_path.exists():
        print(f"log file not found: {log_path}", file=sys.stderr)
        candidates = _candidate_log_files(log_path)
        if candidates:
            print(
                "candidate log files in that directory: "
                + ", ".join(str(path) for path in candidates),
                file=sys.stderr,
            )
        return 1
    log_text = _read_log(log_path)
    if not _log_has_markers(log_text):
        print(
            f"warning: no reconnect/resubscribe markers found in {log_path}: "
            "either the window had no reconnects or this is the wrong sink "
            "(the markers are Nautilus-adapter lines, usually only visible via "
            "`docker logs`)",
            file=sys.stderr,
        )
    snapshot_paths = (
        [Path(value) for value in args.snapshots] if args.snapshots else None
    )
    summary = assess_cycles(
        heartbeat_path,
        log_text,
        cycles_required=args.cycles,
        heartbeat_files=snapshot_paths,
    )
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    else:
        print(
            f"{summary['status']}: "
            f"{summary.get('cycles_observed', 0)}/{summary.get('cycles_required', 0)} "
            "reconnect cycles checked "
            f"(snapshots={summary.get('heartbeat_snapshots_supplied', 0)})"
        )
    exit_code = summary.get("exit_code", 1)
    return exit_code if isinstance(exit_code, int) else 1


if __name__ == "__main__":
    raise SystemExit(main())
