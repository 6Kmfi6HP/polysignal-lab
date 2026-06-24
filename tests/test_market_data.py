from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import JsonValue, TypeAdapter
from typing import assert_type

from polysignal_lab.config import BinanceDataConfig, MarketConfig, PolymarketDataConfig
from polysignal_lab.data.binance_spot_ws import BinanceSpotFeed
from polysignal_lab.data.market_snapshot import MarketSnapshotBuilder
from polysignal_lab.data.polymarket_clob_rest import PolymarketCLOBRestClient
from polysignal_lab.data.public_market_data_client import PublicMarketDataClient
from polysignal_lab.data.polymarket_clob_ws import PolymarketMarketWebSocket
from polysignal_lab.data.polymarket_market_discovery import MarketDiscovery
from polysignal_lab.data.price_to_beat_provider import PriceToBeatProvider
from polysignal_lab.data.state import OrderBookRegistry, SpotRegistry
from polysignal_lab.domain.enums import Side
from factories import BookFactoryConfig, SpotFactoryConfig, sample_book, sample_spot
from polysignal_lab.domain.orderbook import OrderBook

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "public_market_payloads.json"
FIXTURE_ADAPTER = TypeAdapter(dict[str, JsonValue])


def _fixtures() -> dict[str, JsonValue]:
    return FIXTURE_ADAPTER.validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))


@dataclass(frozen=True, slots=True)
class FakeRequest:
    url: str
    params: dict[str, str]
    headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class FakeResponse:
    payload: JsonValue

    def raise_for_status(self) -> None:
        return None

    def json(self) -> JsonValue:
        return self.payload


