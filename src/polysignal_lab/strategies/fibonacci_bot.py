"""FibonacciStrategyBot — 斐波那契回撤策略 (adapter).

Decision logic, ZigZag detector and Fibonacci calculator now live in
:class:`FibonacciAlphaCore` (``polysignal_lab.alpha.fibonacci_core``). This
module keeps the legacy class name, inline config and ``name`` unchanged for
equivalence, and re-exports the helpers for existing importers.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from polysignal_lab.alpha.fibonacci_core import (
    FibonacciAlphaCore,
    FibonacciCalculator,
    ZigZagDetector,
)
from polysignal_lab.alpha.ptb_diff_core import decision_to_signal, market_view_from_snapshot
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies.base import BaseStrategy

__all__ = ["FibonacciBotConfig", "FibonacciStrategyBot", "ZigZagDetector", "FibonacciCalculator"]


class FibonacciBotConfig(BaseModel):
    """斐波那契回撤策略配置"""

    enabled: bool = True
    assets: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "HYPE"])
    timeframes: list[str] = Field(default_factory=lambda: ["5m", "15m"])

    zigzag_pct: float = 0.005
    zone_width_pct: float = 0.001
    ratios: tuple[float, ...] = (0.236, 0.382, 0.500, 0.618, 0.786)
    extension_ratios: tuple[float, ...] = (1.000, 1.272, 1.618)
    fib_size_weights: tuple[int, ...] = (1, 1, 2, 3, 5)
    max_token_price: float = 0.60
    max_notional: float = 25.0
    require_momentum_confirmation: bool = True
    momentum_window: int = 8
    min_momentum_zscore: float = 1.0
    offset_from_fib: float = 0.02


class FibonacciStrategyBot(BaseStrategy):
    """斐波那契回撤策略 (adapter over FibonacciAlphaCore)."""

    name = "fibonacci_bot"

    def __init__(self, config: FibonacciBotConfig) -> None:
        self.config = config
        self.core = FibonacciAlphaCore(config)

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        view = market_view_from_snapshot(snapshot)
        if view is None:
            return []
        return [
            decision_to_signal(decision, snapshot.snapshot_id, self.freshness_policy)
            for decision in self.core.evaluate(view)
        ]