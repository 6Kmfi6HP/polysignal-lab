"""
Input: __future__, datetime, unittest.mock, polysignal_lab.config, polysignal_lab.data.binance_spot_ws, polysignal_lab.data.market_discovery_helpers, polysignal_lab.data.polymarket_clob_ws, polysignal_lab.data.polymarket_market_discovery, polysignal_lab.data.state
Output: test_market_discovery_current_slot_slugs_uses_shared_helper, test_market_discovery_flattens_and_parses_crypto_updown, test_binance_feed_url_and_parse_message, test_polymarket_ws_book_message_updates_registry
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from polysignal_lab.config import MarketConfig, PolymarketDataConfig, BinanceDataConfig
from polysignal_lab.data.binance_spot_ws import BinanceSpotFeed
from polysignal_lab.data.market_discovery_helpers import (
    build_current_slot_slugs,
    parse_gamma_markets,
)
from polysignal_lab.data.polymarket_clob_ws import PolymarketMarketWebSocket
from polysignal_lab.data.polymarket_market_discovery import MarketDiscovery
from polysignal_lab.data.state import OrderBookRegistry, SpotRegistry


def test_market_discovery_current_slot_slugs_uses_shared_helper() -> None:
    fixed_now = datetime(2026, 7, 9, 12, 3, tzinfo=UTC)
    discovery = MarketDiscovery(PolymarketDataConfig(), MarketConfig())

    with patch(
        "polysignal_lab.data.polymarket_market_discovery.utc_now",
        return_value=fixed_now,
    ):
        direct = build_current_slot_slugs(
            assets=list(discovery.market_config.assets),
            timeframes=list(discovery.market_config.timeframes),
            now_ts=int(fixed_now.timestamp()),
        )
        from_discovery = discovery._current_slot_slugs()

    assert from_discovery == direct


def test_market_discovery_flattens_and_parses_crypto_updown():
    payload = {
        "slug": "btc-updown-5m-1",
        "title": "BTC Up or Down 5m",
        "markets": [{"id": "m1", "conditionId": "c1", "clobTokenIds": ["up", "down"], "outcomes": ["Up", "Down"], "active": True}],
    }

    markets = parse_gamma_markets(
        [payload],
        MarketConfig(),
        now=datetime(2026, 7, 13, tzinfo=UTC),
    )

    assert [(market.asset, market.timeframe) for market in markets] == [("BTC", "5m")]


def test_binance_feed_url_and_parse_message():
    spots = SpotRegistry()
    feed = BinanceSpotFeed(BinanceDataConfig(), spots)
    assert "btcusdt@aggTrade" in feed.combined_stream_url()
    feed.handle_message({"stream": "btcusdt@aggTrade", "data": {"s": "BTCUSDT", "p": "100.1", "E": 1}})
    assert spots.get("BTC").price == 100.1


def test_polymarket_ws_book_message_updates_registry():
    registry = OrderBookRegistry()
    ws = PolymarketMarketWebSocket(PolymarketDataConfig(), registry)
    ws.handle_message({"event_type": "book", "market": "m", "asset_id": "tok", "bids": [{"price": "0.4", "size": "1"}], "asks": [{"price": "0.5", "size": "1"}]})
    assert registry.get("tok").best_ask == 0.5
    ws.handle_message({"event_type": "last_trade_price", "asset_id": "tok", "price": "0.49"})
    assert registry.get("tok").last_trade_price == 0.49