class FakeAsyncClient:
    def __init__(self, payloads: list[JsonValue]) -> None:
        self.payloads = payloads
        self.calls: list[FakeRequest] = []

    async def get(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> FakeResponse:
        self.calls.append(FakeRequest(url=url, params=params or {}, headers=headers or {}))
        payload = self.payloads[len(self.calls) - 1] if len(self.calls) <= len(self.payloads) else []
        return FakeResponse(payload)


class _FakePublicMarketData:
    async def get_book(self, token_id: str) -> OrderBook:
        raise NotImplementedError

    async def get_books(self, token_ids: list[str]) -> list[OrderBook]:
        return []

    async def get_mid(self, token_id: str) -> float | None:
        return None

    async def get_spread(self, token_id: str) -> float | None:
        return None


def test_fake_market_data_client_matches_protocol() -> None:
    client: PublicMarketDataClient = _FakePublicMarketData()
    assert_type(client, PublicMarketDataClient)

def _gamma_market_payload(
    *,
    slug: str,
    market_id: str,
    start: str,
    end: str,
    outcomes: str = "[\"Up\", \"Down\"]",
    token_ids: str = "[\"token-up\", \"token-down\"]",
) -> dict[str, JsonValue]:
    return {
        "id": f"event-{market_id}",
        "slug": slug,
        "ticker": slug,
        "title": "Bitcoin Up or Down",
        "active": True,
        "closed": False,
        "markets": [
            {
                "id": market_id,
                "conditionId": f"condition-{market_id}",
                "slug": slug,
                "question": "Bitcoin Up or Down",
                "active": True,
                "closed": False,
                "eventStartTime": start,
                "endDate": end,
                "outcomes": outcomes,
                "clobTokenIds": token_ids,
            }
        ],
    }

def test_binance_feed_url_and_parse_message() -> None:
    spots = SpotRegistry()
    feed = BinanceSpotFeed(BinanceDataConfig(), spots)

    feed.handle_message({"stream": "btcusdt@aggTrade", "data": {"s": "BTCUSDT", "p": "100.1", "E": 1}})

    spot = spots.get("BTC")
    assert spot is not None
    assert spot.price == 100.1


def test_polymarket_ws_book_message_updates_registry() -> None:
    registry = OrderBookRegistry()
    ws = PolymarketMarketWebSocket(PolymarketDataConfig(), registry)

    ws.handle_message(
        {
            "event_type": "book",
            "market": "m",
            "asset_id": "tok",
            "bids": [{"price": "0.4", "size": "1"}],
            "asks": [{"price": "0.5", "size": "1"}],
        }
    )
    ws.handle_message({"event_type": "last_trade_price", "asset_id": "tok", "price": "0.49"})

    book = registry.get("tok")
    assert book is not None
    assert book.best_ask == 0.5
    assert book.last_trade_price == 0.49


def test_last_trade_does_not_refresh_orderbook_depth_freshness() -> None:
    from polysignal_lab.domain.orderbook import OrderBook
    from polysignal_lab.utils import utc_now

    registry = OrderBookRegistry()
    now = utc_now()
    stale_received_at = now - timedelta(milliseconds=20_000)
    registry.update_from_snapshot(
        OrderBook(
            token_id="tok",
            bids=[],
            asks=[],
            received_at=stale_received_at,
        )
    )

    registry.update_last_trade("tok", 0.49)

    book = registry.get("tok")
    assert book is not None
    assert book.last_trade_price == 0.49
    assert book.received_at == stale_received_at
    assert registry.is_fill_eligible("tok", 10_000, now) is False


def test_books_for_market_hides_stale_marked_book_but_get_keeps_raw(market) -> None:
    registry = OrderBookRegistry()
    up_book = sample_book(market.token_for(Side.UP).token_id, BookFactoryConfig(ask=0.82))
    down_book = sample_book(market.token_for(Side.DOWN).token_id, BookFactoryConfig(ask=0.18))
    registry.update_from_snapshot(up_book)
    registry.update_from_snapshot(down_book)

    registry.mark_stale(up_book.token_id, "TICK_SIZE_CHANGE_RESEED_REQUIRED")

    up, down = registry.books_for_market(market)
    assert up is None
    assert down == down_book
    assert registry.get(up_book.token_id) == up_book
    assert registry.is_fill_eligible(up_book.token_id, 10_000, up_book.received_at) is False
    assert (
        registry.metrics.snapshot()["counters"].get(
            "paper_fill_rejected_TICK_SIZE_CHANGE_RESEED_REQUIRED"
        )
        == 1
    )


async def test_market_snapshot_builder_hides_stale_marked_book_from_signal_inputs(
    market,
) -> None:
    books = OrderBookRegistry()
    spots = SpotRegistry()
    up_book = sample_book(market.token_for(Side.UP).token_id, BookFactoryConfig(ask=0.82))
    down_book = sample_book(market.token_for(Side.DOWN).token_id, BookFactoryConfig(ask=0.18))
    books.update_from_snapshot(up_book)
    books.update_from_snapshot(down_book)
    books.mark_stale(up_book.token_id, "RECONNECT_RESEED_FAILED")
    spots.update(sample_spot(SpotFactoryConfig(asset=market.asset, price=100120.0)))

    snapshot = await MarketSnapshotBuilder(books, spots, PriceToBeatProvider()).build(market)

    assert snapshot.book_for(Side.UP) is None
    assert snapshot.up_ask is None
    assert snapshot.freshness.up_book_ms is None
    assert snapshot.metrics["up_ask"] is None
    assert snapshot.book_for(Side.DOWN) == down_book
    assert books.get(up_book.token_id) == up_book


async def test_failed_websocket_reseed_marks_subscribed_books_stale(
    tmp_path: Path, settings
) -> None:
    from polysignal_lab.app.scheduler import PolySignalScheduler
    from polysignal_lab.domain.orderbook import OrderBook

    class FailingRestClient:
        async def get_books(self, token_ids: list[str]) -> list[OrderBook]:
            raise RuntimeError("reseed failed")

    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)
    scheduler.rest = FailingRestClient()
    scheduler.ctx.books.update_from_snapshot(OrderBook(token_id="token-up"))
    scheduler.ctx.books.update_from_snapshot(OrderBook(token_id="token-down"))

    await scheduler._reseed_ws_books(["token-up", "token-down"])

    for token_id in ("token-up", "token-down"):
        state = scheduler.ctx.books.get_state(token_id)
        assert state is not None
        assert state.has_snapshot is False
        assert state.stale_reason == "RECONNECT_RESEED_FAILED"


def test_websocket_event_types_reconciliation() -> None:
    from polysignal_lab.domain.orderbook import OrderBook
    from polysignal_lab.utils import utc_now

    registry = OrderBookRegistry()
    ws = PolymarketMarketWebSocket(PolymarketDataConfig(), registry)

    registry.update_from_snapshot(OrderBook(token_id="token-up", source_timestamp="1710000000000"))

    ws.handle_message({"event_type": "tick_size_change", "asset_id": "token-up"})
    state = registry.get_state("token-up")
    assert state is not None
    assert registry.is_fill_eligible("token-up", 10000, utc_now()) is False
    assert state.stale_reason == "TICK_SIZE_CHANGE_RESEED_REQUIRED"
    assert registry.metrics.snapshot()["counters"].get("ws_event_tick_size_change") == 1

    ws.handle_message({"event_type": "some_unknown_event_type"})
    assert registry.metrics.snapshot()["counters"].get("ws_event_unknown_some_unknown_event_type") == 1


