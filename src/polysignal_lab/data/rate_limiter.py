"""
Input: __future__, __future__.annotations, asyncio, time
Output: AsyncRateLimiter
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""









from __future__ import annotations

import asyncio
import time


class AsyncRateLimiter:
    def __init__(self, rate_per_sec: float):
        self.rate_per_sec = max(rate_per_sec, 0.1)
        self.min_interval = 1.0 / self.rate_per_sec
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = self.min_interval - (now - self._last)
            if delay > 0:
                await asyncio.sleep(delay)
            self._last = time.monotonic()
