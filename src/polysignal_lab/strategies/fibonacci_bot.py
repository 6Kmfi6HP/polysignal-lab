"""
Input: __future__, __future__.annotations, polysignal_lab.domain.signal, polysignal_lab.domain.signal.SignalCandidate, polysignal_lab.domain.snapshot, polysignal_lab.domain.snapshot.MarketSnapshot, polysignal_lab.strategies._compat, polysignal_lab.strategies._compat.decision_to_signal, polysignal_lab.strategies._compat.market_view_from_snapshot, polysignal_lab.strategies.base
Output: FibonacciStrategyBot
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies._compat import decision_to_signal, market_view_from_snapshot
from polysignal_lab.strategies.base import BaseStrategy
from polysignal_lab.strategies.config import FibonacciBotConfig


class FibonacciStrategyBot(BaseStrategy):
    name = "fibonacci_bot"

    def __init__(self, config: FibonacciBotConfig) -> None:
        self.config = config
        from polysignal_lab.alpha.fibonacci_core import FibonacciAlphaCore
        self.core = FibonacciAlphaCore(config)

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        view = market_view_from_snapshot(snapshot)
        if view is None:
            return []
        return [
            decision_to_signal(decision, snapshot.snapshot_id, self.freshness_policy)
            for decision in self.core.evaluate(view)
        ]


__all__ = ["FibonacciStrategyBot"]
