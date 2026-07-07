"""
Input: __future__, __future__.annotations, json, os, pathlib, pathlib.Path, typing, typing.Any, polysignal_lab.utils, polysignal_lab.utils.to_jsonable
Output: StateStore
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from polysignal_lab.utils import to_jsonable


class StateStore:
    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def write(self, name: str, value: Any) -> Path:
        if not name.endswith(".json"):
            name = f"{name}.json"
        path = self.base_dir / name
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(to_jsonable(value), fh, ensure_ascii=False, sort_keys=True, indent=2)
        os.replace(tmp, path)
        return path

    def read(self, name: str, default: Any = None) -> Any:
        if not name.endswith(".json"):
            name = f"{name}.json"
        path = self.base_dir / name
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
