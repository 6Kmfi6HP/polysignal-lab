"""LateConsensusStrategy — Meridian Late Entry V3 (adapter).

Decision logic and callback state now live in
:class:`polysignal_lab.alpha.late_consensus_core.LateConsensusAlphaCore`.
Legacy class name, config, ``name``, freshness policy and readiness are
preserved. The ``entry_sequence`` counter advances ONLY via
``notify_signal_accepted`` → ``core.on_order_accepted``; candidate creation
reads it (for ``metrics["entry_sequence"]``) but does not increment it. The
dedupe suffix ``:{sequence}`` is a candidate concern applied here, after
``decision_to_signal``, from the decision's ``metrics["entry_sequence"]``.
"""

from __future__ import annotations

from polysignal_lab.alpha.late_consensus_core import LateConsensusAlphaCore
from polysignal_lab.alpha.ptb_diff_core import decision_to_signal, market_view_from_snapshot
from polysignal_lab.alpha.types import AlphaOrderEvent
from polysignal_lab.domain.freshness import FreshnessPolicy
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
from polysignal_lab.strategies.base import BaseStrategy
from polysignal_lab.strategies.config import LateConsensusConfig
from polysignal_lab.strategies.readiness import StrategyReadiness


class LateConsensusStrategy(BaseStrategy):
    """Meridian Late Entry V3 strategy — exact 8-step entry flow (adapter)."""

    name = "late_consensus"

    def __init__(self, config: LateConsensusConfig):
        self.config = config
        self.core = LateConsensusAlphaCore(config)

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
            production_enabled=self.config.enabled,
            supported_assets=tuple(self.config.assets),
            supported_timeframes=tuple(self.config.timeframes),
            required_fields=("up_book", "down_book", "market_end_ts"),
            calibration_required=False,
            calibration_status="calibrated",
        )

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        view = market_view_from_snapshot(snapshot)
        if view is None:
            return []
        signals = [
            decision_to_signal(decision, snapshot.snapshot_id, self.freshness_policy)
            for decision in self.core.evaluate(view)
        ]
        for signal in signals:
            sequence = signal.metrics.get("entry_sequence", 0)
            signal.dedupe_key = f"{signal.dedupe_key}:{sequence}"
        return signals

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
                metrics={},
            )
        )

    # ------------------------------------------------------------------
    # Forwarding properties — existing tests read/write callback state via the
    # strategy object; the state now lives on the core.
    # ------------------------------------------------------------------

    @property
    def _last_favorite(self):
        return self.core._last_favorite

    @property
    def _last_entry_at(self):
        return self.core._last_entry_at

    @property
    def _accepted_counts(self):
        return self.core._accepted_counts
