from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from polysignal_lab.config import load_settings
from polysignal_lab.observability.runtime_health import evaluate_liveness


def _heartbeat_path(state_dir: str) -> Path:
    return Path(state_dir) / "runtime_heartbeat.json"


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
        result = evaluate_liveness(
            _heartbeat_path(settings.storage.state_dir),
            max_age_sec=settings.health.liveness.heartbeat_max_age_sec,
        )
        if not result.ok:
            print(f"liveness failed: {result.reason}")
            return 1
        return 0
    raise AssertionError(f"unhandled healthcheck command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
