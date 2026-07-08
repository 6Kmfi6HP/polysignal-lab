"""
Input: __future__, __future__.annotations, json, datetime, datetime.datetime, datetime.timezone, typing, typing.Any, typing.Callable, anyio
Output: PolymarketRtdsPriceFeed
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable

import anyio
import websockets

from polysignal_lab.config import PolymarketDataConfig
from polysignal_lab.data.state import SpotRegistry
from polysignal_lab.domain.spot import SpotPrice
from polysignal_lab.utils import safe_float, utc_now


class PolymarketRtdsPriceFeed:
    """Polymarket RTDS Chainlink crypto price feed."""

    def __init__(
        self,
        registry: SpotRegistry,
        config: PolymarketDataConfig | None = None,
        *,
        on_spot: Callable[[SpotPrice], None] | None = None,
    ) -> None:
        self.registry = registry
        self.config = config or PolymarketDataConfig()
        self.on_spot = on_spot
        self.running = False
        self.connected = False
        self.reconnect_count = 0
        self.last_error: str | None = None
        self.message_count = 0
        self.ignored_message_count = 0

    async def run(self) -> None:
        self.running = True
        while self.running:
            try:
                async with websockets.connect(self.config.rtds_ws_url, ping_interval=20, ping_timeout=60) as ws:
                    self.connected = True
                    self.last_error = None
                    await ws.send(json.dumps(self._subscribe_message()))
                    async for message in ws:
                        self.handle_message(message)
                    if self.running:
                        self.connected = False
                        self.reconnect_count += 1
                        await anyio.sleep(2.0)
            except (OSError, TimeoutError, websockets.exceptions.WebSocketException) as exc:
                self.connected = False
                self.reconnect_count += 1
                self.last_error = str(exc)
                await anyio.sleep(2.0)

    def stop(self) -> None:
        self.running = False
        self.connected = False

    def _subscribe_message(self) -> dict[str, object]:
        return {
            "action": "subscribe",
            "subscriptions": [
                {
                    "topic": "crypto_prices_chainlink",
                    "type": "*",
                    "filters": "",
                }
            ],
        }

    def handle_message(self, message: str | bytes | dict[str, Any]) -> None:
        if isinstance(message, (str, bytes)):
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                return
        else:
            payload = message
        if not isinstance(payload, dict):
            return
        body = payload.get("payload", payload)
        if not isinstance(body, dict):
            return
        symbol = _symbol(body)
        price = _price(body)
        if symbol is None or price is None:
            self.ignored_message_count += 1
            return
        asset = symbol.split("/", 1)[0].upper()
        if asset not in {item.upper() for item in self.config.rtds_assets}:
            self.ignored_message_count += 1
            return
        self.message_count += 1
        spot = SpotPrice(
            asset=asset,
            symbol=symbol.upper().replace("/", ""),
            price=price,
            source="polymarket_rtds",
            event_time=_event_time(body),
            received_at=utc_now(),
        )
        self.registry.update(spot)
        if self.on_spot is not None:
            self.on_spot(spot)


def _data_item(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the last item from payload's ``data`` list, if present."""
    data = payload.get("data")
    if isinstance(data, list) and data:
        item = data[-1]
        if isinstance(item, dict):
            return item
    return None


def _symbol(payload: dict[str, Any]) -> str | None:
    raw = payload.get("symbol")
    if isinstance(raw, str):
        return raw.lower()
    item = _data_item(payload)
    if item is not None:
        raw = item.get("symbol")
        if isinstance(raw, str):
            return raw.lower()
    return None


def _price(payload: dict[str, Any]) -> float | None:
    value = safe_float(payload.get("value"))
    if value is not None:
        return value
    item = _data_item(payload)
    if item is not None:
        return safe_float(item.get("value") or item.get("price"))
    return None


def _event_time(payload: dict[str, Any]) -> datetime | None:
    raw = payload.get("timestamp") or payload.get("ts")
    if raw is None:
        item = _data_item(payload)
        if item is not None:
            raw = item.get("timestamp") or item.get("ts")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value > 1e11:
        value /= 1000.0
    return datetime.fromtimestamp(value, tz=timezone.utc)
