from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import new_class
from typing import Callable, Protocol, cast

from polysignal_lab.config import Settings
from polysignal_lab.data.anchor_price_service import AnchorPriceService, AnchorPriceStore
from polysignal_lab.data.polymarket_rtds_ws import PolymarketRtdsPriceFeed
from polysignal_lab.data.price_to_beat_provider import PriceToBeatProvider
from polysignal_lab.data.state import SpotRegistry
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.spot import SpotPrice
from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
from polysignal_lab.nautilus_bridge.market_registry import PolymarketMarketRegistry
from polysignal_lab.nautilus_runtime.market_data import (
    PolySignalMarketUniverseData,
    register_polysignal_data_types,
)
from polysignal_lab.nautilus_runtime.sidecar_data import (
    SidecarDataActor,
    _market_metadata,
    _timestamp_ns,
)


class _MarketUniverse(Protocol):
    async def refresh_once(self) -> list[Market]: ...


class _Health(Protocol):
    def mark_ok(self, name: str, **metrics: object) -> None: ...

    def mark_down(self, name: str, error: str | None = None, **metrics: object) -> None: ...


class MarketRotationActor:
    def __init__(
        self,
        *,
        settings: Settings,
        startup_markets: tuple[Market, ...],
        market_universe: _MarketUniverse,
        registry: PolymarketMarketRegistry,
        sidecar: ExternalDataSidecar,
        anchor_store: AnchorPriceStore | None = None,
        health: _Health | None = None,
    ) -> None:
        self.settings = settings
        self.market_universe = market_universe
        self.registry = registry
        self.sidecar = sidecar
        self.health = health
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
        self._active_by_condition = _markets_by_condition(startup_markets)
        self._epoch = 0
        self._refresh_task: object | None = None
        self._rtds_task: object | None = None
    def publish_data(self, data_type: object, data: object) -> None:
        base_publish = getattr(super(MarketRotationActor, self), "publish_data", None)
        if callable(base_publish):
            _ = base_publish(data_type, data)

    def on_start(self) -> None:
        _register_polysignal_data_types_if_available()
        if self._epoch == 0:
            next_epoch = self._epoch + 1
            self._publish_market_universe(
                epoch=next_epoch,
                markets=self.active_markets(),
                entered_condition_ids=tuple(self._active_by_condition),
                exited_condition_ids=(),
            )
            self._epoch = next_epoch
        for market in self.active_markets():
            self.publisher.publish_market_metadata(_market_metadata(market))
            _ = asyncio.create_task(self._publish_price_to_beat(market))
        if self.settings.runtime.nautilus.sidecar.spot_source == "polymarket_rtds":
            self._rtds_task = asyncio.create_task(self.rtds_feed.run())
        if self.settings.runtime.nautilus.market_rotation.enabled:
            self._refresh_task = asyncio.create_task(self._run_loop())

    def on_stop(self) -> None:
        self.rtds_feed.stop()
        for task in (self._refresh_task, self._rtds_task):
            if task is not None and hasattr(task, "cancel"):
                task.cancel()

    async def refresh_once(self) -> tuple[Market, ...]:
        try:
            refreshed_markets = tuple(await self.market_universe.refresh_once())
        except Exception as exc:
            self._mark_down(exc)
            raise

        current = _markets_by_condition(refreshed_markets)
        if _universe_signature(current) == _universe_signature(self._active_by_condition):
            self._active_by_condition = current
            self._mark_ok(active_count=len(current), entered_count=0, exited_count=0)
            return tuple(current.values())

        previous = self._active_by_condition
        entered_condition_ids = tuple(
            condition_id for condition_id in current if condition_id not in previous
        )
        exited_condition_ids = tuple(
            condition_id for condition_id in previous if condition_id not in current
        )
        next_epoch = self._epoch + 1
        self._publish_market_universe(
            epoch=next_epoch,
            markets=tuple(current.values()),
            entered_condition_ids=entered_condition_ids,
            exited_condition_ids=exited_condition_ids,
        )
        for condition_id in entered_condition_ids:
            market = current[condition_id]
            self.publisher.publish_market_metadata(_market_metadata(market))
            _ = asyncio.create_task(self._publish_price_to_beat(market))
        self._active_by_condition = current
        self._epoch = next_epoch
        self._mark_ok(
            active_count=len(current),
            entered_count=len(entered_condition_ids),
            exited_count=len(exited_condition_ids),
            epoch=self._epoch,
        )
        return tuple(current.values())

    async def _run_loop(self) -> None:
        interval = max(int(self.settings.runtime.nautilus.market_rotation.interval_sec), 1)
        while True:
            await asyncio.sleep(interval)
            try:
                await self.refresh_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                continue

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
        for market in self.active_markets():
            if market.asset.upper() != spot.asset.upper():
                continue
            _ = self.anchor_prices.capture_for_market(market)
            _ = asyncio.create_task(self._publish_price_to_beat(market))

    def active_markets(self) -> tuple[Market, ...]:
        return tuple(self._active_by_condition.values())

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

    def _publish_market_universe(
        self,
        *,
        epoch: int,
        markets: tuple[Market, ...],
        entered_condition_ids: tuple[str, ...],
        exited_condition_ids: tuple[str, ...],
    ) -> None:
        active_by_condition = _markets_by_condition(markets)
        now = datetime.now(UTC)
        self.publisher.publish_market_universe(
            PolySignalMarketUniverseData(
                epoch=epoch,
                active_condition_ids=tuple(active_by_condition),
                entered_condition_ids=entered_condition_ids,
                exited_condition_ids=exited_condition_ids,
                condition_to_up_token={
                    condition_id: market.token_for(Side.UP).token_id
                    for condition_id, market in active_by_condition.items()
                },
                condition_to_down_token={
                    condition_id: market.token_for(Side.DOWN).token_id
                    for condition_id, market in active_by_condition.items()
                },
                condition_to_asset={
                    condition_id: market.asset
                    for condition_id, market in active_by_condition.items()
                },
                condition_to_timeframe={
                    condition_id: market.timeframe
                    for condition_id, market in active_by_condition.items()
                },
                ts_event=_timestamp_ns(now),
                ts_init=_timestamp_ns(now),
            )
        )

    def _mark_ok(self, **metrics: object) -> None:
        if self.health is not None:
            self.health.mark_ok("market_rotation", **metrics)

    def _mark_down(self, exc: Exception) -> None:
        if self.health is not None:
            self.health.mark_down("market_rotation", str(exc), epoch=self._epoch)


