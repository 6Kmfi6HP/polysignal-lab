"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Callable, collections.abc.Iterable, collections.abc.Mapping, collections.abc.Sequence, datetime, datetime.UTC, datetime.datetime
Output: classify_project_owned_data, DataBoundaryClassification, _Assembler, _Observability
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import Enum
from importlib import import_module
from types import SimpleNamespace
from typing import Protocol, cast

from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog, MarketPairMeta
from polysignal_lab.nautilus_bridge.state import JsonValue, StateSchemaError
from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState
from polysignal_lab.nautilus_runtime.custom_data_types import (
    PolySignalMarketMetaData,
    PolySignalMarketUniverseData,
    PolySignalPriceToBeatData,
    PolySignalSpotData,
)

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
    try:
        up_book = view.book_for(Side.UP)
        down_book = view.book_for(Side.DOWN)
    except (AttributeError, ValueError):
        return False
    return _book_has_quote_depth(up_book) and _book_has_quote_depth(down_book)


class _Assembler(Protocol):
    def build(self, condition_id: str) -> object | None: ...


class _Observability(Protocol):
    def record_decision(self, decision: object, accepted: bool) -> None: ...

    def record_rejected_decision(self, rejected: object) -> None: ...

    def record_nautilus_order_event(self, event: object) -> None: ...

    def record_nautilus_fill_event(self, event: object) -> None: ...

    def record_nautilus_position(self, position: object) -> None: ...


def _identity_instrument_id(token_id: str) -> str:
    return token_id


def _nautilus_instrument_id(value: str) -> object:
    try:
        identifiers = import_module("nautilus_trader.model.identifiers")
    except ModuleNotFoundError:
        return value
    instrument_id_cls = cast(object | None, getattr(identifiers, "InstrumentId", None))
    from_str = cast(object | None, getattr(instrument_id_cls, "from_str", None))
    if callable(from_str):
        return cast(Callable[[str], object], from_str)(value)
    return value


def _nautilus_book_type(value: str) -> object:
    try:
        enums = import_module("nautilus_trader.model.enums")
    except ModuleNotFoundError:
        return value
    converter = getattr(enums, "book_type_from_str", None)
    if callable(converter):
        return cast(Callable[[str], object], converter)(value)
    return value


def _nautilus_data_type(value: object) -> object:
    if not isinstance(value, type):
        return value
    try:
        module = import_module("nautilus_trader.model.data")
    except ModuleNotFoundError:
        return value
    data_type_cls = getattr(module, "DataType", None)
    if callable(data_type_cls):
        return cast(Callable[[type[object]], object], data_type_cls)(value)
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


def _tags(raw: object) -> dict[str, str]:
    if isinstance(raw, Mapping):
        return {
            str(key): str(value)
            for key, value in cast(Mapping[object, object], raw).items()
        }
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes)):
        return {}
    parsed: dict[str, str] = {}
    for item in raw:
        text = str(item)
        if "=" not in text:
            continue
        key, value = text.split("=", 1)
        parsed[key] = value
    return parsed


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


def _projection_order_event(
    event: object, metrics: Mapping[str, object]
) -> SimpleNamespace:
    return SimpleNamespace(
        client_order_id=_value(event, "client_order_id"),
        instrument_id=_value(event, "instrument_id"),
        order_side=_value(event, "order_side"),
        order_type=_value(event, "order_type"),
        time_in_force=_value(event, "time_in_force"),
        quantity=_value(event, "quantity"),
        price=_value(event, "price"),
        status=_value(event, "status"),
        tags=_value(event, "tags", ()),
        metrics=dict(metrics),
        ts_event=_value(event, "ts_event", _value(event, "timestamp")),
    )


def _projection_fill_event(
    event: object, metrics: Mapping[str, object]
) -> SimpleNamespace:
    return SimpleNamespace(
        client_order_id=_value(event, "client_order_id"),
        instrument_id=_value(event, "instrument_id"),
        trade_id=_value(event, "trade_id", _value(event, "fill_id")),
        last_qty=_value(
            event, "last_qty", _value(event, "shares", _value(event, "quantity"))
        ),
        last_px=_value(
            event, "last_px", _value(event, "fill_price", _value(event, "price"))
        ),
        liquidity_side=_value(event, "liquidity_side"),
        tags=_value(event, "tags", ()),
        metrics=dict(metrics),
        ts_event=_value(event, "ts_event", _value(event, "timestamp")),
    )


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


def _datetime_or_now(value: object) -> datetime:
    return value if isinstance(value, datetime) else datetime.now(UTC)


def _subscribe_custom_data(
    strategy: object,
    data_type: object,
    *,
    allow_fallback: bool = True,
) -> None:
    # Lazy import to avoid circular dependency: helpers ← native_strategy
    from polysignal_lab.nautilus_runtime.native_strategy import (  # noqa: PLC0415
        PolySignalNativeStrategy,
    )

    mro = type(strategy).mro()
    try:
        base_index = mro.index(PolySignalNativeStrategy) + 1
    except ValueError:
        base_index = -1
    resolved_data_type = _nautilus_data_type(data_type)
    if _subscribe_custom_data_on_bus(strategy, resolved_data_type):
        return
    base_subscribe = (
        getattr(mro[base_index], "subscribe_data", None)
        if 0 <= base_index < len(mro)
        else None
    )
    if callable(base_subscribe):
        _ = base_subscribe(strategy, resolved_data_type)
        return
    if not allow_fallback:
        return
    fallback = getattr(strategy, "subscribe_data", None)
    if callable(fallback):
        _ = fallback(resolved_data_type)


def _subscribe_custom_data_on_bus(strategy: object, data_type: object) -> bool:
    msgbus = getattr(strategy, "msgbus", None)
    if msgbus is None:
        msgbus = getattr(strategy, "_msgbus", None)
    handler = getattr(strategy, "handle_data", None)
    subscribe = getattr(msgbus, "subscribe", None)
    topic_cache = getattr(strategy, "_topic_cache", None)
    topic_getter = getattr(topic_cache, "get_custom_data_topic", None)

    if not callable(topic_getter):
        try:
            topic_module = import_module("nautilus_trader.common.data_topics")
        except ModuleNotFoundError:
            return False
        topic_cache_cls = getattr(topic_module, "TopicCache", None)
        topic_cache = topic_cache_cls() if callable(topic_cache_cls) else None
        topic_getter = getattr(topic_cache, "get_custom_data_topic", None)
    if not callable(subscribe) or not callable(topic_getter) or not callable(handler):
        return False
    _ = subscribe(topic=topic_getter(data_type, None), handler=handler)
    return True


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
