from __future__ import annotations

from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.configured_markets import instrument_load_ids
from factories import MarketFactoryConfig, sample_market


def test_instrument_load_ids_use_market_catalog(monkeypatch) -> None:
    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m"))
    seen: list[str] = []

    def instrument_id_for_token(self: MarketCatalog, token_id: str) -> str:
        seen.append(token_id)
        return f"catalog:{token_id}.POLYMARKET"

    monkeypatch.setattr(
        MarketCatalog,
        "instrument_id_for_token",
        instrument_id_for_token,
    )

    assert instrument_load_ids((market,)) == tuple(
        sorted(
            (
                f"catalog:{market.token_for(Side.UP).token_id}.POLYMARKET",
                f"catalog:{market.token_for(Side.DOWN).token_id}.POLYMARKET",
            )
        )
    )
    assert seen == [
        market.token_for(Side.UP).token_id,
        market.token_for(Side.DOWN).token_id,
    ]
