from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import JsonValue, TypeAdapter

from polysignal_lab.app.scheduler import PolySignalScheduler
from polysignal_lab.config import BinanceDataConfig, PolymarketDataConfig, Settings
from polysignal_lab.data.binance_spot_ws import BinanceSpotFeed
from polysignal_lab.data.polymarket_clob_ws import PolymarketMarketWebSocket
from polysignal_lab.data.state import OrderBookRegistry, SpotRegistry
from polysignal_lab.utils import utc_now
from factories import sample_book


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "public_market_payloads.json"
FIXTURE_ADAPTER = TypeAdapter(dict[str, JsonValue])


def _fixtures() -> dict[str, JsonValue]:
    return FIXTURE_ADAPTER.validate_json(FIXTURE_PATH.read_text(encoding="utf-8"))


def _seed_polymarket_book(registry: OrderBookRegistry) -> PolymarketMarketWebSocket:
    ws = PolymarketMarketWebSocket(PolymarketDataConfig(), registry)
    book = _fixtures()["polymarket_book"]
    if isinstance(book, dict):
        ws.handle_message(book)
    return ws


class _FakeReseedRest:
    def __init__(self, returned_token_ids: tuple[str, ...]) -> None:
        self.returned_token_ids = returned_token_ids
        self.requested: tuple[str, ...] | None = None

    async def get_books(self, token_ids: list[str]) -> list[object]:
        self.requested = tuple(token_ids)
        return [sample_book(token_id) for token_id in self.returned_token_ids]


@pytest.mark.parametrize(
    "returned_token_ids",
    [
        pytest.param((), id="empty"),
        pytest.param(("token-refresh",), id="partial"),
    ],
)
async def test_reseed_marks_requested_tokens_missing_from_successful_response_stale(
    tmp_path: Path, returned_token_ids: tuple[str, ...]
) -> None:
    scheduler = PolySignalScheduler(Settings(), base_dir=tmp_path)
    requested_token_ids = ["token-refresh", "token-missing"]
    max_staleness_ms = scheduler.settings.data.polymarket.max_book_staleness_ms

    for token_id in requested_token_ids:
        scheduler.ctx.books.update(sample_book(token_id))
        assert scheduler.ctx.books.is_fill_eligible(token_id, max_staleness_ms, utc_now())

    rest = _FakeReseedRest(returned_token_ids)
    scheduler.market_data = rest

    await scheduler._reseed_ws_books(requested_token_ids)

    assert rest.requested == tuple(requested_token_ids)
    for token_id in set(requested_token_ids) - set(returned_token_ids):
        state = scheduler.ctx.books.get_state(token_id)
        assert state is not None
        assert state.has_snapshot is False
        assert state.stale_reason == "RECONNECT_RESEED_FAILED"
        assert not scheduler.ctx.books.is_fill_eligible(
            token_id, max_staleness_ms, utc_now()
        )
    for token_id in returned_token_ids:
        state = scheduler.ctx.books.get_state(token_id)
        assert state is not None
        assert state.has_snapshot is True
        assert scheduler.ctx.books.is_fill_eligible(
            token_id, max_staleness_ms, utc_now()
        )


async def test_websocket_subscribe_calls_reseed_hook() -> None:
    from unittest.mock import AsyncMock, patch

    registry = OrderBookRegistry()
    ws = PolymarketMarketWebSocket(None, registry)
    ws.reseed_hook = AsyncMock()

    ws.config = type("Config", (), {"market_ws_url": "ws://dummy"})()
    with patch("websockets.connect", side_effect=ValueError("stop")):
        try:
            ws.running = True
            await ws.subscribe(["token-1"])
        except ValueError as exc:
            assert str(exc) == "stop"
    ws.reseed_hook.assert_awaited_once_with(["token-1"])



def test_polymarket_price_change_before_snapshot_is_dropped_and_counted() -> None:
    registry = OrderBookRegistry()
    ws = PolymarketMarketWebSocket(PolymarketDataConfig(), registry)

    ws.handle_message(
        {
            "event_type": "price_change",
            "asset_id": "token-before-snapshot",
            "price": "0.41",
            "size": "10",
            "side": "BUY",
        }
    )

    assert registry.get("token-before-snapshot") is None
    assert registry.metrics.snapshot()["counters"].get("delta_without_snapshot") == 1

