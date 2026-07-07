"""
Input: __future__, __future__.annotations, polysignal_lab.domain.signal, polysignal_lab.domain.signal.SignalCandidate, polysignal_lab.domain.snapshot, polysignal_lab.domain.snapshot.MarketSnapshot, polysignal_lab.strategies._compat, polysignal_lab.strategies._compat.decision_to_signal, polysignal_lab.strategies._compat.market_view_from_snapshot, polysignal_lab.strategies.base
Output: SkewMeanReversionStrategy
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies._compat import decision_to_signal, market_view_from_snapshot
from polysignal_lab.strategies.base import BaseStrategy


class SkewMeanReversionStrategy(BaseStrategy):
    name = "skew_mean_reversion"

    def __init__(self, config) -> None:
        self.config = config
        from polysignal_lab.alpha.skew_mean_reversion_core import SkewMeanReversionAlphaCore
        self.core = SkewMeanReversionAlphaCore(config)

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        view = market_view_from_snapshot(snapshot)
        if view is None:
            return []
        return [
            decision_to_signal(decision, snapshot.snapshot_id, self.freshness_policy)
            for decision in self.core.evaluate(view)
        ]


__all__ = ["SkewMeanReversionStrategy"]
