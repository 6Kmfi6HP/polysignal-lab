from __future__ import annotations

import time
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

    def allow(self, market_id: str) -> bool:
        now = time.time()
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
