from __future__ import annotations

from polysignal_lab.alpha.dump_hedge_core import DumpHedgeAlphaCore
from polysignal_lab.alpha.ptb_diff_core import decision_to_signal, market_view_from_snapshot
from polysignal_lab.alpha.types import AlphaFillEvent, AlphaOrderEvent
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies.base import BaseStrategy
from polysignal_lab.strategies.config import DumpHedgeConfig
from polysignal_lab.utils import utc_now


class DumpHedgeStrategy(BaseStrategy):
    name = "dump_hedge"

    def __init__(self, config: DumpHedgeConfig):
        self.config = config
        self.core = DumpHedgeAlphaCore(config)

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        view = market_view_from_snapshot(snapshot)
        if view is None:
            return []
        return [
            decision_to_signal(decision, snapshot.snapshot_id, self.freshness_policy)
            for decision in self.core.evaluate(view)
        ]

    def notify_signal_accepted(self, signal: SignalCandidate) -> None:
        self.core.on_order_accepted(self._order_event(signal))

    def notify_signal_rejected(self, signal: SignalCandidate, rejected) -> None:
        event = self._order_event(signal)
        self.core.on_order_rejected(
            AlphaOrderEvent(
                strategy=event.strategy,
                market_id=event.market_id,
                condition_id=event.condition_id,
                token_id=event.token_id,
                side=event.side,
                order_id=event.order_id,
                client_order_id=event.client_order_id,
                reason=getattr(rejected, "reason_code", None),
                ts_event=event.ts_event,
                metrics=event.metrics,
            )
        )

    def notify_cancel(self, market_id: str, side: Side, reason: str) -> None:
        event = AlphaOrderEvent(
            strategy=self.name,
            market_id=market_id,
            condition_id="",
            token_id="",
            side=side,
            order_id=f"{self.name}:{market_id}:{side.value}",
            client_order_id=None,
            reason=reason,
            ts_event=utc_now(),
            metrics={},
        )
        if reason == "GTD_EXPIRED":
            self.core.on_order_expired(event)
        else:
            self.core.on_order_canceled(event)

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

    def notify_leg_failure(self, pair_id: str, market_id: str, side: Side) -> None:
        self.core.on_leg_failure(pair_id, market_id, side)

    def _order_event(self, signal: SignalCandidate) -> AlphaOrderEvent:
        return AlphaOrderEvent(
            strategy=self.name,
            market_id=signal.market_id,
            condition_id=signal.condition_id,
            token_id=signal.token_id,
            side=signal.side,
            order_id=signal.signal_id,
            client_order_id=None,
            reason=None,
            ts_event=signal.created_at,
            metrics={},
        )

    @property
    def _price_stats(self):
        return self.core._price_stats

    @property
    def _entered_markets(self):
        return self.core._entered_markets

    @property
    def _positions(self):
        return self.core._positions

    @property
    def _dump_detected(self):
        return self.core._dump_detected

    @property
    def _last_price(self):
        return self.core._last_price
