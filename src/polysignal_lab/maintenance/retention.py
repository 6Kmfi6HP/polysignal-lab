"""Retention maintenance runner.

The implementation lives in the package so tests and the CLI share one
entry point; `scripts/retention_maintenance.py` is only an argument parser.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
