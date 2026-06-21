from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import websockets

from polysignal_lab.config import PolymarketDataConfig
from polysignal_lab.data.state import OrderBookRegistry
from polysignal_lab.domain.orderbook import OrderBook
from polysignal_lab.utils import new_id, utc_now


class PolymarketMarketWebSocket:
    def __init__(self, config: PolymarketDataConfig, registry: OrderBookRegistry):
        self.config = config
        self.registry = registry
        self.resolved_events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.running = False

    async def subscribe(self, token_ids: list[str]) -> None:
        self.running = True
        payload = {"assets_ids": token_ids, "type": "market", "custom_feature_enabled": True}
        while self.running:
            try:
                async with websockets.connect(self.config.market_ws_url, ping_interval=20, ping_timeout=20) as ws:
                    await ws.send(json.dumps(payload))
                    async for message in ws:
                        self.handle_message(message)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(2.0)

    def stop(self) -> None:
        self.running = False

    def handle_message(self, message: str | bytes | dict[str, Any]) -> None:
        if isinstance(message, (str, bytes)):
            payload = json.loads(message)
        else:
            payload = message
        if isinstance(payload, list):
            for item in payload:
                self.handle_message(item)
            return
        event_type = payload.get("event_type") or payload.get("type")
        if event_type == "book":
            book = OrderBook.from_polymarket(payload, received_at=utc_now())
            self.registry.update(book)
        elif event_type == "price_change":
            self._apply_price_change(payload)
        elif event_type == "best_bid_ask":
            self._apply_best_bid_ask(payload)
        elif event_type == "last_trade_price":
            self._apply_last_trade(payload)
        elif event_type == "market_resolved":
            self.resolved_events.put_nowait({"event_id": new_id("resolved"), **payload})

    def _apply_price_change(self, payload: dict[str, Any]) -> None:
        token_id = str(payload.get("asset_id") or payload.get("token_id"))
        book = self.registry.get(token_id)
        if not book:
            return
        updated = book.model_copy(deep=True)
        for change in payload.get("changes", []):
            side = change.get("side", "").upper()
            price = float(change.get("price", 0))
            size = float(change.get("size", 0))
            target = updated.bids if side == "BUY" else updated.asks
            target[:] = [level for level in target if level.price != price]
            if size > 0:
                from polysignal_lab.domain.orderbook import BookLevel
                target.append(BookLevel(price=price, size=size))
            updated.bids = sorted(updated.bids, key=lambda x: x.price, reverse=True)
            updated.asks = sorted(updated.asks, key=lambda x: x.price)
        updated.received_at = utc_now()
        self.registry.update(updated)

    def _apply_best_bid_ask(self, payload: dict[str, Any]) -> None:
        token_id = str(payload.get("asset_id") or payload.get("token_id"))
        book = self.registry.get(token_id)
        if not book:
            return
        from polysignal_lab.domain.orderbook import BookLevel
        updated = book.model_copy(deep=True)
        if payload.get("best_bid") is not None:
            updated.bids = [BookLevel(price=float(payload["best_bid"]), size=updated.bids[0].size if updated.bids else 0.0)] + updated.bids[1:]
        if payload.get("best_ask") is not None:
            updated.asks = [BookLevel(price=float(payload["best_ask"]), size=updated.asks[0].size if updated.asks else 0.0)] + updated.asks[1:]
        updated.received_at = utc_now()
        self.registry.update(updated)

    def _apply_last_trade(self, payload: dict[str, Any]) -> None:
        token_id = str(payload.get("asset_id") or payload.get("token_id"))
        book = self.registry.get(token_id)
        if not book:
            return
        updated = book.model_copy(deep=True)
        price = payload.get("price") or payload.get("last_trade_price")
        if price is not None:
            updated.last_trade_price = float(price)
        updated.received_at = utc_now()
        self.registry.update(updated)
