"""
Input: __future__, __future__.annotations, pytest, polysignal_lab.nautilus_runtime.custom_data_types, polysignal_lab.nautilus_runtime.custom_data_types.(
Output: test_custom_spot_data_round_trips_dict, test_custom_price_to_beat_data_round_trips_dict, test_custom_market_meta_data_round_trips_dict
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import UTC, datetime, timedelta

from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState
from polysignal_lab.nautilus_runtime.custom_data_types import (
    PolySignalMarketMetaData,
    PolySignalPriceToBeatData,
    PolySignalSpotData,
)


def test_custom_spot_data_round_trips_dict() -> None:
    data = PolySignalSpotData(asset="BTC", symbol="BTCUSD", price=100000.0, source="polymarket_rtds", freshness_ms=10, ts_event=1, ts_init=2)

    assert PolySignalSpotData.from_dict(data.to_dict()) == data


def test_strategy_custom_data_preserves_spot_receipt_time_for_dynamic_freshness() -> None:
    received_at = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
    data = PolySignalSpotData(
        asset="BTC",
        symbol="BTCUSD",
        price=100000.0,
        source="managed_binance",
        freshness_ms=5,
        ts_event=int(received_at.timestamp() * 1_000_000_000),
        ts_init=int(received_at.timestamp() * 1_000_000_000),
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