def test_polymarket_price_changes_event_updates_registry() -> None:
    registry = OrderBookRegistry()
    ws = _seed_polymarket_book(registry)
    before = registry.get("token-up")
    assert before is not None
    assert before.best_bid == 0.4
    assert before.best_ask == 0.52

    event = _fixtures()["polymarket_price_change"]
    if isinstance(event, dict):
        ws.handle_message(event)

    book = registry.get("token-up")
    assert book is not None
    assert book.best_bid == 0.41
    assert book.best_ask is None
    telemetry = registry.telemetry_for("token-up")
    assert telemetry["best_bid"] == 0.41
    assert telemetry["best_ask"] == 0.53


def test_polymarket_book_best_bid_ask_last_trade_and_lifecycle_events_are_public_contract_safe() -> None:
    registry = OrderBookRegistry()
    ws = _seed_polymarket_book(registry)

    fixtures = _fixtures()
    for key in ("polymarket_best_bid_ask", "polymarket_last_trade_price", "polymarket_new_market", "polymarket_market_resolved"):
        event = fixtures[key]
        if isinstance(event, dict):
            ws.handle_message(event)

    book = registry.get("token-up")
    assert book is not None
    assert book.best_bid == 0.4
    assert book.best_ask == 0.52
    assert book.last_trade_price == 0.51
    telemetry = registry.telemetry_for("token-up")
    assert telemetry["best_bid"] == 0.42
    assert telemetry["best_ask"] == 0.54
    assert ws.resolved_events.qsize() == 1
    assert registry.metrics.snapshot()["counters"].get("ws_event_market_resolved") == 1


def test_binance_bookticker_updates_spot_registry() -> None:
    spots = SpotRegistry()
    feed = BinanceSpotFeed(BinanceDataConfig(streams=["bookTicker"]), spots)

    event = _fixtures()["binance_book_ticker"]
    if isinstance(event, dict):
        feed.handle_message(event)

    spot = spots.get("BTC")
    assert spot is not None
    assert spot.symbol == "BTCUSDT"
    assert spot.price == 100.15


def test_malformed_public_market_events_are_ignored_without_crash() -> None:
    registry = OrderBookRegistry()
    ws = _seed_polymarket_book(registry)
    before = registry.get("token-up")
    assert before is not None

    for event in ("{", {"event_type": "price_change", "price_changes": [{"asset_id": "token-up", "price": "bad"}]}, []):
        ws.handle_message(event)

    after = registry.get("token-up")
    assert after is not None
    assert after.best_bid == before.best_bid
    assert after.best_ask == before.best_ask
    assert registry.metrics.snapshot()["counters"].get("ws_decode_errors") == 1


def test_polymarket_public_payload_text_is_not_executed() -> None:
    registry = OrderBookRegistry()
    ws = _seed_polymarket_book(registry)

    ws.handle_message(
        json.dumps(
            {
                "event_type": "new_market",
                "condition_id": "__import__('os').system('touch /tmp/polysignal_prompt_injection')",
                "clob_token_ids": ["do-not-run"],
            }
        )
    )

    assert not Path("/tmp/polysignal_prompt_injection").exists()


def test_market_resolved_message_updates_resolution_cache() -> None:
    from polysignal_lab.domain.enums import Side
    from polysignal_lab.domain.market import Market, OutcomeToken
    from polysignal_lab.paper.settlement_sources import WsResolutionCache

    cache = WsResolutionCache()
    ws = PolymarketMarketWebSocket(PolymarketDataConfig(), OrderBookRegistry(), resolution_cache=cache)
    ws.handle_message({"event_type": "market_resolved", "condition_id": "0x" + "1" * 64, "winning_asset_id": "token-up"})

    market = Market(
        market_id="market-1",
        market_slug="slug",
        condition_id="0x" + "1" * 64,
        asset="BTC",
        timeframe="5m",
        outcome_tokens=[
            OutcomeToken(token_id="token-up", side=Side.UP, outcome_name="Up", market_id="market-1"),
            OutcomeToken(token_id="token-down", side=Side.DOWN, outcome_name="Down", market_id="market-1"),
        ],
    )

    assert ws.resolved_events.qsize() == 1
    assert cache.evidence_for(market).outcome_values_by_token == {"token-up": 1.0, "token-down": 0.0}
