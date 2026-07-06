from __future__ import annotations

import pytest

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import OutcomeToken
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog, MarketPairMeta
from factories import MarketFactoryConfig, sample_market


def test_market_catalog_registers_binary_yes_no_pair() -> None:
    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m"))
    pair = MarketPairMeta.from_market(market)
    catalog = MarketCatalog()

    catalog.register(pair)

    assert catalog.by_condition(market.condition_id) == pair
    assert catalog.by_token(market.token_for(Side.UP).token_id) == pair
    assert catalog.by_token(market.token_for(Side.DOWN).token_id) == pair
    assert pair.up.token_id == market.token_for(Side.UP).token_id
    assert pair.down.token_id == market.token_for(Side.DOWN).token_id


def test_market_catalog_token_meta_returns_registered_side_metadata() -> None:
    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m"))
    pair = MarketPairMeta.from_market(market)
    catalog = MarketCatalog()

    catalog.register(pair)

    assert catalog.token_meta(market.token_for(Side.UP).token_id) == pair.up
    assert catalog.token_meta(market.token_for(Side.DOWN).token_id) == pair.down
    assert catalog.token_meta("missing") is None


def test_market_catalog_rejects_non_binary_market() -> None:
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


def test_market_catalog_derives_instrument_id_from_condition_and_token(monkeypatch) -> None:
    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m"))
    pair = MarketPairMeta.from_market(market)
    catalog = MarketCatalog()
    catalog.register(pair)

    monkeypatch.setattr(
        "polysignal_lab.nautilus_bridge.market_catalog.polymarket_instrument_id",
        lambda condition_id, token_id: f"{condition_id}-{token_id}.POLYMARKET",
    )

    assert catalog.instrument_id_for_token(pair.up.token_id) == f"{pair.condition_id}-{pair.up.token_id}.POLYMARKET"
    assert catalog.instrument_id_for_token("missing") is None


def test_market_catalog_uses_injected_instrument_id_resolver() -> None:
    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m"))
    pair = MarketPairMeta.from_market(market)
    seen: list[tuple[str, str]] = []

    def resolver(condition_id: str, token_id: str) -> str:
        seen.append((condition_id, token_id))
        return f"test-{condition_id}-{token_id}.POLYMARKET"

    catalog = MarketCatalog(instrument_id_resolver=resolver)
    catalog.register(pair)

    assert catalog.instrument_id_for_token(pair.up.token_id) == (
        f"test-{pair.condition_id}-{pair.up.token_id}.POLYMARKET"
    )
    assert seen == [(pair.condition_id, pair.up.token_id)]
