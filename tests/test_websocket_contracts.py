from __future__ import annotations

import json
from pathlib import Path

from pydantic import JsonValue, TypeAdapter

from polysignal_lab.config import BinanceDataConfig, PolymarketDataConfig
from polysignal_lab.data.binance_spot_ws import BinanceSpotFeed
from polysignal_lab.data.polymarket_clob_ws import PolymarketMarketWebSocket
from polysignal_lab.data.state import OrderBookRegistry, SpotRegistry


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
