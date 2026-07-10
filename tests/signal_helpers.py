"""Shared helpers for signal-layer tests."""

from __future__ import annotations

from polysignal_lab.alpha.legacy_snapshot_adapter import decision_to_signal, market_view_from_snapshot
from polysignal_lab.alpha.ptb_diff_core import PTBDiffAlphaCore
from polysignal_lab.config import Settings
from polysignal_lab.domain.freshness import FreshnessPolicy
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot


def _ptb_freshness_policy(settings: Settings) -> FreshnessPolicy:
    lag_ms = int(settings.strategies.ptb_diff.exit_config.market_data_max_lag_sec * 1000)
    return FreshnessPolicy(
        max_orderbook_staleness_ms=lag_ms,
        max_spot_staleness_ms=lag_ms,
    )


def ptb_signals_from_snapshot(
    snapshot: MarketSnapshot,
    settings: Settings,
) -> list[SignalCandidate]:
    core = PTBDiffAlphaCore(settings.strategies.ptb_diff)
    view = market_view_from_snapshot(snapshot)
    if view is None:
        return []
    freshness_policy = _ptb_freshness_policy(settings)
    return [
        decision_to_signal(decision, view.view_id, freshness_policy)
        for decision in core.evaluate(view)
    ]


def ptb_signal_from_snapshot(
    snapshot: MarketSnapshot,
    settings: Settings,
) -> SignalCandidate:
    signals = ptb_signals_from_snapshot(snapshot, settings)
    if not signals:
        raise ValueError("ptb_diff produced no decisions")
    return signals[0]
