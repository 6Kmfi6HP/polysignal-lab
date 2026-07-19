"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Callable, collections.abc.Mapping, json, dataclasses, dataclasses.field, types, types.MappingProxyType
Output: is_polymarket_rtds_crypto_price, polymarket_rtds_crypto_price_type, polymarket_rtds_crypto_price_data_type, polymarket_rtds_crypto_symbols, custom_data_type, polymarket_rtds_spot_identity, wrap_custom_data, unwrap_custom_data, register_custom_data_type, PolymarketRtdsCryptoPriceData, _FrozenData, PolySignalPriceToBeatData
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""



from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import json
from dataclasses import field
from types import MappingProxyType
from typing import Protocol, TypeGuard, cast

import pyarrow as pa
from nautilus_trader.core import nautilus_pyo3
from nautilus_trader.core.data import Data
from nautilus_trader.model.custom import customdataclass_pyo3

_register_custom_data_class = cast(
    Callable[[type[object]], None],
    getattr(nautilus_pyo3, "register_custom_data_class"),
)

def _arrow_record(data: object) -> dict[str, object]:
    values = data.to_dict()
    schema = type(data)._schema
    record: dict[str, object] = {}
    for schema_field in schema:
        value = values[schema_field.name]
        if isinstance(value, Mapping):
            value = json.dumps(dict(value), sort_keys=True, separators=(",", ":"))
        elif pa.types.is_list(schema_field.type) and isinstance(value, tuple):
            value = list(value)
        record[schema_field.name] = value
    return record


def _to_arrow(data: object) -> pa.RecordBatch:
    return pa.RecordBatch.from_pylist([_arrow_record(data)], schema=type(data)._schema)


def _from_arrow(cls: type[object], table: pa.RecordBatch | pa.Table) -> list[object]:
    return [cls.from_dict(record) for record in table.to_pylist()]


def _encode_record_batch_py(data: object, items: list[object]) -> pa.RecordBatch:
    return pa.RecordBatch.from_pylist(
        [_arrow_record(item) for item in items],
        schema=type(data)._schema,
    )


def _decode_record_batch_py(
    cls: type[object],
    metadata: dict[str, object],
    batch: pa.RecordBatch,
) -> list[object]:
    _ = metadata
    return _from_arrow(cls, batch)


class PolymarketRtdsCryptoPriceData(Protocol):
    symbol: str
    value: str
    ts_event: int
    ts_init: int


_POLYMARKET_RTDS_CRYPTO_PRICE_TYPE = cast(
    type[object],
    getattr(nautilus_pyo3, "PolymarketRtdsCryptoPrice"),
)


def is_polymarket_rtds_crypto_price(
    data: object,
) -> TypeGuard[PolymarketRtdsCryptoPriceData]:
    return isinstance(data, _POLYMARKET_RTDS_CRYPTO_PRICE_TYPE)


