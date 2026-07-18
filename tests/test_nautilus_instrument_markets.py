"""
Input: nautilus_polymarket_fixtures, polysignal_lab
Output: test_instrument_market_builder_emits_binary_market_after_pair
Pos: Test Layer - Unit tests

🔄 Self-reference: When this file changes, update this index and PROJECT_INDEX.md
"""

from nautilus_polymarket_fixtures import polymarket_binary_instrument

from polysignal_lab.config import MarketConfig
from polysignal_lab.domain.enums import MarketStatus, Side
from polysignal_lab.nautilus_runtime.instrument_markets import (
    PolymarketInstrumentMarketBuilder,
)


def test_instrument_market_builder_emits_binary_market_after_pair() -> None:
    builder = PolymarketInstrumentMarketBuilder(
        MarketConfig(assets=["BTC"], timeframes=["5m"])
    )

    assert builder.add(polymarket_binary_instrument("uptoken", "Up")) is None
    market = builder.add(polymarket_binary_instrument("downtoken", "Down"))

    assert market is not None
    assert market.market_id == "market-1"
    assert market.condition_id == "0xcondition1"
    assert market.asset == "BTC"
    assert market.timeframe == "5m"
    assert market.token_for(Side.UP).token_id == "uptoken"
    assert market.token_for(Side.DOWN).token_id == "downtoken"


def test_unknown_market_can_become_active_without_terminal_tombstone() -> None:
    builder = PolymarketInstrumentMarketBuilder(
        MarketConfig(assets=["BTC"], timeframes=["5m"])
    )

    assert (
        builder.add(polymarket_binary_instrument("uptoken", "Up", active=False))
        is None
    )
    unknown = builder.add(
        polymarket_binary_instrument("downtoken", "Down", active=False)
    )

    assert unknown is not None
    assert unknown.status is MarketStatus.UNKNOWN
    assert builder.terminal_condition_ids() == ()

    active = builder.add(polymarket_binary_instrument("uptoken", "Up"))

    assert active is not None
    assert active.status is MarketStatus.ACTIVE
    assert builder.terminal_condition_ids() == ()
