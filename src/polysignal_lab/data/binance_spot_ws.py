from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import websockets

from polysignal_lab.config import BinanceDataConfig
from polysignal_lab.data.state import SpotRegistry
from polysignal_lab.domain.spot import SpotPrice
from polysignal_lab.utils import safe_float, utc_now


class BinanceSpotFeed:
    def __init__(self, config: BinanceDataConfig, registry: SpotRegistry):
        self.config = config
        self.registry = registry
        self.running = False

    def combined_stream_url(self) -> str:
        streams: list[str] = []
        for symbol in self.config.symbols.values():
            sym = symbol.lower()
            for stream in self.config.streams:
                suffix = "aggTrade" if stream == "aggTrade" else stream
                streams.append(f"{sym}@{suffix}")
        return f"{self.config.base_ws_url}?streams={'/'.join(streams)}"

    async def run(self) -> None:
        self.running = True
        while self.running:
            try:
                async with websockets.connect(self.combined_stream_url(), ping_interval=20, ping_timeout=60) as ws:
                    async for message in ws:
                        self.handle_message(message)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(2.0)

    def stop(self) -> None:
        self.running = False

    def handle_message(self, message: str | bytes | dict) -> None:
        payload = json.loads(message) if isinstance(message, (str, bytes)) else message
        data = payload.get("data", payload)
        symbol = data.get("s") or data.get("symbol")
        if not symbol:
            return
        asset = self._asset_for_symbol(symbol)
        if not asset:
            return
        price = safe_float(data.get("p") or data.get("c") or data.get("a") or data.get("b"))
        if price is None:
            return
        event_time_raw = data.get("E") or data.get("eventTime")
        event_time = None
        if event_time_raw:
            event_time = datetime.fromtimestamp(int(event_time_raw) / 1000, tz=timezone.utc)
        self.registry.update(SpotPrice(asset=asset, symbol=symbol, price=price, event_time=event_time, received_at=utc_now()))

    def _asset_for_symbol(self, symbol: str) -> str | None:
        normalized = symbol.upper()
        for asset, configured in self.config.symbols.items():
            if configured.upper() == normalized:
                return asset.upper()
        return None
