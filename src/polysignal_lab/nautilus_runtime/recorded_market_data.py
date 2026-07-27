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
    """Append-only local recording with non-blocking writes from runtime callbacks.

    Not a `ParquetDataCatalog`: the recorded stream must carry pyo3
    `InstrumentClose` and `PolymarketRtdsCryptoPrice`, and neither has an arrow
    serializer registered (the registry holds the Cython `InstrumentClose`).
    """

    def __init__(self, directory: str | Path) -> None:
        self.path: Path = Path(directory) / _RECORDING_FILE
        self._queue: Queue[object | None] = Queue(maxsize=10_000)
        self._writer: Thread | None = None
        self._lock = Lock()

    def start(self) -> bool:
        with self._lock:
            if self._writer is not None:
                return True
            writer = Thread(target=self._write_loop, daemon=True)
            try:
                writer.start()
            except Exception:
                logger.exception("recorded market data writer failed to start")
                return False
            self._writer = writer
            return True

    def record(self, data: object) -> None:
        try:
            if not _is_supported(data):
                return
            if not self.start():
                return
            self._queue.put_nowait(data)
        except Full:
            logger.error("recorded market data queue full; dropping event")
        except Exception:
            logger.exception("recorded market data write failed")

    def _write_loop(self) -> None:
        while True:
            data = self._queue.get()
            try:
                if data is None:
                    return
                record = _encode_record(data)
                if record is not None:
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
                logger.error(
                    "recorded market data shutdown queue full; abandoning writer"
                )
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
        include_prior_context: bool = False,
    ) -> RecordedMarketDataSet:
        self._queue.join()
        instruments: list[object] = []
        data: list[object] = []
        prior_context: list[object] = []
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
                if timestamp < (start_ns or 0):
                    if include_prior_context and isinstance(
                        item,
                        (PolySignalMarketMetaData, PolySignalMarketUniverseData),
                    ):
                        prior_context.append(item)
                    continue
                if end_ns is not None and timestamp > end_ns:
                    continue
                data.append(item)
                markets.update(_market_ids(item))
        data = [*prior_context, *data]
        data.sort(key=lambda item: int(getattr(item, "ts_init")))
        timestamps = [int(getattr(item, "ts_init")) for item in data]
        return RecordedMarketDataSet(
            instruments=tuple(instruments),
            data=tuple(data),
            start_ns=min(timestamps) if timestamps else None,
            end_ns=max(timestamps) if timestamps else None,
            markets=tuple(sorted(markets)),
        )


def _is_supported(data: object) -> bool:
    return isinstance(
        unwrap_custom_data(data),
        (
            nautilus_pyo3.BinaryOption,
            nautilus_pyo3.QuoteTick,
            nautilus_pyo3.InstrumentClose,
            nautilus_pyo3.PolymarketRtdsCryptoPrice,  # pyright: ignore[reportAttributeAccessIssue]
            PolySignalMarketMetaData,
            PolySignalMarketUniverseData,
            PolySignalPriceToBeatData,
        ),
    )


