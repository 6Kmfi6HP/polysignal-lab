from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
import yaml

from polysignal_lab.app.services.persistence_service import PersistenceService
from polysignal_lab.config import RetentionConfig, Settings
from scripts.retention_maintenance import run_maintenance
from polysignal_lab.storage.jsonl_store import JSONLStore
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.storage.state_store import StateStore


def _service(store: Mock) -> PersistenceService:
    return PersistenceService(
        logs=cast(JSONLStore, object()),
        sqlite=cast(SQLiteStore, store),
        state=cast(StateStore, object()),
    )


def test_retention_does_nothing_at_or_below_soft_limit(tmp_path: Path) -> None:
    store = Mock()
    store.db_file_size.return_value = 100
    service = _service(store)

    summary = service.run_retention(
        RetentionConfig(sqlite_soft_limit_bytes=100, archive_dir=str(tmp_path))
    )

    assert summary["rows_deleted"] == 0
    store.archive_table_rows.assert_not_called()
    store.delete_latest_only.assert_not_called()
    store.wal_checkpoint.assert_not_called()


@pytest.mark.parametrize("db_size", [101, 201])
def test_retention_runs_above_soft_and_hard_limits(
    tmp_path: Path, db_size: int
) -> None:
    store = Mock()
    store.db_file_size.return_value = db_size
    store.archive_table_rows.side_effect = lambda table, *_args, **_kwargs: (
        2 if table == "signals" else 0
    )
    store.delete_latest_only.return_value = 1
    store.delete_rows_before.return_value = 0
    store.delete_event_rows_before.return_value = 0
    service = _service(store)

    summary = service.run_retention(
        RetentionConfig(
            sqlite_soft_limit_bytes=100,
            sqlite_hard_limit_bytes=200,
            archive_dir=str(tmp_path),
        )
    )

    assert summary["rows_deleted"] == 3
    assert summary["tables_cleaned"] == ["signals", "strategy_status"]
    store.wal_checkpoint.assert_called_once_with("PASSIVE")


def test_retention_dry_run_reports_without_modifying(tmp_path: Path) -> None:
    store = Mock()
    store.db_file_size.return_value = 101
    store.rows_before.side_effect = (
        lambda table, *_args, **_kwargs: 2 if table == "signals" else 0
    )
    store.latest_only_delete_count.return_value = 1
    store.event_rows_before.return_value = 0
    service = _service(store)

    summary = service.run_retention(
        RetentionConfig(sqlite_soft_limit_bytes=100, archive_dir=str(tmp_path)),
        dry_run=True,
    )

    assert summary["rows_deleted"] == 3
    assert len(summary["archives_created"]) == 1
    store.archive_table_rows.assert_not_called()
    store.delete_latest_only.assert_not_called()
    store.wal_checkpoint.assert_not_called()


def test_maintenance_dry_run_does_not_create_or_modify_storage(tmp_path: Path) -> None:
    db_path = tmp_path / "data.sqlite3"
    store = SQLiteStore(db_path)
    store.insert_signal(
        {
            "signal_id": "old-signal",
            "strategy": "test",
            "asset": "BTC",
            "timeframe": "5m",
            "market_id": "market-1",
            "side": "UP",
            "confidence": 0.8,
            "created_at": "2020-01-01T00:00:00Z",
        }
    )
    store.close()
    before = db_path.read_bytes()
    before_paths = {path.name for path in tmp_path.iterdir()}
    settings = Settings.model_validate(
        {
            "storage": {
                "sqlite_path": str(db_path),
                "jsonl_dir": str(tmp_path / "jsonl"),
                "state_dir": str(tmp_path / "state"),
            },
            "logging": {"directory": str(tmp_path / "runtime")},
            "retention": {
                "archive_dir": str(tmp_path / "archive"),
                "sqlite_soft_limit_bytes": 0,
            },
        }
    )

    summary = run_maintenance(settings, dry_run=True)

    assert summary["sqlite"]["rows_deleted"] == 1
    assert db_path.read_bytes() == before
    assert {path.name for path in tmp_path.iterdir()} == before_paths
    assert not (tmp_path / "jsonl").exists()
    assert not (tmp_path / "state").exists()
    assert not (tmp_path / "archive").exists()
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 1


def test_system_event_overrides_are_deleted_without_archiving(tmp_path: Path) -> None:
    sqlite_store = SQLiteStore(tmp_path / "data.sqlite3")
    service = PersistenceService(
        logs=JSONLStore(tmp_path / "logs"),
        sqlite=sqlite_store,
        state=StateStore(tmp_path / "state"),
    )
    for event_type in ("health_snapshot", "nautilus_decision", "runtime_warning"):
        service.insert_system_event(
            {
                "event_id": f"event-{event_type}",
                "event_type": event_type,
                "severity": "INFO",
                "created_at": "2020-01-01T00:00:00Z",
            }
        )

    summary = service.run_retention(
        RetentionConfig(
            sqlite_soft_limit_bytes=0,
            archive_dir=str(tmp_path / "archive"),
        )
    )

    assert summary["rows_deleted"] == 3
    assert sqlite_store.table_row_count("system_events") == 0
    archives = list((tmp_path / "archive" / "sqlite").glob("system_events_*.gz"))
    assert len(archives) == 1
    with gzip.open(archives[0], "rt", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh]
    assert [row["event_type"] for row in rows] == ["runtime_warning"]
    service.close()


def test_compose_mounts_archive_for_runtime_and_dashboard() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))

    assert "./archive:/app/archive" in compose["services"]["polysignal-lab"]["volumes"]
    assert (
        "./archive:/app/archive:ro"
        in compose["services"]["dashboard-api"]["volumes"]
    )


def test_systemd_timer_runs_non_overlapping_maintenance() -> None:
    service = Path("deploy/polysignal-lab-retention.service").read_text(
        encoding="utf-8"
    )
    timer = Path("deploy/polysignal-lab-retention.timer").read_text(encoding="utf-8")

    assert "/usr/bin/flock -n" in service
    assert "run --rm --no-deps -T polysignal-lab maintenance" in service
    assert "OnCalendar=*-*-* 04:00:00" in timer
    assert "Persistent=true" in timer
