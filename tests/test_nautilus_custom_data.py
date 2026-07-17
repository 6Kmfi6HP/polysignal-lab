"""
Input: __future__, __future__.annotations, pytest, polysignal_lab.nautilus_runtime.custom_data_types, polysignal_lab.nautilus_runtime.custom_data_types.(
Output: test_custom_spot_data_round_trips_dict, test_custom_price_to_beat_data_round_trips_dict, test_custom_market_meta_data_round_trips_dict
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pyarrow as pa
import pytest
from nautilus_trader.core import nautilus_pyo3
from nautilus_trader.serialization.arrow.serializer import ArrowSerializer
from nautilus_trader.core.nautilus_pyo3 import PolymarketRtdsCryptoPrice

from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState
from polysignal_lab.nautilus_runtime.custom_data_types import (
    PolySignalMarketMetaData,
    PolySignalMarketUniverseData,
    PolySignalPriceToBeatData,
    unwrap_custom_data,
    wrap_custom_data,
)


@pytest.fixture
def custom_data_samples() -> tuple[object, ...]:
    return (
        PolySignalPriceToBeatData(
            condition_id="c1",
            value=1.0,
            source="anchor",
            verified=True,
            from_anchor_service=True,
            anchor_source=None,
            anchor_lag_ms=None,
            ts_event=10,
            ts_init=20,
        ),
        PolySignalMarketMetaData(
            market_id="m1",
            market_slug="s1",
            condition_id="c1",
            asset="BTC",
            timeframe="5m",
            start_ts_ns=None,
            end_ts_ns=30,
            up_token_id="up",
            down_token_id="down",
            question=None,
            up_outcome="Yes",
            down_outcome="No",
            ts_event=10,
            ts_init=20,
        ),
        PolySignalMarketUniverseData(
            epoch=1,
            active_condition_ids=("c1", "c2"),
            entered_condition_ids=("c2",),
            exited_condition_ids=("c0",),
            condition_to_up_token={"c1": "up-1", "c2": "up-2"},
            condition_to_down_token={"c1": "down-1"},
            condition_to_asset={"c1": "BTC"},
            condition_to_timeframe={"c1": "5m"},
            ts_event=10,
            ts_init=20,
        ),
    )


def test_custom_data_round_trips_arrow(custom_data_samples) -> None:
    for data in custom_data_samples:
        batch = ArrowSerializer.serialize(data)
        restored = ArrowSerializer.deserialize(type(data), batch)

        assert isinstance(batch, pa.RecordBatch)
        assert batch.schema == type(data)._schema
        assert restored == [data]
        assert restored[0].ts_event == data.ts_event
        assert restored[0].ts_init == data.ts_init


def test_custom_data_round_trips_catalog(tmp_path, custom_data_samples) -> None:
    catalog = nautilus_pyo3.ParquetDataCatalog(str(tmp_path))

    for data in custom_data_samples:
        catalog.write_custom_data([wrap_custom_data(data)])
        restored = catalog.query_custom_data(type(data).__name__)

        assert len(restored) == 1
        assert unwrap_custom_data(restored[0]) == data


def test_strategy_custom_data_preserves_official_spot_receipt_time_for_dynamic_freshness() -> None:
    received_at = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
    data = PolymarketRtdsCryptoPrice(
        "BTCUSD",
        "100000.0",
        int(received_at.timestamp() * 1000),
        int(received_at.timestamp() * 1000),
        int(received_at.timestamp() * 1_000_000_000),
        int(received_at.timestamp() * 1_000_000_000),
    )
    state = StrategyCustomDataState()

    state.apply(data)
    spot = state.spot_for("BTC")

    assert spot is not None
    assert spot.received_at == received_at
    assert spot.freshness_ms_at(received_at + timedelta(milliseconds=250)) == 250


    data = PolySignalPriceToBeatData(
        condition_id="condition-1",
        value=100000.0,
        source="anchor",
        verified=True,
        from_anchor_service=True,
        anchor_source="chainlink",
        anchor_lag_ms=12,
        ts_event=1,
        ts_init=2,
    )

    assert PolySignalPriceToBeatData.from_dict(data.to_dict()) == data


def test_custom_market_meta_data_round_trips_dict() -> None:
    data = PolySignalMarketMetaData(
        market_id="market-1",
        market_slug="slug-1",
        condition_id="condition-1",
        asset="BTC",
        timeframe="5m",
        start_ts_ns=1,
        end_ts_ns=2,
        up_token_id="up",
        down_token_id="down",
        question="Will BTC close above 100k?",
        up_outcome="Yes",
        down_outcome="No",
        ts_event=3,
        ts_init=4,
    )

    assert PolySignalMarketMetaData.from_dict(data.to_dict()) == data
