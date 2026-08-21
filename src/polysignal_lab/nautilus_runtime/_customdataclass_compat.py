# Project-side compatibility implementation of symbols removed in
# nautilus_trader 2.0.0rc3 (upgrade migration, issue69 root fix).
#
# The 2.0 wheel removed the pure-Python `nautilus_trader.model.custom` module
# (`customdataclass` / `customdataclass_pyo3`) and the `Data` base class that
# lived in `nautilus_trader.core.data`. This module is a verbatim copy of the
# 1.x implementations (custom.py, data.pyx) with import paths adapted:
#
# - `Data` base class: pure-Python equivalent of the old Cython cdef class.
# - `register_serializable_type` / `register_arrow`: the Python serialization
#   framework they belonged to no longer exists in 2.0; registration is now
#   owned by the Rust side via `_libnautilus.model.register_custom_data_class`
#   (the decorated classes are registered explicitly by
#   `custom_data_types.register_custom_data_type`). The calls are therefore
#   no-ops here.
#
# Never modify upstream / @refs; this module is project-owned.
# NB: no ``from __future__ import annotations`` here — the decorator inspects
# real annotation objects (string annotations would break schema inference).
# pyright: reportAttributeAccessIssue=false, reportInvalidTypeForm=false, reportMissingTypeArgument=false, reportUnknownVariableType=false, reportExplicitAny=false, reportMissingParameterType=false, reportUnknownMemberType=false, reportUnknownParameterType=false, reportUnusedParameter=false, reportUnusedFunction=false, reportUnusedCallResult=false, reportAssignmentType=false

import json
import sys
from dataclasses import dataclass
from typing import Any, cast
from typing import get_origin

import msgspec
import pyarrow as pa

from nautilus_trader.core.datetime import unix_nanos_to_iso8601

from polysignal_lab.nautilus_runtime.optional_imports import load_nautilus_module

try:
    _lib_model = load_nautilus_module("nautilus_trader._libnautilus.model")
except ImportError:
    # Legacy 1.x layout fallback.
    _lib_model = load_nautilus_module("nautilus_trader.model.identifiers")

InstrumentId = cast(type, _lib_model.InstrumentId)


class Data:
    """
    The abstract base class for all data.

    Mirrors the 1.x `nautilus_trader.core.data.Data` (Cython cdef class)
    contract: abstract `ts_event`/`ts_init` properties plus the
    `fully_qualified_name` / `is_signal` class helpers.

    Warnings
    --------
    This class should not be used directly, but through a concrete subclass.
    """

    @property
    def ts_event(self) -> int:
        """UNIX timestamp (nanoseconds) when the data event occurred."""
        raise NotImplementedError("abstract property must be implemented")

    @property
    def ts_init(self) -> int:
        """UNIX timestamp (nanoseconds) when the instance was created."""
        raise NotImplementedError("abstract property must be implemented")

    @classmethod
    def fully_qualified_name(cls) -> str:
        """Return the fully qualified name for the `Data` class."""
        return f"{cls.__module__}:{cls.__qualname__}"

    @classmethod
    def is_signal(cls, name: str = "") -> bool:
        """Determine if the current class is a signal type, optionally checking for a specific signal name."""
        if name == "":
            return cls.__name__.startswith("Signal")

        return cls.__name__ == f"Signal{name.title()}"


def _noop_register(cls: type, *_: Any, **__: Any) -> None:
    # 2.0 removed the Python serialization framework these hooks belonged to.
    # Rust-side registration (`register_custom_data_class`) is performed
    # explicitly by custom_data_types.register_custom_data_type.
    _ = cls


