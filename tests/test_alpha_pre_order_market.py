from __future__ import annotations

from datetime import timedelta

from polysignal_lab.alpha.pre_order_market_core import PreOrderMarketAlphaCore
from polysignal_lab.alpha.types import AlphaFillEvent, AlphaOrderEvent
from polysignal_lab.domain.enums import Side
from polysignal_lab.strategies.pre_order_market import PreOrderMarketConfig, PreOrderMarketStrategy
from polysignal_lab.utils import utc_now
from alpha_equivalence import assert_legacy_core_equivalent
from factories import sample_snapshot


def _preopen_snapshot():
    now = utc_now()
    snapshot = sample_snapshot(up_ask=0.50, down_ask=0.50, seconds_to_close=300)
    return snapshot.model_copy(
        update={
            "created_at": now,
            "market": snapshot.market.model_copy(update={"start_ts": now + timedelta(seconds=120), "end_ts": now + timedelta(seconds=300)}),
        }
    )


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


def test_pre_order_core_matches_legacy_candidate() -> None:
    config = PreOrderMarketConfig()
    snapshot = _preopen_snapshot()
    assert_legacy_core_equivalent(PreOrderMarketStrategy(config), PreOrderMarketAlphaCore(config), snapshot)


def test_pre_order_candidates_repeat_until_order_submitted() -> None:
    config = PreOrderMarketConfig()
    core = PreOrderMarketAlphaCore(config)
    snapshot = _preopen_snapshot()

    first = core.evaluate_view_from_snapshot_for_test(snapshot)
    second = core.evaluate_view_from_snapshot_for_test(snapshot)

    assert len(first) == 4
    assert len(second) == 4
    assert snapshot.market.market_id not in core._pre_ordered

    core.on_order_submitted(_order(first[0]))

    assert snapshot.market.market_id in core._pre_ordered
    assert core.evaluate_view_from_snapshot_for_test(snapshot) == []


def test_pre_order_cancel_or_expire_rolls_back_pre_order_guard() -> None:
    config = PreOrderMarketConfig()
    core = PreOrderMarketAlphaCore(config)
    snapshot = _preopen_snapshot()
    decisions = core.evaluate_view_from_snapshot_for_test(snapshot)
    assert decisions

    core.on_order_submitted(_order(decisions[0]))
    core.on_order_canceled(_order(decisions[0]))
    assert len(core.evaluate_view_from_snapshot_for_test(snapshot)) == 4

    core.on_order_submitted(_order(decisions[0]))
    core.on_order_expired(_order(decisions[0]))
    assert len(core.evaluate_view_from_snapshot_for_test(snapshot)) == 4


def test_pre_order_adapter_cancel_or_expire_rolls_back_pre_order_guard() -> None:
    config = PreOrderMarketConfig()
    strategy = PreOrderMarketStrategy(config)
    snapshot = _preopen_snapshot()
    signals = strategy.evaluate(snapshot)
    assert signals

    strategy.notify_signal_accepted(signals[0])
    strategy.notify_cancel(snapshot.market.market_id, signals[0].side, "PAPER_REJECTED")
    assert len(strategy.evaluate(snapshot)) == 4

    strategy.notify_signal_accepted(signals[0])
    strategy.notify_cancel(snapshot.market.market_id, signals[0].side, "GTD_EXPIRED")
    assert len(strategy.evaluate(snapshot)) == 4


def test_pre_order_reconcile_uses_fill_event_state() -> None:
    config = PreOrderMarketConfig()
    core = PreOrderMarketAlphaCore(config)
    snapshot = _preopen_snapshot()

    assert snapshot.market.market_id not in core._positions

    core.on_order_filled(
        AlphaFillEvent(
            strategy="pre_order_market",
            market_id=snapshot.market.market_id,
            condition_id=snapshot.market.condition_id,
            token_id=snapshot.market.token_for(Side.UP).token_id,
            side=Side.UP,
            order_id="fill-1",
            client_order_id=None,
            reason=None,
            ts_event=utc_now(),
            metrics={},
            fill_price=0.45,
            shares=5.0,
            liquidity_side=None,
        )
    )

    decisions = core.evaluate_view_from_snapshot_for_test(snapshot)
    assert decisions
    assert decisions[0].side == Side.DOWN
    assert decisions[0].hedge_leg is True
