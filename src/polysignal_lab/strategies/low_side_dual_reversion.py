"""
Input: __future__, __future__.annotations, polysignal_lab.alpha.low_side_dual_reversion_core, polysignal_lab.alpha.low_side_dual_reversion_core.LowSideDualReversionAlphaCore, polysignal_lab.alpha.ptb_diff_core, polysignal_lab.alpha.ptb_diff_core.decision_to_signal, polysignal_lab.alpha.ptb_diff_core.market_view_from_snapshot, polysignal_lab.alpha.types, polysignal_lab.alpha.types.AlphaFillEvent, polysignal_lab.domain.enums
Output: LowSideDualReversionStrategy
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

from polysignal_lab.alpha.low_side_dual_reversion_core import LowSideDualReversionAlphaCore
from polysignal_lab.alpha.ptb_diff_core import decision_to_signal, market_view_from_snapshot
from polysignal_lab.alpha.types import AlphaFillEvent
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies.base import BaseStrategy
from polysignal_lab.strategies.config import LowSideDualReversionConfig
from polysignal_lab.utils import utc_now


class LowSideDualReversionStrategy(BaseStrategy):
    name = "low_side_dual_reversion"

    def __init__(self, config: LowSideDualReversionConfig):
        self.config = config
        self.core = LowSideDualReversionAlphaCore(config)

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        view = market_view_from_snapshot(snapshot)
        if view is None:
            return []
        return [
            decision_to_signal(decision, snapshot.snapshot_id, self.freshness_policy)
            for decision in self.core.evaluate(view)
        ]

    def notify_fill(self, market_id: str, side: Side, fill_price: float, shares: float) -> None:
        self.core.on_order_filled(
            AlphaFillEvent(
                strategy=self.name,
                market_id=market_id,
                condition_id="",
                token_id="",
                side=side,
                order_id=f"{self.name}:{market_id}:{side.value}",
                client_order_id=None,
                reason=None,
                ts_event=utc_now(),
                metrics={},
                fill_price=fill_price,
                shares=shares,
                liquidity_side=None,
            )
        )

    @property
    def _entered_markets(self):
        return self.core._entered_markets

    @property
    def _positions(self):
        return self.core._positions
