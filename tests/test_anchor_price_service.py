"""
Input: __future__, __future__.annotations, datetime, datetime.datetime, datetime.timezone, polysignal_lab.data.anchor_price_service, polysignal_lab.data.anchor_price_service.capture_anchor_price, polysignal_lab.data.anchor_price_service.window_for_market, polysignal_lab.nautilus_runtime.spot_anchor_state, polysignal_lab.nautilus_runtime.spot_anchor_state.SpotAnchorState
Output: test_window_for_market_prefers_event_window, test_window_for_market_derives_from_slug_when_event_start_missing, test_capture_for_market_persists_verified_spot_anchor, test_capture_for_market_keeps_verified_anchor_when_later_sample_is_stale, test_capture_anchor_price_tracks_latest_anchor_by_key, _Store
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""









from __future__ import annotations

from datetime import datetime, timezone

from polysignal_lab.data.anchor_price_service import capture_anchor_price, window_for_market
from polysignal_lab.data.state import SpotPrice
from polysignal_lab.domain.anchor_price import AnchorPrice
from polysignal_lab.domain.market import Market
from polysignal_lab.nautilus_runtime.spot_anchor_state import SpotAnchorState


def _market(slug: str, timeframe: str = "5m") -> Market:
    start = datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 23, 12, 5, tzinfo=timezone.utc)
    return Market(
        market_id="m1",
        condition_id="c1",
        question="BTC Up or Down",
        market_slug=slug,
        asset="BTC",
        timeframe=timeframe,
        start_ts=start,
        end_ts=end,
        outcome_tokens=[],
        raw={},
    )


def test_window_for_market_prefers_event_window() -> None:
    window = window_for_market(_market("btc-updown-5m-1782216000"))
    assert window is not None
    assert window.window_start == datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc)
    assert window.window_end == datetime(2026, 6, 23, 12, 5, tzinfo=timezone.utc)


def test_window_for_market_derives_from_slug_when_event_start_missing() -> None:
    market = _market("btc-updown-15m-1782216000", timeframe="15m")
    market.start_ts = None
    market.end_ts = None
    window = window_for_market(market)
    assert window is not None
    assert int(window.window_start.timestamp()) == 1782216000
    assert int(window.window_end.timestamp()) == 1782216900


class _Store:
    def __init__(self) -> None:
        self.anchors = []

    def upsert_anchor_price(self, anchor):
        self.anchors.append(anchor)

    def get_verified_anchor_price(self, asset, timeframe, market_slug):
        for anchor in reversed(self.anchors):
            if (
                anchor.asset == asset.upper()
                and anchor.timeframe == timeframe
                and anchor.market_slug == market_slug
                and anchor.verified
            ):
                return anchor
        return None


def test_capture_for_market_persists_verified_spot_anchor() -> None:
    store = _Store()
    market = _market("btc-updown-5m-1782216000")
    state = SpotAnchorState(store)
    state.update(
        SpotPrice(
            asset="BTC",
            symbol="BTCUSDT",
            price=64250.25,
            source="binance",
            event_time=market.start_ts,
        )
    )

    anchor = state.capture_for_market(market)

    assert anchor is not None
    assert anchor.verified is True
    assert anchor.source == "binance"
    assert anchor.price == 64250.25
    assert store.anchors == [anchor]


def test_capture_for_market_keeps_verified_anchor_when_later_sample_is_stale() -> None:
    store = _Store()
    market = _market("btc-updown-5m-1782216000")
    latest_by_key: dict[str, AnchorPrice] = {}
    verified_anchor = capture_anchor_price(
        [
            SpotPrice(
                asset="BTC",
                symbol="BTCUSDT",
                price=64250.25,
                source="binance",
                event_time=market.start_ts,
            )
        ],
        market,
        store,
        max_lag_ms=1_000,
        latest_by_key=latest_by_key,
    )
    assert verified_anchor is not None

    stale_capture = capture_anchor_price(
        [
            SpotPrice(
                asset="BTC",
                symbol="BTCUSDT",
                price=64000.0,
                source="binance",
                event_time=datetime(2026, 6, 23, 12, 4, tzinfo=timezone.utc),
            )
        ],
        market,
        store,
        max_lag_ms=1_000,
        latest_by_key=latest_by_key,
    )

    assert stale_capture == verified_anchor
    assert store.anchors == [verified_anchor]
    assert latest_by_key["BTC:5m"].verified is True


def test_capture_anchor_price_tracks_latest_anchor_by_key() -> None:
    store = _Store()
    market = _market("btc-updown-5m-1782216000")
    latest_by_key: dict[str, AnchorPrice] = {}

    capture_anchor_price(
        [
            SpotPrice(
                asset="BTC",
                symbol="BTCUSDT",
                price=64250.25,
                source="binance",
                event_time=market.start_ts,
            )
        ],
        market,
        store,
        max_lag_ms=1_000,
        latest_by_key=latest_by_key,
    )

    anchor = latest_by_key["BTC:5m"]
    assert anchor.source == "binance"
    assert anchor.verified is True
    assert anchor.lag_ms == 0
