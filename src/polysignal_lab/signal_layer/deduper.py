"""
Input: __future__, __future__.annotations, time, dataclasses, dataclasses.dataclass, dataclasses.field, threading, threading.Lock, polysignal_lab.domain.signal, polysignal_lab.domain.signal.SignalCandidate
Output: SignalDeduper
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock

from polysignal_lab.domain.signal import SignalCandidate


@dataclass
class SignalDeduper:
    ttl_sec: int = 300
    _seen: dict[str, float] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def is_duplicate(self, signal: SignalCandidate) -> bool:
        now = time.time()
        with self._lock:
            self._seen = {k: v for k, v in self._seen.items() if now - v <= self.ttl_sec}
            if signal.dedupe_key in self._seen:
                return True
            self._seen[signal.dedupe_key] = now
            return False

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return dict(self._seen)
