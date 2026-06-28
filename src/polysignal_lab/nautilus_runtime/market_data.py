"""Nautilus custom data classes for the PolySignal sidecar bus.

These payload classes stay import-safe when Nautilus is unavailable, but become
real Nautilus ``Data`` subclasses when it is installed so actors can publish
them through ``publish_data`` and ``CustomData``.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nautilus_trader.core.data import Data as _NautilusDataBase
else:
    try:
        from nautilus_trader.core.data import Data as _NautilusDataBase
    except ModuleNotFoundError:  # pragma: no cover - exercised on py3.11 without Nautilus
        class _NautilusDataBase:  # type: ignore[no-redef]
            pass


def _as_str(value: object) -> str:
    return str(value)


def _as_float(value: object) -> float:
    return float(value if isinstance(value, (int, float, str, bytes, bytearray)) else str(value))


def _as_int(value: object) -> int:
    return int(value if isinstance(value, (int, str, bytes, bytearray)) else str(value))


def _as_optional_int(value: object) -> int | None:
    return None if value is None else _as_int(value)


def _as_bool(value: object) -> bool:
    return bool(value)


class _PolySignalDataBase(_NautilusDataBase):
    __slots__ = ("_ts_event", "_ts_init")
    _fields: tuple[str, ...] = ()

    def __eq__(self, other: object) -> bool:
        return type(self) is type(other) and isinstance(other, _PolySignalDataBase) and self.to_dict() == other.to_dict()

    @property
    def ts_event(self) -> int:
        return self._ts_event

    @property
    def ts_init(self) -> int:
        return self._ts_init

    def to_dict(self) -> dict[str, object]:
        payload = {name: getattr(self, name) for name in self._fields}
        payload["ts_event"] = self._ts_event
        payload["ts_init"] = self._ts_init
        return payload


class PolySignalSpotData(_PolySignalDataBase):
    __slots__ = ("asset", "symbol", "price", "source", "freshness_ms")
    _fields = ("asset", "symbol", "price", "source", "freshness_ms")

    def __init__(  # pyright: ignore[reportMissingSuperCall]
        self,
        asset: str,
        symbol: str,
        price: float,
        source: str,
        freshness_ms: int | None,
        ts_event: int,
        ts_init: int,
    ) -> None:
        self.asset = asset
        self.symbol = symbol
        self.price = float(price)
        self.source = source
        self.freshness_ms = freshness_ms
        self._ts_event = int(ts_event)
        self._ts_init = int(ts_init)

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> "PolySignalSpotData":
        return cls(
            asset=_as_str(d["asset"]),
            symbol=_as_str(d["symbol"]),
            price=_as_float(d["price"]),
            source=_as_str(d["source"]),
            freshness_ms=_as_optional_int(d["freshness_ms"]),
            ts_event=_as_int(d["ts_event"]),
            ts_init=_as_int(d["ts_init"]),
        )


class PolySignalPriceToBeatData(_PolySignalDataBase):
    __slots__ = (
        "condition_id",
        "value",
        "source",
        "verified",
        "from_anchor_service",
        "anchor_source",
        "anchor_lag_ms",
    )
    _fields = (
        "condition_id",
        "value",
        "source",
        "verified",
        "from_anchor_service",
        "anchor_source",
        "anchor_lag_ms",
    )

    def __init__(  # pyright: ignore[reportMissingSuperCall]
        self,
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
        self.condition_id = condition_id
        self.value = float(value)
        self.source = source
        self.verified = bool(verified)
        self.from_anchor_service = bool(from_anchor_service)
        self.anchor_source = anchor_source
        self.anchor_lag_ms = anchor_lag_ms
        self._ts_event = int(ts_event)
        self._ts_init = int(ts_init)

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> "PolySignalPriceToBeatData":
        return cls(
            condition_id=_as_str(d["condition_id"]),
            value=_as_float(d["value"]),
            source=_as_str(d["source"]),
            verified=_as_bool(d["verified"]),
            from_anchor_service=_as_bool(d["from_anchor_service"]),
            anchor_source=None if d["anchor_source"] is None else _as_str(d["anchor_source"]),
            anchor_lag_ms=_as_optional_int(d["anchor_lag_ms"]),
            ts_event=_as_int(d["ts_event"]),
            ts_init=_as_int(d["ts_init"]),
        )


class PolySignalMarketMetaData(_PolySignalDataBase):
    __slots__ = (
        "market_id",
        "market_slug",
        "condition_id",
        "asset",
        "timeframe",
        "start_ts_ns",
        "end_ts_ns",
        "up_token_id",
        "down_token_id",
    )
    _fields = (
        "market_id",
        "market_slug",
        "condition_id",
        "asset",
        "timeframe",
        "start_ts_ns",
        "end_ts_ns",
        "up_token_id",
        "down_token_id",
    )

    def __init__(  # pyright: ignore[reportMissingSuperCall]
        self,
        market_id: str,
        market_slug: str,
        condition_id: str,
        asset: str,
        timeframe: str,
        start_ts_ns: int | None,
        end_ts_ns: int | None,
        up_token_id: str,
        down_token_id: str,
        ts_event: int,
        ts_init: int,
    ) -> None:
        self.market_id = market_id
        self.market_slug = market_slug
        self.condition_id = condition_id
        self.asset = asset
        self.timeframe = timeframe
        self.start_ts_ns = start_ts_ns
        self.end_ts_ns = end_ts_ns
        self.up_token_id = up_token_id
        self.down_token_id = down_token_id
        self._ts_event = int(ts_event)
        self._ts_init = int(ts_init)

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> "PolySignalMarketMetaData":
        return cls(
            market_id=_as_str(d["market_id"]),
            market_slug=_as_str(d["market_slug"]),
            condition_id=_as_str(d["condition_id"]),
            asset=_as_str(d["asset"]),
            timeframe=_as_str(d["timeframe"]),
            start_ts_ns=_as_optional_int(d["start_ts_ns"]),
            end_ts_ns=_as_optional_int(d["end_ts_ns"]),
            up_token_id=_as_str(d["up_token_id"]),
            down_token_id=_as_str(d["down_token_id"]),
            ts_event=_as_int(d["ts_event"]),
            ts_init=_as_int(d["ts_init"]),
        )


def register_polysignal_data_types() -> None:
    """Register PolySignal custom data types with the Nautilus serializer."""
    register_serializable_type = getattr(
        import_module("nautilus_trader.serialization.base"),
        "register_serializable_type",
    )

    register_serializable_type(PolySignalSpotData, PolySignalSpotData.to_dict, PolySignalSpotData.from_dict)
    register_serializable_type(PolySignalPriceToBeatData, PolySignalPriceToBeatData.to_dict, PolySignalPriceToBeatData.from_dict)
    register_serializable_type(PolySignalMarketMetaData, PolySignalMarketMetaData.to_dict, PolySignalMarketMetaData.from_dict)
