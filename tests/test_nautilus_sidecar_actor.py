"""
Input: __future__, __future__.annotations, polysignal_lab.nautilus_runtime.custom_data_types, polysignal_lab.nautilus_runtime.custom_data_types.(, polysignal_lab.nautilus_runtime.sidecar_data, polysignal_lab.nautilus_runtime.sidecar_data.CustomDataPublisher
Output: test_custom_data_publisher_publishes_spot_without_local_store, test_custom_data_publisher_publishes_price_to_beat_without_local_store, test_custom_data_publisher_publishes_market_metadata_without_registering_state, test_market_rotation_actor_fails_fast_for_unmanaged_rtds_source, test_market_rotation_actor_does_not_construct_unmanaged_rtds_feed, test_market_rotation_actor_uses_clock_timer_for_startup, FakePublisher
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations


from polysignal_lab.nautilus_runtime.custom_data_types import (
    PolySignalMarketMetaData,
    PolySignalPriceToBeatData,
    PolySignalSpotData,
)
from polysignal_lab.nautilus_runtime.sidecar_data import CustomDataPublisher


class FakePublisher:
    def __init__(self) -> None:
        self.published: list[object] = []

    def publish_data(self, data_type: object, data: object) -> None:
        self.published.append(data)


def test_custom_data_publisher_publishes_price_to_beat_without_local_store() -> None:
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

    assert isinstance(publisher.published[-1], PolySignalPriceToBeatData)
    assert not hasattr(actor, "sidecar")
    assert not hasattr(actor, "registry")


def test_custom_data_publisher_publishes_market_metadata_without_registering_state() -> None:
    publisher = FakePublisher()
    actor = CustomDataPublisher(publisher=publisher)

    actor.publish_market_metadata(
        PolySignalMarketMetaData(
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
    )

    assert isinstance(publisher.published[-1], PolySignalMarketMetaData)
    assert not hasattr(actor, "registry")


def test_market_rotation_actor_accepts_managed_rtds_source() -> None:
    from polysignal_lab.config import Settings
    from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
    from polysignal_lab.nautilus_runtime.market_rotation import MarketRotationActor

    class FakeUniverse:
        async def refresh_once(self):
            return []

        def refresh_once_sync(self):
            return []

    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "polymarket_rtds"
    actor = MarketRotationActor(
        settings=settings,
        startup_markets=(),
        market_universe=FakeUniverse(),
        catalog=MarketCatalog(),
    )

    assert actor.settings.runtime.nautilus.sidecar.spot_source == "polymarket_rtds"


def test_market_rotation_actor_subscribes_to_managed_rtds_spot_and_does_not_republish(
    monkeypatch,
) -> None:
    from polysignal_lab.config import Settings
    from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
    from polysignal_lab.nautilus_runtime import market_rotation
    from polysignal_lab.nautilus_runtime.market_rotation import MarketRotationActor

    class FakeUniverse:
        async def refresh_once(self):
            return []

        def refresh_once_sync(self):
            return []

    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "polymarket_rtds"
    settings.runtime.nautilus.market_rotation.enabled = False
    actor = MarketRotationActor(
        settings=settings,
        startup_markets=(),
        market_universe=FakeUniverse(),
        catalog=MarketCatalog(),
    )
    subscriptions: list[tuple[object, object | None]] = []
    published: list[object] = []
    actor.subscribe_data = lambda data_type, client_id=None: subscriptions.append(
        (data_type, client_id)
    )
    actor.publish_data = lambda data_type, data: published.append(data)
    monkeypatch.setattr(market_rotation, "_register_polysignal_data_types_if_available", lambda: None)

    actor.on_start()
    published.clear()
    actor.on_data(
        PolySignalSpotData(
            asset="BTC",
            symbol="BTCUSD",
            price=100000.0,
            source="polymarket_rtds",
            freshness_ms=0,
            ts_event=1,
            ts_init=1,
        )
    )

    assert len(subscriptions) == 1
    assert getattr(subscriptions[0][0], "type", subscriptions[0][0]) is PolySignalSpotData
    assert str(subscriptions[0][1]) == "POLYSIGNAL_SPOT"
    assert published == []


def test_market_rotation_actor_does_not_construct_legacy_rtds_feed() -> None:
    from polysignal_lab.config import Settings
    from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
    from polysignal_lab.nautilus_runtime import market_rotation
    from polysignal_lab.nautilus_runtime.market_rotation import MarketRotationActor

    class FakeUniverse:
        async def refresh_once(self):
            return []

        def refresh_once_sync(self):
            return []

    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "polymarket_rtds"
    actor = MarketRotationActor(
        settings=settings,
        startup_markets=(),
        market_universe=FakeUniverse(),
        catalog=MarketCatalog(),
    )

    assert actor is not None
    assert not hasattr(market_rotation, "PolymarketRtdsPriceFeed")

def test_market_rotation_actor_uses_clock_timer_for_startup(monkeypatch) -> None:
    from datetime import timedelta

    from polysignal_lab.config import Settings
    from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.market_rotation import (
        REFRESH_TIMER_NAME,
        MarketRotationActor,
    )

    timers: list[tuple[str, timedelta, object]] = []

    class FakeClock:
        def __init__(self) -> None:
            self.now_ns = 1_782_144_000_000_000_000

        def timestamp_ns(self) -> int:
            return self.now_ns

        def set_timer(self, name, interval, callback):
            timers.append((name, interval, callback))

        def cancel_timer(self, name):
            timers.append((f"cancel:{name}", timedelta(seconds=0), None))

    class FakeUniverse:
        async def refresh_once(self):
            return []

        def refresh_once_sync(self):
            return []

    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "disabled"
    actor = MarketRotationActor(
        settings=settings,
        startup_markets=(),
        market_universe=FakeUniverse(),
        catalog=MarketCatalog(),
    )
    fake_clock = FakeClock()
    monkeypatch.setattr(
        MarketRotationActor,
        "clock",
        property(lambda self: fake_clock),
    )
    published: list[object] = []
    actor.publish_data = lambda data_type, data: published.append(data)
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.market_rotation.register_polysignal_data_types",
        lambda: None,
    )

    actor.on_start()

    assert timers[0][0] == REFRESH_TIMER_NAME
    assert callable(timers[0][2])
    universe = next(item for item in published if isinstance(item, PolySignalMarketUniverseData))
    assert universe.ts_event == fake_clock.now_ns
    assert universe.ts_init == fake_clock.now_ns