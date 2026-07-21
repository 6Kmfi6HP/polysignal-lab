"""
Input: logging, pathlib, pytest, nautilus_trader, polysignal_lab.nautilus_runtime
Output: Recorded market data round-trip and fail-open contract tests
Pos: Test Layer - Unit/contract tests

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import logging

from nautilus_trader.core import nautilus_pyo3 as pyo3
from nautilus_trader.test_kit.rust.instruments_pyo3 import TestInstrumentProviderPyo3

from polysignal_lab.config import Settings
from polysignal_lab.nautilus_runtime.backtest_node import build_backtest_engine
from polysignal_lab.nautilus_runtime.custom_data_types import (
    PolySignalMarketMetaData,
    PolySignalPriceToBeatData,
)
from polysignal_lab.nautilus_runtime.recorded_market_data import (
    RecordedCustomDataReplayActor,
    RecordedMarketDataStore,
)


def test_recorded_market_data_round_trip_is_backtest_ready(tmp_path) -> None:
    instrument = TestInstrumentProviderPyo3.binary_option()
    quote = pyo3.QuoteTick(
        instrument_id=instrument.id,
        bid_price=pyo3.Price.from_str("0.40"),
        ask_price=pyo3.Price.from_str("0.41"),
        bid_size=pyo3.Quantity.from_str("10"),
        ask_size=pyo3.Quantity.from_str("11"),
        ts_event=30,
        ts_init=30,
    )
    metadata = PolySignalMarketMetaData(
        market_id="market-1",
        market_slug="btc-updown-5m",
        condition_id="condition-1",
        asset="BTC",
        timeframe="5m",
        up_token_id=str(instrument.id),
        down_token_id="down.POLYMARKET",
        ts_event=10,
        ts_init=10,
    )
    price_to_beat = PolySignalPriceToBeatData(
        condition_id="condition-1",
        value=100_000.0,
        source="test",
        verified=True,
        ts_event=20,
        ts_init=20,
    )
    spot = pyo3.PolymarketRtdsCryptoPrice(
        "BTCUSDT", "99999.0", 0, 0, 25, 25
    )
    store = RecordedMarketDataStore(tmp_path)

    for item in (quote, instrument, price_to_beat, spot, metadata):
        store.record(item)

    dataset = store.read()

    assert [type(item) for item in dataset.data] == [
        PolySignalMarketMetaData,
        PolySignalPriceToBeatData,
        pyo3.PolymarketRtdsCryptoPrice,
        pyo3.QuoteTick,
    ]
    assert [item.to_dict() for item in dataset.data[:2]] == [
        metadata.to_dict(),
        price_to_beat.to_dict(),
    ]
    assert dataset.data[2].to_json() == spot.to_json()
    assert dataset.data[3].to_dict() == quote.to_dict()
    assert dataset.instruments[0].to_dict() == instrument.to_dict()
    assert dataset.start_ns == 10
    assert dataset.end_ns == 30
    assert "condition-1" in dataset.markets
    assert [item.ts_init for item in dataset.data] == sorted(
        item.ts_init for item in dataset.data
    )

    window = store.read(start_ns=20, end_ns=25)
    assert [type(item) for item in window.data] == [
        PolySignalPriceToBeatData,
        pyo3.PolymarketRtdsCryptoPrice,
    ]
    assert window.start_ns == 20
    assert window.end_ns == 25
    assert "condition-1" in window.markets

    settings = Settings()
    settings.runtime.nautilus.execution_mode = "backtest"
    engine = build_backtest_engine(
        settings,
        instruments=dataset.instruments,
        data=dataset.data,
    )
    engine.dispose()


def test_recording_failure_is_logged_and_fail_open(tmp_path, monkeypatch, caplog) -> None:
    store = RecordedMarketDataStore(tmp_path)
    quote = pyo3.QuoteTick(
        instrument_id=pyo3.InstrumentId.from_str("token.POLYMARKET"),
        bid_price=pyo3.Price.from_str("0.40"),
        ask_price=pyo3.Price.from_str("0.41"),
        bid_size=pyo3.Quantity.from_str("1"),
        ask_size=pyo3.Quantity.from_str("1"),
        ts_event=1,
        ts_init=1,
    )

    def fail(_record: dict[str, object]) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(store, "_append", fail)

    with caplog.at_level(logging.ERROR):
        store.record(quote)
        store._queue.join()

    assert "recorded market data write failed" in caplog.text
    store.close()


def test_custom_data_replay_runs_after_subscription_in_timestamp_order() -> None:
    received: list[int] = []

    class Probe(pyo3.DataActor):
        def __init__(self) -> None:
            super().__init__(
                pyo3.DataActorConfig(actor_id=pyo3.ActorId("Recorded-Probe"))
            )

        def on_start(self) -> None:
            self.subscribe_data(pyo3.DataType("PolySignalPriceToBeatData"))

        def on_data(self, data: object) -> None:
            received.append(data.data.ts_init)

    items = tuple(
        PolySignalPriceToBeatData(
            condition_id="condition-1",
            value=float(timestamp),
            source="test",
            ts_event=timestamp,
            ts_init=timestamp,
        )
        for timestamp in (10, 20)
    )
    engine = pyo3.BacktestEngine(
        pyo3.BacktestEngineConfig(
            trader_id=pyo3.TraderId("RECORDED-REPLAY-001"),
            bypass_logging=True,
        )
    )
    engine.add_actor(Probe())
    engine.add_actor(RecordedCustomDataReplayActor(items))

    try:
        engine.run()
        assert received == [10, 20]
    finally:
        engine.dispose()
