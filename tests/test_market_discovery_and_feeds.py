"""
Input: __future__, datetime, unittest.mock, polysignal_lab.config, polysignal_lab.data.market_discovery_helpers, polysignal_lab.data.polymarket_market_discovery
Output: test_market_discovery_current_slot_slugs_uses_shared_helper, test_market_discovery_flattens_and_parses_crypto_updown
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from polysignal_lab.config import MarketConfig, PolymarketDataConfig
from polysignal_lab.data.market_discovery_helpers import (
    build_current_slot_slugs,
    parse_gamma_markets,
)
from polysignal_lab.data.polymarket_market_discovery import MarketDiscovery


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
