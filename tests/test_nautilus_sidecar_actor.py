from __future__ import annotations

from types import SimpleNamespace

from polysignal_lab.nautilus_runtime.market_data import (
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


def test_custom_data_publisher_publishes_spot_without_local_store() -> None:
    publisher = FakePublisher()
    actor = CustomDataPublisher(publisher=publisher)

    actor.publish_spot(
        asset="BTC",
        symbol="BTCUSD",
        price=100001.0,
        source="polymarket_rtds",
        freshness_ms=9,
        ts_event=1,
        ts_init=2,
    )

    assert isinstance(publisher.published[-1], PolySignalSpotData)
    assert not hasattr(actor, "sidecar")
    assert not hasattr(actor, "registry")


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
