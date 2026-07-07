"""
Input: __future__, __future__.annotations, polysignal_lab.alpha.dump_hedge_core, polysignal_lab.alpha.dump_hedge_core.DumpHedgeAlphaCore, polysignal_lab.alpha.types, polysignal_lab.alpha.types.AlphaFillEvent, polysignal_lab.alpha.types.AlphaOrderEvent, polysignal_lab.domain.enums, polysignal_lab.domain.enums.Side, polysignal_lab.strategies.dump_hedge
Output: test_dump_hedge_core_matches_legacy_candidate, test_dump_candidate_generation_does_not_consume_dump_guard, test_dump_hedge_adapter_cancel_rolls_back_dump_guard, test_dump_hedge_uses_fill_event_for_position_state
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

from polysignal_lab.alpha.dump_hedge_core import DumpHedgeAlphaCore
from polysignal_lab.alpha.types import AlphaFillEvent, AlphaOrderEvent
from polysignal_lab.domain.enums import Side
from polysignal_lab.strategies.dump_hedge import DumpHedgeConfig, DumpHedgeStrategy
from polysignal_lab.utils import utc_now
from alpha_equivalence import assert_legacy_core_equivalent
from factories import sample_snapshot


def _order(decision, *, order_id: str = "order-1") -> AlphaOrderEvent:
    return AlphaOrderEvent(
        strategy=decision.strategy,
        market_id=decision.market_id,
        condition_id=decision.condition_id,
        token_id=decision.token_id,
        side=decision.side,
        order_id=order_id,
        client_order_id=None,
        reason=None,
        ts_event=utc_now(),
        metrics={},
    )


def _fill(snapshot, side: Side, price: float) -> AlphaFillEvent:
    return AlphaFillEvent(
        strategy="dump_hedge",
        market_id=snapshot.market.market_id,
        condition_id=snapshot.market.condition_id,
        token_id=snapshot.market.token_for(side).token_id,
        side=side,
        order_id=f"dump_hedge:{snapshot.market.market_id}:{side.value}",
        client_order_id=None,
        reason=None,
        ts_event=utc_now(),
        metrics={},
        fill_price=price,
        shares=10.0,
        liquidity_side=None,
    )


def test_dump_hedge_core_matches_legacy_candidate() -> None:
    config = DumpHedgeConfig()
    first = sample_snapshot(up_ask=0.60, down_ask=0.50)
    second = sample_snapshot(up_ask=0.40, down_ask=0.50)
    second = second.model_copy(update={"market": first.market})
    strategy = DumpHedgeStrategy(config)
    core = DumpHedgeAlphaCore(config)
    strategy.evaluate(first)
    core.evaluate_view_from_snapshot_for_test(first)

    assert_legacy_core_equivalent(strategy, core, second)


def test_dump_candidate_generation_does_not_consume_dump_guard() -> None:
    config = DumpHedgeConfig()
    core = DumpHedgeAlphaCore(config)
    first = sample_snapshot(up_ask=0.60, down_ask=0.50)
    second = sample_snapshot(up_ask=0.10, down_ask=0.50)
    second = second.model_copy(update={"market": first.market})
    core.evaluate_view_from_snapshot_for_test(first)

    first_decisions = core.evaluate_view_from_snapshot_for_test(second)
    second_decisions = core.evaluate_view_from_snapshot_for_test(second)

    assert first_decisions
    assert second_decisions
    assert first.market.market_id not in core._dump_detected

    core.on_order_accepted(_order(first_decisions[0]))

    assert first.market.market_id in core._dump_detected
    assert core.evaluate_view_from_snapshot_for_test(second) == []



def test_dump_hedge_adapter_cancel_rolls_back_dump_guard() -> None:
    config = DumpHedgeConfig()
    first = sample_snapshot(up_ask=0.60, down_ask=0.50)
    second = sample_snapshot(up_ask=0.10, down_ask=0.50)
    second = second.model_copy(update={"market": first.market})
    strategy = DumpHedgeStrategy(config)
    strategy.evaluate(first)
    signals = strategy.evaluate(second)
    assert signals

    strategy.notify_signal_accepted(signals[0])
    strategy.notify_cancel(first.market.market_id, signals[0].side, "PAPER_REJECTED")

    assert strategy.evaluate(second)

def test_dump_hedge_uses_fill_event_for_position_state() -> None:
    config = DumpHedgeConfig()
    core = DumpHedgeAlphaCore(config)
    snapshot = sample_snapshot(up_ask=0.40, down_ask=0.50)

    assert snapshot.market.market_id not in core._positions
    assert core.evaluate_view_from_snapshot_for_test(snapshot) == []

    core.on_order_filled(_fill(snapshot, Side.UP, 0.40))

    hedge = core.evaluate_view_from_snapshot_for_test(snapshot)
    assert hedge
    assert hedge[0].side == Side.DOWN
    assert hedge[0].hedge_leg is True
