"""
Input: __future__, asyncio, contextlib, datetime, json, typing, websockets, nautilus_trader, polysignal_lab.config, polysignal_lab.nautilus_runtime.custom_data_types
Output: PolymarketRtdsSpotDataClientConfig, PolymarketRtdsSpotDataClient, PolymarketRtdsSpotDataClientFactory
Pos: Nautilus-managed spot data client

Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
import json
import logging
from typing import Any

import websockets
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.config import LiveDataClientConfig
from nautilus_trader.cache.cache import Cache
from nautilus_trader.data.messages import RequestData, SubscribeData, UnsubscribeData
from nautilus_trader.live.data_client import LiveDataClient
from nautilus_trader.live.factories import LiveDataClientFactory
from nautilus_trader.model.data import CustomData, DataType
from nautilus_trader.model.identifiers import ClientId

from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalSpotData
from polysignal_lab.utils import safe_float

logger = logging.getLogger("polysignal_lab.nautilus.spot_data_client")


class PolymarketRtdsSpotDataClientConfig(LiveDataClientConfig):
    rtds_ws_url: str = "wss://ws-live-data.polymarket.com"
    assets: tuple[str, ...] = ("BTC", "ETH", "SOL", "XRP")


class PolymarketRtdsSpotDataClient(LiveDataClient):
    """Publish Polymarket RTDS Chainlink prices through Nautilus DataEngine."""

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        client_id: ClientId,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
        config: PolymarketRtdsSpotDataClientConfig,
    ) -> None:
        super().__init__(
            loop=loop,
            client_id=client_id,
            venue=None,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            config=config,
        )
        self._spot_config = config
        self._running = False
        self._subscribed = False
        self._task: asyncio.Task[None] | None = None
        self._assets = {asset.upper() for asset in config.assets}

    async def _connect(self) -> None:
        self._running = True
        if not self._subscribed:
            return
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def _disconnect(self) -> None:
        self._running = False
        task = self._task
        self._task = None
        if task is None or task is asyncio.current_task():
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _subscribe(self, command: SubscribeData) -> None:
        if not _is_spot_data_type(command.data_type):
            return
        self._subscribed = True
        await self._connect()

    async def _unsubscribe(self, command: UnsubscribeData) -> None:
        if not _is_spot_data_type(command.data_type):
            return
        self._subscribed = False
        await self._disconnect()

    async def _request(self, request: RequestData) -> None:
        _ = request

    async def _run(self) -> None:
        while self._running and self._subscribed:
            try:
                async with websockets.connect(
                    self._spot_config.rtds_ws_url,
                    ping_interval=20,
                    ping_timeout=60,
                ) as websocket:
                    await websocket.send(json.dumps(_subscribe_message()))
                    async for message in websocket:
                        if not self._running or not self._subscribed:
                            break
                        self.handle_message(message)
                if self._running and self._subscribed:
                    await asyncio.sleep(2.0)
            except asyncio.CancelledError:
                raise
            except (
                OSError,
                TimeoutError,
                websockets.exceptions.WebSocketException,
            ) as exc:
                if self._running and self._subscribed:
                    logger.warning("RTDS spot connection lost: %s", exc)
                    await asyncio.sleep(2.0)
            except Exception:
                logger.exception("RTDS spot reader failed")
                if self._running and self._subscribed:
                    await asyncio.sleep(2.0)

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
            return
        asset = symbol.split("/", 1)[0].upper()
        if asset not in self._assets:
            return
        received_ns = self._framework_timestamp_ns()
        event_time = _event_time(body)
        event_ns = (
            _timestamp_ns(event_time)
            if event_time is not None
            else received_ns
        )
        self._handle_data(
            CustomData(
                data_type=DataType(PolySignalSpotData),
                data=PolySignalSpotData(
                    asset=asset,
                    symbol=symbol.upper().replace("/", ""),
                    price=price,
                    source="polymarket_rtds",
                    freshness_ms=0,
                    ts_event=event_ns,
                    ts_init=received_ns,
                ),
            )
        )

    def _framework_timestamp_ns(self) -> int:
        value = int(self._clock.timestamp_ns())
        if value <= 0:
            raise RuntimeError("Nautilus framework clock returned an invalid timestamp")
        return value


def _data_item(payload: dict[str, Any]) -> dict[str, Any] | None:
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
    raw = item.get("symbol") if item is not None else None
    return raw.lower() if isinstance(raw, str) else None


def _price(payload: dict[str, Any]) -> float | None:
    value = safe_float(payload.get("value"))
    if value is not None:
        return value
    item = _data_item(payload)
    if item is None:
        return None
    return safe_float(item.get("value") or item.get("price"))


def _event_time(payload: dict[str, Any]) -> datetime | None:
    raw = payload.get("timestamp") or payload.get("ts")
    item = _data_item(payload)
    if raw is None and item is not None:
        raw = item.get("timestamp") or item.get("ts")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value > 1e11:
        value /= 1000.0
    return datetime.fromtimestamp(value, tz=UTC)


def _is_spot_data_type(data_type: object) -> bool:
    return getattr(data_type, "type", data_type) is PolySignalSpotData


def _subscribe_message() -> dict[str, object]:
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


def _timestamp_ns(value: datetime) -> int:
    current = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return int(current.timestamp() * 1_000_000_000)


class PolymarketRtdsSpotDataClientFactory(LiveDataClientFactory):
    @staticmethod
    def create(
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: PolymarketRtdsSpotDataClientConfig,
        msgbus: object,
        cache: object,
        clock: object,
    ) -> PolymarketRtdsSpotDataClient:
        return PolymarketRtdsSpotDataClient(
            loop=loop,
            client_id=ClientId(name),
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            config=config,
        )
