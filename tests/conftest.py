"""
Input: __future__, __future__.annotations, pytest, polysignal_lab.config, polysignal_lab.config.Settings, factories, factories.MarketFactoryConfig, factories.sample_market, factories.sample_market_view
Output: settings, market, market_view
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""










from __future__ import annotations

import pytest

from polysignal_lab.config import Settings
from factories import MarketFactoryConfig, sample_market, sample_market_view


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def market():
    return sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m", seconds_to_close=120, price_to_beat=100000.0))


@pytest.fixture
def market_view(market):
    return sample_market_view(
        asset=market.asset,
        timeframe=market.timeframe,
        seconds_to_close=120,
        price_to_beat=100000.0,
        up_ask=0.82,
        down_ask=0.18,
        spot_price=100120.0,
        spot_source="polymarket_rtds",
        metrics={
            "price_to_beat_source": "market_metadata",
            "price_to_beat_verified": True,
            "price_to_beat_from_anchor_service": False,
            "spot_source": "polymarket_rtds",
        },
    )
