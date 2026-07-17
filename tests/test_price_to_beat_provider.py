"""
Input: __future__, __future__.annotations, datetime, datetime.UTC, datetime.datetime, polysignal_lab.data.price_to_beat_provider, polysignal_lab.data.price_to_beat_provider.PriceToBeatProvider, polysignal_lab.domain.anchor_price, polysignal_lab.domain.anchor_price.AnchorPrice, polysignal_lab.domain.enums
Output: test_ptb_provider_prefers_verified_anchor_over_metadata, _AnchorStore
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import UTC, datetime

from polysignal_lab.data.price_to_beat_provider import PriceToBeatProvider
from polysignal_lab.domain.anchor_price import AnchorPrice
from polysignal_lab.domain.enums import MarketStatus, Side
from polysignal_lab.domain.market import Market, OutcomeToken


class _AnchorStore:
    def __init__(self, anchor):
        self.anchor = anchor

    def get_verified_anchor_price(self, asset, timeframe, market_slug):
        return self.anchor

def _market(*, asset: str = "ETH", timeframe: str = "5m") -> Market:
    market_id = f"{asset.lower()}-{timeframe}"
    return Market(
        market_id=market_id,
        market_slug=f"{asset.lower()}-updown-{timeframe}-1782297000",
        condition_id=f"condition-{market_id}",
        question=f"{asset} Up or Down {timeframe}?",
        asset=asset,
        timeframe=timeframe,
        start_ts=datetime(2026, 6, 24, 10, 30, tzinfo=UTC),
        end_ts=datetime(2026, 6, 24, 10, 35, tzinfo=UTC),
        status=MarketStatus.ACTIVE,
        price_to_beat=None,
        outcome_tokens=[
            OutcomeToken(token_id=f"{market_id}-UP", side=Side.UP, outcome_name="Up", market_id=market_id),
            OutcomeToken(token_id=f"{market_id}-DOWN", side=Side.DOWN, outcome_name="Down", market_id=market_id),
        ],
        raw={"eventStartTime": "2026-06-24T10:30:00Z"},
    )


async def test_ptb_provider_prefers_verified_anchor_over_metadata() -> None:
    sample_market = _market(asset="BTC", timeframe="5m")
    anchor = AnchorPrice(
        asset="BTC",
        timeframe="5m",
        market_slug=sample_market.market_slug,
        window_start=datetime(2026, 6, 24, 10, 30, tzinfo=UTC),
        window_end=datetime(2026, 6, 24, 10, 35, tzinfo=UTC),
        price=64000.0,
        source="binance",
        verified=True,
        captured_at=datetime(2026, 6, 24, 10, 30, tzinfo=UTC),
        lag_ms=100,
    )
    sample_market.price_to_beat = 64100.0
    provider = PriceToBeatProvider(anchor_store=_AnchorStore(anchor))

    result = await provider.get(sample_market)

    assert result.value == 64000.0
    assert result.source == "anchor_service:binance"
    assert result.verified is True
    assert result.anchor_source == "binance"
    assert result.anchor_lag_ms == 100
    assert result.from_anchor_service is True
