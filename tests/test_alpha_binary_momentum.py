from __future__ import annotations

from polysignal_lab.alpha.binary_momentum_core import BinaryMomentumAlphaCore
from polysignal_lab.alpha.types import AlphaOrderEvent
from polysignal_lab.domain.enums import Side
from polysignal_lab.strategies.config import BinaryMomentumConfig
from polysignal_lab.strategies.binary_momentum import BinaryMomentumStrategy
from alpha_equivalence import assert_legacy_core_equivalent
from factories import sample_snapshot


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
    return sample_snapshot(up_ask=0.50, down_ask=0.45, spot_price=130.0)


def _seed(core: BinaryMomentumAlphaCore, market_id: str) -> None:
    core._spot_prices.extend([100.0, 101.0, 102.0, 103.0])
    core._vwap_stats.push(f"{market_id}:{Side.UP.value}", 0.40)


def test_binary_momentum_core_matches_legacy_candidate() -> None:
    config = _momentum_config()
    snapshot = _momentum_snapshot()
    market_id = snapshot.market.market_id

    strategy = BinaryMomentumStrategy(config)
    core = BinaryMomentumAlphaCore(config)
    # Pre-seed identical MACD/RSI history on both sides so the single firing
    # evaluate (run by the harness) actually produces a candidate.
    _seed(strategy.core, market_id)
    _seed(core, market_id)

    assert_legacy_core_equivalent(strategy, core, snapshot)


def test_binary_momentum_entered_only_after_order_acceptance() -> None:
    config = _momentum_config()
    snapshot = _momentum_snapshot()
    core = BinaryMomentumAlphaCore(config)
    _seed(core, snapshot.market.market_id)

    first = core.evaluate_view_from_snapshot_for_test(snapshot)
    second = core.evaluate_view_from_snapshot_for_test(snapshot)

    assert first
    assert second  # guard NOT consumed by candidate creation

    core.on_order_accepted(
        AlphaOrderEvent(
            strategy="binary_momentum",
            market_id=first[0].market_id,
            condition_id=first[0].condition_id,
            token_id=first[0].token_id,
            side=first[0].side,
            order_id="order-1",
            client_order_id="client-1",
            reason=None,
            ts_event=first[0].metrics["created_at_for_test"],
            metrics={},
        )
    )

    assert core.evaluate_view_from_snapshot_for_test(snapshot) == []