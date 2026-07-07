"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Callable, pytest, polysignal_lab.domain.enums, polysignal_lab.domain.enums.Side, polysignal_lab.domain.signal, polysignal_lab.domain.signal.SignalCandidate, polysignal_lab.signal_layer.arbiter
Output: candidate_factory, test_arbiter_suppresses_same_market_opposite_side_conflicts, test_arbiter_stable_sorts_by_priority_and_indexes
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from collections.abc import Callable

import pytest

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.signal_layer.arbiter import SignalArbiter


@pytest.fixture
def candidate_factory() -> Callable[..., SignalCandidate]:
    def make_candidate(
        *,
        strategy: str,
        market_id: str,
        side: Side,
    ) -> SignalCandidate:
        token_suffix = "up" if side == Side.UP else "down"
        return SignalCandidate.build(
            strategy=strategy,
            asset="BTC",
            timeframe="5m",
            market_id=market_id,
            market_slug=f"slug-{market_id}",
            condition_id=f"condition-{market_id}",
            token_id=f"{market_id}-{token_suffix}",
            side=side,
            confidence=0.75,
            entry_reference_price=0.45,
            max_entry_price=0.50,
            seconds_to_close=120,
            data_freshness_ms=10,
            reason_codes=["TEST"],
            metrics={"max_spread": 0.1},
        )

    return make_candidate


def test_arbiter_suppresses_same_market_opposite_side_conflicts(
    candidate_factory: Callable[..., SignalCandidate],
) -> None:
    up = candidate_factory(strategy="slow", market_id="m1", side=Side.UP)
    down = candidate_factory(strategy="fast", market_id="m1", side=Side.DOWN)
    arbiter = SignalArbiter(conflict_policy="suppress_ambiguous")

    result = arbiter.arbitrate(
        [up, down],
        strategy_priorities={"fast": 10, "slow": 20},
        strategy_config_indexes={"fast": 0, "slow": 1},
        market_config_indexes={"m1": 0},
    )

    assert result == []


def test_arbiter_stable_sorts_by_priority_and_indexes(
    candidate_factory: Callable[..., SignalCandidate],
) -> None:
    late = candidate_factory(strategy="late", market_id="m2", side=Side.UP)
    early = candidate_factory(strategy="early", market_id="m1", side=Side.UP)
    arbiter = SignalArbiter()

    result = arbiter.arbitrate(
        [late, early],
        strategy_priorities={"early": 10, "late": 20},
        strategy_config_indexes={"early": 1, "late": 0},
        market_config_indexes={"m1": 0, "m2": 1},
    )

    assert result == [early, late]