def polymarket_rtds_crypto_price_type() -> type[object]:
    return _POLYMARKET_RTDS_CRYPTO_PRICE_TYPE



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
class PolySignalPriceToBeatData(Data, _FrozenData):
    """A price-to-beat observation used for consensus / anchor comparison."""

    condition_id: str = ""
    value: float = 0.0
    source: str = ""
    verified: bool = False
    from_anchor_service: bool = False
    anchor_source: str | None = None
    anchor_lag_ms: int | None = None
    _schema = pa.schema(
        [
            ("condition_id", pa.string()),
            ("value", pa.float64()),
            ("source", pa.string()),
            ("verified", pa.bool_()),
            ("from_anchor_service", pa.bool_()),
            ("anchor_source", pa.string()),
            ("anchor_lag_ms", pa.int64()),
            ("type", pa.string()),
            ("ts_event", pa.int64()),
            ("ts_init", pa.int64()),
        ]
    )
    to_arrow = _to_arrow
    from_arrow = classmethod(_from_arrow)
    encode_record_batch_py = _encode_record_batch_py
    decode_record_batch_py = classmethod(_decode_record_batch_py)

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
    _schema = pa.schema(
        [
            ("market_id", pa.string()),
            ("market_slug", pa.string()),
            ("condition_id", pa.string()),
            ("asset", pa.string()),
            ("timeframe", pa.string()),
            ("start_ts_ns", pa.int64()),
            ("end_ts_ns", pa.int64()),
            ("up_token_id", pa.string()),
            ("down_token_id", pa.string()),
            ("question", pa.string()),
            ("up_outcome", pa.string()),
            ("down_outcome", pa.string()),
            ("type", pa.string()),
            ("ts_event", pa.int64()),
            ("ts_init", pa.int64()),
        ]
    )
    to_arrow = _to_arrow
    from_arrow = classmethod(_from_arrow)
    encode_record_batch_py = _encode_record_batch_py
    decode_record_batch_py = classmethod(_decode_record_batch_py)

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
    _schema = pa.schema(
        [
            ("epoch", pa.int64()),
            ("active_condition_ids", pa.list_(pa.string())),
            ("entered_condition_ids", pa.list_(pa.string())),
            ("exited_condition_ids", pa.list_(pa.string())),
            ("condition_to_up_token", pa.string()),
            ("condition_to_down_token", pa.string()),
            ("condition_to_asset", pa.string()),
            ("condition_to_timeframe", pa.string()),
            ("type", pa.string()),
            ("ts_event", pa.int64()),
            ("ts_init", pa.int64()),
        ]
    )
    to_arrow = _to_arrow
    from_arrow = classmethod(_from_arrow)
    encode_record_batch_py = _encode_record_batch_py
    decode_record_batch_py = classmethod(_decode_record_batch_py)

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
    if isinstance(value, str):
        value = json.loads(value)
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


def polymarket_rtds_crypto_price_data_type(symbol: str) -> nautilus_pyo3.DataType:
    """Build an RTDS crypto-price DataType with required metadata['symbol']."""
    normalized = str(symbol).strip()
    if not normalized:
        raise ValueError("Polymarket RTDS crypto symbol must not be empty")
    return nautilus_pyo3.DataType(
        "PolymarketRtdsCryptoPrice",
        {"symbol": normalized},
    )


def polymarket_rtds_crypto_symbols(
    assets: Sequence[str],
    symbol_by_asset: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Resolve per-asset RTDS venue symbols (e.g. BTCUSDT) for subscription metadata."""
    symbols: list[str] = []
    for asset in assets:
        key = str(asset).strip().upper()
        if not key:
            continue
        mapped = None
        if symbol_by_asset is not None:
            mapped = symbol_by_asset.get(key) or symbol_by_asset.get(asset)
        raw = str(mapped).strip() if mapped is not None else f"{key}USDT"
        if not raw:
            continue
        symbols.append(raw)
    return tuple(dict.fromkeys(symbols))


def polymarket_rtds_spot_identity(symbol: object) -> tuple[str, str]:
    normalized = str(symbol).upper().replace("/", "")
    for quote in ("USDT", "USDC", "USD"):
        if normalized.endswith(quote) and len(normalized) > len(quote):
            return normalized[: -len(quote)], normalized
    return normalized, normalized


def wrap_custom_data(payload: object) -> nautilus_pyo3.CustomData:
    return nautilus_pyo3.CustomData(custom_data_type(type(payload)), payload)


def unwrap_custom_data(data: object) -> object:
    if isinstance(data, nautilus_pyo3.CustomData):
        return getattr(data, "data")
    return data


def register_custom_data_type(payload_cls: type[object]) -> None:
    _register_custom_data_class(payload_cls)


for _payload_cls in (
    PolySignalPriceToBeatData,
    PolySignalMarketMetaData,
    PolySignalMarketUniverseData,
):
    register_custom_data_type(_payload_cls)
