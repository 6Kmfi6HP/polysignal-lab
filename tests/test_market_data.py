from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import JsonValue, TypeAdapter

from polysignal_lab.config import BinanceDataConfig, MarketConfig, PolymarketDataConfig
from polysignal_lab.data.binance_spot_ws import BinanceSpotFeed
from polysignal_lab.data.polymarket_clob_rest import PolymarketCLOBRestClient
from polysignal_lab.data.polymarket_clob_ws import PolymarketMarketWebSocket
from polysignal_lab.data.polymarket_market_discovery import MarketDiscovery
from polysignal_lab.data.state import OrderBookRegistry, SpotRegistry


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

    assert [call.params["offset"] for call in client.calls] == ["0", "200"]
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
