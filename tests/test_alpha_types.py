"""
Input: __future__, __future__.annotations, datetime, datetime.UTC, datetime.datetime, pytest, polysignal_lab.alpha.types, polysignal_lab.alpha.types.(, polysignal_lab.domain.enums, polysignal_lab.domain.enums.OrderIntent
Output: test_market_view_exposes_side_books_and_asks, test_market_view_is_immutable, test_alpha_decision_carries_order_intent_spec, test_market_group_view_carries_relation_members, test_nautilus_order_spec_carries_quantity_and_tags
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""









from __future__ import annotations

from datetime import UTC, datetime

import pytest

from polysignal_lab.alpha.types import (
    AlphaDecision,
    FreshnessView,
    MarketGroupView,
    MarketView,
    OrderIntentSpec,
    SideBookView,
    SpotView,
)
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.nautilus_runtime.order_plan import OrderSubmissionPlan


def _view() -> MarketView:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return MarketView(
        view_id="view-1",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        asset="BTC",
        timeframe="5m",
        start_ts=now,
        end_ts=now,
        created_at=now,
        seconds_to_close=60,
        up=SideBookView(token_id="up-token", best_bid=0.81, best_ask=0.82, spread=0.01, freshness_ms=100),
        down=SideBookView(token_id="down-token", best_bid=0.17, best_ask=0.18, spread=0.01, freshness_ms=120),
        spot=SpotView(asset="BTC", symbol="BTCUSD", price=100120.0, source="polymarket_rtds", freshness_ms=90),
        price_to_beat=100000.0,
        up_trades=(),
        down_trades=(),
        metrics={"price_to_beat_verified": True},
        freshness=FreshnessView(up_book_ms=100, down_book_ms=120, spot_ms=90, max_ms=120),
    )


def test_market_view_exposes_side_books_and_asks() -> None:
    view = _view()

    assert view.book_for(Side.UP).token_id == "up-token"
    assert view.book_for(Side.DOWN).token_id == "down-token"
    assert view.ask_for(Side.UP) == 0.82
    assert view.ask_for(Side.DOWN) == 0.18


def test_market_view_is_immutable() -> None:
    view = _view()

    with pytest.raises(AttributeError):
        view.asset = "ETH"  # type: ignore[misc]


def test_alpha_decision_carries_order_intent_spec() -> None:
    intent = OrderIntentSpec(intent=OrderIntent.PASSIVE_GTD, expiry_seconds=45)
    decision = AlphaDecision(
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        token_id="up-token",
        side=Side.UP,
        confidence=0.75,
        entry_reference_price=0.82,
        max_entry_price=0.92,
        seconds_to_close=60,
        data_freshness_ms=120,
        reason_codes=("PTB_DIFF_THRESHOLD_OK",),
        metrics={"diff_usd": 120.0},
        order_intent=intent,
        hedge_leg=False,
    )

    assert decision.order_intent == intent
    assert decision.reason_codes == ("PTB_DIFF_THRESHOLD_OK",)


def test_market_group_view_carries_relation_members() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    view = _view()
    group = MarketGroupView(
        group_id="basket-1",
        relation_id="all_markets",
        created_at=now,
        views_by_condition_id={view.condition_id: view},
        max_source_skew_ms=25,
        metrics={"relation_count": 1},
    )

    assert group.views_by_condition_id[view.condition_id] is view
    assert group.max_source_skew_ms == 25


def test_nautilus_order_spec_carries_quantity_and_tags() -> None:
    spec = OrderSubmissionPlan(
        instrument_id="token-up.POLYMARKET",
        side=Side.UP,
        price=0.81,
        quantity=12.0,
        intent=OrderIntent.PASSIVE_GTD,
        expiry_seconds=45,
        pair_id="pair-1",
        reduce_only=False,
        hedge_leg=True,
        tags={"strategy": "vwap_momentum"},
    )

    assert spec.quantity == 12.0
    assert spec.tags["strategy"] == "vwap_momentum"
