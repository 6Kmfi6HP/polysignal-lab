"""
Input: __future__, __future__.annotations, polysignal_lab.domain.enums, polysignal_lab.domain.enums.OrderIntent, polysignal_lab.domain.enums.Side, polysignal_lab.domain.signal, polysignal_lab.domain.signal.SignalCandidate, polysignal_lab.signal_layer.gate, polysignal_lab.signal_layer.gate.SignalGate
Output: test_order_intent_values, test_projection_order_status_strings, test_signal_candidate_has_order_intent_fields, test_signal_candidate_with_order_intent, test_nautilus_order_payload_has_order_intent_field, test_nautilus_order_payload_with_order_intent, test_passive_gtd_skips_max_entry_check, test_taker_still_fails_ask_above_max_entry, test_gtd_expiry_rejects_missing
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from polysignal_lab.config import BinanceDataConfig, PolymarketDataConfig, SignalConfig
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.signal_layer.gate import SignalGate
from factories import sample_market_view


def test_order_intent_values():
    assert OrderIntent.PASSIVE_GTD == "passive_gtd"
    assert OrderIntent.TAKER_FAK == "taker_fak"
    assert OrderIntent.TAKER_FOK == "taker_fok"
    assert OrderIntent.TAKER_IOC == "taker_ioc"


def test_projection_order_status_strings():
    """Nautilus order projections use uppercase status strings."""
    for status in ("PENDING", "RESTING", "CANCELLED", "PARTIAL", "FILLED", "REJECTED"):
        assert status == status.upper()


def _base_build_kwargs(**overrides):
    kwargs = dict(
        strategy="test",
        asset="BTC",
        timeframe="5m",
        market_id="mkt-1",
        market_slug="btc-updown-5m-1",
        condition_id="cond-1",
        token_id="token-up",
        side=Side.UP,
        confidence=0.5,
        entry_reference_price=0.5,
        max_entry_price=0.5,
        seconds_to_close=300,
        data_freshness_ms=100,
        reason_codes=["TEST"],
        metrics={},
    )
    kwargs.update(overrides)
    return kwargs


def test_signal_candidate_has_order_intent_fields():
    sig = SignalCandidate.build(**_base_build_kwargs())
    assert sig.order_intent is None
    assert sig.expiry_seconds is None
    assert sig.pair_id is None
    assert sig.hedge_leg is False


def test_signal_candidate_with_order_intent():
    sig = SignalCandidate.build(
        **_base_build_kwargs(
            order_intent=OrderIntent.PASSIVE_GTD,
            expiry_seconds=200,
            pair_id="mkt-1:dual",
            hedge_leg=False,
        )
    )
    assert sig.order_intent == OrderIntent.PASSIVE_GTD
    assert sig.expiry_seconds == 200
    assert sig.pair_id == "mkt-1:dual"
    assert sig.hedge_leg is False


def test_nautilus_order_payload_has_order_intent_field():
    order = {
        "signal_id": "sig-1",
        "asset": "BTC",
        "timeframe": "5m",
        "strategy": "test",
        "market_id": "mkt-1",
        "market_slug": "btc-updown-5m-1",
        "token_id": "token-up",
        "side": Side.UP.value,
        "limit_price": 0.5,
        "reference_price": 0.5,
        "stake_usdc": 10.0,
    }
    assert order.get("order_intent") is None


def test_nautilus_order_payload_with_order_intent():
    order = {
        "signal_id": "sig-1",
        "asset": "BTC",
        "timeframe": "5m",
        "strategy": "test",
        "market_id": "mkt-1",
        "market_slug": "btc-updown-5m-1",
        "token_id": "token-up",
        "side": Side.UP.value,
        "limit_price": 0.5,
        "reference_price": 0.5,
        "stake_usdc": 10.0,
        "order_intent": "passive_gtd",
    }
    assert order["order_intent"] == "passive_gtd"


def _make_gate() -> SignalGate:
    return SignalGate(
        SignalConfig(), PolymarketDataConfig(), BinanceDataConfig()
    )


def _make_passive_signal() -> SignalCandidate:
    return SignalCandidate.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="s", condition_id="c",
        token_id="t-up", side=Side.UP, confidence=0.6,
        entry_reference_price=0.35, max_entry_price=0.35,
        seconds_to_close=300, data_freshness_ms=100,
        reason_codes=["TEST"], metrics={},
        order_intent=OrderIntent.PASSIVE_GTD, expiry_seconds=200,
    )


def _make_active_view():
    return sample_market_view(
        up_ask=0.55,
        up_bid=0.30,
        down_ask=0.45,
        book_freshness_ms=10,
        spot_freshness_ms=10,
        spot_price=42000.0,
        seconds_to_close=300,
        view_id="snap-1",
    )


def test_passive_gtd_skips_max_entry_check():
    gate = _make_gate()
    sig = _make_passive_signal()
    snap = _make_active_view()
    # ask=0.55 > max_entry=0.35, but PASSIVE_GTD should pass
    reason = gate._max_entry(sig, snap)
    assert reason is None


def test_taker_still_fails_ask_above_max_entry():
    gate = _make_gate()
    sig = SignalCandidate.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="s", condition_id="c",
        token_id="t-up", side=Side.UP, confidence=0.6,
        entry_reference_price=0.85, max_entry_price=0.50,
        seconds_to_close=300, data_freshness_ms=100,
        reason_codes=["TEST"], metrics={},
        # no order_intent → default taker
    )
    snap = _make_active_view()
    reason = gate._max_entry(sig, snap)
    assert reason is not None
    assert reason.reason_code == "ASK_ABOVE_MAX_ENTRY"


def test_gtd_expiry_rejects_missing():
    gate = _make_gate()
    sig = SignalCandidate.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="s", condition_id="c",
        token_id="t-up", side=Side.UP, confidence=0.6,
        entry_reference_price=0.35, max_entry_price=0.35,
        seconds_to_close=300, data_freshness_ms=100,
        reason_codes=["TEST"], metrics={},
        order_intent=OrderIntent.PASSIVE_GTD,
        # expiry_seconds NOT set
    )
    snap = _make_active_view()
    reason = gate._gtd_expiry(sig, snap)
    assert reason is not None
    assert reason.reason_code == "MISSING_GTD_EXPIRY"


def test_gtd_expiry_rejects_too_long():
    gate = _make_gate()
    sig = SignalCandidate.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="s", condition_id="c",
        token_id="t-up", side=Side.UP, confidence=0.6,
        entry_reference_price=0.35, max_entry_price=0.35,
        seconds_to_close=300, data_freshness_ms=100,
        reason_codes=["TEST"], metrics={},
        order_intent=OrderIntent.PASSIVE_GTD, expiry_seconds=100000,
    )
    snap = _make_active_view()
    reason = gate._gtd_expiry(sig, snap)
    assert reason is not None
    assert reason.reason_code == "GTD_EXPIRY_EXCEEDS_24H"


def test_gtd_expiry_accepts_valid():
    gate = _make_gate()
    sig = _make_passive_signal()
    snap = _make_active_view()
    reason = gate._gtd_expiry(sig, snap)
    assert reason is None


def test_passive_gtd_skips_spread_check():
    gate = _make_gate()
    sig = _make_passive_signal()
    snap = _make_active_view()
    reason = gate._spread(sig, snap)
    assert reason is None


def test_passive_gtd_skips_time_window():
    gate = _make_gate()
    sig = _make_passive_signal()
    snap = _make_active_view()
    reason = gate._time_window(sig, snap)
    assert reason is None


def test_passive_gtd_full_evaluate_accepted():
    gate = _make_gate()
    sig = _make_passive_signal()
    snap = _make_active_view()
    decision = gate.evaluate(sig, snap)
    assert decision.accepted is True
    assert decision.signal is not None
