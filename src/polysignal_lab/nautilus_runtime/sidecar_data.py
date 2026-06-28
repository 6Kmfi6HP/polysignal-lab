"""Sidecar data actor — publishes PolySignal custom data on the Nautilus bus.

The actor wraps an :class:`ExternalDataSidecar` and a market registry, exposing
``publish_*`` methods that both update the in-memory sidecar/registry and push a
typed payload onto the Nautilus MessageBus via the injected publisher.

Nautilus is never imported at module load time. The ``DataType`` wrapper is
constructed lazily inside each publish method; when Nautilus is not installed,
the data class itself is passed as ``data_type`` so tests stay Nautilus-free.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from importlib import import_module
from types import new_class
from typing import Callable, Protocol, cast

from polysignal_lab.alpha.types import SpotView
from polysignal_lab.config import Settings
from polysignal_lab.data.anchor_price_service import AnchorPriceService, AnchorPriceStore
from polysignal_lab.data.polymarket_rtds_ws import PolymarketRtdsPriceFeed
from polysignal_lab.data.price_to_beat_provider import PriceToBeatProvider
from polysignal_lab.data.state import SpotRegistry
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.spot import SpotPrice
from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
from polysignal_lab.nautilus_bridge.market_registry import MarketPairMeta, PolymarketMarketRegistry
from polysignal_lab.nautilus_runtime.market_data import (
    PolySignalMarketMetaData,
    PolySignalMarketUniverseData,
    PolySignalPriceToBeatData,
    PolySignalSpotData,
    register_polysignal_data_types,
)


class _Publisher(Protocol):
    def publish_data(self, data_type: object, data: object) -> None: ...


def _data_type(payload_cls: type[object]) -> object:
    """Return ``DataType(payload_cls)`` when Nautilus is installed, else the class itself."""
    try:
        module = import_module("nautilus_trader.model.data")
    except ModuleNotFoundError:
        return payload_cls
    data_type_cls = cast(Callable[[type[object]], object], getattr(module, "DataType"))
    return data_type_cls(payload_cls)



class SidecarDataActor:
    def __init__(
        self,
        *,
        publisher: _Publisher,
        sidecar: ExternalDataSidecar | None = None,
        registry: PolymarketMarketRegistry | None = None,
    ) -> None:
        self.publisher = publisher
        self.sidecar = sidecar or ExternalDataSidecar()
        self.registry = registry

    def publish_spot(
        self,
        *,
        asset: str,
        symbol: str,
        price: float,
        source: str,
        freshness_ms: int | None,
        ts_event: int,
        ts_init: int,
    ) -> None:
        data = PolySignalSpotData(
            asset=asset,
            symbol=symbol,
            price=price,
            source=source,
            freshness_ms=freshness_ms,
            ts_event=ts_event,
            ts_init=ts_init,
        )
        self.sidecar.update_spot(SpotView(asset=asset, symbol=symbol, price=price, source=source, freshness_ms=freshness_ms))
        self.publisher.publish_data(_data_type(PolySignalSpotData), data)

    def publish_price_to_beat(
        self,
        *,
        condition_id: str,
        value: float,
        source: str,
        verified: bool,
        from_anchor_service: bool,
        anchor_source: str | None,
        anchor_lag_ms: int | None,
        ts_event: int,
        ts_init: int,
    ) -> None:
        data = PolySignalPriceToBeatData(
            condition_id=condition_id,
            value=value,
            source=source,
            verified=verified,
            from_anchor_service=from_anchor_service,
            anchor_source=anchor_source,
            anchor_lag_ms=anchor_lag_ms,
            ts_event=ts_event,
            ts_init=ts_init,
        )
        self.sidecar.update_price_to_beat(
            condition_id=condition_id,
            value=value,
            source=source,
            verified=verified,
            from_anchor_service=from_anchor_service,
            anchor_source=anchor_source,
            anchor_lag_ms=anchor_lag_ms,
        )
        self.publisher.publish_data(_data_type(PolySignalPriceToBeatData), data)

    def publish_market_metadata(self, meta: PolySignalMarketMetaData) -> None:
        self.publisher.publish_data(_data_type(PolySignalMarketMetaData), meta)
        if self.registry is not None:
            self.registry.register(_pair_from_metadata(self.registry, meta))

    def publish_market_universe(self, data: PolySignalMarketUniverseData) -> None:
        self.publisher.publish_data(_data_type(PolySignalMarketUniverseData), data)


def runtime_sidecar_actor_type(
    nautilus_base: type[object] | None,
    config_factory: Callable[[], object] | None,
) -> type["PolySignalRuntimeSidecarActor"]:
    if nautilus_base is None:
        return PolySignalRuntimeSidecarActor

    def exec_body(namespace: dict[str, object]) -> None:
        def __init__(
            self: PolySignalRuntimeSidecarActor,
            *,
            settings: Settings,
            markets: tuple[Market, ...],
            registry: PolymarketMarketRegistry,
            sidecar: ExternalDataSidecar,
            anchor_store: AnchorPriceStore | None = None,
        ) -> None:
            base_init = cast(Callable[..., None], nautilus_base.__init__)
            if config_factory is None:
                base_init(self)
            else:
                base_init(self, config=config_factory())
            PolySignalRuntimeSidecarActor.__init__(
                self,
                settings=settings,
                markets=markets,
                registry=registry,
                sidecar=sidecar,
                anchor_store=anchor_store,
            )

        namespace["__init__"] = __init__

    actor_cls = new_class(
        "NautilusPolySignalRuntimeSidecarActor",
        (PolySignalRuntimeSidecarActor, nautilus_base),
        exec_body=exec_body,
    )
    return cast(type[PolySignalRuntimeSidecarActor], actor_cls)


class PolySignalRuntimeSidecarActor:
    def __init__(
        self,
        *,
        settings: Settings,
        markets: tuple[Market, ...],
        registry: PolymarketMarketRegistry,
        sidecar: ExternalDataSidecar,
        anchor_store: AnchorPriceStore | None = None,
    ) -> None:
        self.settings = settings
        self.markets = markets
        self.registry = registry
        self.sidecar = sidecar
        self.publisher = SidecarDataActor(
            publisher=self,
            sidecar=sidecar,
            registry=registry,
        )
        self.spots = SpotRegistry()
        self.anchor_prices = (
            AnchorPriceService(self.spots, anchor_store)
            if anchor_store is not None
            else None
        )
        self.ptb_provider = PriceToBeatProvider(
            use_crypto_price_api=settings.data.polymarket.use_crypto_price_api,
            anchor_store=anchor_store,
        )
        self.rtds_feed = PolymarketRtdsPriceFeed(
            self.spots,
            settings.data.polymarket,
            on_spot=self._on_spot,
        )
        self._rtds_task = None

    def publish_data(self, data_type: object, data: object) -> None:
        base_publish = getattr(super(PolySignalRuntimeSidecarActor, self), "publish_data", None)
        if callable(base_publish):
            _ = base_publish(data_type, data)

    def on_start(self) -> None:
        register_polysignal_data_types()
        for market in self.markets:
            self.publisher.publish_market_metadata(_market_metadata(market))
            _ = asyncio.create_task(self._publish_price_to_beat(market))
        if self.settings.runtime.nautilus.sidecar.spot_source == "polymarket_rtds":
            self._rtds_task = asyncio.create_task(self.rtds_feed.run())

    def on_stop(self) -> None:
        self.rtds_feed.stop()
        task = self._rtds_task
        if task is not None:
            task.cancel()

    def _on_spot(self, spot: SpotPrice) -> None:
        self.publisher.publish_spot(
            asset=spot.asset,
            symbol=spot.symbol,
            price=spot.price,
            source=spot.source,
            freshness_ms=spot.freshness_ms(),
            ts_event=_timestamp_ns(spot.event_time),
            ts_init=_timestamp_ns(spot.received_at),
        )
        if self.anchor_prices is None:
            return
        for market in self.markets:
            if market.asset.upper() != spot.asset.upper():
                continue
            _ = self.anchor_prices.capture_for_market(market)
            _ = asyncio.create_task(self._publish_price_to_beat(market))

    async def _publish_price_to_beat(self, market: Market) -> None:
        result = await self.ptb_provider.get(market)
        if result.value is None:
            return
        now = datetime.now(UTC)
        self.publisher.publish_price_to_beat(
            condition_id=market.condition_id,
            value=result.value,
            source=result.source,
            verified=result.verified,
            from_anchor_service=result.from_anchor_service,
            anchor_source=result.anchor_source,
            anchor_lag_ms=result.anchor_lag_ms,
            ts_event=_timestamp_ns(now),
            ts_init=_timestamp_ns(now),
        )


def _market_metadata(market: Market) -> PolySignalMarketMetaData:
    now = datetime.now(UTC)
    return PolySignalMarketMetaData(
        market_id=market.market_id,
        market_slug=market.market_slug,
        condition_id=market.condition_id,
        asset=market.asset,
        timeframe=market.timeframe,
        start_ts_ns=_timestamp_ns(market.start_ts),
        end_ts_ns=_timestamp_ns(market.end_ts),
        up_token_id=market.token_for(Side.UP).token_id,
        down_token_id=market.token_for(Side.DOWN).token_id,
        ts_event=_timestamp_ns(now),
        ts_init=_timestamp_ns(now),
    )


def _timestamp_ns(value: datetime | None) -> int:
    if value is None:
        return 0
    current = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    delta = current.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000


def _datetime_ns(value: int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1_000_000_000, UTC)


def _pair_from_metadata(
    registry: PolymarketMarketRegistry,
    meta: PolySignalMarketMetaData,
) -> MarketPairMeta:
    from polysignal_lab.nautilus_runtime.instrument_mapping import polymarket_instrument_id

    existing = registry.by_condition(meta.condition_id)
    up_instrument_id = (
        existing.up.instrument_id
        if existing is not None
        else polymarket_instrument_id(meta.condition_id, meta.up_token_id)
    )
    down_instrument_id = (
        existing.down.instrument_id
        if existing is not None
        else polymarket_instrument_id(meta.condition_id, meta.down_token_id)
    )
    return MarketPairMeta(
        market_id=meta.market_id,
        market_slug=meta.market_slug,
        condition_id=meta.condition_id,
        asset=meta.asset.upper(),
        timeframe=meta.timeframe,
        start_ts=_datetime_ns(meta.start_ts_ns),
        end_ts=_datetime_ns(meta.end_ts_ns),
        up=type(existing.up if existing is not None else MarketPairMeta.from_metadata(meta).up)(
            instrument_id=up_instrument_id,
            token_id=meta.up_token_id,
            side=Side.UP,
        ),
        down=type(existing.down if existing is not None else MarketPairMeta.from_metadata(meta).down)(
            instrument_id=down_instrument_id,
            token_id=meta.down_token_id,
            side=Side.DOWN,
        ),
    )
