from __future__ import annotations

import gzip
import json
import sqlite3
import threading
from pathlib import Path

import pytest

from polysignal_lab.storage import sqlite_store as sqlite_store_module
from polysignal_lab.storage.sqlite_store import SQLiteStore


def _pause_gzip_writes(
    monkeypatch: pytest.MonkeyPatch,
    started: threading.Event,
    release: threading.Event,
) -> None:
    original_gzip_open = sqlite_store_module.gzip.open

    class BlockingGzipFile:
        def __init__(self, path: Path, mode: str, encoding: str) -> None:
            self._file = original_gzip_open(path, mode, encoding=encoding)

        def __enter__(self) -> "BlockingGzipFile":
            self._file.__enter__()
            return self

        def __exit__(self, *args: object) -> object:
            return self._file.__exit__(*args)

        def write(self, value: str) -> int:
            started.set()
            assert release.wait(timeout=5)
            return self._file.write(value)

    monkeypatch.setattr(
        sqlite_store_module.gzip,
        "open",
        lambda path, mode, encoding: BlockingGzipFile(path, mode, encoding),
    )


def _insert_signal(store: SQLiteStore, signal_id: str, created_at: str) -> None:
    store.insert_signal(
        {
            "signal_id": signal_id,
            "strategy": "test",
            "asset": "BTC",
            "timeframe": "5m",
            "market_id": "market-1",
            "side": "UP",
            "confidence": 0.8,
            "created_at": created_at,
        }
    )


def test_archive_table_rows_exports_then_deletes_old_rows(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "data.sqlite3")
    _insert_signal(store, "old-1", "2026-01-01T00:00:00Z")
    _insert_signal(store, "old-2", "2026-01-02T00:00:00Z")
    _insert_signal(store, "hot-1", "2026-08-01T00:00:00Z")
    archive = tmp_path / "archive" / "signals.jsonl.gz"

    deleted = store.archive_table_rows(
        "signals",
        "created_at",
        "2026-02-01T00:00:00Z",
        archive,
        batch_rows=1,
    )

    assert deleted == 2
    assert store.table_row_count("signals") == 1
    assert store.oldest_timestamp("signals", "created_at") == "2026-08-01T00:00:00Z"
    with gzip.open(archive, "rt", encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh]
    assert {row["signal_id"] for row in rows} == {"old-1", "old-2"}
    store.close()


def test_archive_table_rows_creates_no_empty_archive(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "data.sqlite3")
    archive = tmp_path / "archive" / "signals.jsonl.gz"

    assert (
        store.archive_table_rows(
            "signals", "created_at", "2026-02-01T00:00:00Z", archive
        )
        == 0
    )
    assert not archive.exists()
    store.close()


def test_delete_latest_only_keeps_latest_row_per_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SQLiteStore(tmp_path / "data.sqlite3")
    timestamps = iter(
        (
            "2026-01-01T00:00:00Z",
            "2026-01-02T00:00:00Z",
            "2026-01-01T00:00:00Z",
            "2026-01-03T00:00:00Z",
        )
    )
    monkeypatch.setattr(sqlite_store_module, "utc_iso", lambda *_args: next(timestamps))
    for strategy in ("alpha", "alpha", "beta", "beta"):
        store.insert_strategy_status(
            {
                "strategy": strategy,
                "asset": "BTC",
                "timeframe": "5m",
                "status": "READY",
                "reason": None,
            }
        )

    assert (
        store.latest_only_delete_count(
            "strategy_status", ("strategy", "asset", "timeframe"), "created_at"
        )
        == 2
    )
    assert (
        store.delete_latest_only(
            "strategy_status", ("strategy", "asset", "timeframe"), "created_at"
        )
        == 2
    )
    rows = store.query_json("strategy_status", limit=10)
    assert sorted(row["strategy"] for row in rows) == ["alpha", "beta"]
    assert store.table_row_count("strategy_status") == 2
    assert store.db_file_size() > 0
    store.close()


def test_archive_compression_does_not_hold_sqlite_writer_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "data.sqlite3"
    store = SQLiteStore(db_path)
    writer = SQLiteStore(db_path)
    _insert_signal(store, "old-1", "2020-01-01T00:00:00Z")
    compression_started = threading.Event()
    release_compression = threading.Event()
    _pause_gzip_writes(monkeypatch, compression_started, release_compression)
    errors: list[BaseException] = []

    def archive() -> None:
        try:
            store.archive_table_rows(
                "signals",
                "created_at",
                "2026-01-01T00:00:00Z",
                tmp_path / "archive.jsonl.gz",
            )
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=archive)
    thread.start()
    assert compression_started.wait(timeout=5)
    try:
        _insert_signal(writer, "hot-1", "2026-08-01T00:00:00Z")
    finally:
        release_compression.set()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert errors == []
    assert writer.table_row_count("signals") == 1
    writer.close()
    store.close()


def test_archive_aborts_delete_when_exported_row_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "data.sqlite3"
    store = SQLiteStore(db_path)
    _insert_signal(store, "old-1", "2020-01-01T00:00:00Z")
    compression_started = threading.Event()
    release_compression = threading.Event()
    _pause_gzip_writes(monkeypatch, compression_started, release_compression)
    errors: list[BaseException] = []

    def archive() -> None:
        try:
            store.archive_table_rows(
                "signals",
                "created_at",
                "2026-01-01T00:00:00Z",
                tmp_path / "archive.jsonl.gz",
            )
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=archive)
    thread.start()
    assert compression_started.wait(timeout=5)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE signals SET confidence=? WHERE signal_id=?",
            (0.9, "old-1"),
        )
    release_compression.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert "remain unchanged" in str(errors[0])
    assert store.table_row_count("signals") == 1
    store.close()