def customdataclass(*args, **kwargs):  # noqa: C901 (too complex)
    def wrapper(cls):  # noqa: C901 (too complex)
        create_init = False
        create_repr = False

        if cls.__init__ is object.__init__:
            create_init = True

        if cls.__repr__ is object.__repr__:
            create_repr = True

        cls = dataclass(cls, **kwargs)

        if create_init:
            # cls.fields_init allows to use positional arguments for parameters other than ts_event and ts_init
            cls.fields_init = cls.__init__

            def __init__(self, ts_event: int = 0, ts_init: int = 0, *args2, **kwargs2):
                self.fields_init(*args2, **kwargs2)

                self._ts_event = ts_event
                self._ts_init = ts_init

            cls.__init__ = __init__

        if create_repr:
            cls.fields_repr = cls.__repr__

            def __repr__(self):
                repr = self.fields_repr()
                has_fields = not repr.endswith("()")

                time_repr = (
                    f"{', ' if has_fields else ''}ts_event={unix_nanos_to_iso8601(self._ts_event)}, "
                    f"ts_init={unix_nanos_to_iso8601(self._ts_init)})"
                )

                return repr[:-1] + time_repr

            cls.__repr__ = __repr__

        if "ts_event" not in cls.__dict__:

            @property
            def ts_event(self) -> int:
                return self._ts_event

            cls.ts_event = ts_event

        if "ts_init" not in cls.__dict__:

            @property
            def ts_init(self) -> int:
                return self._ts_init

            cls.ts_init = ts_init

        if "to_dict" not in cls.__dict__:

            def to_dict(self) -> dict[str, Any]:
                annotations = _get_annotations(self.__class__)
                result = {attr: getattr(self, attr) for attr in annotations}

                if hasattr(self, "instrument_id"):
                    result["instrument_id"] = self.instrument_id.value

                result["type"] = str(cls.__name__)
                result["ts_event"] = self._ts_event
                result["ts_init"] = self._ts_init

                return result

            cls.to_dict = to_dict

        if "from_dict" not in cls.__dict__:

            @classmethod
            def from_dict(cls, data: dict[str, Any]) -> cls:
                data = dict(data)
                data.pop("type", None)
                data.pop("data_type", None)

                if "instrument_id" in data:
                    data["instrument_id"] = InstrumentId.from_str(data["instrument_id"])

                for attr, annotation in _get_annotations(cls).items():
                    if attr in data:
                        data[attr] = _deserialize_field_value(annotation, data[attr])

                return cls(**data)

            cls.from_dict = from_dict

        if "to_bytes" not in cls.__dict__:

            def to_bytes(self) -> bytes:
                return msgspec.msgpack.encode(self.to_dict())

            cls.to_bytes = to_bytes

        if "from_bytes" not in cls.__dict__:

            @classmethod
            def from_bytes(cls, data: bytes) -> cls:
                return cls.from_dict(msgspec.msgpack.decode(data))

            cls.from_bytes = from_bytes

        if "to_arrow" not in cls.__dict__:

            def to_arrow(self) -> pa.RecordBatch:
                return pa.RecordBatch.from_pylist(
                    [_arrow_dict_for_instance(self)],
                    schema=cls._schema,
                )

            cls.to_arrow = to_arrow

        if "from_arrow" not in cls.__dict__:

            @classmethod
            def from_arrow(cls, table: pa.Table) -> cls:
                return [cls.from_dict(d) for d in table.to_pylist()]

            cls.from_arrow = from_arrow

        if "_schema" not in cls.__dict__:
            cls._schema = _arrow_schema_for_class(cls)

        # 2.0 removed the Python serialization registry; these hooks are no-ops.
        _noop_register(cls, cls.to_dict, cls.from_dict)  # was register_serializable_type
        _noop_register(cls, cls._schema, cls.to_arrow, cls.from_arrow)  # was register_arrow

        return cls

    if args and callable(args[0]):
        return wrapper(args[0])

    return wrapper


