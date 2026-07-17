"""
Input: __future__, __future__.annotations, datetime, datetime.UTC, datetime.datetime, datetime.timedelta, polysignal_lab.alpha.pre_order_market_core, polysignal_lab.alpha.pre_order_market_core.PreOrderMarketAlphaCore, polysignal_lab.alpha.types, polysignal_lab.alpha.types.MarketView
Output: test_pre_order_expiry_uses_fixed_view_time_when_wall_clock_is_unavailable, test_pre_order_candidates_repeat_until_order_submitted, test_pre_order_without_active_cache_order_remains_eligible, test_pre_order_reconcile_uses_cache_position_projection
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from datetime import UTC, datetime, timedelta

from polysignal_lab.alpha.pre_order_market_core import PreOrderMarketAlphaCore
from polysignal_lab.alpha.types import MarketView
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.strategy_config import PreOrderMarketConfig
from polysignal_lab.utils import utc_now
from alpha_helpers import evaluate_core, with_active_order, with_open_position
from factories import sample_market_view


def _preopen_view() -> MarketView:
    now = utc_now()
    return sample_market_view(
        up_ask=0.50,
        down_ask=0.50,
        seconds_to_close=300,
        created_at=now,
        start_ts=now + timedelta(seconds=120),
        end_ts=now + timedelta(seconds=300),
    )


def test_pre_order_expiry_uses_fixed_view_time_when_wall_clock_is_unavailable(
    monkeypatch,
) -> None:
    fixed_time = datetime(2026, 1, 1, 12, tzinfo=UTC)
    view = sample_market_view(
        up_ask=0.50,
        down_ask=0.50,
        created_at=fixed_time,
        start_ts=fixed_time + timedelta(seconds=120),
        end_ts=fixed_time + timedelta(seconds=300),
        seconds_to_close=300,
    )
    core = PreOrderMarketAlphaCore(PreOrderMarketConfig())

    class NoWallClockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            raise AssertionError("pre-order expiry must use MarketView.created_at")

    import polysignal_lab.alpha.pre_order_market_core as pre_order_module

    monkeypatch.setattr(pre_order_module, "datetime", NoWallClockDateTime)
    decisions = evaluate_core(core, view)

    assert decisions
    assert {decision.order_intent.expiry_seconds for decision in decisions} == {150}


def test_pre_order_candidates_repeat_until_order_submitted() -> None:
    config = PreOrderMarketConfig()
    core = PreOrderMarketAlphaCore(config)
    view = _preopen_view()

    first = evaluate_core(core, view)
    second = evaluate_core(core, view)

    assert len(first) == 4
    assert len(second) == 4
    cached = with_active_order(view, "pre_order_market", side=first[0].side)
    assert evaluate_core(core, cached) == []


def test_pre_order_without_active_cache_order_remains_eligible() -> None:
    config = PreOrderMarketConfig()
    core = PreOrderMarketAlphaCore(config)
    view = _preopen_view()
    decisions = evaluate_core(core, view)
    assert decisions

    assert len(evaluate_core(core, view)) == 4


def test_pre_order_reconcile_uses_cache_position_projection() -> None:
    config = PreOrderMarketConfig()
    core = PreOrderMarketAlphaCore(config)
    view = _preopen_view()

    cached = with_open_position(
        view,
        "pre_order_market",
        side=Side.UP,
        avg_entry_price=0.45,
        quantity=5.0,
    )
    decisions = evaluate_core(core, cached)
    assert decisions
    assert decisions[0].side == Side.DOWN
    assert decisions[0].hedge_leg is True
