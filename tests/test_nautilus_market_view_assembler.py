from __future__ import annotations

from datetime import UTC, datetime, timedelta

from polysignal_lab.alpha.types import SideBookView, SpotView, TradeView
from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
from polysignal_lab.nautilus_bridge.market_registry import MarketPairMeta, PolymarketMarketRegistry
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from factories import MarketFactoryConfig, sample_market


class FakeBookProvider:
    def __init__(self) -> None:
        self.books: dict[str, SideBookView] = {}
        self.trades: dict[str, tuple[TradeView, ...]] = {}

    def book_for_token(self, token_id: str) -> SideBookView | None:
        return self.books.get(token_id)

    def trades_for_token(self, token_id: str) -> tuple[TradeView, ...]:
        return self.trades.get(token_id, ())


def _components() -> tuple[MarketViewAssembler, MarketPairMeta, FakeBookProvider, ExternalDataSidecar]:
    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m", seconds_to_close=60, price_to_beat=100000.0))
    pair = MarketPairMeta.from_market(market)
    registry = PolymarketMarketRegistry()
    registry.register(pair)
    books = FakeBookProvider()
    sidecar = ExternalDataSidecar()
    assembler = MarketViewAssembler(registry=registry, books=books, sidecar=sidecar)
    return assembler, pair, books, sidecar


def test_assembler_builds_coherent_market_view() -> None:
    assembler, pair, books, sidecar = _components()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    books.books[pair.up.token_id] = SideBookView(pair.up.token_id, best_bid=0.81, best_ask=0.82, spread=0.01, freshness_ms=10)
    books.books[pair.down.token_id] = SideBookView(pair.down.token_id, best_bid=0.17, best_ask=0.18, spread=0.01, freshness_ms=20)
    books.trades[pair.up.token_id] = (TradeView(price=0.82, size=5.0, side="BUY", ts=now),)
    sidecar.update_spot(SpotView(asset="BTC", symbol="BTCUSD", price=100120.0, source="polymarket_rtds", freshness_ms=30))
    sidecar.update_price_to_beat(
        condition_id=pair.condition_id,
        value=100000.0,
        source="anchor",
        verified=True,
        from_anchor_service=True,
        anchor_source="chainlink",
        anchor_lag_ms=40,
    )

    view = assembler.build(pair.condition_id, created_at=now)

    assert view is not None
    assert view.market_id == pair.market_id
    assert view.condition_id == pair.condition_id
    assert view.ask_for(Side.UP) == 0.82
    assert view.ask_for(Side.DOWN) == 0.18
    assert view.spot is not None
    assert view.spot.price == 100120.0
    assert view.price_to_beat == 100000.0
    assert view.up_trades == books.trades[pair.up.token_id]
    assert view.metrics["price_to_beat_verified"] is True
    assert view.metrics["price_to_beat_from_anchor_service"] is True
    assert view.freshness.max_ms == 30


def test_assembler_returns_none_when_down_leg_missing() -> None:
    assembler, pair, books, sidecar = _components()
    books.books[pair.up.token_id] = SideBookView(pair.up.token_id, best_bid=0.81, best_ask=0.82, spread=0.01, freshness_ms=10)
    sidecar.update_spot(SpotView(asset="BTC", symbol="BTCUSD", price=100120.0, source="polymarket_rtds", freshness_ms=30))
    sidecar.update_price_to_beat(
        condition_id=pair.condition_id,
        value=100000.0,
        source="anchor",
        verified=True,
        from_anchor_service=True,
        anchor_source="chainlink",
        anchor_lag_ms=40,
    )

    assert assembler.build(pair.condition_id) is None


def test_assembler_returns_none_when_sidecar_data_missing() -> None:
    assembler, pair, books, _sidecar = _components()
    books.books[pair.up.token_id] = SideBookView(pair.up.token_id, best_bid=0.81, best_ask=0.82, spread=0.01, freshness_ms=10)
    books.books[pair.down.token_id] = SideBookView(pair.down.token_id, best_bid=0.17, best_ask=0.18, spread=0.01, freshness_ms=20)

    assert assembler.build(pair.condition_id) is None
