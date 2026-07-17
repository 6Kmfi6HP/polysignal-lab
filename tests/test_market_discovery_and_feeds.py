"""
Input: __future__, __future__.annotations, datetime, datetime.UTC, datetime.datetime, unittest.mock, unittest.mock.patch, polysignal_lab.config, polysignal_lab.config.MarketConfig, polysignal_lab.config.PolymarketDataConfig
Output: test_market_discovery_current_slot_slugs_uses_shared_helper, test_market_discovery_flattens_and_parses_crypto_updown, test_gamma_page_limit_matches_official_markets_cap, test_gamma_markets_slug_query_uses_official_builder, test_paginate_gamma_events_continues_when_page_is_full_cap
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from polysignal_lab.config import MarketConfig, PolymarketDataConfig
from polysignal_lab.data.market_discovery_helpers import (
    GAMMA_PAGE_LIMIT,
    build_current_slot_slugs,
    gamma_markets_slug_query_params,
    paginate_gamma_events,
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
        "markets": [
            {
                "id": "m1",
                "conditionId": "c1",
                "clobTokenIds": ["up", "down"],
                "outcomes": ["Up", "Down"],
                "active": True,
            }
        ],
    }

    markets = parse_gamma_markets(
        [payload],
        MarketConfig(),
        now=datetime(2026, 7, 13, tzinfo=UTC),
    )

    assert [(market.asset, market.timeframe) for market in markets] == [("BTC", "5m")]


def test_gamma_page_limit_matches_official_markets_cap() -> None:
    from nautilus_trader.adapters.polymarket.common import gamma_markets as official

    assert GAMMA_PAGE_LIMIT == official._GAMMA_MARKETS_PAGE_LIMIT == 100


def test_gamma_markets_slug_query_uses_official_builder() -> None:
    params = gamma_markets_slug_query_params("btc-updown-5m-1")
    assert params == {"slug": "btc-updown-5m-1"}


def test_paginate_gamma_events_continues_when_page_is_full_cap() -> None:
    pages = {
        0: [{"id": str(i)} for i in range(GAMMA_PAGE_LIMIT)],
        100: [{"id": "tail"}],
    }
    offsets: list[int] = []

    def fetch(offset: int) -> list[dict[str, str]]:
        offsets.append(offset)
        return pages.get(offset, [])

    events = paginate_gamma_events(fetch)
    assert offsets == [0, 100]
    assert len(events) == GAMMA_PAGE_LIMIT + 1
