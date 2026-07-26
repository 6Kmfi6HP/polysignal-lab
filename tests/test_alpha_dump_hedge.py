from __future__ import annotations

from datetime import UTC, datetime, timedelta

from polysignal_lab.alpha.dump_hedge_core import DumpHedgeAlphaCore
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.strategy_config import DumpHedgeConfig
from alpha_helpers import evaluate_core, with_active_order, with_open_position
from factories import sample_market_view


def test_dump_detection_uses_fixed_view_time_when_wall_clock_is_unavailable(
    monkeypatch,
) -> None:
    fixed_time = datetime(2026, 1, 1, 12, tzinfo=UTC)
    first = sample_market_view(
        up_ask=0.60,
        down_ask=0.50,
        created_at=fixed_time,
        start_ts=fixed_time - timedelta(seconds=30),
    )
    second = sample_market_view(
        up_ask=0.10,
        down_ask=0.50,
        created_at=fixed_time,
        start_ts=first.start_ts,
        end_ts=first.end_ts,
        view_id=first.view_id,
    )
    # Keep same market identity across views.
    from dataclasses import replace

    second = replace(
        second,
        market_id=first.market_id,
        market_slug=first.market_slug,
        condition_id=first.condition_id,
        up=replace(second.up, token_id=first.up.token_id),
        down=replace(second.down, token_id=first.down.token_id),
    )
    core = DumpHedgeAlphaCore(DumpHedgeConfig())

    class NoWallClockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            raise AssertionError("dump hedge must use MarketView.created_at")

    import polysignal_lab.alpha.dump_hedge_core as dump_hedge_module

    monkeypatch.setattr(
        dump_hedge_module,
        "datetime",
        NoWallClockDateTime,
        raising=False,
    )
    evaluate_core(core, first)
    decisions = evaluate_core(core, second)

    assert decisions
    assert decisions[0].reason_codes[0] == "DUMP_DETECTED"


def test_dump_candidate_generation_does_not_consume_dump_guard() -> None:
    from dataclasses import replace

    config = DumpHedgeConfig()
    core = DumpHedgeAlphaCore(config)
    first = sample_market_view(up_ask=0.60, down_ask=0.50)
    second = sample_market_view(up_ask=0.10, down_ask=0.50)
    second = replace(
        second,
        market_id=first.market_id,
        market_slug=first.market_slug,
        condition_id=first.condition_id,
        up=replace(second.up, token_id=first.up.token_id),
        down=replace(second.down, token_id=first.down.token_id),
    )
    evaluate_core(core, first)

    first_decisions = evaluate_core(core, second)
    second_decisions = evaluate_core(core, second)

    assert first_decisions
    assert second_decisions
    cached = with_active_order(second, "dump_hedge", side=first_decisions[0].side)
    assert evaluate_core(core, cached) == []


def test_dump_hedge_uses_cache_position_projection() -> None:
    config = DumpHedgeConfig()
    core = DumpHedgeAlphaCore(config)
    view = sample_market_view(up_ask=0.40, down_ask=0.50)

    assert evaluate_core(core, view) == []
    cached = with_open_position(
        view,
        "dump_hedge",
        side=Side.UP,
        avg_entry_price=0.40,
    )
    hedge = evaluate_core(core, cached)
    assert hedge
    assert hedge[0].side == Side.DOWN
    assert hedge[0].hedge_leg is True
