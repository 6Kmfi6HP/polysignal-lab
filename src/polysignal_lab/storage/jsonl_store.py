from __future__ import annotations

import gzip
import json
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from polysignal_lab.utils import to_jsonable


class JSONLStore:
    def __init__(
        self,
        base_dir: str | Path,
        max_file_bytes: int = 100_000_000,
        hot_days: int = 14,
        archive_days: int = 365,
        archive_dir: str | Path = "archive",
        *,
        create_base_dir: bool = True,
    ) -> None:
        self.base_dir = Path(base_dir)
        if create_base_dir:
            self.base_dir.mkdir(parents=True, exist_ok=True)
        self.max_file_bytes = max_file_bytes
        self.hot_days = hot_days
        self.archive_days = archive_days
        self.archive_dir = Path(archive_dir)
        self._lock = Lock()

    def append(self, stream: str, record: Any) -> Path:
        if not stream.endswith(".jsonl"):
            stream = f"{stream}.jsonl"
        path = self.base_dir / stream
        with self._lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(to_jsonable(record), ensure_ascii=False, sort_keys=True)
                    + "\n"
                )
            if path.stat().st_size > self.max_file_bytes:
                self._rotate(stream)
        return path

    def _rotate(self, stream: str) -> Path:
        if not stream.endswith(".jsonl"):
            stream = f"{stream}.jsonl"
        active_path = self.base_dir / stream
        stem = Path(stream).stem
        date = datetime.now(UTC).date().isoformat()
        existing = sorted(self.base_dir.glob(f"{stem}_{date}_*.jsonl"))
        sequences = [
            int(match.group(1))
            for path in existing
            if (match := re.search(r"_(\d+)\.jsonl$", path.name))
        ]
        sequence = max(sequences, default=0) + 1
        rotated_path = self.base_dir / f"{stem}_{date}_{sequence:03d}.jsonl"
        active_path.replace(rotated_path)
        active_path.touch()
        return active_path

    def _compress_and_archive_old_files(
        self,
        *,
        dry_run: bool = False,
    ) -> list[str]:
        cutoff = datetime.now(UTC).timestamp() - 86_400
        rotated_pattern = re.compile(r".+_\d{4}-\d{2}-\d{2}_\d{3}\.jsonl$")
        candidates = [
            path
            for path in self.base_dir.glob("*.jsonl")
            if rotated_pattern.fullmatch(path.name) and path.stat().st_mtime < cutoff
        ]
        archived: list[str] = []
        for path in sorted(candidates):
            destination = self.archive_dir / f"{path.name}.gz"
            archived.append(str(destination))
            if dry_run:
                continue
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            temporary_path = Path(f"{destination}.tmp")
            stat = path.stat()
            try:
                with path.open("rb") as source, gzip.open(
                    temporary_path, "wb"
                ) as target:
                    shutil.copyfileobj(source, target)
                temporary_path.replace(destination)
                os.utime(destination, (stat.st_atime, stat.st_mtime))
                path.unlink()
            finally:
                temporary_path.unlink(missing_ok=True)
        return archived

    def cleanup_expired_archives(self, *, dry_run: bool = False) -> int:
        if not self.archive_dir.exists():
            return 0
        cutoff = datetime.now(UTC).timestamp() - self.archive_days * 86_400
        expired = [
            path
            for path in self.archive_dir.glob("*.jsonl.gz")
            if path.stat().st_mtime < cutoff
        ]
        if not dry_run:
            for path in expired:
                path.unlink()
        return len(expired)

    def read_all(self, stream: str) -> list[dict[str, Any]]:
        if not stream.endswith(".jsonl"):
            stream = f"{stream}.jsonl"
        path = self.base_dir / stream
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    out.append(json.loads(line))
        return out
