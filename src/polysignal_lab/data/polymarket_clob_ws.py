from __future__ import annotations

from collections.abc import Callable, Coroutine

import json
from queue import Queue
from typing import Any

import anyio
import websockets
from pydantic import JsonValue

from polysignal_lab.config import PolymarketDataConfig
from polysignal_lab.data.state import OrderBookRegistry
from polysignal_lab.domain.orderbook import BookLevel, OrderBook
from polysignal_lab.utils import new_id, safe_float, utc_now

JsonObject = dict[str, JsonValue]


class PolymarketMarketWebSocket:
    def __init__(self, config: PolymarketDataConfig, registry: OrderBookRegistry):
        self.config = config
        self.registry = registry
        self.resolved_events: Queue[JsonObject] = Queue()
        self.running = False
        self.reseed_hook: Callable[[list[str]], Coroutine[Any, Any, None]] | None = None
        self.connected = False
        self.reconnect_count = 0
        self.subscribed_token_count = 0
        self.last_error: str | None = None

    def note_connected(self, token_ids: list[str]) -> None:
        self.connected = True
        self.subscribed_token_count = len(token_ids)
        self.last_error = None

    def note_reconnect(self, exc: BaseException) -> None:
        self.connected = False
        self.reconnect_count += 1
        self.last_error = str(exc)
        self.registry.metrics.inc("clob_ws_reconnect_count")

    async def subscribe(self, token_ids: list[str]) -> None:
        self.running = True
        payload = {"assets_ids": token_ids, "type": "market", "custom_feature_enabled": True}
        while self.running:
            try:
                if self.reseed_hook is not None:
                    try:
                        await self.reseed_hook(token_ids)
                    except Exception:
                        pass
                async with websockets.connect(self.config.market_ws_url, ping_interval=20, ping_timeout=20) as ws:
                    self.note_connected(token_ids)
                    await ws.send(json.dumps(payload))
                    async for message in ws:
                        self.handle_message(message)
                    if self.running:
                        self.note_reconnect(RuntimeError("websocket closed"))
                        await anyio.sleep(2.0)
            except (OSError, TimeoutError, websockets.exceptions.WebSocketException) as exc:
                self.note_reconnect(exc)
                await anyio.sleep(2.0)

    def stop(self) -> None:
        self.running = False
        self.connected = False

    def handle_message(self, message: str | bytes | JsonObject | list[JsonValue]) -> None:
        if isinstance(message, (str, bytes)):
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                self.registry.metrics.inc("ws_decode_errors")
                return
        else:
            payload = message
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    self.handle_message(item)
            return
        if not isinstance(payload, dict):
            return
        event_type = payload.get("event_type") or payload.get("type")
        match event_type:
            case "book":
                self.registry.update_from_snapshot(OrderBook.from_polymarket(payload, received_at=utc_now()))
            case "price_change" | "price_changes":
                self._apply_price_change(payload)
            case "best_bid_ask":
                self._apply_best_bid_ask(payload)
            case "last_trade_price":
                self._apply_last_trade(payload)
            case "tick_size_change":
                self.registry.metrics.inc("ws_event_tick_size_change")
                token_id = _token_id(payload)
                if token_id:
                    self.registry.mark_stale(token_id, "TICK_SIZE_CHANGE_RESEED_REQUIRED")
            case "market_resolved":
                self.registry.metrics.inc("ws_event_market_resolved")
                self.resolved_events.put_nowait({"event_id": new_id("resolved"), **payload})
            case "new_market" | None:
                return
            case _:
                self.registry.metrics.inc(f"ws_event_unknown_{event_type}")
                return

    def _apply_price_change(self, payload: JsonObject) -> None:
        raw_changes = payload.get("price_changes") or payload.get("changes") or [payload]
        if not isinstance(raw_changes, list):
            return
        for change in raw_changes:
            if isinstance(change, dict):
                self._apply_single_price_change(change)

    def _apply_single_price_change(self, change: JsonObject) -> None:
        token_id = _token_id(change)
        if token_id is None:
            return
        book = self.registry.get(token_id)
        if not book:
            self.registry.update_from_delta(OrderBook(token_id=token_id, received_at=utc_now()))
            return
        price = safe_float(change.get("price"))
        size = safe_float(change.get("size"), 0.0)
        if price is None or size is None:
            return
        updated = book.model_copy(deep=True)
        target = updated.bids if str(change.get("side") or "").upper() == "BUY" else updated.asks
        target[:] = [level for level in target if level.price != price]
        if size > 0:
            target.append(BookLevel(price=price, size=size))
        updated.bids = sorted(updated.bids, key=lambda level: level.price, reverse=True)
        updated.asks = sorted(updated.asks, key=lambda level: level.price)
        updated.received_at = utc_now()

        best_bid = safe_float(change.get("best_bid"))
        best_ask = safe_float(change.get("best_ask"))
        if best_bid is not None or best_ask is not None:
            self.registry.update_telemetry(token_id, best_bid, best_ask)

        self.registry.update_from_delta(updated)

    def _apply_best_bid_ask(self, payload: JsonObject) -> None:
        token_id = _token_id(payload)
        if token_id is None:
            return
        best_bid = safe_float(payload.get("best_bid"))
        best_ask = safe_float(payload.get("best_ask"))
        self.registry.update_telemetry(token_id, best_bid, best_ask)

    def _apply_last_trade(self, payload: JsonObject) -> None:
        token_id = _token_id(payload)
        if token_id is None:
            return
        price = safe_float(payload.get("price") or payload.get("last_trade_price"))
        if price is None:
            return
        self.registry.update_last_trade(token_id, price)


def _token_id(payload: JsonObject) -> str | None:
    raw = payload.get("asset_id") or payload.get("token_id") or payload.get("assetId")
    return str(raw) if raw else None
