from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime
import json
from pathlib import Path

from polysignal_lab.config import load_settings
from polysignal_lab.observability.runtime_health import evaluate_liveness


def _heartbeat_path(state_dir: str) -> Path:
    return Path(state_dir) / "runtime_heartbeat.json"

def _startup_marker_path(state_dir: str) -> Path:
    return Path(state_dir) / "runtime_startup.json"


def _read_or_create_startup_started_at(path: Path) -> datetime | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload["started_at"], str):
            return None
        return datetime.fromisoformat(payload["started_at"]).astimezone(UTC)
    except FileNotFoundError:
        started_at = datetime.now(UTC)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"started_at": started_at.isoformat()}, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(path)
        return started_at
    except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PolySignal Lab healthcheck")
    subcommands = parser.add_subparsers(dest="command", required=True)
    liveness = subcommands.add_parser("liveness")
    liveness.add_argument("--config", default="config/signal_bot.yaml")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings(args.config)
    if args.command == "liveness":
        startup_started_at = _read_or_create_startup_started_at(
            _startup_marker_path(settings.storage.state_dir)
        )
        result = evaluate_liveness(
            _heartbeat_path(settings.storage.state_dir),
            max_age_sec=settings.health.liveness.heartbeat_max_age_sec,
            startup_started_at=startup_started_at,
            startup_grace_sec=settings.health.startup_grace_sec,
        )
        if not result.ok:
            print(f"liveness failed: {result.reason}")
            return 1
        return 0
    raise AssertionError(f"unhandled healthcheck command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
