"""VWAPMomentumStrategy — PolyBullLabs VWAP/Deviation/Momentum (adapter).

Decision logic, ``TradeHistory`` and callback state now live in
:class:`polysignal_lab.alpha.vwap_momentum_core.VWAPMomentumAlphaCore`.
Legacy class name, config, ``name``, freshness policy and readiness are
preserved. The per-market entry guard (``_can_enter``) is consumed ONLY via
``notify_signal_accepted`` → ``core.on_order_accepted``; candidate creation
reads it but does not consume it. ``follow_up_signals`` is retained as a
scheduler-facing shim that translates ``order``/``fill`` into the core's
``on_order_filled`` (taker fill → hedge decision) / ``on_order_expired``
(GTD fill → clear pending hedge) events.
"""

from __future__ import annotations

from polysignal_lab.alpha.ptb_diff_core import decision_to_signal, market_view_from_snapshot
from polysignal_lab.alpha.types import AlphaFillEvent, AlphaOrderEvent
from polysignal_lab.alpha.vwap_momentum_core import TradeHistory, VWAPMomentumAlphaCore
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.freshness import FreshnessPolicy
from polysignal_lab.domain.signal import RejectedSignal, SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies.base import BaseStrategy
from polysignal_lab.strategies.config import VWAPMomentumConfig
from polysignal_lab.strategies.readiness import StrategyReadiness
from polysignal_lab.utils import utc_now

__all__ = ["TradeHistory", "VWAPMomentumStrategy"]


class VWAPMomentumStrategy(BaseStrategy):
    """PolyBullLabs VWAP / Deviation / Momentum signal strategy (adapter)."""

    name = "vwap_momentum"

    def __init__(self, config: VWAPMomentumConfig):
        self.config = config
        self.core = VWAPMomentumAlphaCore(config)

    @property
    def freshness_policy(self) -> FreshnessPolicy:
        return FreshnessPolicy(
            max_orderbook_staleness_ms=self.config.max_orderbook_staleness_ms,
            max_spot_staleness_ms=self.config.max_spot_staleness_ms,
        )

    @property
    def readiness(self) -> StrategyReadiness:
        return StrategyReadiness(
            name=self.name,
            production_enabled=bool(self.config.enabled),
            supported_assets=tuple(asset.upper() for asset in self.config.assets),
            supported_timeframes=tuple(self.config.timeframes),
            required_fields=("up_book", "down_book", "spot", "market_end_ts"),
            calibration_required=False,
            calibration_status="calibrated",
        )

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        view = market_view_from_snapshot(snapshot)
        if view is None:
            return []
        signals = []
        for decision in self.core.evaluate(view):
            signal = decision_to_signal(decision, snapshot.snapshot_id, self.freshness_policy)
            if decision.hedge_leg:
                signal.dedupe_key = f"{signal.dedupe_key}:hedge"
            self.core.bind_signal(decision.market_id, signal.signal_id)
            signals.append(signal)
        return signals

    # ------------------------------------------------------------------
    # Callbacks — forwarded to the core
    # ------------------------------------------------------------------

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
                ts_event=signal.created_at,
                metrics={"hedge_leg": signal.hedge_leg},
            )
        )

    def notify_signal_rejected(
        self, signal: SignalCandidate, rejected: RejectedSignal
    ) -> None:
        self.core.on_order_rejected(
            AlphaOrderEvent(
                strategy=self.name,
                market_id=signal.market_id,
                condition_id=signal.condition_id,
                token_id=signal.token_id,
                side=signal.side,
                order_id=signal.signal_id,
                client_order_id=None,
                reason=rejected.reason_code,
                ts_event=signal.created_at,
                metrics={},
            )
        )

    def notify_fill(self, market_id: str, side: Side, fill_price: float, shares: float) -> None:
        self.core.on_notify_fill(market_id, side, shares)

    def notify_cancel(self, market_id: str, side: Side, reason: str) -> None:
        if reason == "GTD_EXPIRED":
            self.core.on_order_expired(
                AlphaOrderEvent(
                    strategy=self.name,
                    market_id=market_id,
                    condition_id="",
                    token_id="",
                    side=side,
                    order_id="",
                    client_order_id=None,
                    reason=reason,
                    ts_event=utc_now(),
                    metrics={},
                )
            )

    def follow_up_signals(self, order: object, fill: object) -> list[SignalCandidate]:
        if not self.config.hedge_enabled:
            return []
        order_intent = getattr(order, "order_intent", None)
        market_id = str(getattr(order, "market_id"))
        if order_intent == OrderIntent.PASSIVE_GTD.value:
            # GTD hedge filled → no reverse hedge; clear the pending hedge.
            self.core.on_order_expired(self._order_event(order, market_id))
            return []
        # Taker fill → consume the staged pending hedge, emit hedge candidate(s).
        event = AlphaFillEvent(
            strategy=self.name,
            market_id=market_id,
            condition_id=str(getattr(order, "condition_id", None) or ""),
            token_id=str(getattr(order, "token_id", None) or ""),
            side=getattr(order, "side"),
            order_id=str(getattr(order, "signal_id", None) or getattr(order, "paper_order_id", "")),
            client_order_id=None,
            reason=None,
            ts_event=utc_now(),
            fill_price=getattr(fill, "fill_price", 0.0),
            shares=float(getattr(fill, "shares", 0.0)),
            liquidity_side=None,
            metrics=self._hedge_metrics_from_order(order),
        )
        signals = []
        for decision in self.core.on_order_filled(event):
            signal = decision_to_signal(decision, None, self.freshness_policy)
            signal.dedupe_key = f"{signal.dedupe_key}:hedge"
            signals.append(signal)
        return signals

    def reset_entry_guard(self, market_id: str) -> None:
        """Re-allow entry for a market (used by tests or manual reset)."""
        self.core.reset_entry_guard(market_id)

    # ------------------------------------------------------------------
    # Helpers + forwarding properties
    # ------------------------------------------------------------------

    def _market_key(self, market_id: str, side: Side) -> str:
        return self.core._market_key(market_id, side)

    def _order_event(self, order: object, market_id: str) -> AlphaOrderEvent:
        return AlphaOrderEvent(
            strategy=self.name,
            market_id=market_id,
            condition_id=str(getattr(order, "condition_id", None) or ""),
            token_id=str(getattr(order, "token_id", None) or ""),
            side=getattr(order, "side"),
            order_id=str(getattr(order, "signal_id", None) or getattr(order, "paper_order_id", "")),
            client_order_id=None,
            reason=None,
            ts_event=utc_now(),
            metrics={},
        )

    def _hedge_metrics_from_order(self, order: object) -> dict:
        order_metrics = getattr(order, "metrics", None)
        signal_metrics = (
            order_metrics.get("signal_metrics") if isinstance(order_metrics, dict) else None
        ) or {}
        return {
            "opposite_token_id": signal_metrics.get("opposite_token_id"),
            "condition_id": signal_metrics.get("condition_id"),
            "seconds_to_close": signal_metrics.get("seconds_to_close"),
            "asset": str(getattr(order, "asset", "")),
            "timeframe": str(getattr(order, "timeframe", "")),
            "market_slug": str(getattr(order, "market_slug", "")),
            "signal_confidence": getattr(order, "signal_confidence", None),
        }

    @property
    def trades(self) -> TradeHistory:
        return self.core.trades

    @property
    def _can_enter(self):
        return self.core._can_enter

    @property
    def _pending_hedges(self):
        return self.core._pending_hedges
