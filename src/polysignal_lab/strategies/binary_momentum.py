"""BinaryMomentumStrategy — MACD/RSI/VWAP 二元动量策略 (adapter).

Decision logic now lives in :class:`BinaryMomentumAlphaCore`. Legacy class
name, config and ``name`` are preserved. The entered-market guard is advanced
on order acceptance, not during candidate generation.
"""

from __future__ import annotations

from dataclasses import dataclass

from polysignal_lab.alpha.binary_momentum_core import BinaryMomentumAlphaCore
from polysignal_lab.alpha.ptb_diff_core import decision_to_signal, market_view_from_snapshot
from polysignal_lab.alpha.types import AlphaOrderEvent
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies.base import BaseStrategy
from polysignal_lab.utils import utc_now


@dataclass
class BinaryMomentumConfig:
    """BinaryMomentumStrategy 配置"""

    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    rsi_period: int = 14
    rsi_upper: int = 75
    rsi_lower: int = 25
    rsi_up_min: int = 50
    rsi_down_max: int = 50
    vwap_deviation: float = 0.002
    max_token_price: float = 0.70
    max_notional: float = 25.0
    stop_loss_pct: float = 0.20
    take_profit_pct: float = 0.25


class BinaryMomentumStrategy(BaseStrategy):
    """二元动量策略 (adapter over BinaryMomentumAlphaCore)."""

    name = "binary_momentum"

    def __init__(self, config: BinaryMomentumConfig | None = None) -> None:
        self.config = config or BinaryMomentumConfig()
        self.core = BinaryMomentumAlphaCore(self.config)

    def reset(self) -> None:
        self.core.reset()

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
                metrics={},
            )
        )