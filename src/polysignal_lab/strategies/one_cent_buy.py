"""OneCentBuyStrategy — 1c Buy 极端低价被动限价捕捉策略 (adapter).

Decision logic now lives in :class:`OneCentBuyAlphaCore`. Legacy class name,
config and ``name`` are preserved for equivalence. The submitted-level guard is
advanced on order acceptance (``notify_signal_accepted``), not during
candidate generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from polysignal_lab.alpha.one_cent_buy_core import OneCentBuyAlphaCore
from polysignal_lab.alpha.ptb_diff_core import decision_to_signal, market_view_from_snapshot
from polysignal_lab.alpha.types import AlphaOrderEvent
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies.base import BaseStrategy
from polysignal_lab.strategies.readiness import StrategyReadiness
from polysignal_lab.utils import utc_now


@dataclass
class OneCentBuyConfig:
    """OneCentBuyStrategy 配置"""

    entry_prices: tuple[float, ...] = (0.01, 0.02, 0.03)
    shares_per_level: int = 10
    cancel_before_close_seconds: float = 20.0
    min_seconds_after_open: float = 0.0
    max_seconds_after_open: float = 280.0
    take_profit_ladder: list[tuple[float, float]] = field(
        default_factory=lambda: [(0.10, 0.50), (0.15, 1.00)]
    )


class OneCentBuyStrategy(BaseStrategy):
    """极端低价被动限价捕捉策略 (adapter over OneCentBuyAlphaCore)."""

    name = "one_cent_buy"

    def __init__(self, config: OneCentBuyConfig | None = None) -> None:
        self.config = config or OneCentBuyConfig()
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