def runtime_market_rotation_actor_type(
    nautilus_base: type[object] | None,
    config_factory: Callable[[], object] | None,
) -> type["MarketRotationActor"]:
    if nautilus_base is None:
        return MarketRotationActor

    def exec_body(namespace: dict[str, object]) -> None:
        def __init__(
            self: MarketRotationActor,
            *,
            settings: Settings,
            startup_markets: tuple[Market, ...],
            market_universe: _MarketUniverse,
            registry: PolymarketMarketRegistry,
            sidecar: ExternalDataSidecar,
            anchor_store: AnchorPriceStore | None = None,
            health: _Health | None = None,
        ) -> None:
            base_init = cast(Callable[..., None], nautilus_base.__init__)
            if config_factory is None:
                base_init(self)
            else:
                base_init(self, config=config_factory())
            MarketRotationActor.__init__(
                self,
                settings=settings,
                startup_markets=startup_markets,
                market_universe=market_universe,
                registry=registry,
                sidecar=sidecar,
                anchor_store=anchor_store,
                health=health,
            )

        namespace["__init__"] = __init__

    actor_cls = new_class(
        "NautilusMarketRotationActor",
        (MarketRotationActor, nautilus_base),
        exec_body=exec_body,
    )
    return cast(type[MarketRotationActor], actor_cls)


def _markets_by_condition(markets: tuple[Market, ...] | list[Market]) -> dict[str, Market]:
    return {market.condition_id: market for market in markets if market.condition_id}


def _universe_signature(markets_by_condition: dict[str, Market]) -> tuple[
    tuple[str, ...],
    dict[str, str],
    dict[str, str],
    dict[str, str],
    dict[str, str],
]:
    return (
        tuple(sorted(markets_by_condition)),
        {
            condition_id: market.token_for(Side.UP).token_id
            for condition_id, market in markets_by_condition.items()
        },
        {
            condition_id: market.token_for(Side.DOWN).token_id
            for condition_id, market in markets_by_condition.items()
        },
        {condition_id: market.asset for condition_id, market in markets_by_condition.items()},
        {condition_id: market.timeframe for condition_id, market in markets_by_condition.items()},
    )


def _register_polysignal_data_types_if_available() -> None:
    try:
        register_polysignal_data_types()
    except ModuleNotFoundError:
        return None
