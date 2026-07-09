"""
Input: __future__, collections.abc, dataclasses, types, typing, pyarrow, nautilus_trader.core.data, nautilus_trader.model.custom
Output: PolySignalSpotData, PolySignalPriceToBeatData, PolySignalMarketMetaData, PolySignalMarketUniverseData, register_polysignal_data_types
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import field
from types import MappingProxyType

import pyarrow as pa
from nautilus_trader.core.data import Data
from nautilus_trader.model.custom import customdataclass

_polysignal_data_types_registered = False

# --------------------------------------------------------------------------
#  Arrow support
# --------------------------------------------------------------------------

# Placeholder schema – Arrow serialization is not used at runtime, but
# @customdataclass requires a valid pa.Schema for registration.
_EMPTY_ARROW_SCHEMA = pa.schema({})

# --------------------------------------------------------------------------
#  Frozen mixin -- provides __setattr__-based immutability.
#  Inherit from (Data, _FrozenData) to keep Nautilus's Data base first.
# --------------------------------------------------------------------------


class _FrozenData:
    """Minimal mixin: __setattr__ guard that rejects mutation after freeze."""

    def __setattr__(self, name: str, value: object) -> None:
        # Always allow these internal names so the decorator can write them
        # after __post_init__ (or custom __init__) freezes the instance.
        if name in ("_frozen", "_ts_event", "_ts_init"):
            super().__setattr__(name, value)
            return
        try:
            frozen = super().__getattribute__("_frozen")
        except AttributeError:
            frozen = False
        if frozen:
            raise AttributeError(
                f"{type(self).__name__} is immutable"
            )
        super().__setattr__(name, value)


# --------------------------------------------------------------------------
#  Data types
# --------------------------------------------------------------------------


@customdataclass
class PolySignalSpotData(Data, _FrozenData):
    """A single spot price observation from a data source."""

    asset: str = ""
    symbol: str = ""
    price: float = 0.0
    source: str = ""
    freshness_ms: int | None = None
    _schema = _EMPTY_ARROW_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "_frozen", True)


@customdataclass
class PolySignalPriceToBeatData(Data, _FrozenData):
    """A price-to-beat observation used for consensus / anchor comparison."""

    condition_id: str = ""
    value: float = 0.0
    source: str = ""
    verified: bool = False
    from_anchor_service: bool = False
    anchor_source: str | None = None
    anchor_lag_ms: int | None = None
    _schema = _EMPTY_ARROW_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "_frozen", True)


@customdataclass
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
    _schema = _EMPTY_ARROW_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "_frozen", True)


@customdataclass
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
    _schema = _EMPTY_ARROW_SCHEMA

    def __init__(  # pyright: ignore[reportMissingSuperCall]
        self,
        epoch: int = 0,
        active_condition_ids: tuple[str, ...] = (),
        entered_condition_ids: tuple[str, ...] = (),
        exited_condition_ids: tuple[str, ...] = (),
        condition_to_up_token: dict[str, str] | None = None,
        condition_to_down_token: dict[str, str] | None = None,
        condition_to_asset: dict[str, str] | None = None,
        condition_to_timeframe: dict[str, str] | None = None,
        ts_event: int = 0,
        ts_init: int = 0,
    ) -> None:
        self.epoch = int(epoch)
        self.active_condition_ids = tuple(active_condition_ids)
        self.entered_condition_ids = tuple(entered_condition_ids)
        self.exited_condition_ids = tuple(exited_condition_ids)
        self.condition_to_up_token = MappingProxyType(dict(condition_to_up_token or {}))
        self.condition_to_down_token = MappingProxyType(dict(condition_to_down_token or {}))
        self.condition_to_asset = MappingProxyType(dict(condition_to_asset or {}))
        self.condition_to_timeframe = MappingProxyType(dict(condition_to_timeframe or {}))
        self._ts_event = int(ts_event)
        self._ts_init = int(ts_init)
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


# @customdataclass registers all types at class definition time, so the
# legacy register_polysignal_data_types() is a no-op at runtime. Tests
# that monkeypatch _polysignal_data_types_registered can still exercise
# the function body.
_polysignal_data_types_registered = True


def register_polysignal_data_types() -> None:
    """Register PolySignal custom data types with the Nautilus serializer.

    Registration is handled automatically by ``@customdataclass`` at import
    time.  This function is retained for backward compatibility.
    """
    # @customdataclass auto-registers at class definition time, so no-op.
    # If called during a re-import (e.g., test isolation), ignore the
    # duplicate-registration KeyError that Nautilus raises.
    if _polysignal_data_types_registered:
        return

    from nautilus_trader.serialization.base import register_serializable_type

    for cls in (
        PolySignalSpotData,
        PolySignalPriceToBeatData,
        PolySignalMarketMetaData,
        PolySignalMarketUniverseData,
    ):
        try:
            register_serializable_type(cls, cls.to_dict, cls.from_dict)
        except KeyError:
            pass  # already registered by @customdataclass


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
