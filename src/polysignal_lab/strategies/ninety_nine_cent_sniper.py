"""NinetyNineCentSniperStrategy — 99c Sniper 临近结算高概率狙击策略 (adapter).

Decision logic now lives in :class:`NinetyNineCentSniperAlphaCore`. Legacy
class name, config and ``name`` are preserved. The sniped-side guard is
advanced on order acceptance, not during candidate generation.
"""

from __future__ import annotations

from dataclasses import dataclass

from polysignal_lab.alpha.ninety_nine_cent_sniper_core import NinetyNineCentSniperAlphaCore
from polysignal_lab.alpha.ptb_diff_core import decision_to_signal, market_view_from_snapshot
from polysignal_lab.alpha.types import AlphaOrderEvent
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies.base import BaseStrategy
from polysignal_lab.strategies.readiness import StrategyReadiness
from polysignal_lab.utils import utc_now


@dataclass
class NinetyNineCentSniperConfig:
    """NinetyNineCentSniperStrategy 配置"""

    max_entry_price: float = 0.99
    min_external_probability: float = 0.995
    min_seconds_before_close: float = 0.0
    max_seconds_before_close: float = 90.0
    max_notional_per_trade: float = 25.0
    stop_price: float = 0.94
    require_effectively_settled: bool = True


class NinetyNineCentSniperStrategy(BaseStrategy):
    """临近结算高概率狙击策略 (adapter over NinetyNineCentSniperAlphaCore)."""

    name = "ninety_nine_cent_sniper"

    def __init__(self, config: NinetyNineCentSniperConfig | None = None) -> None:
        self.config = config or NinetyNineCentSniperConfig()
        self.core = NinetyNineCentSniperAlphaCore(self.config)

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
                metrics={},
            )
        )