def test_order_book_parses_hash_field() -> None:
    from polysignal_lab.domain.orderbook import OrderBook

    payload = {
        "market": "market-1",
        "asset_id": "token-up",
        "hash": "test-hash-value",
        "bids": [],
        "asks": [],
    }
    book = OrderBook.from_polymarket(payload)
    assert book.hash == "test-hash-value"


def test_book_epoch_state_instantiation() -> None:
    from polysignal_lab.data.book_reconciliation import BookEpochState

    state = BookEpochState(
        token_id="token-1",
        epoch=1,
        has_snapshot=True,
        stale_reason=None,
        last_hash="hash-1",
        last_source_timestamp=None,
        last_received_at=None,
    )

    assert state.token_id == "token-1"


def test_registry_reconciliation_methods() -> None:
    from polysignal_lab.data.state import OrderBookRegistry
    from polysignal_lab.domain.orderbook import OrderBook
    from polysignal_lab.utils import utc_now

    registry = OrderBookRegistry()
    now = utc_now()

    # 1. Delta without snapshot is ignored/counted
    delta_book = OrderBook(token_id="token-1", source_timestamp="1710000000100", received_at=now)
    registry.update_from_delta(delta_book)
    assert registry.get("token-1") is None
    assert registry.metrics.snapshot()["counters"].get("delta_without_snapshot") == 1

    # 2. Snapshot creates eligibility
    snapshot_book = OrderBook(token_id="token-1", source_timestamp="1710000000000", received_at=now)
    registry.update_from_snapshot(snapshot_book)
    assert registry.get("token-1") == snapshot_book
    assert registry.is_fill_eligible("token-1", 10000, now) is True

    # 3. Delta after snapshot is accepted
    registry.update_from_delta(delta_book)
    assert registry.get("token-1") == delta_book

    # 4. Regression invalidates
    regressed_book = OrderBook(token_id="token-1", source_timestamp="1700000000000", received_at=now)
    registry.update_from_delta(regressed_book)
    assert registry.is_fill_eligible("token-1", 10000, now) is False
    assert registry.metrics.snapshot()["counters"].get("book_sequence_invalid") == 1


async def test_gamma_active_market_discovery_paginates_filters_and_extracts_token_ids() -> None:
    fixtures = _fixtures()
    page_1 = fixtures["gamma_event_page_1"]
    page_2 = fixtures["gamma_event_page_2"]
    if not isinstance(page_1, list) or not isinstance(page_2, list):
        raise AssertionError("gamma fixtures must be lists")
    padded_page_1 = page_1 + [page_1[1]] * 198
    client = FakeAsyncClient([padded_page_1, page_2, []])
    discovery = MarketDiscovery(
        PolymarketDataConfig(),
        MarketConfig(assets=["BTC"], timeframes=["5m"], active_only=True, closed=False),
        client=client,
    )

    markets = await discovery.discover()

    event_list_calls = [call for call in client.calls if call.url.endswith("/events")]
    assert [call.params["offset"] for call in event_list_calls] == ["0", "200"]
    assert all("Authorization" not in call.headers for call in client.calls)
    assert len(markets) == 1
    market = markets[0]
    assert market.market_id == "market-1"
    assert {token.token_id for token in market.outcome_tokens} == {"token-up", "token-down"}


async def test_gamma_discovery_skips_future_active_crypto_windows() -> None:
    payloads = [
        {
            "id": "event-future",
            "slug": "btc-updown-5m-4102444800",
            "title": "Bitcoin Up or Down - 5m",
            "active": True,
            "closed": False,
            "markets": [
                {
                    "id": "market-future",
                    "conditionId": "0xfuture",
                    "slug": "btc-updown-5m-4102444800",
                    "question": "Bitcoin Up or Down - 5m",
                    "active": True,
                    "closed": False,
                    "startDate": "2026-06-23T10:39:56Z",
                    "eventStartTime": "2100-01-01T00:00:00Z",
                    "endDate": "2100-01-01T00:05:00Z",
                    "outcomes": "[\"Up\", \"Down\"]",
                    "clobTokenIds": "[\"future-up\", \"future-down\"]",
                }
            ],
        }
    ]
    client = FakeAsyncClient([payloads])
    discovery = MarketDiscovery(
        PolymarketDataConfig(),
        MarketConfig(assets=["BTC"], timeframes=["5m"], active_only=True, closed=False),
        client=client,
    )

    markets = await discovery.discover()

    assert markets == []


