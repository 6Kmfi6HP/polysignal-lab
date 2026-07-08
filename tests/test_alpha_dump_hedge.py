"""
Input: __future__, __future__.annotations, polysignal_lab.alpha.dump_hedge_core, polysignal_lab.alpha.dump_hedge_core.DumpHedgeAlphaCore, polysignal_lab.alpha.types, polysignal_lab.alpha.types.AlphaFillEvent, polysignal_lab.alpha.types.AlphaOrderEvent, polysignal_lab.domain.enums, polysignal_lab.domain.enums.Side
Output: test_dump_candidate_generation_does_not_consume_dump_guard, test_dump_hedge_uses_fill_event_for_position_state
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from polysignal_lab.alpha.dump_hedge_core import DumpHedgeAlphaCore
from polysignal_lab.alpha.types import AlphaFillEvent, AlphaOrderEvent
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.strategy_config import DumpHedgeConfig
from polysignal_lab.utils import utc_now
from alpha_helpers import evaluate_core_from_snapshot
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


def test_dump_candidate_generation_does_not_consume_dump_guard() -> None:
    config = DumpHedgeConfig()
    core = DumpHedgeAlphaCore(config)
    first = sample_snapshot(up_ask=0.60, down_ask=0.50)
    second = sample_snapshot(up_ask=0.10, down_ask=0.50)
    second = second.model_copy(update={"market": first.market})
    evaluate_core_from_snapshot(core, first)

    first_decisions = evaluate_core_from_snapshot(core, second)
    second_decisions = evaluate_core_from_snapshot(core, second)

    assert first_decisions
    assert second_decisions
    assert first.market.market_id not in core._dump_detected

    core.on_order_accepted(_order(first_decisions[0]))

    assert first.market.market_id in core._dump_detected
    assert evaluate_core_from_snapshot(core, second) == []


def test_dump_hedge_uses_fill_event_for_position_state() -> None:
    config = DumpHedgeConfig()
    core = DumpHedgeAlphaCore(config)
    snapshot = sample_snapshot(up_ask=0.40, down_ask=0.50)

    assert snapshot.market.market_id not in core._positions
    assert evaluate_core_from_snapshot(core, snapshot) == []

    core.on_order_filled(_fill(snapshot, Side.UP, 0.40))

    hedge = evaluate_core_from_snapshot(core, snapshot)
    assert hedge
    assert hedge[0].side == Side.DOWN
    assert hedge[0].hedge_leg is True
