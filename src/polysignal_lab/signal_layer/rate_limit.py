"""
Input: __future__, __future__.annotations, time, collections, collections.defaultdict, collections.deque, dataclasses, dataclasses.dataclass, dataclasses.field, threading
Output: ChannelRateLimiter
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class ChannelRateLimiter:
    max_per_hour: int
    max_per_market: int
    _global: deque[float] = field(default_factory=deque)
    _market: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    _lock: Lock = field(default_factory=Lock)

    def can_allow(self, market_ids: list[str], *, now: float) -> bool:
        cutoff = now - 3600
        with self._lock:
            global_count = sum(ts >= cutoff for ts in self._global)
            if global_count + len(market_ids) > self.max_per_hour:
                return False
            counts = {
                market_id: sum(ts >= cutoff for ts in self._market[market_id])
                for market_id in set(market_ids)
            }
            for market_id in market_ids:
                counts[market_id] += 1
                if counts[market_id] > self.max_per_market:
                    return False
            return True

    def allow(self, market_id: str, *, now: float) -> bool:
        cutoff = now - 3600
        with self._lock:
            while self._global and self._global[0] < cutoff:
                self._global.popleft()
            dq = self._market[market_id]
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(self._global) >= self.max_per_hour or len(dq) >= self.max_per_market:
                return False
            self._global.append(now)
            dq.append(now)
            return True
