from __future__ import annotations

import gzip
import os
from pathlib import Path
from time import time

from polysignal_lab.storage.jsonl_store import JSONLStore


def test_append_rotates_full_file_and_keeps_active_path(tmp_path: Path) -> None:
    store = JSONLStore(tmp_path / "logs", max_file_bytes=100)

    active = store.append("signals", {"payload": "x" * 120})

    rotated = list((tmp_path / "logs").glob("signals_*_001.jsonl"))
    assert active == tmp_path / "logs" / "signals.jsonl"
    assert active.exists()
    assert active.read_text(encoding="utf-8") == ""
    assert len(rotated) == 1
    assert "x" * 120 in rotated[0].read_text(encoding="utf-8")


def test_rotation_sequence_increases_within_day(tmp_path: Path) -> None:
    store = JSONLStore(tmp_path / "logs", max_file_bytes=10)

    store.append("signals", {"value": "first"})
    store.append("signals", {"value": "second"})

    names = sorted(path.name for path in (tmp_path / "logs").glob("signals_*.jsonl"))
    assert names[0].endswith("_001.jsonl")
    assert names[1].endswith("_002.jsonl")


def test_compresses_old_rotated_files_into_archive(tmp_path: Path) -> None:
    archive_dir = tmp_path / "archive"
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    hot = logs_dir / "signals_2026-08-01_001.jsonl"
    hot.write_text('{"signal_id":"hot"}\n', encoding="utf-8")
    old = logs_dir / "signals_2026-07-01_001.jsonl"
    old.write_text('{"signal_id":"old"}\n', encoding="utf-8")
    hot_mtime = time() - 2 * 86_400
    old_mtime = time() - 15 * 86_400
    os.utime(hot, (hot_mtime, hot_mtime))
    os.utime(old, (old_mtime, old_mtime))
    store = JSONLStore(logs_dir, hot_days=14, archive_dir=archive_dir)

    archived = store._compress_and_archive_old_files()

    compressed = archive_dir / f"{old.name}.gz"
    assert archived == [str(compressed)]
    assert hot.exists()
    assert not old.exists()
    with gzip.open(compressed, "rt", encoding="utf-8") as fh:
        assert fh.read() == '{"signal_id":"old"}\n'


def test_cleanup_expired_archives_and_dry_run(tmp_path: Path) -> None:
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    expired = archive_dir / "signals_2025-01-01_001.jsonl.gz"
    expired.write_bytes(b"old")
    old = time() - 3 * 86_400
    os.utime(expired, (old, old))
    store = JSONLStore(tmp_path / "logs", archive_days=1, archive_dir=archive_dir)

    assert store.cleanup_expired_archives(dry_run=True) == 1
    assert expired.exists()
    assert store.cleanup_expired_archives() == 1
    assert not expired.exists()
