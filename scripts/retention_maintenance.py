#!/usr/bin/env python3
"""Data retention maintenance CLI.

Usage:
    python -m scripts.retention_maintenance --config config/signal_bot.yaml [--dry-run]

Or via entrypoint:
    docker compose run --rm --no-deps -T polysignal-lab maintenance [--dry-run]

Implementation lives in `polysignal_lab.maintenance.retention`.
"""

from __future__ import annotations

import argparse
import json
from typing import Sequence

from polysignal_lab.config import Settings
from polysignal_lab.maintenance.retention import run_maintenance


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run data retention maintenance")
    parser.add_argument("--config", default="config/signal_bot.yaml")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    settings = Settings.from_yaml(args.config)
    print(json.dumps(run_maintenance(settings, dry_run=args.dry_run), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
