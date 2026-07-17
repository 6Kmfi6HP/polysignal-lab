"""
Input: __future__, __future__.annotations, polysignal_lab.alpha.vwap_trade_history, polysignal_lab.alpha.vwap_trade_history.(, polysignal_lab.alpha.types, polysignal_lab.alpha.types.TradeView, polysignal_lab.domain.enums, polysignal_lab.domain.enums.Side, datetime, datetime.UTC
Output: test_latest_price_returns_last_sample, test_trades_in_window_filters_by_timestamp, test_vwap_computes_volume_weighted_average, test_momentum_uses_time_band_mean, test_samples_from_trade_views_uses_event_timestamp
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from polysignal_lab.alpha.vwap_trade_history import (
    TradeSample,
    latest_price,
    momentum,
    samples_from_trade_views,
    trades_in_window,
    vwap,
)
from polysignal_lab.alpha.types import TradeView
from polysignal_lab.domain.enums import Side
from datetime import UTC, datetime


def test_latest_price_returns_last_sample() -> None:
    trades = (
        TradeSample(0.55, 1.0, 1000.0),
        TradeSample(0.60, 2.0, 1001.0),
    )
    assert latest_price(trades) == 0.60
    assert latest_price(()) is None


def test_trades_in_window_filters_by_timestamp() -> None:
    trades = (
        TradeSample(0.50, 1.0, 100.0),
        TradeSample(0.55, 1.0, 200.0),
    )
    windowed = trades_in_window(trades, window_sec=50.0, now=200.0)
    assert windowed == (TradeSample(0.55, 1.0, 200.0),)


def test_vwap_computes_volume_weighted_average() -> None:
    trades = (
        TradeSample(0.50, 2.0, 100.0),
        TradeSample(0.60, 1.0, 101.0),
    )
    assert vwap(trades, window_sec=10.0, now=101.0) == (0.50 * 2.0 + 0.60) / 3.0


def test_momentum_uses_time_band_mean() -> None:
    now = 1000.0
    trades = (
        TradeSample(0.50, 1.0, now - 5.0),
        TradeSample(0.60, 1.0, now),
    )
    assert momentum(trades, window_sec=5.0, now=now) == (0.60 - 0.50) / 0.50


def test_samples_from_trade_views_uses_event_timestamp() -> None:
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    views = (TradeView(price=0.60, size=2.0, side=Side.UP.value, ts=ts),)
    samples = samples_from_trade_views(views, now_ts=ts.timestamp() + 10)
    assert samples == (TradeSample(0.60, 2.0, ts.timestamp()),)
