"""
Input: __future__, __future__.annotations, polysignal_lab.alpha.binary_momentum_core, polysignal_lab.alpha.binary_momentum_core.BinaryMomentumAlphaCore, polysignal_lab.alpha.types, polysignal_lab.alpha.types.AlphaOrderEvent, polysignal_lab.domain.enums, polysignal_lab.domain.enums.Side, polysignal_lab.domain.strategy_config, polysignal_lab.domain.strategy_config.BinaryMomentumConfig
Output: test_binary_momentum_core_matches_legacy_candidate, test_binary_momentum_entered_only_after_order_acceptance
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from polysignal_lab.alpha.binary_momentum_core import BinaryMomentumAlphaCore
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.strategy_config import BinaryMomentumConfig
from alpha_helpers import evaluate_core, with_active_order
from factories import sample_market_view


def _momentum_config() -> BinaryMomentumConfig:
    # Short lookbacks so a handful of seeded spot prices can produce a MACD/RSI
    # signal. spot_price=130 keeps the histogram positive even after a duplicate
    # sample is appended on the second evaluate (mutation-timing robustness).
    return BinaryMomentumConfig(
        macd_fast=2,
        macd_slow=3,
        macd_signal=2,
        rsi_period=2,
        rsi_upper=100,
        vwap_deviation=0.0,
    )


def _momentum_snapshot():
    return sample_market_view(up_ask=0.50, down_ask=0.45, spot_price=130.0)


def _seed(core: BinaryMomentumAlphaCore, market_id: str) -> None:
    core._spot_prices.extend([100.0, 101.0, 102.0, 103.0])
    core._vwap_stats.push(f"{market_id}:{Side.UP.value}", 0.40)


def test_binary_momentum_entered_only_after_order_acceptance() -> None:
    config = _momentum_config()
    snapshot = _momentum_snapshot()
    core = BinaryMomentumAlphaCore(config)
    _seed(core, snapshot.market_id)

    first = evaluate_core(core, snapshot)
    second = evaluate_core(core, snapshot)

    assert first
    assert second  # guard NOT consumed by candidate creation

    cached = with_active_order(snapshot, "binary_momentum", side=first[0].side)
    assert evaluate_core(core, cached) == []
