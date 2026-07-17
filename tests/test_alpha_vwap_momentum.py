"""
Input: __future__, __future__.annotations, dataclasses, dataclasses.replace, datetime, datetime.timedelta, polysignal_lab.alpha.state, polysignal_lab.alpha.state.restore_utc_datetime, polysignal_lab.alpha.types, polysignal_lab.alpha.types.TradeView
Output: test_vwap_entry_guard_not_consumed_until_acceptance, test_vwap_core_accepts_trade_view_events, test_vwap_core_skips_entry_when_favorite_ask_missing, test_vwap_cache_position_creates_hedge_decision, test_vwap_active_hedge_order_prevents_reverse_hedge, test_vwap_evaluate_requires_projected_trades, test_vwap_core_state_roundtrip_is_empty, test_vwap_duplicate_trade_view_payload_is_stateless, test_vwap_state_round_trip_excludes_trading_state
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from polysignal_lab.alpha.state import restore_utc_datetime
from polysignal_lab.alpha.types import TradeView
from polysignal_lab.alpha.vwap_momentum_core import VWAPMomentumAlphaCore
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.strategy_config import VWAPMomentumConfig
from alpha_helpers import evaluate_core, with_active_order, with_open_position
from factories import sample_market_view


def _fast_config(**updates) -> VWAPMomentumConfig:
    base = dict(
        min_price=0.35,
        max_price=0.85,
        momentum_window_sec=5,
        min_deviation_pct=0.0,
        max_deviation_pct=1.0,
        min_momentum=0.001,
        min_elapsed_sec=0,
        no_entry_before_end_sec=0,
        max_spread=0.03,
        max_orderbook_staleness_ms=60_000,
    )
    base.update(updates)
    return VWAPMomentumConfig(**base)


def _snapshot_with_trades():
    """MarketView whose trades come only from Cache-style TradeView projection."""
    base = sample_market_view(up_ask=0.60, down_ask=0.40, seconds_to_close=120)
    now = base.created_at
    band_ts = now - timedelta(seconds=5)
    return replace(
        base,
        up_trades=(
            TradeView(price=0.50, size=1.0, side=Side.UP.value, ts=band_ts),
            TradeView(price=0.60, size=1.0, side=Side.UP.value, ts=now),
        ),
        down_trades=(
            TradeView(price=0.40, size=1.0, side=Side.DOWN.value, ts=band_ts),
            TradeView(price=0.40, size=1.0, side=Side.DOWN.value, ts=now),
        ),
    )


def test_vwap_entry_guard_not_consumed_until_acceptance() -> None:
    config = _fast_config()
    core = VWAPMomentumAlphaCore(config)
    snapshot = _snapshot_with_trades()

    first = evaluate_core(core, snapshot)
    assert len(first) == 1

    second = evaluate_core(core, snapshot)
    assert len(second) == 1
    cached = with_active_order(snapshot, "vwap_momentum", side=first[0].side)
    assert evaluate_core(core, cached) == []


def test_vwap_core_accepts_trade_view_events() -> None:
    config = _fast_config()
    core = VWAPMomentumAlphaCore(config)
    snapshot = _snapshot_with_trades()

    decisions = evaluate_core(core, snapshot)

    assert len(decisions) == 1
    assert decisions[0].side == Side.UP
    assert decisions[0].metrics["fav_price"] == 0.60


def test_vwap_core_skips_entry_when_favorite_ask_missing() -> None:
    config = _fast_config()
    core = VWAPMomentumAlphaCore(config)
    base = _snapshot_with_trades()
    view = replace(base, up=replace(base.up, best_ask=None))
    assert core.evaluate(view) == []


def test_vwap_cache_position_creates_hedge_decision() -> None:
    config = _fast_config(hedge_enabled=True, hedge_price=0.02, hedge_expiry_seconds=3600)
    core = VWAPMomentumAlphaCore(config)
    view = _snapshot_with_trades()
    cached = with_open_position(
        view,
        "vwap_momentum",
        side=Side.UP,
        avg_entry_price=0.60,
        quantity=10.0,
    )
    decisions = core.evaluate(cached)

    assert len(decisions) == 1
    hedge = decisions[0]
    assert hedge.side == Side.DOWN
    assert hedge.hedge_leg is True
    assert hedge.order_intent is not None
    assert hedge.order_intent.intent == OrderIntent.PASSIVE_GTD
    assert hedge.order_intent.expiry_seconds == 3600
    assert hedge.order_intent.pair_id == f"{view.market_id}:vwap"
    assert hedge.max_entry_price == 0.02
    assert hedge.entry_reference_price == 0.02
    assert hedge.metrics["contracts"] == 10
    assert hedge.metrics["hedge_price"] == 0.02
    assert hedge.metrics["hedge_source"] == "vwap_entry_fill"
    assert hedge.token_id == view.down.token_id
    assert hedge.reason_codes == ("VWAP_GTD_HEDGE",)


def test_vwap_active_hedge_order_prevents_reverse_hedge() -> None:
    config = _fast_config(hedge_enabled=True, hedge_price=0.02, hedge_expiry_seconds=3600)
    core = VWAPMomentumAlphaCore(config)
    view = with_open_position(
        _snapshot_with_trades(),
        "vwap_momentum",
        side=Side.UP,
        quantity=10.0,
    )
    cached = with_active_order(
        view,
        "vwap_momentum",
        side=Side.DOWN,
        hedge_leg=True,
    )
    assert core.evaluate(cached) == []


def test_vwap_evaluate_requires_projected_trades() -> None:
    config = _fast_config()
    core = VWAPMomentumAlphaCore(config)
    # No up/down trades projected from Cache → no local book-trade fallback.
    snapshot = sample_market_view(up_ask=0.60, down_ask=0.40, seconds_to_close=120)
    assert evaluate_core(core, snapshot) == []


def test_vwap_core_state_roundtrip_is_empty() -> None:
    config = _fast_config()
    core = VWAPMomentumAlphaCore(config)
    payload = core.save_state()

    fresh = VWAPMomentumAlphaCore(config)
    fresh.load_state(
        {
            "trades": {"btc:UP": [{"price": 0.55, "size": 1.0, "timestamp": 1.0}]},
            "last_trade_signatures": {},
            "seen_trade_signatures": {},
        }
    )
    assert fresh.save_state() == payload
    assert restore_utc_datetime("2026-06-25T00:00:00+00:00").tzinfo is not None


def test_vwap_duplicate_trade_view_payload_is_stateless() -> None:
    config = _fast_config()
    core = VWAPMomentumAlphaCore(config)
    snapshot = _snapshot_with_trades()

    first = evaluate_core(core, snapshot)
    second = evaluate_core(core, snapshot)
    assert second == first


def test_vwap_state_round_trip_excludes_trading_state() -> None:
    config = _fast_config(hedge_enabled=True)
    core = VWAPMomentumAlphaCore(config)
    restored = VWAPMomentumAlphaCore(config)
    restored.load_state(core.save_state())

    assert restored.save_state() == core.save_state()
    assert "can_enter" not in restored.save_state()
    assert "pending_hedges" not in restored.save_state()
    assert "trades" not in restored.save_state()
