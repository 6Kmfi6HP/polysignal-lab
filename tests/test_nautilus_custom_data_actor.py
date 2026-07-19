"""
Input: __future__, __future__.annotations, types, types.SimpleNamespace, typing, typing.Any, typing.cast, nautilus_trader.core, nautilus_trader.core.nautilus_pyo3, nautilus_trader.core.nautilus_pyo3.PolymarketRtdsCryptoPrice
Output: test_custom_data_publisher_publishes_price_to_beat_as_pyo3_custom_data, test_custom_data_publisher_publishes_market_metadata_without_shadow_state, test_market_rotation_actor_accepts_managed_rtds_source, test_market_rotation_actor_subscribes_to_managed_rtds_spot, test_market_rotation_actor_does_not_construct_legacy_rtds_feed, test_pyo3_engine_routes_rtds_custom_data_by_data_type, FakePublisher
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""


from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from nautilus_trader.core import nautilus_pyo3
from nautilus_trader.core.nautilus_pyo3 import PolymarketRtdsCryptoPrice

from polysignal_lab.config import Settings
from polysignal_lab.nautilus_runtime import market_rotation
from polysignal_lab.nautilus_runtime.custom_data_types import (
    PolySignalMarketMetaData,
    PolySignalPriceToBeatData,
    custom_data_type,
    unwrap_custom_data,
)
from polysignal_lab.nautilus_runtime.custom_data_publisher import CustomDataPublisher
from polysignal_lab.nautilus_runtime.market_rotation import MarketRotationActor
from polysignal_lab.nautilus_runtime.polymarket_clients import (
    polymarket_rtds_data_client_id,
)


class FakePublisher:
    def __init__(self) -> None:
        self.published: list[tuple[object, object]] = []

    def publish_data(self, data_type: object, data: object) -> None:
        self.published.append((data_type, data))


def _actor(settings: Settings) -> MarketRotationActor:
    settings.runtime.nautilus.market_rotation.enabled = False
    return MarketRotationActor(settings=settings)


def test_custom_data_publisher_publishes_price_to_beat_as_pyo3_custom_data() -> None:
    publisher = FakePublisher()
    actor = CustomDataPublisher(publisher=publisher)

    actor.publish_price_to_beat(
        condition_id="condition-1",
        value=100000.0,
        source="anchor",
        verified=True,
        from_anchor_service=True,
        anchor_source="chainlink",
        anchor_lag_ms=15,
        ts_event=1,
        ts_init=2,
    )

    data_type, envelope = publisher.published[-1]
    assert data_type == custom_data_type(PolySignalPriceToBeatData)
    assert isinstance(envelope, nautilus_pyo3.CustomData)
    assert isinstance(unwrap_custom_data(envelope), PolySignalPriceToBeatData)
    assert not hasattr(actor, "registry")


def test_custom_data_publisher_publishes_market_metadata_without_shadow_state() -> None:
    publisher = FakePublisher()
    actor = CustomDataPublisher(publisher=publisher)
    payload = PolySignalMarketMetaData(
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        asset="BTC",
        timeframe="5m",
        start_ts_ns=0,
        end_ts_ns=0,
        up_token_id="up-token",
        down_token_id="down-token",
        ts_event=1,
        ts_init=2,
    )

    actor.publish_market_metadata(payload)

    data_type, envelope = publisher.published[-1]
    assert data_type == custom_data_type(PolySignalMarketMetaData)
    assert unwrap_custom_data(envelope) is payload
    assert not hasattr(actor, "registry")


def test_market_rotation_actor_accepts_managed_rtds_source() -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "polymarket_rtds"

    actor = _actor(settings)

    assert actor.settings.runtime.nautilus.spot_data.source == "polymarket_rtds"


def test_market_rotation_actor_subscribes_to_managed_rtds_spot(
    monkeypatch,
) -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "polymarket_rtds"
    actor = _actor(settings)
    fake_clock = SimpleNamespace(timestamp_ns=lambda: 1_700_000_000_000_000_000)
    monkeypatch.setattr(
        MarketRotationActor,
        "trader_id",
        property(lambda _self: "TEST-TRADER"),
    )
    monkeypatch.setattr(
        MarketRotationActor,
        "clock",
        property(lambda _self: fake_clock),
    )
    subscriptions: list[tuple[object, object | None]] = []
    published: list[object] = []
    actor.subscribe_data = cast(
        Any,
        lambda data_type, client_id=None: subscriptions.append((data_type, client_id)),
    )
    actor.publish_data = lambda data_type, data: published.append(data)

    actor.on_start()
    published.clear()
    actor.on_data(
        PolymarketRtdsCryptoPrice("BTCUSD", "100000.0", 0, 0, 1, 1)
    )

    from polysignal_lab.nautilus_runtime.custom_data_types import (
        polymarket_rtds_crypto_price_data_type,
        polymarket_rtds_crypto_symbols,
    )

    expected_client = polymarket_rtds_data_client_id(settings.markets.timeframes)
    expected = [
        (
            polymarket_rtds_crypto_price_data_type(symbol),
            expected_client,
        )
        for symbol in polymarket_rtds_crypto_symbols(
            settings.markets.assets,
            settings.data.binance.symbols,
        )
    ]
    assert subscriptions == expected
    assert published == []
    assert all(
        getattr(data_type, "metadata", None) is not None
        and "symbol" in getattr(data_type, "metadata")
        for data_type, _ in subscriptions
    )


def test_market_rotation_actor_does_not_construct_legacy_rtds_feed() -> None:
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "polymarket_rtds"

    actor = _actor(settings)

    assert actor is not None
    assert not hasattr(actor, "rtds_feed")
    assert not hasattr(market_rotation, "PolymarketRtdsPriceFeed")


def test_pyo3_engine_routes_rtds_custom_data_by_data_type() -> None:
    rtds_type = custom_data_type(PolymarketRtdsCryptoPrice)
    other_type = nautilus_pyo3.DataType("OtherSpotPrice")

    class ProbeActor(nautilus_pyo3.DataActor):
        def __init__(self) -> None:
            super().__init__(
                nautilus_pyo3.DataActorConfig(
                    actor_id=nautilus_pyo3.ActorId("RTDS-Probe")
                )
            )
            self.received: list[object] = []

        def on_start(self) -> None:
            self.subscribe_data(rtds_type)

        def on_data(self, data: object) -> None:
            self.received.append(data)

    class PublisherActor(nautilus_pyo3.DataActor):
        def __init__(self) -> None:
            super().__init__(
                nautilus_pyo3.DataActorConfig(
                    actor_id=nautilus_pyo3.ActorId("RTDS-Publisher")
                )
            )

        def on_start(self) -> None:
            payload = PolymarketRtdsCryptoPrice("BTCUSD", "100000.0", 0, 0, 1, 2)
            self.publish_data(
                other_type,
                nautilus_pyo3.CustomData(other_type, payload),
            )
            self.publish_data(
                rtds_type,
                nautilus_pyo3.CustomData(rtds_type, payload),
            )

    engine = nautilus_pyo3.BacktestEngine(
        nautilus_pyo3.BacktestEngineConfig(
            trader_id=nautilus_pyo3.TraderId("RTDS-DISPATCH-001"),
            bypass_logging=True,
        )
    )
    probe = ProbeActor()
    engine.add_actor(probe)
    engine.add_actor(PublisherActor())

    try:
        engine.run()

        assert len(probe.received) == 1
        envelope = probe.received[0]
        assert isinstance(envelope, nautilus_pyo3.CustomData)
        assert envelope.data_type == rtds_type
        assert isinstance(unwrap_custom_data(envelope), PolymarketRtdsCryptoPrice)
    finally:
        engine.dispose()
