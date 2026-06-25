from __future__ import annotations

from polysignal_lab.nautilus_runtime.market_data import PolySignalPriceToBeatData, PolySignalSpotData
from polysignal_lab.nautilus_runtime.sidecar_data import SidecarDataActor


class FakePublisher:
    def __init__(self) -> None:
        self.published: list[object] = []

    def publish_data(self, data_type: object, data: object) -> None:
        self.published.append(data)


def test_sidecar_actor_updates_registry_and_publishes_spot() -> None:
    publisher = FakePublisher()
    actor = SidecarDataActor(publisher=publisher)

    actor.publish_spot(asset="BTC", symbol="BTCUSD", price=100001.0, source="polymarket_rtds", freshness_ms=9, ts_event=1, ts_init=2)

    assert isinstance(publisher.published[-1], PolySignalSpotData)
    assert actor.sidecar.spot_for("btc").price == 100001.0


def test_sidecar_actor_updates_registry_and_publishes_price_to_beat() -> None:
    publisher = FakePublisher()
    actor = SidecarDataActor(publisher=publisher)

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
    assert actor.sidecar.ptb_for("condition-1").verified is True
