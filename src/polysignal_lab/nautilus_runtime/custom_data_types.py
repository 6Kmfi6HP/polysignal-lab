"""
Input: __future__, collections.abc, dataclasses, types, typing, pyarrow, nautilus_trader.core, nautilus_trader.core.data, nautilus_trader.model.custom, nautilus_trader.model.data
Output: PolySignalSpotData, PolySignalPriceToBeatData, PolySignalMarketMetaData, PolySignalMarketUniverseData, custom_data_type, wrap_custom_data, unwrap_custom_data
Pos: Application code

Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import field
from types import MappingProxyType
from typing import cast

import pyarrow as pa
from nautilus_trader.core import nautilus_pyo3
from nautilus_trader.core.data import Data
from nautilus_trader.model.custom import customdataclass_pyo3
from nautilus_trader.model.data import CustomData as CythonCustomData

SPOT_DATA_CLIENT_ID = "POLYSIGNAL_SPOT"
_register_custom_data_class = cast(
    Callable[[type[object]], None],
    getattr(nautilus_pyo3, "register_custom_data_class"),
)

# Registration-only schema so @customdataclass skips auto-schema generation
# (project field types include unions/tuples/mappings that auto-schema rejects).
# Arrow is not used on production paths; to_arrow/from_arrow fail fast.
_ARROW_REGISTRATION_SCHEMA = pa.schema([])


def _unsupported_arrow(self_or_cls: object, *_args: object, **_kwargs: object) -> object:
    name = (
        self_or_cls.__name__
        if isinstance(self_or_cls, type)
        else type(self_or_cls).__name__
    )
    raise TypeError(f"Arrow serialization is unsupported for {name}")


# Frozen mixin -- provides __setattr__-based immutability.
# Inherit from (Data, _FrozenData) to keep Nautilus's Data base first.


class _FrozenData:
    """Minimal mixin: __setattr__ guard that rejects mutation after freeze."""

    def __setattr__(self, name: str, value: object) -> None:
        # Never allow thawing via normal assignment; construction uses
        # object.__setattr__(self, "_frozen", True).
        if name == "_frozen":
            raise AttributeError(
                f"{type(self).__name__} cannot change freeze state via attribute assignment"
            )
        # Decorator __init__ assigns _ts_event/_ts_init once after fields_init;
        # allow only the first assignment of each.
        if name in ("_ts_event", "_ts_init"):
            try:
                super().__getattribute__(name)
            except AttributeError:
                super().__setattr__(name, value)
                return
            raise AttributeError(f"{type(self).__name__} is immutable")
        try:
            frozen = super().__getattribute__("_frozen")
        except AttributeError:
            frozen = False
        if frozen:
            raise AttributeError(f"{type(self).__name__} is immutable")
        super().__setattr__(name, value)


# Data types


@customdataclass_pyo3()
class PolySignalSpotData(Data, _FrozenData):
    """A single spot price observation from a data source."""

    asset: str = ""
    symbol: str = ""
    price: float = 0.0
    source: str = ""
    freshness_ms: int | None = None
    _schema = _ARROW_REGISTRATION_SCHEMA
    to_arrow = _unsupported_arrow
    from_arrow = classmethod(_unsupported_arrow)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_frozen", True)


@customdataclass_pyo3()
class PolySignalPriceToBeatData(Data, _FrozenData):
    """A price-to-beat observation used for consensus / anchor comparison."""

    condition_id: str = ""
    value: float = 0.0
    source: str = ""
    verified: bool = False
    from_anchor_service: bool = False
    anchor_source: str | None = None
    anchor_lag_ms: int | None = None
    _schema = _ARROW_REGISTRATION_SCHEMA
    to_arrow = _unsupported_arrow
    from_arrow = classmethod(_unsupported_arrow)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_frozen", True)


@customdataclass_pyo3()
class PolySignalMarketMetaData(Data, _FrozenData):
    """Metadata for a prediction market (Polymarket condition)."""

    market_id: str = ""
    market_slug: str = ""
    condition_id: str = ""
    asset: str = ""
    timeframe: str = ""
    start_ts_ns: int | None = None
    end_ts_ns: int | None = None
    up_token_id: str = ""
    down_token_id: str = ""
    question: str | None = None
    up_outcome: str | None = None
    down_outcome: str | None = None
    _schema = _ARROW_REGISTRATION_SCHEMA
    to_arrow = _unsupported_arrow
    from_arrow = classmethod(_unsupported_arrow)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_frozen", True)


@customdataclass_pyo3()
class PolySignalMarketUniverseData(Data, _FrozenData):
    """Snapshot of active, entered, and exited conditions at an epoch."""

    epoch: int = 0
    active_condition_ids: tuple[str, ...] = ()
    entered_condition_ids: tuple[str, ...] = ()
    exited_condition_ids: tuple[str, ...] = ()
    condition_to_up_token: Mapping[str, str] = field(default_factory=dict)
    condition_to_down_token: Mapping[str, str] = field(default_factory=dict)
    condition_to_asset: Mapping[str, str] = field(default_factory=dict)
    condition_to_timeframe: Mapping[str, str] = field(default_factory=dict)
    _schema = _ARROW_REGISTRATION_SCHEMA
    to_arrow = _unsupported_arrow
    from_arrow = classmethod(_unsupported_arrow)

    def __post_init__(self) -> None:
        object.__setattr__(self, "active_condition_ids", tuple(self.active_condition_ids))
        object.__setattr__(self, "entered_condition_ids", tuple(self.entered_condition_ids))
        object.__setattr__(self, "exited_condition_ids", tuple(self.exited_condition_ids))
        object.__setattr__(self, "condition_to_up_token", MappingProxyType(dict(self.condition_to_up_token)))
        object.__setattr__(self, "condition_to_down_token", MappingProxyType(dict(self.condition_to_down_token)))
        object.__setattr__(self, "condition_to_asset", MappingProxyType(dict(self.condition_to_asset)))
        object.__setattr__(self, "condition_to_timeframe", MappingProxyType(dict(self.condition_to_timeframe)))
        object.__setattr__(self, "_frozen", True)

    def to_dict(self) -> dict[str, object]:
        return {
            "epoch": self.epoch,
            "active_condition_ids": list(self.active_condition_ids),
            "entered_condition_ids": list(self.entered_condition_ids),
            "exited_condition_ids": list(self.exited_condition_ids),
            "condition_to_up_token": dict(self.condition_to_up_token),
            "condition_to_down_token": dict(self.condition_to_down_token),
            "condition_to_asset": dict(self.condition_to_asset),
            "condition_to_timeframe": dict(self.condition_to_timeframe),
            "type": type(self).__name__,
            "ts_event": self._ts_event,
            "ts_init": self._ts_init,
        }

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> "PolySignalMarketUniverseData":
        raw = dict(d)
        raw.pop("type", None)
        raw.pop("data_type", None)
        return cls(
            epoch=_require_int(raw["epoch"], "epoch"),
            active_condition_ids=_require_str_tuple(
                raw["active_condition_ids"],
                "active_condition_ids",
            ),
            entered_condition_ids=_require_str_tuple(
                raw["entered_condition_ids"],
                "entered_condition_ids",
            ),
            exited_condition_ids=_require_str_tuple(
                raw["exited_condition_ids"],
                "exited_condition_ids",
            ),
            condition_to_up_token=_require_str_mapping(
                raw["condition_to_up_token"],
                "condition_to_up_token",
            ),
            condition_to_down_token=_require_str_mapping(
                raw["condition_to_down_token"],
                "condition_to_down_token",
            ),
            condition_to_asset=_require_str_mapping(
                raw["condition_to_asset"],
                "condition_to_asset",
            ),
            condition_to_timeframe=_require_str_mapping(
                raw["condition_to_timeframe"],
                "condition_to_timeframe",
            ),
            ts_event=_require_int(raw["ts_event"], "ts_event"),
            ts_init=_require_int(raw["ts_init"], "ts_init"),
        )


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise TypeError(f"{field_name} must be int-compatible")
    return int(value)


def _require_str_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        raise TypeError(f"{field_name} must be a list or tuple of strings")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise TypeError(f"{field_name} must contain only strings")
        items.append(item)
    return tuple(items)


def _require_str_mapping(value: object, field_name: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping of strings")
    items: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise TypeError(f"{field_name} must contain only string keys and values")
        items[key] = item
    return items


def custom_data_type(payload_cls: type[object]) -> nautilus_pyo3.DataType:
    return nautilus_pyo3.DataType(payload_cls.__name__)


def wrap_custom_data(payload: object) -> nautilus_pyo3.CustomData:
    return nautilus_pyo3.CustomData(custom_data_type(type(payload)), payload)


def unwrap_custom_data(data: object) -> object:
    if isinstance(data, nautilus_pyo3.CustomData | CythonCustomData):
        return getattr(data, "data")
    return data


def register_custom_data_type(payload_cls: type[object]) -> None:
    _register_custom_data_class(payload_cls)


for _payload_cls in (
    PolySignalSpotData,
    PolySignalPriceToBeatData,
    PolySignalMarketMetaData,
    PolySignalMarketUniverseData,
):
    register_custom_data_type(_payload_cls)
