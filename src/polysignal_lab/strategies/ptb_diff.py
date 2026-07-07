"""
Input: __future__, __future__.annotations, polysignal_lab.domain.freshness, polysignal_lab.domain.freshness.FreshnessPolicy, polysignal_lab.domain.signal, polysignal_lab.domain.signal.SignalCandidate, polysignal_lab.domain.snapshot, polysignal_lab.domain.snapshot.MarketSnapshot, polysignal_lab.strategies._compat, polysignal_lab.strategies._compat.decision_to_signal
Output: PTBDiffStrategy
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from polysignal_lab.domain.freshness import FreshnessPolicy
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies._compat import decision_to_signal, market_view_from_snapshot
from polysignal_lab.strategies.base import BaseStrategy
from polysignal_lab.strategies.config import PTBDiffConfig
from polysignal_lab.strategies.readiness import StrategyReadiness


class PTBDiffStrategy(BaseStrategy):
    name = "ptb_diff"

    def __init__(self, config: PTBDiffConfig):
        self.config = config
        from polysignal_lab.alpha.ptb_diff_core import PTBDiffAlphaCore
        self.core = PTBDiffAlphaCore(config)

    @property
    def freshness_policy(self) -> FreshnessPolicy:
        max_lag_ms = round(self.config.exit_config.market_data_max_lag_sec * 1000)
        return FreshnessPolicy(
            max_orderbook_staleness_ms=max_lag_ms,
            max_spot_staleness_ms=max_lag_ms,
        )

    @property
    def readiness(self) -> StrategyReadiness:
        return StrategyReadiness(
            name=self.name,
            production_enabled=bool(self.config.enabled),
            supported_assets=tuple(asset.upper() for asset in self.config.assets),
            supported_timeframes=tuple(self.config.timeframes),
            required_fields=("up_book", "down_book", "spot", "price_to_beat", "market_end_ts"),
            calibration_required=False,
            calibration_status="calibrated",
        )

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        view = market_view_from_snapshot(snapshot)
        if view is None:
            return []
        return [
            decision_to_signal(decision, snapshot.snapshot_id, self.freshness_policy)
            for decision in self.core.evaluate(view)
        ]


__all__ = ["PTBDiffStrategy"]
