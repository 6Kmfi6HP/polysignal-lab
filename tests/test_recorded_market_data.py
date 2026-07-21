"""
Input: pathlib, pytest, nautilus_trader, polysignal_lab.nautilus_runtime
Output: Recorded market data round-trip and fail-open contract tests
Pos: Test Layer - Unit/contract tests

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from pathlib import Path
from threading import Thread
from typing import Any, cast

import pytest
from nautilus_trader.core import nautilus_pyo3 as pyo3
from nautilus_trader.test_kit.rust.instruments_pyo3 import TestInstrumentProviderPyo3

from polysignal_lab.config import Settings
from polysignal_lab.nautilus_runtime.backtest_node import build_backtest_engine
from polysignal_lab.nautilus_runtime.custom_data_types import (
    PolySignalMarketMetaData,
    PolySignalPriceToBeatData,
)
from polysignal_lab.nautilus_runtime.recorded_market_data import RecordedMarketDataStore


def test_recorded_market_data_round_trip_is_backtest_ready(tmp_path: Path) -> None:
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
    spot = pyo3.PolymarketRtdsCryptoPrice(  # pyright: ignore[reportAttributeAccessIssue]
        "BTCUSDT", "99999.0", 0, 0, 25, 25
    )
    store = RecordedMarketDataStore(tmp_path)

    for item in (quote, instrument, price_to_beat, spot, metadata):
        store.record(item)

    dataset = store.read()
    window = store.read(start_ns=20, end_ns=25)
    settings = Settings()
    settings.runtime.nautilus.execution_mode = "backtest"
    engine = cast(
        Any,
        build_backtest_engine(
            settings,
            instruments=dataset.instruments,
            data=dataset.data,
        ),
    )
    engine.dispose()

    recorded = cast(tuple[Any, ...], dataset.data)
    recorded_instruments = cast(tuple[Any, ...], dataset.instruments)

    assert [type(item) for item in recorded] == [
        PolySignalMarketMetaData,
        PolySignalPriceToBeatData,
        pyo3.PolymarketRtdsCryptoPrice,  # pyright: ignore[reportAttributeAccessIssue]
        pyo3.QuoteTick,
    ]
    assert [item.to_dict() for item in recorded[:2]] == [
        metadata.to_dict(),
        price_to_beat.to_dict(),
    ]
    assert recorded[2].to_json() == spot.to_json()
    assert recorded[3].to_dict() == quote.to_dict()
    assert recorded_instruments[0].to_dict() == instrument.to_dict()
    assert dataset.start_ns == 10
    assert dataset.end_ns == 30
    assert "condition-1" in dataset.markets
    assert [item.ts_init for item in recorded] == sorted(
        item.ts_init for item in recorded
    )

    assert [type(item) for item in window.data] == [
        PolySignalPriceToBeatData,
        pyo3.PolymarketRtdsCryptoPrice,  # pyright: ignore[reportAttributeAccessIssue]
    ]
    assert window.start_ns == 20
    assert window.end_ns == 25
    assert "condition-1" in window.markets


def test_recording_failure_is_fail_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    store.record(quote)
    store._queue.join()

    assert store._writer is not None and store._writer.is_alive()
    store.close()


def test_writer_start_failure_is_fail_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = RecordedMarketDataStore(tmp_path)

    def fail(_thread: Thread) -> None:
        raise OSError("thread unavailable")

    monkeypatch.setattr(Thread, "start", fail)

    assert store.start() is False
    assert store._writer is None


def test_custom_data_only_replay_completes() -> None:
    received: list[int] = []
    instrument = TestInstrumentProviderPyo3.binary_option()
    price_to_beat = PolySignalPriceToBeatData(
        condition_id="condition-1",
        value=100_000.0,
        source="test",
        ts_event=20,
        ts_init=20,
    )

    class Probe(pyo3.DataActor):
        def __init__(self) -> None:
            super().__init__(
                pyo3.DataActorConfig(  # pyright: ignore[reportAttributeAccessIssue]
                    actor_id=pyo3.ActorId("Custom-Only-Probe")
                )
            )

        def on_start(self) -> None:
            self.subscribe_data(pyo3.DataType("PolySignalPriceToBeatData"))

        def on_data(self, data: object) -> None:
            received.append(int(getattr(getattr(data, "data"), "ts_init")))

    settings = Settings()
    settings.runtime.nautilus.execution_mode = "backtest"
    settings.runtime.nautilus.sandbox_book_type = "L1_MBP"
    engine = build_backtest_engine(
        settings,
        instruments=(instrument,),
        data=(price_to_beat,),
    )
    engine.add_actor(Probe())  # pyright: ignore[reportAttributeAccessIssue]

    try:
        engine.run()  # pyright: ignore[reportAttributeAccessIssue]
        assert received == [20]
    finally:
        engine.dispose()  # pyright: ignore[reportAttributeAccessIssue]


def test_recorded_data_replays_quotes_and_custom_data_in_timestamp_order() -> None:
    received: list[tuple[str, int]] = []
    instrument = TestInstrumentProviderPyo3.binary_option()
    quote = pyo3.QuoteTick(
        instrument_id=instrument.id,
        bid_price=pyo3.Price.from_str("0.40"),
        ask_price=pyo3.Price.from_str("0.41"),
        bid_size=pyo3.Quantity.from_str("1"),
        ask_size=pyo3.Quantity.from_str("1"),
        ts_event=30,
        ts_init=30,
    )
    price_to_beat = PolySignalPriceToBeatData(
        condition_id="condition-1",
        value=100_000.0,
        source="test",
        ts_event=20,
        ts_init=20,
    )

    class Probe(pyo3.DataActor):
        def __init__(self) -> None:
            super().__init__(
                pyo3.DataActorConfig(  # pyright: ignore[reportAttributeAccessIssue]
                    actor_id=pyo3.ActorId("Recorded-Probe")
                )
            )

        def on_start(self) -> None:
            self.subscribe_quotes(instrument.id)
            self.subscribe_data(pyo3.DataType("PolySignalPriceToBeatData"))

        def on_quote(self, tick: object) -> None:
            received.append(("quote", int(getattr(tick, "ts_init"))))

        def on_data(self, data: object) -> None:
            payload = getattr(data, "data")
            received.append(("custom", int(getattr(payload, "ts_init"))))

    settings = Settings()
    settings.runtime.nautilus.execution_mode = "backtest"
    settings.runtime.nautilus.sandbox_book_type = "L1_MBP"
    engine = build_backtest_engine(
        settings,
        instruments=(instrument,),
        data=(price_to_beat, quote),
    )
    engine.add_actor(Probe())  # pyright: ignore[reportAttributeAccessIssue]

    try:
        engine.run()  # pyright: ignore[reportAttributeAccessIssue]
        assert received == [("custom", 20), ("quote", 30)]
    finally:
        engine.dispose()  # pyright: ignore[reportAttributeAccessIssue]
