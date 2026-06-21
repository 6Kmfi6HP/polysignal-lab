from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict, deque
from statistics import mean, pstdev

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot


class BaseStrategy(ABC):
    name: str

    @abstractmethod
    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        raise NotImplementedError

    def _candidate(
        self,
        snapshot: MarketSnapshot,
        side: Side,
        confidence: float,
        max_entry_price: float,
        reason_codes: list[str],
        metrics: dict,
    ) -> SignalCandidate | None:
        ask = snapshot.ask_for(side)
        if ask is None:
            return None
        token_id = snapshot.market.token_for(side).token_id
        return SignalCandidate.build(
            strategy=self.name,
            asset=snapshot.market.asset,
            timeframe=snapshot.market.timeframe,
            market_id=snapshot.market.market_id,
            market_slug=snapshot.market.market_slug,
            condition_id=snapshot.market.condition_id,
            token_id=token_id,
            side=side,
            confidence=confidence,
            entry_reference_price=ask,
            max_entry_price=max_entry_price,
            seconds_to_close=snapshot.seconds_to_close,
            data_freshness_ms=snapshot.freshness.max_ms,
            reason_codes=reason_codes,
            metrics=metrics,
            snapshot_id=snapshot.snapshot_id,
        )


class RollingPriceStats:
    def __init__(self, window_size: int = 16):
        self.values: dict[str, deque[tuple[float, float]]] = defaultdict(lambda: deque(maxlen=window_size))

    def push(self, key: str, price: float, size: float = 1.0) -> None:
        self.values[key].append((price, max(size, 1e-9)))

    def stats(self, key: str) -> dict[str, float | None]:
        vals = list(self.values[key])
        if not vals:
            return {"vwap": None, "momentum": None, "z_score": None, "count": 0}
        total_size = sum(size for _, size in vals)
        vwap = sum(price * size for price, size in vals) / total_size if total_size else mean([p for p, _ in vals])
        momentum = vals[-1][0] - vals[0][0] if len(vals) > 1 else 0.0
        prices = [p for p, _ in vals]
        stdev = pstdev(prices) if len(prices) > 1 else 0.0
        z = (prices[-1] - mean(prices)) / stdev if stdev > 0 else 0.0
        return {"vwap": vwap, "momentum": momentum, "z_score": z, "count": len(vals)}
