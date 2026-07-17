"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Callable, collections.abc.Mapping, collections.abc.Sequence, datetime, datetime.UTC, datetime.datetime, polysignal_lab.nautilus_runtime.projections
Output: classify_project_owned_data, DataBoundaryClassification, _Assembler, _Observability
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Protocol, cast

from nautilus_trader.core.nautilus_pyo3 import (
    BookType as _Pyo3BookType,
    ClientId as _Pyo3ClientId,
    DataType as _Pyo3DataType,
    InstrumentId as _Pyo3InstrumentId,
)

from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog, MarketPairMeta
from polysignal_lab.nautilus_runtime.state import JsonValue, StateSchemaError
from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState
from polysignal_lab.nautilus_runtime.custom_data_types import (
    PolySignalMarketMetaData,
    PolySignalMarketUniverseData,
    PolySignalPriceToBeatData,
    PolySignalSpotData,
    SPOT_DATA_CLIENT_ID,
)
from polysignal_lab.nautilus_runtime.projections import _tags  # noqa: F401

_book_type_from_str = cast(
    Callable[[str], object],
    getattr(_Pyo3BookType, "from_str"),
)
_instrument_id_from_str = cast(
    Callable[[str], object],
    getattr(_Pyo3InstrumentId, "from_str"),
)


def _nautilus_instrument_id(value: object) -> object:
    if isinstance(value, str):
        return _instrument_id_from_str(value)
    return value


def _nautilus_book_type(value: str) -> object:
    return _book_type_from_str(value)


def _data_client_id(value: str) -> object:
    return _Pyo3ClientId(value)

DEFAULT_NATIVE_DATA_NAMES = ("quote_ticks", "trade_ticks", "order_book_deltas")
MISSING_PROJECTIONS_ERROR = "PolySignalNativeStrategy requires injected registry and assembler projections"
EVALUATION_HEARTBEAT_TIMER_NAME = "polysignal_evaluation_heartbeat"
EVALUATION_HEARTBEAT_INTERVAL = timedelta(seconds=10)
DEFAULT_L1_BOOK_SNAPSHOT_INTERVAL_MS = 1000
L1_RAW_DELTA_FALLBACK_PHASE = "l1_raw_delta_fallback"


class DataBoundaryClassification(Enum):
    VALID_DATA = "ValidData"
    DROPPED_FRAME = "DroppedFrame"
    RECOVERABLE_FEED_ERROR = "RecoverableFeedError"
    FATAL_FEED_ERROR = "FatalFeedError"


def classify_project_owned_data(data: object) -> DataBoundaryClassification:
    if isinstance(
        data,
        (
            PolySignalSpotData,
            PolySignalPriceToBeatData,
            PolySignalMarketMetaData,
            PolySignalMarketUniverseData,
        ),
    ):
        return DataBoundaryClassification.VALID_DATA
    if type(data).__name__ == "DataEvent" and getattr(data, "condition_id", None) is not None:
        return DataBoundaryClassification.VALID_DATA
    return DataBoundaryClassification.DROPPED_FRAME


def _book_has_quote_depth(book: object) -> bool:
    if getattr(book, "best_ask", None) is not None:
        return True
    ask_levels = getattr(book, "ask_levels", ()) or ()
    return len(ask_levels) > 0


def _market_view_ready(view: object) -> bool:
    book_for = getattr(view, "book_for", None)
    if not callable(book_for):
        return False
    try:
        up_book = book_for(Side.UP)
        down_book = book_for(Side.DOWN)
    except ValueError:
        return False
    return _book_has_quote_depth(up_book) and _book_has_quote_depth(down_book)


class _Assembler(Protocol):
    def build(self, condition_id: str, *, created_at: datetime) -> object | None: ...


class _Observability(Protocol):
    def record_decision(self, decision: object, accepted: bool) -> None: ...

    def record_rejected_decision(self, rejected: object) -> None: ...

    def record_nautilus_order_event(self, event: object) -> None: ...

    def record_nautilus_fill_event(self, event: object) -> None: ...

    def record_nautilus_position(self, position: object) -> None: ...


class _CustomDataSubscriber(Protocol):
    def subscribe_data(
        self,
        data_type: object,
        client_id: object | None = None,
    ) -> object: ...


def _identity_instrument_id(token_id: str) -> str:
    return token_id


def _nautilus_data_type(value: object) -> object:
    if isinstance(value, type):
        return _Pyo3DataType(value.__name__)
    return value


def _assembler_with_custom_data(
    assembler: _Assembler | None,
    custom_data: StrategyCustomDataState,
) -> _Assembler | None:
    if assembler is None:
        return None
    with_custom_data = getattr(assembler, "with_custom_data", None)
    if callable(with_custom_data):
        return cast(_Assembler, with_custom_data(custom_data))
    if hasattr(assembler, "custom_data"):
        setattr(assembler, "custom_data", custom_data)
    return assembler


def _value(obj: object, name: str, default: object = None) -> object:
    if isinstance(obj, Mapping):
        return cast(Mapping[object, object], obj).get(name, default)
    return getattr(obj, name, default)



def _optional_str(value: object) -> str | None:
    text = _lookup_id_text(value)
    return text


