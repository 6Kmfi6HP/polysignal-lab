from __future__ import annotations

import json
from datetime import datetime, timezone

import anyio
import websockets
from pydantic import JsonValue

from polysignal_lab.config import BinanceDataConfig
from polysignal_lab.data.state import SpotRegistry
from polysignal_lab.domain.spot import SpotPrice
from polysignal_lab.utils import safe_float, utc_now

JsonObject = dict[str, JsonValue]


class BinanceSpotFeed:
    def __init__(self, config: BinanceDataConfig, registry: SpotRegistry):
        self.config = config
        self.registry = registry
        self.running = False
        self.connected = False
        self.reconnect_count = 0
        self.last_error: str | None = None

    def note_connected(self) -> None:
        self.connected = True
        self.last_error = None

    def note_reconnect(self, exc: BaseException) -> None:
        self.connected = False
        self.reconnect_count += 1
        self.last_error = str(exc)

    def combined_stream_url(self) -> str:
        streams: list[str] = []
        for symbol in self.config.symbols.values():
            sym = symbol.lower()
            for stream in self.config.streams:
                streams.append(f"{sym}@{stream}")
        return f"{self.config.base_ws_url}?streams={'/'.join(streams)}"

    async def run(self) -> None:
        self.running = True
        while self.running:
            try:
                async with websockets.connect(self.combined_stream_url(), ping_interval=20, ping_timeout=60) as ws:
                    self.note_connected()
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

    def handle_message(self, message: str | bytes | JsonObject) -> None:
        if isinstance(message, (str, bytes)):
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                return
        else:
            payload = message
        if not isinstance(payload, dict):
            return
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            return
        symbol = data.get("s") or data.get("symbol")
        if not symbol:
            return
        asset = self._asset_for_symbol(str(symbol))
        if not asset:
            return
        price = _spot_price(data)
        if price is None:
            return
        event_time = _event_time(data)
        self.registry.update(SpotPrice(asset=asset, symbol=str(symbol), price=price, event_time=event_time, received_at=utc_now()))

    def _asset_for_symbol(self, symbol: str) -> str | None:
        normalized = symbol.upper()
        for asset, configured in self.config.symbols.items():
            if configured.upper() == normalized:
                return asset.upper()
        return None


def _spot_price(data: JsonObject) -> float | None:
    bid = safe_float(data.get("b"))
    ask = safe_float(data.get("a"))
    if bid is not None and ask is not None:
        return round((bid + ask) / 2.0, 10)
    return safe_float(data.get("p") or data.get("c") or data.get("a") or data.get("b"))


def _event_time(data: JsonObject) -> datetime | None:
    raw = data.get("E") or data.get("eventTime")
    if not raw:
        return None
    try:
        return datetime.fromtimestamp(int(str(raw)) / 1000, tz=timezone.utc)
    except ValueError:
        return None
