from __future__ import annotations

from datetime import datetime, timezone

from polysignal_lab.data.anchor_price_service import window_for_market
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