def _lookup_id_text(value: object) -> str | None:
    if value is None:
        return None
    text = _identifier_text(value)
    return None if text in (None, "") else text


def _market_id_for_condition(
    registry: MarketCatalog, condition_id: str
) -> str | None:
    pair = registry.by_condition(condition_id)
    return None if pair is None else pair.market_id


def _event_side(
    registry: MarketCatalog | None,
    instrument_id: str | None,
    token_id: str | None,
    value: object,
) -> Side:
    if isinstance(value, Side):
        return value
    text = _identifier_text(value)
    if text in {Side.UP.value, Side.DOWN.value}:
        return Side(text)
    if registry is not None:
        resolved_token_id = token_id
        if resolved_token_id is None and instrument_id is not None:
            condition_id = _condition_id_from_catalog_instrument(
                registry, registry.condition_ids(), instrument_id
            )
            if condition_id is not None:
                resolved_token_id = _token_id_from_catalog_instrument(
                    registry, condition_id, instrument_id
                )
        if resolved_token_id is not None:
            meta = registry.token_meta(resolved_token_id)
            if meta is not None:
                return meta.side
    return Side.UP


def _instrument_ids(
    registry: MarketCatalog,
    condition_ids: Sequence[str],
) -> tuple[object, ...]:
    instrument_ids: list[object] = []
    for condition_id in condition_ids:
        pair = registry.by_condition(condition_id)
        if pair is None:
            continue
        for token_id in (pair.up.token_id, pair.down.token_id):
            instrument_id = registry.instrument_id_for_token(token_id)
            if instrument_id is not None:
                instrument_ids.append(_nautilus_instrument_id(instrument_id))
    return tuple(instrument_ids)


def _asset_conditions(
    registry: MarketCatalog | None,
    condition_ids: Sequence[str],
) -> dict[str, tuple[str, ...]]:
    if registry is None:
        return {}
    grouped: dict[str, list[str]] = {}
    for condition_id in condition_ids:
        pair = registry.by_condition(condition_id)
        if pair is None:
            continue
        grouped.setdefault(pair.asset.upper(), []).append(condition_id)
    return {asset: tuple(ids) for asset, ids in grouped.items()}


def _identifier_text(value: object) -> str | None:
    if value is None:
        return None
    raw = getattr(value, "value", None)
    text = str(raw if raw is not None else value)
    return text or None


def _token_id_from_catalog_instrument(
    registry: MarketCatalog,
    condition_id: str,
    instrument_id: str,
) -> str | None:
    pair = registry.by_condition(condition_id)
    if pair is None:
        return None
    for token_id in (pair.up.token_id, pair.down.token_id):
        if registry.instrument_id_for_token(token_id) == instrument_id:
            return token_id
    return None


def _condition_id_from_catalog_instrument(
    registry: MarketCatalog,
    condition_ids: Sequence[str],
    instrument_id: str,
) -> str | None:
    for condition_id in condition_ids:
        if _token_id_from_catalog_instrument(registry, condition_id, instrument_id) is not None:
            return condition_id
    return None


def _maybe_float(value: object) -> float | None:
    if value is None:
        return None
    if callable(value):
        value = value()
    coerced = (
        value if isinstance(value, (int, float, str, bytes, bytearray)) else str(value)
    )
    try:
        return float(coerced)
    except (TypeError, ValueError):
        return None


def _positive_value(source: Mapping[str, object], key: str) -> float | None:
    value = _maybe_float(source.get(key))
    return value if value is not None and value > 0.0 else None


def _fallback_fill_price(
    metrics: Mapping[str, object],
    tags: Mapping[str, object],
    side: Side,
) -> float | None:
    side_key = side.value.lower()
    for key in (
        "fill_price",
        "favorite_price",
        "fav_price",
        f"{side_key}_ask",
        f"{side_key}_last_price",
        "best_ask",
        "current_ask",
        "hedge_price",
        "level_price",
        "bid_price",
        "entry_reference_price",
        "max_entry_price",
    ):
        value = _positive_value(metrics, key) or _positive_value(tags, key)
        if value is not None:
            return value
    return None


def event_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        try:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("ts_event datetime must be timezone-aware")
            return value.astimezone(UTC)
        except Exception as exc:
            raise ValueError("ts_event datetime must be timezone-aware") from exc
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError("ts_event must be a positive Unix nanosecond timestamp")
    try:
        return datetime.fromtimestamp(value / 1_000_000_000, UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("ts_event must be a positive Unix nanosecond timestamp") from exc


def _spot_data_client_id() -> object | None:
    return _data_client_id(SPOT_DATA_CLIENT_ID)


def _subscribe_custom_data(
    strategy: _CustomDataSubscriber,
    data_type: object,
    *,
    client_id: object | None = None,
) -> None:
    _ = strategy.subscribe_data(_nautilus_data_type(data_type), client_id=client_id)


def _json_state_payload(value: object) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise StateSchemaError(
            f"{type(value).__name__} core save_state() returned non-mapping state"
        )
    return {str(key): cast(JsonValue, item) for key, item in value.items()}


def _datetime_ns(value: int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1_000_000_000, UTC)


def _pair_from_metadata(meta: PolySignalMarketMetaData) -> MarketPairMeta:
    return MarketPairMeta.from_metadata(meta)
