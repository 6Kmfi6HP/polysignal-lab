from __future__ import annotations

import asyncio
import sys
from collections.abc import Coroutine
from types import SimpleNamespace
from typing import Any, cast

from polysignal_lab.config import Settings
from polysignal_lab.data.price_to_beat_provider import PriceToBeatResult
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.nautilus_runtime.market_data import PolySignalMarketMetaData, PolySignalPriceToBeatData, PolySignalSpotData
from polysignal_lab.nautilus_runtime.sidecar_data import PolySignalRuntimeSidecarActor, SidecarDataActor


class FakePublisher:
    def __init__(self) -> None:
        self.published: list[object] = []

    def publish_data(self, data_type: object, data: object) -> None:
        self.published.append(data)


def _install_fake_polymarket_id_helper(monkeypatch) -> None:
    def helper(condition_id: str, token_id: str) -> str:
        return f"{condition_id}-{token_id}.POLYMARKET"

    monkeypatch.setitem(
        sys.modules,
        "nautilus_trader.adapters.polymarket",
        SimpleNamespace(get_polymarket_instrument_id=helper),
    )


def test_sidecar_actor_updates_registry_and_publishes_spot() -> None:
    publisher = FakePublisher()
    actor = SidecarDataActor(publisher=publisher)

    actor.publish_spot(asset="BTC", symbol="BTCUSD", price=100001.0, source="polymarket_rtds", freshness_ms=9, ts_event=1, ts_init=2)

    assert isinstance(publisher.published[-1], PolySignalSpotData)
    spot = actor.sidecar.spot_for("btc")
    assert spot is not None
    assert spot.price == 100001.0


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
    ptb = actor.sidecar.ptb_for("condition-1")
    assert ptb is not None
    assert ptb.verified is True


def test_sidecar_actor_publish_market_metadata_preserves_existing_instrument_ids() -> None:
    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )

    publisher = FakePublisher()
    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token.POLYMARKET", "up-token", Side.UP),
            down=InstrumentTokenMeta("down-token.POLYMARKET", "down-token", Side.DOWN),
        )
    )
    actor = SidecarDataActor(publisher=publisher, registry=registry)

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

    pair = registry.by_condition("condition-btc-5m")
    assert pair is not None
    assert pair.up.instrument_id == "up-token.POLYMARKET"
    assert pair.down.instrument_id == "down-token.POLYMARKET"


def test_runtime_sidecar_actor_on_start_publishes_metadata_and_ptb(monkeypatch) -> None:
    import polysignal_lab.nautilus_runtime.sidecar_data as sidecar_mod
    from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
    from polysignal_lab.nautilus_bridge.market_registry import PolymarketMarketRegistry

    _install_fake_polymarket_id_helper(monkeypatch)
    published: list[object] = []
    created: list[Coroutine[Any, Any, object]] = []

    class DummyTask:
        def cancel(self) -> None:
            return None

    def fake_create_task(coro: Coroutine[Any, Any, object]) -> DummyTask:
        created.append(coro)
        return DummyTask()

    actor = PolySignalRuntimeSidecarActor(
        settings=Settings(),
        markets=(
            Market(
                market_id="btc-5m",
                market_slug="btc-updown-5m",
                condition_id="condition-btc-5m",
                asset="BTC",
                timeframe="5m",
                outcome_tokens=[
                    OutcomeToken(token_id="up-token", side=Side.UP, outcome_name="Up", market_id="btc-5m"),
                    OutcomeToken(token_id="down-token", side=Side.DOWN, outcome_name="Down", market_id="btc-5m"),
                ],
            ),
        ),
        registry=PolymarketMarketRegistry(),
        sidecar=ExternalDataSidecar(),
        anchor_store=None,
    )
    actor.publish_data = lambda data_type, data: published.append(data)

    async def fake_get(market):
        _ = market
        return PriceToBeatResult(
            value=99950.0,
            source="anchor",
            verified=True,
            anchor_source="chainlink",
            anchor_lag_ms=5,
            from_anchor_service=True,
        )

    monkeypatch.setattr("asyncio.create_task", fake_create_task)
    monkeypatch.setattr(sidecar_mod, "register_polysignal_data_types", lambda: None)
    monkeypatch.setattr(actor.ptb_provider, "get", fake_get)

    actor.on_start()

    assert any(isinstance(item, PolySignalMarketMetaData) for item in published)
    asyncio.run(created[0])
    for coro in created[1:]:
        cast(Coroutine[Any, Any, object], coro).close()
    assert any(isinstance(item, PolySignalPriceToBeatData) for item in published)
