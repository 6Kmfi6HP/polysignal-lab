from __future__ import annotations

from datetime import UTC, datetime

from polysignal_lab.alpha.mid_price_sizing_core import MidPriceSizingAlphaCore
from polysignal_lab.alpha.types import (
    FreshnessView,
    MarketView,
    SideBookView,
    SpotView,
)
from polysignal_lab.config import Settings
from alpha_helpers import with_open_position


def _view(
    *, up_ask: float, up_bid: float, down_ask: float = 0.45, down_bid: float = 0.44
) -> MarketView:
    now = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
    up = SideBookView(
        token_id="token-up",
        best_bid=up_bid,
        best_ask=up_ask,
        spread=up_ask - up_bid,
        freshness_ms=10,
    )
    down = SideBookView(
        token_id="token-down",
        best_bid=down_bid,
        best_ask=down_ask,
        spread=down_ask - down_bid,
        freshness_ms=10,
    )
    return MarketView(
        view_id="view-1",
        market_id="market-1",
        market_slug="btc-updown-5m",
        condition_id="condition-1",
        asset="BTC",
        timeframe="5m",
        start_ts=None,
        end_ts=None,
        created_at=now,
        seconds_to_close=300,
        up=up,
        down=down,
        spot=SpotView(
            asset="BTC",
            symbol="BTCUSD",
            price=100_000.0,
            source="test",
            freshness_ms=10,
        ),
        price_to_beat=100_000.0,
        up_trades=(),
        down_trades=(),
        metrics={},
        freshness=FreshnessView(10, 10, 10, 10),
    )


def test_mid_price_exit_bypasses_entry_regime_and_uses_exit_confidence() -> None:
    core = MidPriceSizingAlphaCore(Settings().strategies.mid_price_sizing)
    view = with_open_position(
        _view(up_ask=0.80, up_bid=0.70),
        "mid_price_sizing",
        avg_entry_price=0.45,
    )
    decisions = core.evaluate(view)

    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.order_intent is not None
    assert decision.order_intent.reduce_only is True
    assert decision.metrics["action"] == "CLOSE_TAKE_PROFIT"
    assert decision.confidence >= 0.50


def test_mid_price_entry_and_addition_export_configured_notional_contracts() -> None:
    config = Settings().strategies.mid_price_sizing.model_copy(
        update={"adverse_step": 0.04}
    )
    core = MidPriceSizingAlphaCore(config)

    entry = core.evaluate(_view(up_ask=0.45, up_bid=0.44))[0]
    assert entry.metrics["contracts"] == 5.0 / 0.45

    view = with_open_position(
        _view(up_ask=0.40, up_bid=0.39),
        "mid_price_sizing",
        avg_entry_price=0.45,
    )
    addition = core.evaluate(view)[0]

    assert addition.metrics["action"] == "MARTINGALE_ADD"
    assert addition.metrics["contracts"] == 5.0 / 0.40


def test_mid_price_without_cache_position_has_no_shadow_state() -> None:
    core = MidPriceSizingAlphaCore(Settings().strategies.mid_price_sizing)

    assert core.evaluate(_view(up_ask=0.45, up_bid=0.44))
    assert not hasattr(core, "_layer_intent")
    assert not hasattr(core, "_entry_price_intent")
