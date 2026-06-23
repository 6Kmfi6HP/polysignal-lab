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
