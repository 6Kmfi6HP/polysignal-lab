from __future__ import annotations

from datetime import timedelta

import pytest

from polysignal_lab.config import ExitModelConfig
from polysignal_lab.domain.enums import ExitMode, Side
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import PaperTradeResult
from polysignal_lab.nautilus_runtime.position_policy import PositionPolicyActor
from polysignal_lab.utils import utc_now


def _position(side: Side = Side.UP, opened_seconds_ago: int = 30) -> PaperPosition:
    return PaperPosition(
        signal_id="sig-tp-test",
        paper_order_id="order-tp-test",
        paper_fill_id="fill-tp-test",
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="btc-5m-test",
        market_slug="btc-updown-5m-test",
        token_id="btc-5m-test-UP",
        side=side,
        entry_price=0.50,
        shares=20.0,
        stake_usdc=10.0,
        opened_at=utc_now() - timedelta(seconds=opened_seconds_ago),
    )


def _position_with_metrics(
    metrics: dict, side: Side = Side.UP, opened_seconds_ago: int = 30
) -> PaperPosition:
    pos = _position(side=side, opened_seconds_ago=opened_seconds_ago)
    pos.signal_metrics = metrics
    return pos


def _actor(
    tp_price: float = 0.90,
    sl_price: float = 0.35,
    max_hold_sec: int = 900,
) -> PositionPolicyActor:
    return PositionPolicyActor(
        ExitModelConfig(
            take_profit_enabled=True,
            stop_loss_enabled=True,
            take_profit_price=tp_price,
            stop_loss_price=sl_price,
            max_hold_time_sec=max_hold_sec,
        )
    )


def _actor_disabled() -> PositionPolicyActor:
    return PositionPolicyActor(
        ExitModelConfig(
            take_profit_enabled=False,
            stop_loss_enabled=False,
            take_profit_price=0.0,
            stop_loss_price=0.0,
            max_hold_time_sec=0,
        )
    )


def _exit_mode(result: PaperTradeResult | None) -> ExitMode | None:
    return result.exit_mode if result is not None else None


# ── Take-profit ──────────────────────────────────────────────────────────────


def test_take_profit_triggered_when_bid_above_tp_price() -> None:
    position = _position()
    actor = _actor(tp_price=0.85)
    result = actor.evaluate(position, current_bid=0.88)
    assert _exit_mode(result) == ExitMode.TAKE_PROFIT


def test_take_profit_triggered_when_bid_equals_tp_price() -> None:
    position = _position()
    actor = _actor(tp_price=0.90)
    result = actor.evaluate(position, current_bid=0.90)
    assert _exit_mode(result) == ExitMode.TAKE_PROFIT


def test_take_profit_not_triggered_when_bid_below_tp_price() -> None:
    position = _position()
    actor = _actor(tp_price=0.90)
    result = actor.evaluate(position, current_bid=0.89)
    assert _exit_mode(result) != ExitMode.TAKE_PROFIT


# ── Stop-loss ────────────────────────────────────────────────────────────────


def test_stop_loss_triggered_when_bid_below_sl_price() -> None:
    position = _position()
    actor = _actor(sl_price=0.40)
    result = actor.evaluate(position, current_bid=0.37)
    assert _exit_mode(result) == ExitMode.STOP_LOSS


def test_stop_loss_triggered_when_bid_equals_sl_price() -> None:
    position = _position()
    actor = _actor(sl_price=0.40)
    result = actor.evaluate(position, current_bid=0.40)
    assert _exit_mode(result) == ExitMode.STOP_LOSS


def test_stop_loss_not_triggered_when_bid_above_sl_price() -> None:
    position = _position()
    actor = _actor(sl_price=0.35)
    result = actor.evaluate(position, current_bid=0.36)
    assert _exit_mode(result) != ExitMode.STOP_LOSS


# ── Max hold time ────────────────────────────────────────────────────────────


def test_max_hold_time_triggered_when_position_opened_too_long() -> None:
    position = _position(opened_seconds_ago=120)
    actor = _actor(max_hold_sec=60)
    result = actor.evaluate(position, current_bid=0.55)
    assert _exit_mode(result) == ExitMode.MAX_HOLD_TIME


@pytest.mark.parametrize(
    "elapsed_sec, max_hold_sec",
    [(59, 60), (30, 60), (0, 60)],
)
def test_max_hold_time_not_triggered_before_deadline(
    elapsed_sec: int, max_hold_sec: int
) -> None:
    position = _position(opened_seconds_ago=elapsed_sec)
    actor = _actor(max_hold_sec=max_hold_sec)
    result = actor.evaluate(position, current_bid=0.55)
    assert _exit_mode(result) != ExitMode.MAX_HOLD_TIME


# ── No exit condition ────────────────────────────────────────────────────────


def test_returns_none_when_no_exit_condition_met() -> None:
    position = _position()
    actor = _actor(tp_price=0.95, sl_price=0.20)
    result = actor.evaluate(position, current_bid=0.55)
    assert result is None


def test_returns_none_when_tp_and_sl_disabled_and_hold_not_expired() -> None:
    position = _position(opened_seconds_ago=10)
    actor = _actor_disabled()
    result = actor.evaluate(position, current_bid=0.55)
    assert result is None


# ── Strategy-specific metrics preserved in alpha cores ───────────────────────


def test_signal_metrics_preserved_through_position_policy() -> None:
    metrics = {
        "tp_sl_tp_prob": 0.85,
        "flip_stop_price": 0.45,
        "flip_stop_enabled": True,
    }
    position = _position_with_metrics(metrics)
    actor = _actor(tp_price=0.90)
    result = actor.evaluate(position, current_bid=0.96)
    assert result is not None
    assert _exit_mode(result) == ExitMode.TAKE_PROFIT
    assert position.signal_metrics == metrics


def test_actor_does_not_require_signal_metrics_for_global_exits() -> None:
    position = _position()
    actor = _actor(tp_price=0.80, sl_price=0.10)
    result = actor.evaluate(position, current_bid=0.82)
    assert _exit_mode(result) == ExitMode.TAKE_PROFIT
    assert position.signal_metrics == {}
