from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

from polysignal_lab.utils import to_jsonable


class JSONLStore:
    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def append(self, stream: str, record: Any) -> Path:
        if not stream.endswith(".jsonl"):
            stream = f"{stream}.jsonl"
        path = self.base_dir / stream
        with self._lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(to_jsonable(record), ensure_ascii=False, sort_keys=True) + "\n")
        return path

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
