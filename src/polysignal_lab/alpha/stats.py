"""
Input: __future__, __future__.annotations, collections, collections.defaultdict, collections.deque, statistics, statistics.mean, statistics.pstdev, typing, typing.TypedDict
Output: RollingStatsResult, RollingPriceStats
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from collections import defaultdict, deque
from statistics import mean, pstdev
from typing import TypedDict


class RollingStatsResult(TypedDict):
    vwap: float | None
    momentum: float | None
    z_score: float | None
    count: int


class RollingPriceStats:
    def __init__(self, window_size: int = 16) -> None:
        self.values: dict[str, deque[tuple[float, float]]] = defaultdict(
            lambda: deque(maxlen=window_size)
        )

    def push(self, key: str, price: float, size: float = 1.0) -> None:
        self.values[key].append((price, max(size, 1e-9)))

    def stats(self, key: str) -> RollingStatsResult:
        vals = list(self.values[key])
        if not vals:
            return {"vwap": None, "momentum": None, "z_score": None, "count": 0}

        prices = [price for price, _ in vals]
        total_size = sum(size for _, size in vals)
        vwap = (
            sum(price * size for price, size in vals) / total_size
            if total_size
            else mean(prices)
        )
        momentum = vals[-1][0] - vals[0][0] if len(vals) > 1 else 0.0
        stdev = pstdev(prices) if len(prices) > 1 else 0.0
        z_score = (prices[-1] - mean(prices)) / stdev if stdev > 0 else 0.0
        return {
            "vwap": vwap,
            "momentum": momentum,
            "z_score": z_score,
            "count": len(vals),
        }


_RollingPriceStats = RollingPriceStats
