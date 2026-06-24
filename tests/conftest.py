from __future__ import annotations

import pytest

from polysignal_lab.config import Settings
from polysignal_lab.data.price_to_beat_provider import PriceToBeatProvider
from polysignal_lab.data.state import OrderBookRegistry, SpotRegistry
from polysignal_lab.data.market_snapshot import MarketSnapshotBuilder
from polysignal_lab.domain.enums import Side
from factories import (
    BookFactoryConfig,
    MarketFactoryConfig,
    SpotFactoryConfig,
    sample_book,
    sample_market,
    sample_spot,
)


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def market():
    return sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m", seconds_to_close=120, price_to_beat=100000.0))


@pytest.fixture
def books(market):
    reg = OrderBookRegistry()
    reg.update(sample_book(market.token_for(Side.UP).token_id, BookFactoryConfig(ask=0.82, bid=0.79, size=500)))
    reg.update(sample_book(market.token_for(Side.DOWN).token_id, BookFactoryConfig(ask=0.18, bid=0.15, size=500)))
    return reg


@pytest.fixture
def spots():
    reg = SpotRegistry()
    reg.update(sample_spot(SpotFactoryConfig(asset="BTC", price=100120.0)).model_copy(update={"source": "polymarket_rtds"}))
    return reg


@pytest.fixture
async def snapshot(market, books, spots):
    builder = MarketSnapshotBuilder(books, spots, PriceToBeatProvider())
    return await builder.build(market)
