from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class MetricsRegistry:
    counters: Counter = field(default_factory=Counter)
    gauges: dict[str, float] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def inc(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self.counters[name] += amount

    def set_gauge(self, name: str, value: float) -> None:
        with self._lock:
            self.gauges[name] = value

    def snapshot(self) -> dict:
        with self._lock:
            return {"counters": dict(self.counters), "gauges": dict(self.gauges)}