def _encode_record(data: object) -> dict[str, object] | None:
    payload = unwrap_custom_data(data)
    if not _is_supported(payload):
        return None
    to_dict = getattr(payload, "to_dict", None)
    values = (
        to_dict()
        if callable(to_dict)
        else json.loads(cast(str, getattr(payload, "to_json")()))
    )
    return {
        "kind": "instrument"
        if isinstance(payload, nautilus_pyo3.BinaryOption)
        else "data",
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
    if type_name == "InstrumentClose":
        return nautilus_pyo3.InstrumentClose.from_dict(payload)
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
                (
                    *item.active_condition_ids,
                    *item.entered_condition_ids,
                    *item.exited_condition_ids,
                )
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
        self._instrument_markets = PolymarketInstrumentMarketBuilder(
            self.settings.markets
        )
        self._quote_subscriptions: dict[
            str,
            tuple[nautilus_pyo3.ClientId, tuple[nautilus_pyo3.InstrumentId, ...]],
        ] = {}
        self._close_subscriptions: dict[
            str,
            tuple[nautilus_pyo3.ClientId, tuple[nautilus_pyo3.InstrumentId, ...]],
        ] = {}
        self._inactive_condition_ids: set[str] = set()
        self._subscriptions_started = False

    def on_start(self) -> None:
        self.store.start()
        venue = nautilus_pyo3.Venue.from_str("POLYMARKET")
        for timeframe in self.settings.markets.timeframes:
            self.subscribe_instruments(
                venue,
                client_id=polymarket_data_client_id(timeframe),
            )
        for data_type in (
            custom_data_type(PolySignalPriceToBeatData),
            custom_data_type(PolySignalMarketMetaData),
            custom_data_type(PolySignalMarketUniverseData),
        ):
            self.subscribe_data(data_type)
        if self.settings.runtime.nautilus.spot_data.source == "polymarket_rtds":
            self._subscribe_spot_data()
        self._subscriptions_started = True

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
        if self._subscriptions_started:
            venue = nautilus_pyo3.Venue.from_str("POLYMARKET")
            for condition_id in tuple(self._quote_subscriptions):
                self._retire_quote_subscriptions((condition_id,))
            for condition_id, (client_id, instrument_ids) in tuple(
                self._close_subscriptions.items()
            ):
                for instrument_id in instrument_ids:
                    self.unsubscribe_instrument_close(
                        instrument_id,
                        client_id=client_id,
                    )
                self._close_subscriptions.pop(condition_id, None)
            for timeframe in self.settings.markets.timeframes:
                self.unsubscribe_instruments(
                    venue,
                    client_id=polymarket_data_client_id(timeframe),
                )
            for data_type in (
                custom_data_type(PolySignalPriceToBeatData),
                custom_data_type(PolySignalMarketMetaData),
                custom_data_type(PolySignalMarketUniverseData),
            ):
                self.unsubscribe_data(data_type)
            if self.settings.runtime.nautilus.spot_data.source == "polymarket_rtds":
                self._unsubscribe_spot_data()
            self._inactive_condition_ids.clear()
            self._subscriptions_started = False
        self.store.close()

    def _unsubscribe_spot_data(self) -> None:
        client_id = polymarket_rtds_data_client_id(self.settings.markets.timeframes)
        for symbol in polymarket_rtds_crypto_symbols(
            self.settings.markets.assets,
            self.settings.data.binance.symbols,
        ):
            self.unsubscribe_data(
                polymarket_rtds_crypto_price_data_type(symbol),
                client_id=client_id,
            )

    def on_dispose(self) -> None:
        self.on_stop()

    def on_instrument(self, instrument: object) -> None:
        self.store.record(instrument)
        market = self._instrument_markets.add(instrument)
        if (
            market is None
            or market.condition_id in self._quote_subscriptions
            or market.condition_id in self._inactive_condition_ids
        ):
            return
        client_id = polymarket_data_client_id(market.timeframe)
        instrument_ids = tuple(
            nautilus_pyo3.InstrumentId.from_str(
                str(
                    get_polymarket_instrument_id(
                        market.condition_id,
                        token.token_id,
                    )
                )
            )
            for token in market.outcome_tokens
        )
        close_subscription_exists = market.condition_id in self._close_subscriptions
        for instrument_id in instrument_ids:
            self.subscribe_quotes(instrument_id, client_id=client_id)
            if not close_subscription_exists:
                self.subscribe_instrument_close(instrument_id, client_id=client_id)
        self._quote_subscriptions[market.condition_id] = (client_id, instrument_ids)
        self._close_subscriptions.setdefault(
            market.condition_id,
            (client_id, instrument_ids),
        )

    def _retire_quote_subscriptions(self, condition_ids: tuple[str, ...]) -> None:
        self._inactive_condition_ids.update(condition_ids)
        for condition_id in condition_ids:
            subscription = self._quote_subscriptions.pop(condition_id, None)
            if subscription is None:
                continue
            client_id, instrument_ids = subscription
            for instrument_id in instrument_ids:
                self.unsubscribe_quotes(instrument_id, client_id=client_id)

    def _reactivate_conditions(self, condition_ids: tuple[str, ...]) -> None:
        for condition_id in condition_ids:
            if condition_id not in self._inactive_condition_ids:
                continue
            self._inactive_condition_ids.remove(condition_id)
            subscription = self._close_subscriptions.get(condition_id)
            if subscription is None:
                continue
            client_id, instrument_ids = subscription
            for instrument_id in instrument_ids:
                self.subscribe_quotes(instrument_id, client_id=client_id)
            self._quote_subscriptions[condition_id] = (client_id, instrument_ids)

    def on_quote(self, tick: object) -> None:
        self.store.record(tick)

    def on_instrument_close(self, update: object) -> None:
        self.store.record(update)
        instrument_id = getattr(update, "instrument_id", None)
        if instrument_id is None:
            return
        for condition_id, (client_id, instrument_ids) in tuple(
            self._close_subscriptions.items()
        ):
            remaining = tuple(item for item in instrument_ids if item != instrument_id)
            if len(remaining) == len(instrument_ids):
                continue
            self.unsubscribe_instrument_close(instrument_id, client_id=client_id)
            if remaining:
                self._close_subscriptions[condition_id] = (client_id, remaining)
            else:
                self._close_subscriptions.pop(condition_id, None)
            return

    def on_data(self, data: object) -> None:
        payload = unwrap_custom_data(data)
        self.store.record(payload)
        if isinstance(payload, PolySignalMarketUniverseData):
            active_condition_ids = tuple(
                dict.fromkeys(
                    (*payload.active_condition_ids, *payload.entered_condition_ids)
                )
            )
            active = set(active_condition_ids)
            self._retire_quote_subscriptions(
                tuple(
                    condition_id
                    for condition_id in payload.exited_condition_ids
                    if condition_id not in active
                )
            )
            self._reactivate_conditions(active_condition_ids)
