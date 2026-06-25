"""Sidecar data actor — publishes PolySignal custom data on the Nautilus bus.

The actor wraps an :class:`ExternalDataSidecar` and a market registry, exposing
``publish_*`` methods that both update the in-memory sidecar/registry and push a
typed payload onto the Nautilus MessageBus via the injected publisher.

Nautilus is never imported at module load time. The ``DataType`` wrapper is
constructed lazily inside each publish method; when Nautilus is not installed,
the data class itself is passed as ``data_type`` so tests stay Nautilus-free.
"""

from __future__ import annotations

from polysignal_lab.alpha.types import SpotView
from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
from polysignal_lab.nautilus_bridge.market_registry import MarketPairMeta, PolymarketMarketRegistry
from polysignal_lab.nautilus_runtime.market_data import (
    PolySignalMarketMetaData,
    PolySignalPriceToBeatData,
    PolySignalSpotData,
)


def _data_type(payload_cls: type) -> object:
    """Return ``DataType(payload_cls)`` when Nautilus is installed, else the class itself."""
    try:
        from nautilus_trader.model.data import DataType
    except ImportError:
        return payload_cls
    return DataType(payload_cls)


class SidecarDataActor:
    def __init__(
        self,
        *,
        publisher: object,
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
            pair = MarketPairMeta.from_metadata(meta)
            self.registry.register(pair)
