from __future__ import annotations

from datetime import UTC, datetime

from polysignal_lab.alpha.types import SpotView
from polysignal_lab.data.state import MarketRegistry, OrderBookRegistry, SpotRegistry
from polysignal_lab.domain.enums import MarketStatus, Side
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.domain.orderbook import BookLevel, OrderBook
from polysignal_lab.domain.spot import SpotPrice
from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
from polysignal_lab.nautilus_bridge.market_registry import PolymarketMarketRegistry
from polysignal_lab.nautilus_runtime.book_data import NautilusBookDataProvider
from polysignal_lab.nautilus_runtime.data_ingestor import NautilusDataIngestor


def _market(active: bool = True) -> Market:
    return Market(
        market_id="m1",
        market_slug="btc-updown-5m",
        condition_id="c1",
        asset="BTC",
        timeframe="5m",
        status=MarketStatus.ACTIVE if active else MarketStatus.CLOSED,
        price_to_beat=100_000.0,
        outcome_tokens=[
            OutcomeToken(token_id="up-token", side=Side.UP, outcome_name="Up", market_id="m1"),
            OutcomeToken(token_id="down-token", side=Side.DOWN, outcome_name="Down", market_id="m1"),
        ],
    )


def _book(token_id: str) -> OrderBook:
    return OrderBook(
        token_id=token_id,
        bids=[BookLevel(price=0.81, size=10.0)],
        asks=[BookLevel(price=0.83, size=10.0)],
        received_at=datetime.now(UTC),
    )


class RecordingMatchingClient:
    def __init__(self) -> None:
        self.books: list[tuple[str, OrderBook]] = []
        self.trades: list[tuple[str, float, float, str | None, object | None]] = []

    def update_book(self, token_id: str, book: OrderBook) -> None:
        self.books.append((token_id, book))

    def update_trade(
        self,
        token_id: str,
        price: float,
        size: float,
        side: str | None,
        ts_event: object | None,
    ) -> None:
        self.trades.append((token_id, price, size, side, ts_event))


def _ingestor() -> tuple[NautilusDataIngestor, PolymarketMarketRegistry, ExternalDataSidecar, NautilusBookDataProvider, RecordingMatchingClient]:
    markets = MarketRegistry()
    markets.upsert_many([_market()])
    books = OrderBookRegistry()
    books.update(_book("up-token"))
    books.update_last_trade("up-token", price=0.82, size=2.0, timestamp=datetime.now(UTC).isoformat())
    spots = SpotRegistry()
    spots.update(SpotPrice(asset="BTC", symbol="BTC/USD", price=100_010.0, source="test", received_at=datetime.now(UTC)))
    bridge_registry = PolymarketMarketRegistry()
    sidecar = ExternalDataSidecar()
    provider = NautilusBookDataProvider()
    matching = RecordingMatchingClient()
    return (
        NautilusDataIngestor(
            markets=markets,
            books=books,
            spots=spots,
            bridge_registry=bridge_registry,
            sidecar=sidecar,
            book_data_provider=provider,
            matching_client=matching,
        ),
        bridge_registry,
        sidecar,
        provider,
        matching,
    )


def test_sync_all_registers_active_markets_and_returns_condition_ids() -> None:
    ingestor, bridge_registry, sidecar, _, _ = _ingestor()

    condition_ids = ingestor.sync_all()

    assert condition_ids == ("c1",)
    assert bridge_registry.by_condition("c1") is not None
    assert sidecar.ptb_for("c1") is not None


def test_sync_orderbooks_updates_provider_and_matching_client() -> None:
    ingestor, _, _, provider, matching = _ingestor()

    ingestor.sync_orderbooks()

    assert provider.book_for_token("up-token") is not None
    assert [token_id for token_id, _ in matching.books] == ["up-token"]
    assert matching.trades == [("up-token", 0.82, 2.0, None, None)]


def test_sync_orderbooks_sends_retained_trade_once_across_syncs() -> None:
    ingestor, _, _, _, matching = _ingestor()

    ingestor.sync_orderbooks()
    ingestor.sync_orderbooks()

    assert matching.trades == [("up-token", 0.82, 2.0, None, None)]


def test_sync_spots_reads_real_spot_registry() -> None:
    ingestor, _, sidecar, _, _ = _ingestor()

    ingestor.sync_spots()

    spot = sidecar.spot_for("BTC")
    assert isinstance(spot, SpotView)
    assert spot.price == 100_010.0
    assert spot.source == "test"


def test_empty_registries_are_noop() -> None:
    bridge_registry = PolymarketMarketRegistry()
    sidecar = ExternalDataSidecar()
    ingestor = NautilusDataIngestor(
        markets=MarketRegistry(),
        books=OrderBookRegistry(),
        spots=SpotRegistry(),
        bridge_registry=bridge_registry,
        sidecar=sidecar,
        book_data_provider=NautilusBookDataProvider(),
        matching_client=RecordingMatchingClient(),
    )

    assert ingestor.sync_all() == ()
