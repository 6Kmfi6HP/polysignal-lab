from __future__ import annotations

from polysignal_lab.alpha.low_side_dual_reversion_core import LowSideDualReversionAlphaCore
from polysignal_lab.alpha.types import AlphaFillEvent
from polysignal_lab.domain.enums import Side
from polysignal_lab.strategies.low_side_dual_reversion import LowSideDualReversionConfig, LowSideDualReversionStrategy
from polysignal_lab.utils import utc_now
from alpha_equivalence import assert_legacy_core_equivalent
from factories import sample_snapshot
from polysignal_lab.domain.orderbook import BookLevel


def _fill(snapshot, side: Side, price: float) -> AlphaFillEvent:
    return AlphaFillEvent(
        strategy="low_side_dual_reversion",
        market_id=snapshot.market.market_id,
        condition_id=snapshot.market.condition_id,
        token_id=snapshot.market.token_for(side).token_id,
        side=side,
        order_id=f"low_side_dual_reversion:{snapshot.market.market_id}:{side.value}",
        client_order_id=None,
        reason=None,
        ts_event=utc_now(),
        metrics={},
        fill_price=price,
        shares=5.0,
        liquidity_side=None,
    )



def _snapshot_with_down_asks(asks: list[BookLevel]):
    snapshot = sample_snapshot(up_ask=0.50, down_ask=asks[0].price, seconds_to_close=120)
    return snapshot.model_copy(
        update={
            "down_book": snapshot.down_book.model_copy(update={"asks": asks}),
        }
    )

def test_low_side_dual_core_matches_legacy_candidate() -> None:
    config = LowSideDualReversionConfig()
    snapshot = sample_snapshot(up_ask=0.50, down_ask=0.50, seconds_to_close=120)
    assert_legacy_core_equivalent(LowSideDualReversionStrategy(config), LowSideDualReversionAlphaCore(config), snapshot)


def test_hedge_decisions_use_actual_fill_position_state() -> None:
    config = LowSideDualReversionConfig()
    core = LowSideDualReversionAlphaCore(config)
    snapshot = sample_snapshot(up_ask=0.50, down_ask=0.50, seconds_to_close=120)

    initial = core.evaluate_view_from_snapshot_for_test(snapshot)
    assert initial
    assert {decision.hedge_leg for decision in initial} == {False}
    assert snapshot.market.market_id not in core._positions

    repeat = core.evaluate_view_from_snapshot_for_test(snapshot)
    assert repeat
    assert {decision.hedge_leg for decision in repeat} == {False}

    core.on_order_filled(_fill(snapshot, Side.UP, 0.35))

    hedge = core.evaluate_view_from_snapshot_for_test(snapshot)
    assert hedge
    assert hedge[0].side == Side.DOWN
    assert hedge[0].hedge_leg is True


def test_hedge_uses_depth_weighted_ask_and_rejects_shallow_depth() -> None:
    config = LowSideDualReversionConfig()
    shallow = _snapshot_with_down_asks([BookLevel(price=0.50, size=1)])
    core = LowSideDualReversionAlphaCore(config)
    core.on_order_filled(_fill(shallow, Side.UP, 0.35))

    assert core.evaluate_view_from_snapshot_for_test(shallow) == []

    deep = _snapshot_with_down_asks([BookLevel(price=0.50, size=1), BookLevel(price=0.60, size=4)])
    core = LowSideDualReversionAlphaCore(config)
    core.on_order_filled(_fill(deep, Side.UP, 0.35))
    hedge = core.evaluate_view_from_snapshot_for_test(deep)

    assert hedge
    assert hedge[0].side == Side.DOWN
    assert hedge[0].max_entry_price == 0.58
