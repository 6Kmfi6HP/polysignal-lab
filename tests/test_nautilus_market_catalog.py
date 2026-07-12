"""
Input: __future__, __future__.annotations, pytest, polysignal_lab.domain.enums, polysignal_lab.domain.enums.Side, polysignal_lab.domain.market, polysignal_lab.domain.market.OutcomeToken, polysignal_lab.nautilus_bridge.market_catalog, polysignal_lab.nautilus_bridge.market_catalog.MarketCatalog, polysignal_lab.nautilus_bridge.market_catalog.MarketPairMeta
Output: test_market_catalog_registers_binary_yes_no_pair, test_register_replacement_removes_previous_token_indexes, test_market_catalog_token_meta_returns_registered_side_metadata, test_market_catalog_rejects_non_binary_market, test_market_catalog_derives_instrument_id_from_condition_and_token, test_market_catalog_uses_injected_instrument_id_resolver, test_market_catalog_resolves_market_from_instrument_id, test_market_catalog_from_sidecar_metadata_keeps_optional_binary_option_fields
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import OutcomeToken
from polysignal_lab.nautilus_bridge.market_catalog import (
    InstrumentTokenMeta,
    MarketCatalog,
    MarketPairMeta,
)
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
    assert pair.up.outcome == market.token_for(Side.UP).outcome_name
    assert pair.up.description == market.question
    assert pair.up.expiry == market.end_ts


def test_register_replacement_removes_previous_token_indexes() -> None:
    catalog = MarketCatalog(instrument_id_resolver=lambda condition_id, token_id: token_id)
    first = MarketPairMeta(
        market_id="market-1",
        market_slug="market-1",
        condition_id="condition-1",
        asset="BTC",
        timeframe="5m",
        start_ts=None,
        end_ts=None,
        up=InstrumentTokenMeta("up-old", Side.UP),
        down=InstrumentTokenMeta("down-old", Side.DOWN),
    )
    replacement = MarketPairMeta(
        market_id="market-1",
        market_slug="market-1",
        condition_id="condition-1",
        asset="BTC",
        timeframe="5m",
        start_ts=None,
        end_ts=None,
        up=InstrumentTokenMeta("up-new", Side.UP),
        down=InstrumentTokenMeta("down-new", Side.DOWN),
    )

    catalog.register(first)
    catalog.register(replacement)

    assert catalog.by_token("up-old") is None
    assert catalog.by_token("down-old") is None
    assert catalog.by_token("up-new") == replacement
    assert catalog.by_token("down-new") == replacement


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

    monkeypatch.setitem(
        sys.modules,
        "nautilus_trader.adapters.polymarket",
        SimpleNamespace(
            get_polymarket_instrument_id=lambda condition_id, token_id: (
                f"{condition_id}-{token_id}.POLYMARKET"
            )
        ),
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


def test_market_catalog_resolves_market_from_instrument_id() -> None:
    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m"))
    pair = MarketPairMeta.from_market(market)
    catalog = MarketCatalog(
        instrument_id_resolver=lambda condition_id, token_id: f"{condition_id}:{token_id}"
    )
    catalog.register(pair)

    instrument_id = f"{pair.condition_id}:{pair.up.token_id}"

    assert catalog.market_id_for_instrument(instrument_id) == pair.market_id
    assert catalog.market_id_for_instrument("missing") is None


def test_instrument_token_meta_keeps_positional_constructors_compatible() -> None:
    meta = InstrumentTokenMeta("token", Side.UP)

    assert meta.side == Side.UP
    assert meta.outcome is None


def test_market_catalog_from_sidecar_metadata_keeps_optional_binary_option_fields() -> None:
    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m"))
    pair = MarketPairMeta.from_metadata(
        SimpleNamespace(
            market_id=market.market_id,
            market_slug=market.market_slug,
            condition_id=market.condition_id,
            asset=market.asset,
            timeframe=market.timeframe,
            start_ts_ns=1,
            end_ts_ns=int(market.end_ts.timestamp() * 1_000_000_000) if market.end_ts is not None else None,
            up_token_id=market.token_for(Side.UP).token_id,
            down_token_id=market.token_for(Side.DOWN).token_id,
            question=market.question,
            up_outcome=market.token_for(Side.UP).outcome_name,
            down_outcome=market.token_for(Side.DOWN).outcome_name,
        )
    )

    assert pair.up.outcome == market.token_for(Side.UP).outcome_name
    assert pair.down.outcome == market.token_for(Side.DOWN).outcome_name
    assert pair.up.description == market.question
    assert pair.up.expiry == market.end_ts
