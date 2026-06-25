from __future__ import annotations

from datetime import UTC, datetime

import pytest

from polysignal_lab.alpha.types import (
    AlphaDecision,
    FreshnessView,
    MarketView,
    OrderIntentSpec,
    SideBookView,
    SpotView,
)
from polysignal_lab.domain.enums import OrderIntent, Side


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
