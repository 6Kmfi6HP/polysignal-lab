"""
Input: __future__, __future__.annotations, polysignal_lab.alpha.ptb_diff_core, polysignal_lab.alpha.types, polysignal_lab.config, polysignal_lab.domain.freshness
Output: ptb_decisions_from_view, ptb_decision_from_view, ptb_signals_from_view, ptb_signal_from_view
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""


from __future__ import annotations

from polysignal_lab.alpha.ptb_diff_core import PTBDiffAlphaCore
from polysignal_lab.alpha.types import AlphaDecision, MarketView
from polysignal_lab.config import Settings
from polysignal_lab.domain.freshness import FreshnessPolicy
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import candidate_from_decision


def _ptb_freshness_policy(settings: Settings) -> FreshnessPolicy:
    lag_ms = int(settings.strategies.ptb_diff.exit_config.market_data_max_lag_sec * 1000)
    return FreshnessPolicy(
        max_orderbook_staleness_ms=lag_ms,
        max_spot_staleness_ms=lag_ms,
    )


def ptb_decisions_from_view(
    view: MarketView,
    settings: Settings,
) -> list[AlphaDecision]:
    return PTBDiffAlphaCore(settings.strategies.ptb_diff).evaluate(view)


def ptb_decision_from_view(
    view: MarketView,
    settings: Settings,
) -> AlphaDecision:
    decisions = ptb_decisions_from_view(view, settings)
    if not decisions:
        raise ValueError("ptb_diff produced no decisions")
    return decisions[0]


def ptb_signals_from_view(
    view: MarketView,
    settings: Settings,
) -> list[SignalCandidate]:
    """Publish projections only — tests that need trading intent use ptb_decisions_*."""
    freshness_policy = _ptb_freshness_policy(settings)
    return [
        candidate_from_decision(decision, view).model_copy(
            update={"freshness_policy": freshness_policy}
        )
        for decision in ptb_decisions_from_view(view, settings)
    ]


def ptb_signal_from_view(
    view: MarketView,
    settings: Settings,
) -> SignalCandidate:
    signals = ptb_signals_from_view(view, settings)
    if not signals:
        raise ValueError("ptb_diff produced no decisions")
    return signals[0]
