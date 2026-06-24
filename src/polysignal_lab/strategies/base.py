from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict, deque
from statistics import mean, pstdev

from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.freshness import FreshnessPolicy
from polysignal_lab.domain.signal import RejectedSignal, SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies.readiness import StrategyReadiness


class BaseStrategy(ABC):
    name: str

    @property
    def freshness_policy(self) -> FreshnessPolicy | None:
        return None

    @property
    def readiness(self) -> StrategyReadiness:
        return StrategyReadiness(
            name=self.name,
            production_enabled=True,
            supported_assets=tuple(getattr(self.config, "assets", ("BTC", "ETH", "SOL", "XRP"))),
            supported_timeframes=tuple(getattr(self.config, "timeframes", ("5m", "15m"))),
            required_fields=("up_book", "down_book"),
            calibration_required=False,
            calibration_status="calibrated",
        )

    @abstractmethod
    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        raise NotImplementedError

    def notify_signal_accepted(self, signal: SignalCandidate) -> None:
        pass

    def notify_signal_rejected(
        self, signal: SignalCandidate, rejected: RejectedSignal
    ) -> None:
        pass

    def _candidate(
        self,
        snapshot: MarketSnapshot,
        side: Side,
        confidence: float,
        max_entry_price: float,
        reason_codes: list[str],
        metrics: dict,
        *,
        order_intent: OrderIntent | None = None,
        expiry_seconds: int | None = None,
        pair_id: str | None = None,
        hedge_leg: bool = False,
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
            freshness_policy=self.freshness_policy,
            reason_codes=reason_codes,
            metrics=metrics,
            snapshot_id=snapshot.snapshot_id,
            order_intent=order_intent,
            expiry_seconds=expiry_seconds,
            pair_id=pair_id,
            hedge_leg=hedge_leg,
        )

    def notify_fill(self, market_id: str, side: Side, fill_price: float, shares: float) -> None:
        pass

    def notify_cancel(self, market_id: str, side: Side, reason: str) -> None:
        pass

    def notify_leg_failure(self, pair_id: str, market_id: str, side: Side) -> None:
        pass

    def follow_up_signals(self, order: object, fill: object) -> list[SignalCandidate]:
        return []


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