async def test_gamma_discovery_fetches_current_slot_by_slug_when_list_has_only_future_windows(
    monkeypatch,
) -> None:
    from polysignal_lab.data import polymarket_market_discovery as discovery_module

    now = datetime(2026, 6, 23, 22, 41, tzinfo=timezone.utc)
    monkeypatch.setattr(discovery_module, "utc_now", lambda: now)
    future = _gamma_market_payload(
        slug="btc-updown-5m-4102444800",
        market_id="market-future",
        start="2100-01-01T00:00:00Z",
        end="2100-01-01T00:05:00Z",
    )
    current = _gamma_market_payload(
        slug="btc-updown-5m-1782254400",
        market_id="market-current",
        start="2026-06-23T22:40:00Z",
        end="2026-06-23T22:45:00Z",
    )
    client = FakeAsyncClient([[future], current])
    discovery = MarketDiscovery(
        PolymarketDataConfig(),
        MarketConfig(assets=["BTC"], timeframes=["5m"], active_only=True, closed=False),
        client=client,
    )

    markets = await discovery.discover()

    assert [market.market_id for market in markets] == ["market-current"]
    assert any(call.url.endswith("/events/slug/btc-updown-5m-1782254400") for call in client.calls)


async def test_gamma_discovery_maps_current_slot_tokens_by_outcome_label(monkeypatch) -> None:
    from polysignal_lab.data import polymarket_market_discovery as discovery_module

    now = datetime(2026, 6, 23, 22, 41, tzinfo=timezone.utc)
    monkeypatch.setattr(discovery_module, "utc_now", lambda: now)
    current = _gamma_market_payload(
        slug="btc-updown-5m-1782254400",
        market_id="market-current",
        start="2026-06-23T22:40:00Z",
        end="2026-06-23T22:45:00Z",
        outcomes="[\"Down\", \"Up\"]",
        token_ids="[\"token-down\", \"token-up\"]",
    )
    client = FakeAsyncClient([[], current])
    discovery = MarketDiscovery(
        PolymarketDataConfig(),
        MarketConfig(assets=["BTC"], timeframes=["5m"], active_only=True, closed=False),
        client=client,
    )

    markets = await discovery.discover()

    assert len(markets) == 1
    assert markets[0].token_for(Side.UP).token_id == "token-up"
    assert markets[0].token_for(Side.DOWN).token_id == "token-down"


async def test_gamma_discovery_dedupes_list_and_current_slug_payload(monkeypatch) -> None:
    from polysignal_lab.data import polymarket_market_discovery as discovery_module

    now = datetime(2026, 6, 23, 22, 41, tzinfo=timezone.utc)
    monkeypatch.setattr(discovery_module, "utc_now", lambda: now)
    current = _gamma_market_payload(
        slug="btc-updown-5m-1782254400",
        market_id="market-current",
        start="2026-06-23T22:40:00Z",
        end="2026-06-23T22:45:00Z",
    )
    client = FakeAsyncClient([[current], current])
    discovery = MarketDiscovery(
        PolymarketDataConfig(),
        MarketConfig(assets=["BTC"], timeframes=["5m"], active_only=True, closed=False),
        client=client,
    )

    markets = await discovery.discover()

    assert [market.market_id for market in markets] == ["market-current"]

async def test_clob_rest_public_book_mid_and_spread_parsing_handles_official_shapes() -> None:
    fixtures = _fixtures()
    midpoint_payload = fixtures["clob_midpoint"]
    if not isinstance(midpoint_payload, dict):
        raise AssertionError("CLOB midpoint fixture must be a JSON object")
    assert midpoint_payload == {"mid_price": "0.475"}
    client = FakeAsyncClient(
        [
            fixtures["polymarket_book"],
            midpoint_payload,
            fixtures["clob_spread"],
        ]
    )
    rest = PolymarketCLOBRestClient(PolymarketDataConfig(), client=client)

    book = await rest.get_book("token-up")
    mid = await rest.get_mid("token-up")
    spread = await rest.get_spread("token-up")

    assert book.token_id == "token-up"
    assert book.best_bid == 0.4
    assert book.best_ask == 0.52
    assert book.last_trade_price == 0.49
    assert mid == 0.475
    assert spread == 0.12
    assert [call.params["token_id"] for call in client.calls] == ["token-up", "token-up", "token-up"]
    assert all("Authorization" not in call.headers for call in client.calls)
