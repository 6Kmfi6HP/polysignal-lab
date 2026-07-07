"""
Input: __future__, __future__.annotations, polysignal_lab.alpha.types, polysignal_lab.alpha.types.AlphaOrderEvent, polysignal_lab.domain.signal, polysignal_lab.domain.signal.SignalCandidate, polysignal_lab.domain.snapshot, polysignal_lab.domain.snapshot.MarketSnapshot, polysignal_lab.strategies._compat, polysignal_lab.strategies._compat.decision_to_signal
Output: OneCentBuyStrategy
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from polysignal_lab.alpha.types import AlphaOrderEvent
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies._compat import decision_to_signal, market_view_from_snapshot
from polysignal_lab.strategies.base import BaseStrategy
from polysignal_lab.strategies.config import OneCentBuyConfig
from polysignal_lab.strategies.readiness import StrategyReadiness
from polysignal_lab.utils import utc_now


class OneCentBuyStrategy(BaseStrategy):
    name = "one_cent_buy"

    def __init__(self, config: OneCentBuyConfig | None = None) -> None:
        self.config = config or OneCentBuyConfig()
        from polysignal_lab.alpha.one_cent_buy_core import OneCentBuyAlphaCore
        self.core = OneCentBuyAlphaCore(self.config)

    def reset(self) -> None:
        self.core.reset()

    @property
    def readiness(self) -> StrategyReadiness:
        return StrategyReadiness(
            name=self.name,
            production_enabled=bool(getattr(self.config, "enabled", True)),
            supported_assets=("BTC", "ETH", "SOL", "XRP"),
            supported_timeframes=("5m", "15m"),
            required_fields=("up_book", "down_book", "market_end_ts"),
            calibration_required=True,
            calibration_status="unknown",
        )

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        view = market_view_from_snapshot(snapshot)
        if view is None:
            return []
        return [
            decision_to_signal(decision, snapshot.snapshot_id, self.freshness_policy)
            for decision in self.core.evaluate(view)
        ]

    def notify_signal_accepted(self, signal: SignalCandidate) -> None:
        self.core.on_order_accepted(
            AlphaOrderEvent(
                strategy=self.name,
                market_id=signal.market_id,
                condition_id=signal.condition_id,
                token_id=signal.token_id,
                side=signal.side,
                order_id=signal.signal_id,
                client_order_id=None,
                reason=None,
                ts_event=utc_now(),
                metrics={"level_price": signal.metrics.get("limit_price")},
            )
        )


__all__ = ["OneCentBuyStrategy"]