def customdataclass_pyo3(*args, **kwargs):  # noqa: C901 (too complex)
    """
    Extend customdataclass with methods required for the PyO3 (Rust) catalog.

    Use this when you want to write/query custom data via ParquetDataCatalog
    (nautilus_pyo3). After defining your class, register it once by type:

        from nautilus_trader.core.nautilus_pyo3.model import register_custom_data_class
        register_custom_data_class(MyClass)

    Then use catalog.write_custom_data([...]) and catalog.query("MyClass", ...).

    """

    def wrapper(cls):  # noqa: C901 (too complex)
        cls = customdataclass(*args, **kwargs)(cls)

        if "to_json" not in cls.__dict__:

            def to_json(self) -> str:
                return json.dumps(self.to_dict())

            cls.to_json = to_json

        if "from_json" not in cls.__dict__:

            @classmethod
            def from_json(cls_inner, data: dict[str, Any]) -> Any:
                return cls_inner.from_dict(data)

            cls.from_json = from_json

        if "type_name_static" not in cls.__dict__:

            @classmethod
            def type_name_static(cls_inner) -> str:
                return cls_inner.__name__

            cls.type_name_static = type_name_static

        if "encode_record_batch_py" not in cls.__dict__:

            def encode_record_batch_py(self, items: list) -> pa.RecordBatch:
                if not hasattr(self.__class__, "_schema"):
                    msg = (
                        f"{self.__class__.__name__}: _schema not set. "
                        "Register the type with register_custom_data_class(...) so the "
                        "catalog can encode record batches."
                    )
                    raise AttributeError(msg)

                dicts = [_arrow_dict_for_instance(x) for x in items]

                return pa.RecordBatch.from_pylist(dicts, schema=self.__class__._schema)

            cls.encode_record_batch_py = encode_record_batch_py

        if "decode_record_batch_py" not in cls.__dict__:

            @classmethod
            def decode_record_batch_py(cls_inner, metadata: dict, batch: pa.RecordBatch) -> list:
                return [cls_inner.from_dict(d) for d in batch.to_pylist()]

            cls.decode_record_batch_py = decode_record_batch_py

        return cls

    if args and callable(args[0]):
        return wrapper(args[0])

    return wrapper


def _arrow_schema_for_class(cls) -> pa.Schema:
    type_mapping = {
        "InstrumentId": pa.string(),
        "str": pa.string(),
        "bool": pa.bool_(),
        "float": pa.float64(),
        "int": pa.int64(),
        "bytes": pa.binary(),
        "ndarray": pa.binary(),
        "dict": pa.string(),
    }
    annotations = _get_annotations(cls)
    fields = {}

    for attr, annotation in annotations.items():
        annotation_name = _annotation_name(annotation)
        if annotation_name not in type_mapping:
            msg = (
                f"Unsupported custom data field type for `{cls.__name__}.{attr}`: "
                f"{annotation!r}. Supported types are: {', '.join(type_mapping)}"
            )
            raise TypeError(msg)

        fields[attr] = type_mapping[annotation_name]

    return pa.schema(
        fields
        | {
            "type": pa.string(),
            "ts_event": pa.int64(),
            "ts_init": pa.int64(),
        },
    )


def _annotation_name(annotation: Any) -> str:
    if _is_dict_annotation(annotation):
        return "dict"

    if hasattr(annotation, "__name__"):
        return annotation.__name__

    origin = get_origin(annotation)
    if origin is not None and hasattr(origin, "__name__"):
        return origin.__name__

    msg = f"Unsupported custom data annotation: {annotation!r}"

    raise TypeError(msg)


def _arrow_dict_for_instance(instance: Any) -> dict[str, Any]:
    data = instance.to_dict().copy()
    annotations = _get_annotations(instance.__class__)

    for attr, annotation in annotations.items():
        data[attr] = _serialize_field_value(annotation, data[attr])

    return data


def _serialize_field_value(annotation: Any, value: Any) -> Any:
    if value is None:
        return None

    if _is_dict_annotation(annotation):
        return json.dumps(value, sort_keys=True)

    return value


def _get_annotations(cls) -> dict[str, Any]:
    # Python 3.14+ uses PEP 649 lazy annotations.
    if sys.version_info >= (3, 14) and hasattr(cls, "__annotate__") and cls.__annotate__:
        return cls.__annotate__(1)  # 1 = eval annotations

    return getattr(cls, "__annotations__", {})


def _deserialize_field_value(annotation: Any, value: Any) -> Any:
    if value is None:
        return None

    if _is_dict_annotation(annotation) and isinstance(value, str):
        return json.loads(value)

    return value


def _is_dict_annotation(annotation: Any) -> bool:
    return annotation is dict or get_origin(annotation) is dict
