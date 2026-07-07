"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Iterable, collections.abc.Mapping, importlib, importlib.import_module, types, types.MappingProxyType, typing
Output: register_polysignal_data_types, _PolySignalDataBase, PolySignalSpotData, PolySignalPriceToBeatData, PolySignalMarketMetaData, PolySignalMarketUniverseData
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""








from __future__ import annotations

from collections.abc import Iterable, Mapping
from importlib import import_module
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, Callable, cast

from typing_extensions import override

_POLYSIGNAL_DATA_TYPES_REGISTERED = False

if TYPE_CHECKING:
    _NautilusDataBase = object
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

def _as_str_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError("expected a string sequence")
    return tuple(_as_str(item) for item in cast(Iterable[object], value))


def _as_str_dict(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError("expected a string mapping")
    mapping = cast(Mapping[object, object], value)
    return {_as_str(key): _as_str(item) for key, item in mapping.items()}



class _PolySignalDataBase(_NautilusDataBase):
    __slots__: ClassVar[tuple[str, ...]] = ("_ts_event", "_ts_init")
    _fields: ClassVar[tuple[str, ...]] = ()
    _ts_event: int
    _ts_init: int

    def __init__(self) -> None:
        self._ts_event = 0
        self._ts_init = 0

    @override
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
    __slots__: ClassVar[tuple[str, ...]] = ("asset", "symbol", "price", "source", "freshness_ms")
    _fields: ClassVar[tuple[str, ...]] = ("asset", "symbol", "price", "source", "freshness_ms")
    asset: str
    symbol: str
    price: float
    source: str
    freshness_ms: int | None
    _ts_event: int
    _ts_init: int

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
    __slots__: ClassVar[tuple[str, ...]] = (
        "condition_id",
        "value",
        "source",
        "verified",
        "from_anchor_service",
        "anchor_source",
        "anchor_lag_ms",
    )
    _fields: ClassVar[tuple[str, ...]] = (
        "condition_id",
        "value",
        "source",
        "verified",
        "from_anchor_service",
        "anchor_source",
        "anchor_lag_ms",
    )
    condition_id: str
    value: float
    source: str
    verified: bool
    from_anchor_service: bool
    anchor_source: str | None
    anchor_lag_ms: int | None
    _ts_event: int
    _ts_init: int

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
    __slots__: ClassVar[tuple[str, ...]] = (
        "_sealed",
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
    _fields: ClassVar[tuple[str, ...]] = (
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
    _sealed: bool
    market_id: str
    market_slug: str
    condition_id: str
    asset: str
    timeframe: str
    start_ts_ns: int | None
    end_ts_ns: int | None
    up_token_id: str
    down_token_id: str
    _ts_event: int
    _ts_init: int

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
        self._sealed = False
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
        self._sealed = True

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

    @override
    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("PolySignalMarketMetaData is immutable")
        object.__setattr__(self, name, value)


class PolySignalMarketUniverseData(_PolySignalDataBase):
    __slots__: ClassVar[tuple[str, ...]] = (
        "_sealed",
        "epoch",
        "active_condition_ids",
        "entered_condition_ids",
        "exited_condition_ids",
        "condition_to_up_token",
        "condition_to_down_token",
        "condition_to_asset",
        "condition_to_timeframe",
    )
    _fields: ClassVar[tuple[str, ...]] = (
        "epoch",
        "active_condition_ids",
        "entered_condition_ids",
        "exited_condition_ids",
        "condition_to_up_token",
        "condition_to_down_token",
        "condition_to_asset",
        "condition_to_timeframe",
    )
    _sealed: bool
    epoch: int
    active_condition_ids: tuple[str, ...]
    entered_condition_ids: tuple[str, ...]
    exited_condition_ids: tuple[str, ...]
    condition_to_up_token: Mapping[str, str]
    condition_to_down_token: Mapping[str, str]
    condition_to_asset: Mapping[str, str]
    condition_to_timeframe: Mapping[str, str]
    _ts_event: int
    _ts_init: int

    def __init__(  # pyright: ignore[reportMissingSuperCall]
        self,
        epoch: int,
        active_condition_ids: tuple[str, ...],
        entered_condition_ids: tuple[str, ...],
        exited_condition_ids: tuple[str, ...],
        condition_to_up_token: dict[str, str],
        condition_to_down_token: dict[str, str],
        condition_to_asset: dict[str, str],
        condition_to_timeframe: dict[str, str],
        ts_event: int,
        ts_init: int,
    ) -> None:
        self._sealed = False
        self.epoch = int(epoch)
        self.active_condition_ids = tuple(active_condition_ids)
        self.entered_condition_ids = tuple(entered_condition_ids)
        self.exited_condition_ids = tuple(exited_condition_ids)
        self.condition_to_up_token = MappingProxyType(dict(condition_to_up_token))
        self.condition_to_down_token = MappingProxyType(dict(condition_to_down_token))
        self.condition_to_asset = MappingProxyType(dict(condition_to_asset))
        self.condition_to_timeframe = MappingProxyType(dict(condition_to_timeframe))
        self._ts_event = int(ts_event)
        self._ts_init = int(ts_init)
        self._sealed = True

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> "PolySignalMarketUniverseData":
        return cls(
            epoch=_as_int(d["epoch"]),
            active_condition_ids=_as_str_tuple(d["active_condition_ids"]),
            entered_condition_ids=_as_str_tuple(d["entered_condition_ids"]),
            exited_condition_ids=_as_str_tuple(d["exited_condition_ids"]),
            condition_to_up_token=_as_str_dict(d["condition_to_up_token"]),
            condition_to_down_token=_as_str_dict(d["condition_to_down_token"]),
            condition_to_asset=_as_str_dict(d["condition_to_asset"]),
            condition_to_timeframe=_as_str_dict(d["condition_to_timeframe"]),
            ts_event=_as_int(d["ts_event"]),
            ts_init=_as_int(d["ts_init"]),
        )

    @override
    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("PolySignalMarketUniverseData is immutable")
        object.__setattr__(self, name, value)

    @override
    def to_dict(self) -> dict[str, object]:
        payload = super().to_dict()
        payload["active_condition_ids"] = list(self.active_condition_ids)
        payload["entered_condition_ids"] = list(self.entered_condition_ids)
        payload["exited_condition_ids"] = list(self.exited_condition_ids)
        payload["condition_to_up_token"] = dict(self.condition_to_up_token)
        payload["condition_to_down_token"] = dict(self.condition_to_down_token)
        payload["condition_to_asset"] = dict(self.condition_to_asset)
        payload["condition_to_timeframe"] = dict(self.condition_to_timeframe)
        return payload



def register_polysignal_data_types() -> None:
    """Register PolySignal custom data types with the Nautilus serializer."""
    global _POLYSIGNAL_DATA_TYPES_REGISTERED

    if _POLYSIGNAL_DATA_TYPES_REGISTERED:
        return

    register_serializable_type = cast(
        Callable[[type[object], object, object], None],
        getattr(
            import_module("nautilus_trader.serialization.base"),
            "register_serializable_type",
        ),
    )
    register_serializable_type(
        PolySignalSpotData,
        PolySignalSpotData.to_dict,
        PolySignalSpotData.from_dict,
    )
    register_serializable_type(
        PolySignalPriceToBeatData,
        PolySignalPriceToBeatData.to_dict,
        PolySignalPriceToBeatData.from_dict,
    )
    register_serializable_type(
        PolySignalMarketMetaData,
        PolySignalMarketMetaData.to_dict,
        PolySignalMarketMetaData.from_dict,
    )
    register_serializable_type(
        PolySignalMarketUniverseData,
        PolySignalMarketUniverseData.to_dict,
        PolySignalMarketUniverseData.from_dict,
    )
    _POLYSIGNAL_DATA_TYPES_REGISTERED = True  # pyright: ignore[reportConstantRedefinition]
