from __future__ import annotations
# pyright: reportCallIssue=false, reportAttributeAccessIssue=false, reportUnknownMemberType=false, reportUnknownVariableType=false

import pyarrow as pa
import pytest

from polysignal_lab.nautilus_runtime._customdataclass_compat import Data
from polysignal_lab.nautilus_runtime._customdataclass_compat import (
    customdataclass_pyo3,
)
from polysignal_lab.nautilus_runtime.optional_imports import load_nautilus_module


@customdataclass_pyo3()
class CompatTestData(Data):
    """Minimal decorated data type mirroring the project's custom data classes."""

    condition_id: str = ""
    value: float = 0.0
    source: str = ""
    # Project classes always carry an explicit schema (the decorator's
    # annotation-based inference does not support PEP 563 string annotations).
    _schema = pa.schema(
        [
            ("condition_id", pa.string()),
            ("value", pa.float64()),
            ("source", pa.string()),
            ("type", pa.string()),
            ("ts_event", pa.int64()),
            ("ts_init", pa.int64()),
        ]
    )


@customdataclass_pyo3()
class SignalTest(Data):
    """Name carries the Signal prefix for is_signal checks."""

    name: str = ""
    _schema = pa.schema(
        [
            ("name", pa.string()),
            ("type", pa.string()),
            ("ts_event", pa.int64()),
            ("ts_init", pa.int64()),
        ]
    )


def _sample() -> CompatTestData:
    return CompatTestData(
        condition_id="c1",
        value=1.5,
        source="anchor",
        ts_event=10,
        ts_init=20,
    )


# --- Data base class contract (mirrors old Cython `nautilus_trader.core.data.Data`) ---


def test_data_base_is_abstract() -> None:
    data = Data()
    with pytest.raises(NotImplementedError):
        _ = data.ts_event
    with pytest.raises(NotImplementedError):
        _ = data.ts_init


def test_data_base_fully_qualified_name() -> None:
    assert CompatTestData.fully_qualified_name() == (
        f"{CompatTestData.__module__}:{CompatTestData.__qualname__}"
    )


def test_data_base_is_signal() -> None:
    assert SignalTest.is_signal()
    assert SignalTest.is_signal("Test")
    assert not CompatTestData.is_signal()


# --- customdataclass_pyo3 core protocol (dict / json / bytes / arrow) ---


def test_customdataclass_dict_roundtrip() -> None:
    data = _sample()
    restored = CompatTestData.from_dict(data.to_dict())
    assert restored == data
    assert restored.ts_event == 10
    assert restored.ts_init == 20
    assert data.to_dict()["type"] == "CompatTestData"


def test_customdataclass_json_roundtrip() -> None:
    data = _sample()
    # from_json mirrors the 1.x contract: it takes the JSON-decoded dict.
    restored = CompatTestData.from_json(data.to_dict())
    assert restored == data


def test_customdataclass_bytes_roundtrip() -> None:
    data = _sample()
    restored = CompatTestData.from_bytes(data.to_bytes())
    assert restored == data


def test_customdataclass_type_name_static() -> None:
    assert CompatTestData.type_name_static() == "CompatTestData"


def test_customdataclass_arrow_record_batch_roundtrip() -> None:
    items = [_sample(), CompatTestData(condition_id="c2", value=2.5, source="x")]
    batch = items[0].encode_record_batch_py(items)
    assert isinstance(batch, pa.RecordBatch)
    restored = CompatTestData.decode_record_batch_py({}, batch)
    assert restored == items


# --- Rust pyo3 integration contract (2.0 wheel) ---


def test_customdataclass_registers_and_roundtrips_through_rust() -> None:
    from nautilus_trader._libnautilus.model import CustomData
    from nautilus_trader._libnautilus.model import DataType
    from nautilus_trader._libnautilus.model import register_custom_data_class

    register_custom_data_class(CompatTestData)
    data = _sample()
    wrapped = CustomData(DataType("CompatTestData"), data)
    assert wrapped.ts_event == 10
    restored = CustomData.from_json_bytes(wrapped.to_json_bytes())
    assert restored.data == data


def test_customdataclass_catalog_roundtrip(tmp_path) -> None:
    from nautilus_trader._libnautilus.model import CustomData
    from nautilus_trader._libnautilus.model import DataType
    from nautilus_trader._libnautilus.model import register_custom_data_class
    from nautilus_trader._libnautilus.persistence import ParquetDataCatalog

    register_custom_data_class(CompatTestData)
    catalog = ParquetDataCatalog(str(tmp_path))
    catalog.write_custom_data(
        [CustomData(DataType("CompatTestData"), _sample())]
    )
    restored = catalog.query_custom_data("CompatTestData")
    assert len(restored) == 1
    assert restored[0].data == _sample()


# --- legacy module path resolution (how custom_data_types.py accesses symbols) ---


def test_legacy_model_custom_path_resolves_decorator() -> None:
    model_custom = load_nautilus_module("nautilus_trader.model.custom")
    assert callable(model_custom.customdataclass_pyo3)


def test_legacy_core_data_path_resolves_data_base() -> None:
    core_data = load_nautilus_module("nautilus_trader.core.data")
    assert core_data.Data is Data
