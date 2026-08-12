from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Protocol, cast

from polysignal_lab.nautilus_runtime.optional_imports import load_nautilus_module
from polysignal_lab.nautilus_runtime.strategy_state import JsonValue, StateSchemaError

_pyo3 = load_nautilus_module("nautilus_trader.core.nautilus_pyo3")
_Pyo3BookType = _pyo3.BookType
_Pyo3DataType = _pyo3.DataType
_Pyo3InstrumentId = _pyo3.InstrumentId

_book_type_from_str = cast(
    Callable[[str], object],
    getattr(_Pyo3BookType, "from_str"),
)
_instrument_id_from_str = cast(
    Callable[[str], object],
    getattr(_Pyo3InstrumentId, "from_str"),
)


def _nautilus_instrument_id(value: object) -> object:
    """Coerce any instrument id into the PyO3 family the runtime subscribes with.

    nautilus_trader ships a Cython and a PyO3 `InstrumentId` of the same name.
    Passing the wrong one into a PyO3 call raises the self-contradictory
    `'InstrumentId' object is not an instance of 'InstrumentId'`, which is what
    `on_instrument` failed with on every callback. The two render identically,
    so a string round-trip is a safe normalisation.
    """
    if isinstance(value, str):
        return _instrument_id_from_str(value)
    if isinstance(value, _Pyo3InstrumentId):
        return value
    return _instrument_id_from_str(str(value))


def _nautilus_book_type(value: str) -> object:
    return _book_type_from_str(value)


def _nautilus_data_type(value: object) -> object:
    if isinstance(value, type):
        return _Pyo3DataType(value.__name__)
    return value


class _CustomDataSubscriber(Protocol):
    def subscribe_data(
        self,
        data_type: object,
        client_id: object | None = None,
    ) -> object: ...

    def unsubscribe_data(
        self,
        data_type: object,
        client_id: object | None = None,
    ) -> object: ...


def _subscribe_custom_data(
    strategy: _CustomDataSubscriber,
    data_type: object,
    *,
    client_id: object | None = None,
) -> None:
    _ = strategy.subscribe_data(_nautilus_data_type(data_type), client_id=client_id)


def unsubscribe_custom_data(
    strategy: _CustomDataSubscriber,
    data_type: object,
    *,
    client_id: object | None = None,
) -> None:
    _ = strategy.unsubscribe_data(_nautilus_data_type(data_type), client_id=client_id)


def _value(obj: object, name: str, default: object = None) -> object:
    if isinstance(obj, Mapping):
        return cast(Mapping[object, object], obj).get(name, default)
    return getattr(obj, name, default)


def _identifier_text(value: object) -> str | None:
    if value is None:
        return None
    raw = getattr(value, "value", None)
    text = str(raw if raw is not None else value)
    return text or None


def _lookup_id_text(value: object) -> str | None:
    if value is None:
        return None
    text = _identifier_text(value)
    return None if text in (None, "") else text


def _optional_str(value: object) -> str | None:
    text = _lookup_id_text(value)
    return text


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


def _datetime_ns(value: int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1_000_000_000, UTC)


def _json_state_payload(value: object) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise StateSchemaError(
            f"{type(value).__name__} core save_state() returned non-mapping state"
        )
    return {str(key): cast(JsonValue, item) for key, item in value.items()}
