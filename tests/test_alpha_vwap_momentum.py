"""
Input: __future__, __future__.annotations, dataclasses, dataclasses.replace, polysignal_lab.alpha.ptb_diff_core, polysignal_lab.alpha.ptb_diff_core.market_view_from_snapshot, polysignal_lab.alpha.state, polysignal_lab.alpha.state.restore_utc_datetime, polysignal_lab.alpha.types, polysignal_lab.alpha.types.AlphaDecision
Output: test_vwap_core_matches_legacy_candidate, test_vwap_entry_guard_not_consumed_until_acceptance, test_vwap_core_accepts_trade_view_events, test_vwap_core_skips_entry_when_favorite_ask_missing, test_vwap_on_order_rejected_reverts_pending_samples, test_vwap_on_order_rejected_reverts_trade_view_samples, test_vwap_on_order_filled_taker_creates_hedge_decision, test_vwap_on_order_expired_gtd_clears_pending_hedge, test_vwap_evaluate_prunes_old_trade_history_and_dedupe_state, test_vwap_core_state_roundtrip
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""








from __future__ import annotations

from dataclasses import replace

from polysignal_lab.alpha.ptb_diff_core import market_view_from_snapshot
from polysignal_lab.alpha.state import restore_utc_datetime
from polysignal_lab.alpha.types import AlphaFillEvent, AlphaOrderEvent, TradeView
from polysignal_lab.alpha.vwap_momentum_core import TradeHistory, VWAPMomentumAlphaCore
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.strategy_config import VWAPMomentumConfig
from alpha_helpers import evaluate_core_from_snapshot
from factories import sample_snapshot


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


def _snapshot():
    # up_ask=0.60 → last_trade_price mid ≈ 0.585; down_ask=0.40 → mid ≈ 0.385.
    return sample_snapshot(up_ask=0.60, down_ask=0.40, seconds_to_close=120)


def _seed_band(owner: VWAPMomentumAlphaCore, market_id: str, now_ts: float) -> None:
    """Seed a single trade per side in the momentum band (now - 5s)."""
    owner.trades.push(f"{market_id}:{Side.UP.value}", 0.50, 1.0, now_ts - 5.0)
    owner.trades.push(f"{market_id}:{Side.DOWN.value}", 0.40, 1.0, now_ts - 5.0)


def _accept_event(decision, *, order_id: str = "order-1") -> AlphaOrderEvent:
    return AlphaOrderEvent(
        strategy=decision.strategy,
        market_id=decision.market_id,
        condition_id=decision.condition_id,
        token_id=decision.token_id,
        side=decision.side,
        order_id=order_id,
        client_order_id=None,
        reason=None,
        ts_event=decision.metrics["created_at_for_test"],
        metrics={},
    )


# ---------------------------------------------------------------------------
# Entry guard: consumed only on acceptance
# ---------------------------------------------------------------------------


def test_vwap_entry_guard_not_consumed_until_acceptance() -> None:
    config = _fast_config()
    core = VWAPMomentumAlphaCore(config)
    snapshot = _snapshot()
    market_id = snapshot.market.market_id
    _seed_band(core, market_id, snapshot.created_at.timestamp())

    first = evaluate_core_from_snapshot(core, snapshot)
    assert len(first) == 1

    # Repeated candidate generation must NOT consume the entry guard.
    second = evaluate_core_from_snapshot(core, snapshot)
    assert len(second) == 1
    assert core._can_enter[market_id] is True

    # Acceptance is the ONLY thing that consumes the guard.
    core.on_order_accepted(_accept_event(first[0]))

    assert core._can_enter[market_id] is False
    assert evaluate_core_from_snapshot(core, snapshot) == []



def test_vwap_core_accepts_trade_view_events() -> None:
    config = _fast_config()
    core = VWAPMomentumAlphaCore(config)
    snapshot = _snapshot()
    trade_ts = snapshot.created_at
    snapshot = snapshot.model_copy(
        update={
            "metrics": {
                "up_trades": (TradeView(price=0.60, size=2.0, side=Side.UP.value, ts=trade_ts),),
                "down_trades": (TradeView(price=0.42, size=1.0, side=Side.DOWN.value, ts=trade_ts),),
            }
        }
    )
    now_ts = snapshot.created_at.timestamp()
    _seed_band(core, snapshot.market.market_id, now_ts)

    decisions = evaluate_core_from_snapshot(core, snapshot)

    assert len(decisions) == 1
    assert decisions[0].side == Side.UP
    assert core.trades.latest_price(f"{snapshot.market.market_id}:{Side.UP.value}") == 0.60


def test_vwap_core_skips_entry_when_favorite_ask_missing() -> None:
    config = _fast_config()
    core = VWAPMomentumAlphaCore(config)
    snapshot = _snapshot()
    _seed_band(core, snapshot.market.market_id, snapshot.created_at.timestamp())
    view = market_view_from_snapshot(snapshot)
    assert view is not None
    view = replace(view, up=replace(view.up, best_ask=None))

    assert core.evaluate(view) == []

# ---------------------------------------------------------------------------
# Rejection reverts the pending trade samples staged during evaluate
# ---------------------------------------------------------------------------


def test_vwap_on_order_rejected_reverts_pending_samples() -> None:
    config = _fast_config()
    core = VWAPMomentumAlphaCore(config)
    snapshot = _snapshot()
    market_id = snapshot.market.market_id
    now_ts = snapshot.created_at.timestamp()
    _seed_band(core, market_id, now_ts)

    decision = evaluate_core_from_snapshot(core, snapshot)[0]
    # The evaluate pushed a current UP sample (mid ≈ 0.585) staged as pending.
    core.bind_signal(market_id, "sig-rejected")

    up_key = f"{market_id}:{Side.UP.value}"
    assert core.trades.latest_price(up_key) != 0.50  # the pushed sample is present

    core.on_order_rejected(
        AlphaOrderEvent(
            strategy=decision.strategy,
            market_id=market_id,
            condition_id=decision.condition_id,
            token_id=decision.token_id,
            side=decision.side,
            order_id="sig-rejected",
            client_order_id=None,
            reason=None,
            ts_event=decision.metrics["created_at_for_test"],
            metrics={},
        )
    )

    # The pushed sample is reverted; only the seeded band trade remains.
    assert core.trades.latest_price(up_key) == 0.50



def test_vwap_on_order_rejected_reverts_trade_view_samples() -> None:
    config = _fast_config()
    core = VWAPMomentumAlphaCore(config)
    snapshot = _snapshot()
    market_id = snapshot.market.market_id
    trade_ts = snapshot.created_at
    snapshot = snapshot.model_copy(
        update={
            "metrics": {
                "up_trades": (TradeView(price=0.60, size=2.0, side=Side.UP.value, ts=trade_ts),),
                "down_trades": (TradeView(price=0.42, size=1.0, side=Side.DOWN.value, ts=trade_ts),),
            }
        }
    )
    _seed_band(core, market_id, snapshot.created_at.timestamp())

    decision = evaluate_core_from_snapshot(core, snapshot)[0]
    core.bind_signal(market_id, "sig-tradeview-rejected")

    up_key = f"{market_id}:{Side.UP.value}"
    assert core.trades.latest_price(up_key) == 0.60

    core.on_order_rejected(_accept_event(decision, order_id="sig-tradeview-rejected"))

    assert core.trades.latest_price(up_key) == 0.50
# ---------------------------------------------------------------------------
# Hedge flow: taker fill creates a hedge decision; GTD fill clears it
# ---------------------------------------------------------------------------


def _hedge_fill_event(market_id: str, entry_side: Side, *, order_id: str = "entry-1") -> AlphaFillEvent:
    return AlphaFillEvent(
        strategy="vwap_momentum",
        market_id=market_id,
        condition_id="cond-test",
        token_id=f"{market_id}-{entry_side.value}",
        side=entry_side,
        order_id=order_id,
        client_order_id=None,
        reason=None,
        ts_event=__import__("polysignal_lab.utils", fromlist=["utc_now"]).utc_now(),
        fill_price=0.60,
        shares=10.0,
        liquidity_side=None,
        metrics={
            "opposite_token_id": f"{market_id}-{entry_side.opposite.value}",
            "condition_id": "cond-test",
            "seconds_to_close": 120,
            "asset": "BTC",
            "timeframe": "5m",
            "market_slug": f"btc-updown-5m-{market_id}",
            "signal_confidence": 0.72,
        },
    )


def test_vwap_on_order_filled_taker_creates_hedge_decision() -> None:
    config = _fast_config(hedge_enabled=True, hedge_price=0.02, hedge_expiry_seconds=3600)
    core = VWAPMomentumAlphaCore(config)
    market_id = "btc-5m-hedge"

    # A taker entry fill stages the pending hedge via notify_fill.
    core.on_notify_fill(market_id, Side.UP, shares=10.0)
    assert core._pending_hedges == {market_id: (Side.DOWN, 10.0)}

    decisions = core.on_order_filled(_hedge_fill_event(market_id, Side.UP))

    assert len(decisions) == 1
    hedge = decisions[0]
    assert hedge.side == Side.DOWN
    assert hedge.hedge_leg is True
    assert hedge.order_intent is not None
    assert hedge.order_intent.intent == OrderIntent.PASSIVE_GTD
    assert hedge.order_intent.expiry_seconds == 3600
    assert hedge.order_intent.pair_id == f"{market_id}:vwap"
    assert hedge.max_entry_price == 0.02
    assert hedge.entry_reference_price == 0.02
    assert hedge.metrics["contracts"] == 10
    assert hedge.metrics["hedge_price"] == 0.02
    assert hedge.metrics["hedge_source"] == "vwap_entry_fill"
    assert hedge.token_id == f"{market_id}-{Side.DOWN.value}"
    assert hedge.reason_codes == ("VWAP_GTD_HEDGE",)
    # The pending hedge is consumed.
    assert core._pending_hedges == {}


def test_vwap_on_order_expired_gtd_clears_pending_hedge() -> None:
    config = _fast_config(hedge_enabled=True, hedge_price=0.02, hedge_expiry_seconds=3600)
    core = VWAPMomentumAlphaCore(config)
    market_id = "btc-5m-hedge"

    # The GTD hedge itself fills: notify_fill stages a reverse hedge ...
    core.on_notify_fill(market_id, Side.DOWN, shares=10.0)
    assert core._pending_hedges == {market_id: (Side.UP, 10.0)}

    # ... but a GTD fill must NOT create a reverse hedge — it clears the pending.
    core.on_order_expired(
        AlphaOrderEvent(
            strategy="vwap_momentum",
            market_id=market_id,
            condition_id="cond-test",
            token_id=f"{market_id}-{Side.DOWN.value}",
            side=Side.DOWN,
            order_id="gtd-hedge-1",
            client_order_id=None,
            reason=None,
            ts_event=__import__("polysignal_lab.utils", fromlist=["utc_now"]).utc_now(),
            metrics={},
        )
    )
    assert core._pending_hedges == {}

    # And a subsequent taker-fill event finds no pending hedge → no decision.
    decisions = core.on_order_filled(_hedge_fill_event(market_id, Side.UP))
    assert decisions == []


def test_vwap_evaluate_prunes_old_trade_history_and_dedupe_state() -> None:
    config = _fast_config(vwap_window_sec=5, momentum_window_sec=5)
    core = VWAPMomentumAlphaCore(config)
    snapshot = _snapshot()
    market_id = snapshot.market.market_id
    now_ts = snapshot.created_at.timestamp()
    up_key = f"{market_id}:{Side.UP.value}"
    down_key = f"{market_id}:{Side.DOWN.value}"

    core.trades.push(up_key, 0.49, 1.0, now_ts - 500.0)
    core.trades.push(down_key, 0.39, 1.0, now_ts - 500.0)
    core._seen_trade_signatures[up_key].add((0.49, 1.0, now_ts - 500.0))
    core._seen_trade_signatures[down_key].add((0.39, 1.0, now_ts - 500.0))
    _seed_band(core, market_id, now_ts)

    decisions = evaluate_core_from_snapshot(core, snapshot)

    assert len(decisions) == 1
    assert min(trade.timestamp for trade in core.trades._trades[up_key]) >= now_ts - 6.5
    assert min(trade.timestamp for trade in core.trades._trades[down_key]) >= now_ts - 6.5
    assert (0.49, 1.0, now_ts - 500.0) not in core._seen_trade_signatures[up_key]
    assert (0.39, 1.0, now_ts - 500.0) not in core._seen_trade_signatures[down_key]


# ---------------------------------------------------------------------------
# State round-trip
# ---------------------------------------------------------------------------


def test_vwap_core_state_roundtrip() -> None:
    from datetime import UTC, datetime

    config = _fast_config()
    core = VWAPMomentumAlphaCore(config)
    market_id = "btc-5m-rt"
    up_key = f"{market_id}:{Side.UP.value}"

    core.trades.push(up_key, 0.55, 2.0, 1000.0)
    core.trades.push(up_key, 0.60, 1.0, 1001.0)
    core._can_enter[market_id] = False
    core._last_trade_signatures[up_key] = (0.60, 1.0, None, 1001.0)
    core._seen_trade_signatures[up_key].add((0.55, 2.0, 1000.0))
    core._pending_hedges[market_id] = (Side.DOWN, 10.0)

    payload = core.save_state()

    fresh = VWAPMomentumAlphaCore(config)
    fresh.load_state(payload)

    assert fresh.trades.latest_price(up_key) == 0.60
    assert fresh.trades.vwap(up_key, config.vwap_window_sec, 1001.0) == (0.55 * 2.0 + 0.60) / 3.0
    assert fresh._can_enter[market_id] is False
    assert fresh._last_trade_signatures[up_key] == (0.60, 1.0, None, 1001.0)
    assert fresh._seen_trade_signatures[up_key] == {(0.55, 2.0, 1000.0)}
    assert fresh._pending_hedges[market_id] == (Side.DOWN, 10.0)
    # restore_utc_datetime is exercised by the round-trip indirectly (datetimes
    # are not stored by TradeHistory, but the helper remains importable).
    assert restore_utc_datetime("2026-06-25T00:00:00+00:00").tzinfo is not None
    assert datetime.now(UTC).tzinfo is not None
    # TradeHistory is exported from the alpha package.
    from polysignal_lab.alpha import TradeHistory as ExportedTradeHistory

    assert ExportedTradeHistory is TradeHistory
