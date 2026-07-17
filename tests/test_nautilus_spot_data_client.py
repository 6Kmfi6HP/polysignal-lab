"""
Input: __future__, types, pytest, polysignal_lab.nautilus_runtime.spot_data_client
Output: test_managed_rtds_client_emits_spot_custom_data, test_managed_rtds_client_filters_assets
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from nautilus_trader.model.data import CustomData

from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalSpotData
from polysignal_lab.nautilus_runtime.spot_data_client import (
    PolymarketRtdsSpotDataClient,
    PolymarketRtdsSpotDataClientFactory,
)
from polysignal_lab.nautilus_runtime.strategy.helpers import (
    _spot_data_client_id,
    _subscribe_custom_data,
)


def test_rtds_client_factory_implements_nautilus_factory_contract() -> None:
    from nautilus_trader.live.factories import LiveDataClientFactory

    assert issubclass(PolymarketRtdsSpotDataClientFactory, LiveDataClientFactory)


def _client(*, assets: set[str]) -> tuple[PolymarketRtdsSpotDataClient, list[object]]:
    client = PolymarketRtdsSpotDataClient.__new__(PolymarketRtdsSpotDataClient)
    client._assets = assets
    # __new__ clients cannot assign Cython Component._clock; stub the helper.
    client._framework_timestamp_ns = lambda: 2_000_000_000
    received: list[object] = []
    client._handle_data = received.append
    return client, received


def test_rtds_client_uses_the_nautilus_clock() -> None:
    holder = SimpleNamespace(
        _clock=SimpleNamespace(timestamp_ns=lambda: 2_000_000_000),
    )

    assert (
        PolymarketRtdsSpotDataClient._framework_timestamp_ns(holder) == 2_000_000_000
    )



@pytest.mark.asyncio
async def test_managed_rtds_client_waits_for_subscription_before_reader_start() -> None:
    client = PolymarketRtdsSpotDataClient.__new__(PolymarketRtdsSpotDataClient)
    client._running = False
    client._subscribed = False
    client._task = None

    async def fake_run() -> None:
        await asyncio.sleep(0)

    client._run = fake_run

    await client._connect()
    assert client._task is None

    client._subscribed = True
    await client._connect()
    assert client._task is not None
    await asyncio.sleep(0)
    await client._disconnect()

    client, received = _client(assets={"BTC"})

    client.handle_message(
        {
            "payload": {
                "symbol": "btc/usd",
                "value": "100.5",
                "timestamp": 2000,
            }
        }
    )

    assert len(received) == 1
    wrapped = received[0]
    assert isinstance(wrapped, CustomData)
    assert wrapped.data_type.type is PolySignalSpotData
    assert wrapped.data == PolySignalSpotData(
        asset="BTC",
        symbol="BTCUSD",
        price=100.5,
        source="polymarket_rtds",
        freshness_ms=0,
        ts_event=2_000_000_000_000,
        ts_init=2_000_000_000,
    )


def test_native_spot_subscription_routes_to_managed_client() -> None:
    calls: list[tuple[object, object | None]] = []

    class FakeStrategy:
        def subscribe_data(self, data_type: object, client_id: object | None = None) -> None:
            calls.append((data_type, client_id))

    _subscribe_custom_data(
        FakeStrategy(),
        PolySignalSpotData,
        client_id=_spot_data_client_id(),
    )

    assert len(calls) == 1
    assert calls[0][1] is not None
    assert str(calls[0][1]) == "POLYSIGNAL_SPOT"




@pytest.mark.asyncio
async def test_managed_rtds_client_backs_off_after_clean_disconnect(monkeypatch) -> None:
    import polysignal_lab.nautilus_runtime.spot_data_client as module

    client = PolymarketRtdsSpotDataClient.__new__(PolymarketRtdsSpotDataClient)
    client._running = True
    client._subscribed = True
    client._spot_config = SimpleNamespace(rtds_ws_url="ws://test")
    client._task = None
    sleeps: list[float] = []

    class FakeWebSocket:
        async def send(self, message: str) -> None:
            _ = message

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class FakeConnection:
        async def __aenter__(self):
            return FakeWebSocket()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(module.websockets, "connect", lambda *args, **kwargs: FakeConnection())

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        client._running = False

    monkeypatch.setattr(module.asyncio, "sleep", fake_sleep)

    await client._run()

    assert sleeps == [2.0]

    client, received = _client(assets={"BTC"})

    client.handle_message(
        {
            "payload": {
                "symbol": "eth/usd",
                "value": 2000.0,
                "timestamp": 2000,
            }
        }
    )

    assert received == []
