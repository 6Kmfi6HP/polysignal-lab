from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import datetime
import json
from pathlib import Path

from polysignal_lab.config import load_settings
from polysignal_lab.observability.runtime_health import (
    evaluate_liveness,
    read_runtime_startup_started_at,
)


def _heartbeat_path(state_dir: str) -> Path:
    return Path(state_dir) / "runtime_heartbeat.json"


def _startup_marker_path(state_dir: str) -> Path:
    return Path(state_dir) / "runtime_startup.json"


def _read_startup_started_at(path: Path) -> datetime | None:
    try:
        return read_runtime_startup_started_at(path)
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
        startup_started_at = _read_startup_started_at(
            _startup_marker_path(settings.storage.state_dir)
        )
        result = evaluate_liveness(
            _heartbeat_path(settings.storage.state_dir),
            max_age_sec=settings.health.liveness.heartbeat_max_age_sec,
            startup_started_at=startup_started_at,
            startup_grace_sec=settings.health.startup_grace_sec,
            max_readiness_miss_sec=settings.health.liveness.max_readiness_miss_sec,
            max_data_starvation_sec=settings.health.liveness.max_data_starvation_sec,
        )
        if not result.ok:
            print(f"liveness failed: {result.reason}")
            return 1
        return 0
    raise AssertionError(f"unhandled healthcheck command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
