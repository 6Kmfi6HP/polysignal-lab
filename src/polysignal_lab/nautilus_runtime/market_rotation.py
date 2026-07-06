from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Protocol

from polysignal_lab.config import Settings
from polysignal_lab.data.anchor_price_service import AnchorPriceService, AnchorPriceStore
from polysignal_lab.data.polymarket_rtds_ws import PolymarketRtdsPriceFeed
from polysignal_lab.data.price_to_beat_provider import PriceToBeatProvider
from polysignal_lab.data.state import SpotRegistry
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.spot import SpotPrice
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.market_data import (
    PolySignalMarketUniverseData,
    register_polysignal_data_types,
)
from polysignal_lab.nautilus_runtime.sidecar_data import (
    CustomDataPublisher,
    _market_metadata,  # pyright: ignore[reportPrivateUsage] - shared sidecar serializer has no public equivalent.
    _timestamp_ns,  # pyright: ignore[reportPrivateUsage] - shared sidecar timestamp helper has no public equivalent.
)

logger = logging.getLogger("polysignal_lab.nautilus.market_rotation")

REFRESH_TIMER_NAME = "market_rotation_refresh"


_PriceToBeatSignature = tuple[float, str, bool, bool, str | None]


class _MarketUniverse(Protocol):
    async def refresh_once(self) -> list[Market]: ...

    def refresh_once_sync(self) -> list[Market]: ...


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
        catalog: MarketCatalog,
        anchor_store: AnchorPriceStore | None = None,
        health: _Health | None = None,
    ) -> None:
        self.settings: Settings = settings
        self.market_universe: _MarketUniverse = market_universe
        self.catalog: MarketCatalog = catalog
        self.health: _Health | None = health
        self.publisher: CustomDataPublisher = CustomDataPublisher(publisher=self)
        self.spots: SpotRegistry = SpotRegistry()
        self.anchor_prices: AnchorPriceService | None = (
            AnchorPriceService(self.spots, anchor_store)
            if anchor_store is not None
            else None
        )
        self.ptb_provider: PriceToBeatProvider = PriceToBeatProvider(
            use_crypto_price_api=settings.data.polymarket.use_crypto_price_api,
            anchor_store=anchor_store,
        )
        self.rtds_feed: PolymarketRtdsPriceFeed | None = (
            PolymarketRtdsPriceFeed(
                self.spots,
                settings.data.polymarket,
                on_spot=self._on_spot,
            )
            if settings.runtime.nautilus.sidecar.spot_source == "polymarket_rtds"
            else None
        )
        self._active_by_condition: dict[str, Market] = _markets_by_condition(startup_markets)
        self._epoch: int = 0
        self._refresh_in_flight: bool = False
        self._last_published_ptb: dict[str, _PriceToBeatSignature] = {}

    def publish_data(self, data_type: object, data: object) -> None:
        base_publish = getattr(super(MarketRotationActor, self), "publish_data", None)
        if callable(base_publish):
            _ = base_publish(data_type, data)

    def on_start(self) -> None:
        _register_polysignal_data_types_if_available()
        if self.rtds_feed is not None:
            raise RuntimeError(
                "Nautilus RTDS spot source requires a managed Nautilus data-client lifecycle; "
                "set runtime.nautilus.sidecar.spot_source=disabled until that seam is implemented"
            )
        if self._epoch == 0:
            next_epoch = self._epoch + 1
            self._publish_market_universe(
                epoch=next_epoch,
                markets=self.active_markets(),
                entered_condition_ids=tuple(self._active_by_condition),
                exited_condition_ids=(),
            )
            self._epoch = next_epoch
            self._mark_ok(
                active_count=len(self._active_by_condition),
                entered_count=len(self._active_by_condition),
                exited_count=0,
                epoch=self._epoch,
                phase="startup",
            )
            logger.info(
                "market_rotation phase=startup epoch=%s active=%s entered=%s exited=%s",
                self._epoch,
                len(self._active_by_condition),
                len(self._active_by_condition),
                0,
            )
        markets = self.active_markets()
        for market in markets:
            self.publisher.publish_market_metadata(_market_metadata(market))
        self._publish_price_to_beat_batch_sync(markets)
        if self.settings.runtime.nautilus.market_rotation.enabled:
            interval = max(int(self.settings.runtime.nautilus.market_rotation.interval_sec), 1)
            clock = getattr(self, "clock", None)
            set_timer = getattr(clock, "set_timer", None)
            if not callable(set_timer):
                raise RuntimeError("Nautilus actor clock is required for market rotation")
            _ = set_timer(
                REFRESH_TIMER_NAME,
                timedelta(seconds=interval),
                callback=self._on_refresh_timer,
            )

    def on_stop(self) -> None:
        if self.rtds_feed is not None:
            self.rtds_feed.stop()
        clock = getattr(self, "clock", None)
        cancel_timer = getattr(clock, "cancel_timer", None)
        if callable(cancel_timer):
            _ = cancel_timer(REFRESH_TIMER_NAME)

    async def refresh_once(self) -> tuple[Market, ...]:
        try:
            refreshed_markets = tuple(await self.market_universe.refresh_once())
        except Exception as exc:
            logger.exception("market_rotation phase=refresh failed epoch=%s", self._epoch)
            self._mark_down(exc, phase="refresh")
            raise
        markets = self._apply_refreshed_markets(refreshed_markets)
        self._publish_price_to_beat_batch_sync(markets)
        return markets

    def _apply_refreshed_markets(
        self,
        refreshed_markets: tuple[Market, ...],
    ) -> tuple[Market, ...]:
        current = _markets_by_condition(refreshed_markets)
        previous = self._active_by_condition
        if _universe_signature(current) == _universe_signature(previous):
            self._active_by_condition = current
            self._mark_ok(
                active_count=len(current),
                entered_count=0,
                exited_count=0,
                epoch=self._epoch,
                phase="refresh",
            )
            logger.info(
                "market_rotation phase=refresh epoch=%s active=%s entered=0 exited=0",
                self._epoch,
                len(current),
            )
            return tuple(current.values())

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
            self.publisher.publish_market_metadata(_market_metadata(current[condition_id]))
        for condition_id in exited_condition_ids:
            _ = self._last_published_ptb.pop(condition_id, None)
        self._active_by_condition = current
        self._epoch = next_epoch
        self._mark_ok(
            active_count=len(current),
            entered_count=len(entered_condition_ids),
            exited_count=len(exited_condition_ids),
            epoch=self._epoch,
            phase="refresh",
        )
        logger.info(
            "market_rotation phase=refresh epoch=%s active=%s entered=%s exited=%s",
            self._epoch,
            len(current),
            len(entered_condition_ids),
            len(exited_condition_ids),
        )
        return tuple(current.values())

    def _on_refresh_timer(self, _event: object = None) -> None:
        if self._refresh_in_flight:
            return
        self._refresh_in_flight = True
        try:
            refreshed_markets = tuple(self.market_universe.refresh_once_sync())
            markets = self._apply_refreshed_markets(refreshed_markets)
            self._publish_price_to_beat_batch_sync(markets)
        except Exception as exc:
            logger.exception("market_rotation phase=refresh failed epoch=%s", self._epoch)
            self._mark_down(exc, phase="refresh")
        finally:
            self._refresh_in_flight = False

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
            self._publish_price_to_beat_sync(market)

    def active_markets(self) -> tuple[Market, ...]:
        return tuple(self._active_by_condition.values())

    def _publish_price_to_beat_sync(self, market: Market) -> None:
        result = self.ptb_provider.get_sync(market)
        if result.value is None:
            return
        signature: _PriceToBeatSignature = (
            result.value,
            result.source,
            result.verified,
            result.from_anchor_service,
            result.anchor_source,
        )
        if self._last_published_ptb.get(market.condition_id) == signature:
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
        self._last_published_ptb[market.condition_id] = signature

    def _publish_price_to_beat_batch_sync(self, markets: tuple[Market, ...]) -> None:
        for market in markets:
            try:
                self._publish_price_to_beat_sync(market)
            except Exception:
                logger.exception(
                    "market_rotation phase=refresh_ptb failed epoch=%s condition_id=%s",
                    self._epoch,
                    market.condition_id,
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

    def _mark_down(self, exc: Exception, **metrics: object) -> None:
        if self.health is not None:
            self.health.mark_down("market_rotation", str(exc), epoch=self._epoch, **metrics)




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
