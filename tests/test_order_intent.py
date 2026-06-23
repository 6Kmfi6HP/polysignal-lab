from __future__ import annotations

from polysignal_lab.domain.enums import OrderIntent, OrderStatus, Side
from polysignal_lab.domain.signal import SignalCandidate


def test_order_intent_values():
    assert OrderIntent.PASSIVE_GTD == "passive_gtd"
    assert OrderIntent.TAKER_FAK == "taker_fak"
    assert OrderIntent.TAKER_FOK == "taker_fok"
    assert OrderIntent.TAKER_IOC == "taker_ioc"


def test_order_status_new_values():
    assert OrderStatus.RESTING == "RESTING"
    assert OrderStatus.CANCELLED == "CANCELLED"
    assert OrderStatus.PARTIAL == "PARTIAL"
    # existing values still present
    assert OrderStatus.PENDING == "PENDING"
    assert OrderStatus.FILLED == "FILLED"
    assert OrderStatus.REJECTED == "REJECTED"


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


def test_paper_order_has_order_intent_field():
    from polysignal_lab.domain.paper_order import PaperOrder

    po = PaperOrder(
        signal_id="sig-1",
        asset="BTC",
        timeframe="5m",
        strategy="test",
        market_id="mkt-1",
        market_slug="btc-updown-5m-1",
        token_id="token-up",
        side=Side.UP,
        limit_price=0.5,
        reference_price=0.5,
        stake_usdc=10.0,
    )
    assert po.order_intent is None


def test_paper_order_with_order_intent():
    from polysignal_lab.domain.paper_order import PaperOrder

    po = PaperOrder(
        signal_id="sig-1",
        asset="BTC",
        timeframe="5m",
        strategy="test",
        market_id="mkt-1",
        market_slug="btc-updown-5m-1",
        token_id="token-up",
        side=Side.UP,
        limit_price=0.5,
        reference_price=0.5,
        stake_usdc=10.0,
        order_intent="passive_gtd",
    )
    assert po.order_intent == "passive_gtd"
from polysignal_lab.signal_layer.gate import SignalGate
from polysignal_lab.config import SignalConfig, PolymarketDataConfig, BinanceDataConfig
from polysignal_lab.domain.snapshot import MarketSnapshot, FreshnessState
from polysignal_lab.domain.orderbook import BookLevel, OrderBook
from polysignal_lab.domain.enums import MarketStatus, Action
from datetime import timedelta
from polysignal_lab.utils import utc_now
from polysignal_lab.domain.spot import SpotPrice

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

def _make_fresh_book() -> OrderBook:
    return OrderBook(
        token_id="t-up", bids=[BookLevel(price=0.30, size=100)],
        asks=[BookLevel(price=0.55, size=100)],
        last_trade_price=0.42, received_at=utc_now(),
    )

def _make_active_snapshot(book: OrderBook) -> MarketSnapshot:
    from polysignal_lab.domain.market import Market, OutcomeToken
    now = utc_now()
    market = Market(
        market_id="mkt-1", market_slug="s", condition_id="c",
        question_id="q", question="Q", asset="BTC", timeframe="5m",
        start_ts=now - timedelta(seconds=100),
        end_ts=now + timedelta(seconds=300),
        status=MarketStatus.ACTIVE, resolution_source="test",
        outcome_tokens=[
            OutcomeToken(token_id="t-up", side=Side.UP, outcome_name="Up", market_id="mkt-1"),
            OutcomeToken(token_id="t-down", side=Side.DOWN, outcome_name="Down", market_id="mkt-1"),
        ],
    )
    return MarketSnapshot(
        snapshot_id="snap-1", market=market,
        up_book=book, down_book=None,
        spot=SpotPrice(asset="BTC", symbol="BTCUSDT", price=42000.0),
        freshness=FreshnessState(up_book_ms=10, down_book_ms=None, spot_ms=10, max_ms=10),
    )

def test_passive_gtd_skips_max_entry_check():
    gate = _make_gate()
    sig = _make_passive_signal()
    snap = _make_active_snapshot(_make_fresh_book())
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
    snap = _make_active_snapshot(_make_fresh_book())
    reason = gate._max_entry(sig, snap)
    assert reason == "ASK_ABOVE_MAX_ENTRY"

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
    gate = _make_gate()
    snap = _make_active_snapshot(_make_fresh_book())
    reason = gate._gtd_expiry(sig, snap)
    assert reason == "MISSING_GTD_EXPIRY"

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
    snap = _make_active_snapshot(_make_fresh_book())
    reason = gate._gtd_expiry(sig, snap)
    assert reason == "GTD_EXPIRY_EXCEEDS_24H"

def test_gtd_expiry_accepts_valid():
    gate = _make_gate()
    sig = _make_passive_signal()
    snap = _make_active_snapshot(_make_fresh_book())
    reason = gate._gtd_expiry(sig, snap)
    assert reason is None

def test_passive_gtd_skips_spread_check():
    gate = _make_gate()
    sig = _make_passive_signal()
    snap = _make_active_snapshot(_make_fresh_book())
    reason = gate._spread(sig, snap)
    assert reason is None

def test_passive_gtd_skips_time_window():
    gate = _make_gate()
    sig = _make_passive_signal()
    snap = _make_active_snapshot(_make_fresh_book())
    reason = gate._time_window(sig, snap)
    assert reason is None

def test_passive_gtd_full_evaluate_accepted():
    gate = _make_gate()
    sig = _make_passive_signal()
    snap = _make_active_snapshot(_make_fresh_book())
    decision = gate.evaluate(sig, snap)
    assert decision.accepted is True
    assert decision.signal is not None
