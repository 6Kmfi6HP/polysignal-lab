"""
Input: __future__, __future__.annotations, polysignal_lab.alpha.ptb_diff_core, polysignal_lab.alpha.ptb_diff_core.decision_to_signal, polysignal_lab.alpha.ptb_diff_core.market_view_from_snapshot, polysignal_lab.alpha.skew_mean_reversion_core, polysignal_lab.alpha.skew_mean_reversion_core.SkewMeanReversionAlphaCore, polysignal_lab.domain.signal, polysignal_lab.domain.signal.SignalCandidate, polysignal_lab.domain.snapshot
Output: SkewMeanReversionStrategy
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

from polysignal_lab.alpha.ptb_diff_core import decision_to_signal, market_view_from_snapshot
from polysignal_lab.alpha.skew_mean_reversion_core import SkewMeanReversionAlphaCore
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies.base import BaseStrategy


class SkewMeanReversionStrategy(BaseStrategy):
    """Signal when one side is excessively cheap vs the other (mean reversion).

    Thin adapter over :class:`SkewMeanReversionAlphaCore`; the decision logic
    now lives in the pure core (no scheduler/Telegram/SQLite/Nautilus imports).
    """

    name = "skew_mean_reversion"

    def __init__(self, config) -> None:
        self.config = config
        self.core = SkewMeanReversionAlphaCore(config)

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        view = market_view_from_snapshot(snapshot)
        if view is None:
            return []
        return [
            decision_to_signal(decision, snapshot.snapshot_id, self.freshness_policy)
            for decision in self.core.evaluate(view)
        ]