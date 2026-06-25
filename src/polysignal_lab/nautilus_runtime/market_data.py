"""Nautilus custom data classes for the PolySignal sidecar bus.

These are plain frozen dataclasses with ``to_dict``/``from_dict`` round-trip
serialization so they can be registered with Nautilus' MessageBus serializer
when Nautilus is installed, and used as inert payloads in tests when it is not.

Nautilus is never imported at module load time. The only Nautilus touchpoint is
``register_polysignal_data_types()``, which imports
``register_serializable_type`` lazily inside its body.
"""

from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class PolySignalSpotData:
    asset: str
    symbol: str
    price: float
    source: str
    freshness_ms: int | None
    ts_event: int
    ts_init: int

    def to_dict(self) -> dict[str, object]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> "PolySignalSpotData":
        return cls(**{f.name: d[f.name] for f in fields(cls)})


@dataclass(frozen=True, slots=True)
class PolySignalPriceToBeatData:
    condition_id: str
    value: float
    source: str
    verified: bool
    from_anchor_service: bool
    anchor_source: str | None
    anchor_lag_ms: int | None
    ts_event: int
    ts_init: int

    def to_dict(self) -> dict[str, object]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> "PolySignalPriceToBeatData":
        return cls(**{f.name: d[f.name] for f in fields(cls)})


@dataclass(frozen=True, slots=True)
class PolySignalMarketMetaData:
    market_id: str
    market_slug: str
    condition_id: str
    asset: str
    timeframe: str
    start_ts_ns: int | None
    end_ts_ns: int | None
    up_token_id: str
    down_token_id: str
    ts_event: int
    ts_init: int

    def to_dict(self) -> dict[str, object]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> "PolySignalMarketMetaData":
        return cls(**{f.name: d[f.name] for f in fields(cls)})


def register_polysignal_data_types() -> None:
    """Register PolySignal custom data types with the Nautilus serializer.

    Nautilus is imported lazily here so default runtime tests run without it.
    """
    from nautilus_trader.serialization.base import register_serializable_type

    register_serializable_type(PolySignalSpotData, PolySignalSpotData.to_dict, PolySignalSpotData.from_dict)
    register_serializable_type(PolySignalPriceToBeatData, PolySignalPriceToBeatData.to_dict, PolySignalPriceToBeatData.from_dict)
    register_serializable_type(PolySignalMarketMetaData, PolySignalMarketMetaData.to_dict, PolySignalMarketMetaData.from_dict)
