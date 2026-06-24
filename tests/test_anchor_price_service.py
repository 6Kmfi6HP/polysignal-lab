from __future__ import annotations

from datetime import datetime, timezone

from polysignal_lab.data.anchor_price_service import AnchorPriceService, window_for_market
from polysignal_lab.data.state import SpotPrice, SpotRegistry
from polysignal_lab.domain.market import Market


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


def test_capture_for_market_persists_verified_spot_anchor() -> None:
    store = _Store()
    spots = SpotRegistry()
    market = _market("btc-updown-5m-1782216000")
    spots.update(
        SpotPrice(
            asset="BTC",
            symbol="BTCUSDT",
            price=64250.25,
            source="binance",
            event_time=market.start_ts,
        )
    )
    service = AnchorPriceService(spots=spots, store=store, max_lag_ms=1_000)

    anchor = service.capture_for_market(market)

    assert anchor is not None
    assert anchor.verified is True
    assert anchor.source == "binance"
    assert anchor.price == 64250.25
    assert store.anchors == [anchor]


def test_anchor_service_health_reports_latest_lag_and_source() -> None:
    store = _Store()
    spots = SpotRegistry()
    market = _market("btc-updown-5m-1782216000")
    spots.update(
        SpotPrice(
            asset="BTC",
            symbol="BTCUSDT",
            price=64250.25,
            source="binance",
            event_time=market.start_ts,
        )
    )
    service = AnchorPriceService(spots=spots, store=store, max_lag_ms=1_000)
    service.capture_for_market(market)

    metrics = service.health_metrics()

    assert metrics["BTC:5m"]["source"] == "binance"
    assert metrics["BTC:5m"]["verified"] is True
    assert metrics["BTC:5m"]["lag_ms"] == 0
