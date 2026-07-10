"""Shared helpers for alpha-core tests."""

from __future__ import annotations

from polysignal_lab.alpha.legacy_snapshot_adapter import market_view_from_snapshot
from polysignal_lab.alpha.types import AlphaCore, AlphaDecision
from polysignal_lab.domain.snapshot import MarketSnapshot


def evaluate_core_from_snapshot(
    core: AlphaCore,
    snapshot: MarketSnapshot,
) -> list[AlphaDecision]:
    view = market_view_from_snapshot(snapshot)
    return [] if view is None else list(core.evaluate(view))
