"""
Input: json, logging, pathlib, queue, threading, nautilus_trader, polysignal_lab.config
Output: RecordedMarketDataStore, RecordedMarketDataSet, RecordedMarketDataActor
Pos: Nautilus runtime recording boundary

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from queue import Full, Queue
from threading import Lock, Thread
from typing import cast

from nautilus_trader.adapters.polymarket import get_polymarket_instrument_id
from nautilus_trader.adapters.polymarket.common import symbol as polymarket_symbol
from nautilus_trader.common.config import ActorConfig
from nautilus_trader.core import nautilus_pyo3

from polysignal_lab.config import Settings
from polysignal_lab.nautilus_runtime.custom_data_types import (
    PolySignalMarketMetaData,
    PolySignalMarketUniverseData,
    PolySignalPriceToBeatData,
    custom_data_type,
    polymarket_rtds_crypto_price_data_type,
    polymarket_rtds_crypto_symbols,
    unwrap_custom_data,
    wrap_custom_data,
)
from polysignal_lab.nautilus_runtime.instrument_markets import (
    PolymarketInstrumentMarketBuilder,
)
from polysignal_lab.nautilus_runtime.polymarket_clients import (
    polymarket_data_client_id,
    polymarket_rtds_data_client_id,
)

logger = logging.getLogger(__name__)
_RECORDING_FILE = "market_data.jsonl"
_CUSTOM_TYPES = {
    cls.__name__: cls
    for cls in (
        PolySignalMarketMetaData,
        PolySignalMarketUniverseData,
        PolySignalPriceToBeatData,
    )
}


@dataclass(frozen=True, slots=True)
class RecordedMarketDataSet:
    instruments: tuple[object, ...]
    data: tuple[object, ...]
    start_ns: int | None
    end_ns: int | None
    markets: tuple[str, ...]


class RecordedMarketDataStore:
    """Append-only local recording with non-blocking writes from runtime callbacks."""

    def __init__(self, directory: str | Path) -> None:
        self.path: Path = Path(directory) / _RECORDING_FILE
        self._queue: Queue[dict[str, object] | None] = Queue(maxsize=10_000)
        self._writer: Thread | None = None
        self._lock = Lock()

    def start(self) -> None:
        with self._lock:
            if self._writer is not None:
                return
            self._writer = Thread(target=self._write_loop, daemon=True)
            self._writer.start()

    def record(self, data: object) -> None:
        try:
            record = _encode_record(data)
            if record is None:
                return
            self.start()
            self._queue.put_nowait(record)
        except Full:
            logger.error("recorded market data queue full; dropping event")
        except Exception:
            logger.exception("recorded market data write failed")

    def _write_loop(self) -> None:
        while True:
            record = self._queue.get()
            try:
                if record is None:
                    return
                self._append(record)
            except Exception:
                logger.exception("recorded market data write failed")
            finally:
                self._queue.task_done()

    def _append(self, record: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            _ = file.write(json.dumps(record, separators=(",", ":"), sort_keys=True))
            _ = file.write("\n")

    def close(self) -> None:
        with self._lock:
            writer = self._writer
            if writer is None:
                return
            try:
                self._queue.put_nowait(None)
            except Full:
                logger.error("recorded market data shutdown queue full; abandoning writer")
                return
            self._writer = None
        writer.join(timeout=1.0)
        if writer.is_alive():
            logger.error("recorded market data writer did not stop within timeout")

    def read(
        self,
        *,
        start_ns: int | None = None,
        end_ns: int | None = None,
    ) -> RecordedMarketDataSet:
        self._queue.join()
        instruments: list[object] = []
        data: list[object] = []
        markets: set[str] = set()
        if not self.path.exists():
            return RecordedMarketDataSet((), (), None, None, ())
        with self.path.open(encoding="utf-8") as file:
            for line in file:
                try:
                    record = cast(dict[str, object], json.loads(line))
                    item = _decode_record(record)
                except Exception:
                    logger.exception("skipping invalid recorded market data line")
                    continue
                if record["kind"] == "instrument":
                    instruments.append(item)
                    markets.update(_market_ids(item))
                    continue
                timestamp = int(getattr(item, "ts_init"))
                if start_ns is not None and timestamp < start_ns:
                    continue
                if end_ns is not None and timestamp > end_ns:
                    continue
                data.append(item)
                markets.update(_market_ids(item))
        data.sort(key=lambda item: int(getattr(item, "ts_init")))
        timestamps = [int(getattr(item, "ts_init")) for item in data]
        return RecordedMarketDataSet(
            instruments=tuple(instruments),
            data=tuple(data),
            start_ns=min(timestamps) if timestamps else None,
            end_ns=max(timestamps) if timestamps else None,
            markets=tuple(sorted(markets)),
        )


def _encode_record(data: object) -> dict[str, object] | None:
    payload = unwrap_custom_data(data)
    supported = (
        nautilus_pyo3.BinaryOption,
        nautilus_pyo3.QuoteTick,
        nautilus_pyo3.PolymarketRtdsCryptoPrice,  # pyright: ignore[reportAttributeAccessIssue]
        PolySignalMarketMetaData,
        PolySignalMarketUniverseData,
        PolySignalPriceToBeatData,
    )
    if not isinstance(payload, supported):
        return None
    to_dict = getattr(payload, "to_dict", None)
    values = (
        to_dict()
        if callable(to_dict)
        else json.loads(cast(str, getattr(payload, "to_json")()))
    )
    return {
        "kind": "instrument" if isinstance(payload, nautilus_pyo3.BinaryOption) else "data",
        "type": type(payload).__name__,
        "payload": values,
    }


def _decode_record(record: dict[str, object]) -> object:
    payload = cast(dict[str, object], record["payload"])
    type_name = str(record["type"])
    if type_name == "BinaryOption":
        return nautilus_pyo3.BinaryOption.from_dict(cast(dict[str, str], payload))
    if type_name == "QuoteTick":
        return nautilus_pyo3.QuoteTick.from_dict(payload)
    if type_name == "PolymarketRtdsCryptoPrice":
        return nautilus_pyo3.PolymarketRtdsCryptoPrice.from_json(  # pyright: ignore[reportAttributeAccessIssue]
            payload
        )
    custom_type = _CUSTOM_TYPES.get(type_name)
    if custom_type is None:
        raise ValueError(f"unsupported recorded data type: {type_name}")
    return custom_type.from_dict(payload)


def _market_ids(item: object) -> tuple[str, ...]:
    if isinstance(item, PolySignalMarketMetaData | PolySignalPriceToBeatData):
        return (item.condition_id,)
    if isinstance(item, PolySignalMarketUniverseData):
        return tuple(
            dict.fromkeys(
                (*item.active_condition_ids, *item.entered_condition_ids, *item.exited_condition_ids)
            )
        )
    instrument_id = getattr(item, "instrument_id", getattr(item, "id", None))
    if instrument_id is None:
        return ()
    try:
        return (polymarket_symbol.get_polymarket_condition_id(instrument_id),)
    except (TypeError, ValueError):
        return ()


class RecordedCustomDataReplayActor(nautilus_pyo3.DataActor):
    def __init__(self, data: tuple[object, ...]) -> None:
        super().__init__(
            nautilus_pyo3.DataActorConfig(  # pyright: ignore[reportAttributeAccessIssue]
                actor_id=nautilus_pyo3.ActorId("PolySignal-CustomDataReplay")
            )
        )
        self.data = data

    def on_start(self) -> None:
        for index, item in enumerate(self.data):
            self.clock.set_time_alert_ns(  # pyright: ignore[reportAny]
                f"recorded-custom-data-{index}",
                int(getattr(item, "ts_init")),
                callback=partial(self._publish, item),
            )

    def _publish(self, item: object, _event: object) -> None:
        is_rtds = type(item).__name__ == "PolymarketRtdsCryptoPrice"
        data_type = (
            polymarket_rtds_crypto_price_data_type(str(getattr(item, "symbol")))
            if is_rtds
            else custom_data_type(type(item))
        )
        self.publish_data(  # pyright: ignore[reportAttributeAccessIssue]
            data_type, wrap_custom_data(item)
        )


class RecordedMarketDataActorConfig(ActorConfig, frozen=True):
    directory: str
    settings_json: str
    actor_id: str = "PolySignal-MarketDataRecorder"

    @classmethod
    def build(cls, settings: Settings) -> RecordedMarketDataActorConfig:
        return cls(
            directory=settings.storage.recorded_market_data_dir,
            settings_json=settings.model_dump_json(),
            actor_id="PolySignal-MarketDataRecorder",
            component_id="PolySignal-MarketDataRecorder",
        )


class RecordedMarketDataActor(nautilus_pyo3.DataActor):
    """Nautilus subscriber that records strategy-visible sandbox market data."""

    def __init__(self, config: RecordedMarketDataActorConfig) -> None:
        actor_config = nautilus_pyo3.DataActorConfig(  # pyright: ignore[reportAttributeAccessIssue]
            actor_id=nautilus_pyo3.ActorId(str(config.actor_id))
        )
        super().__init__(actor_config)
        self.settings = Settings.model_validate_json(config.settings_json)
        self.store = RecordedMarketDataStore(config.directory)
        self._instrument_markets = PolymarketInstrumentMarketBuilder(self.settings.markets)

    def on_start(self) -> None:
        self.store.start()
        venue = nautilus_pyo3.Venue.from_str("POLYMARKET")
        for timeframe in self.settings.markets.timeframes:
            self.subscribe_instruments(venue, client_id=polymarket_data_client_id(timeframe))
        for data_type in (
            custom_data_type(PolySignalPriceToBeatData),
            custom_data_type(PolySignalMarketMetaData),
            custom_data_type(PolySignalMarketUniverseData),
        ):
            self.subscribe_data(data_type)
        if self.settings.runtime.nautilus.spot_data.source == "polymarket_rtds":
            self._subscribe_spot_data()

    def _subscribe_spot_data(self) -> None:
        client_id = polymarket_rtds_data_client_id(self.settings.markets.timeframes)
        for symbol in polymarket_rtds_crypto_symbols(
            self.settings.markets.assets,
            self.settings.data.binance.symbols,
        ):
            self.subscribe_data(
                polymarket_rtds_crypto_price_data_type(symbol),
                client_id=client_id,
            )

    def on_stop(self) -> None:
        self.store.close()

    def on_dispose(self) -> None:
        self.store.close()

    def on_instrument(self, instrument: object) -> None:
        self.store.record(instrument)
        market = self._instrument_markets.add(instrument)
        if market is None:
            return
        client_id = polymarket_data_client_id(market.timeframe)
        for token in market.outcome_tokens:
            instrument_id = get_polymarket_instrument_id(
                market.condition_id,
                token.token_id,
            )
            self.subscribe_quotes(instrument_id, client_id=client_id)

    def on_quote(self, tick: object) -> None:
        self.store.record(tick)

    def on_data(self, data: object) -> None:
        self.store.record(data)
