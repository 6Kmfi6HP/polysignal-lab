from __future__ import annotations

from polysignal_lab.alpha.mid_price_sizing_core import MidPriceSizingAlphaCore
from polysignal_lab.alpha.ptb_diff_core import decision_to_signal, market_view_from_snapshot
from polysignal_lab.alpha.types import AlphaFillEvent
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies.base import BaseStrategy
from polysignal_lab.strategies.config import MidPriceSizingConfig, SizingMode
from polysignal_lab.utils import utc_now


class MidPriceSizingStrategy(BaseStrategy):
    name = "mid_price_sizing"

    def __init__(self, config: MidPriceSizingConfig):
        self.config = config
        self.core = MidPriceSizingAlphaCore(config)

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

    def reset_position(self, market_id: str, side: Side | None = None) -> None:
        self.core.reset_position(market_id, side)

    def _pos_key(self, market_id: str, side: Side) -> str:
        return self.core._pos_key(market_id, side)

    def _avg_cost(self, key: str) -> float | None:
        return self.core._avg_cost(key)

    @property
    def _layer_count(self):
        return self.core._layer_count

    @property
    def _entry_prices(self):
        return self.core._entry_prices
