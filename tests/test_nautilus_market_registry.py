from __future__ import annotations

import pytest

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import OutcomeToken
from polysignal_lab.nautilus_bridge.market_registry import MarketPairMeta, PolymarketMarketRegistry
from factories import MarketFactoryConfig, sample_market


def test_market_registry_registers_binary_yes_no_pair() -> None:
    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m"))
    pair = MarketPairMeta.from_market(market, up_instrument_id="PM-UP", down_instrument_id="PM-DOWN")
    registry = PolymarketMarketRegistry()

    registry.register(pair)

    assert registry.by_condition(market.condition_id) == pair
    assert registry.by_token(market.token_for(Side.UP).token_id) == pair
    assert registry.by_token(market.token_for(Side.DOWN).token_id) == pair
    assert pair.up.instrument_id == "PM-UP"
    assert pair.down.instrument_id == "PM-DOWN"


def test_market_registry_rejects_non_binary_market() -> None:
    market = sample_market().model_copy(
        update={
            "outcome_tokens": [
                OutcomeToken(token_id="a", side=Side.UP, outcome_name="A", market_id="m"),
                OutcomeToken(token_id="b", side=Side.DOWN, outcome_name="B", market_id="m"),
                OutcomeToken(token_id="c", side=Side.UP, outcome_name="C", market_id="m"),
            ]
        }
    )

    with pytest.raises(ValueError, match="binary YES/NO"):
        MarketPairMeta.from_market(market)
