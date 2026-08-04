#!/usr/bin/env python3
"""Data retention maintenance script.

Usage:
    python -m scripts.retention_maintenance --config config/signal_bot.yaml [--dry-run]

Or via entrypoint:
    docker compose run --rm --no-deps -T polysignal-lab maintenance [--dry-run]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from polysignal_lab.app.services.persistence_service import PersistenceService
from polysignal_lab.config import Settings
from polysignal_lab.nautilus_runtime.node_crash import cleanup_old_crash_logs
from polysignal_lab.observability.logger import cleanup_runtime_logs
from polysignal_lab.storage.jsonl_store import JSONLStore
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.storage.state_store import StateStore


def run_maintenance(settings: Settings, *, dry_run: bool = False) -> dict[str, Any]:
    retention = settings.retention
    summary: dict[str, Any] = {"enabled": retention.enabled, "dry_run": dry_run}
    if not retention.enabled:
        return summary

    archive_dir = Path(retention.archive_dir)
    logs = JSONLStore(
        settings.storage.jsonl_dir,
        max_file_bytes=retention.jsonl_max_file_bytes,
        hot_days=retention.jsonl_hot_days,
        archive_days=retention.jsonl_archive_days,
        archive_dir=archive_dir,
        create_base_dir=not dry_run,
    )
    sqlite_path = Path(settings.storage.sqlite_path)
    service: PersistenceService | None = None
    try:
        if dry_run and not sqlite_path.exists():
            summary["sqlite"] = {
                "db_size_bytes": 0,
                "tables_cleaned": [],
                "rows_deleted": 0,
                "archives_created": [],
            }
        else:
            service = PersistenceService(
                logs=logs,
                sqlite=SQLiteStore(sqlite_path, read_only=dry_run),
                state=StateStore(
                    settings.storage.state_dir,
                    create_base_dir=not dry_run,
                ),
            )
            summary["sqlite"] = service.run_retention(retention, dry_run=dry_run)
        summary["jsonl_archived"] = logs._compress_and_archive_old_files(
            dry_run=dry_run
        )
        summary["jsonl_archives_deleted"] = logs.cleanup_expired_archives(
            dry_run=dry_run
        )
        summary["runtime_logs"] = cleanup_runtime_logs(
            Path(settings.logging.directory),
            archive_dir,
            retention.runtime_log_soft_limit_bytes,
            retention.runtime_log_hard_limit_bytes,
            dry_run=dry_run,
        )
        summary["crash_logs_deleted"] = cleanup_old_crash_logs(
            settings.logging.directory,
            retention.crash_log_max_days,
            dry_run=dry_run,
        )
    finally:
        if service is not None:
            service.close()
    return summary


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
