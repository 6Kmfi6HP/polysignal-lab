#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import queue
import signal
import threading
import time
from pathlib import Path
from typing import Any

from nautilus_trader.common.config import ActorConfig
from nautilus_trader.core import nautilus_pyo3 as pyo3


class SnapshotProbeConfig(ActorConfig, frozen=True):
    instrument_id: str
    client_id: str
    output_path: str
    request_delay_sec: float = 5.0
    resync_live_book: bool = False


def _book_summary(book: object | None) -> dict[str, object]:
    if book is None:
        return {"present": False}

    def levels(side: str) -> list[tuple[str, str]]:
        values = getattr(book, f"{side}_to_dict")(20)
        return [(str(price), str(size)) for price, size in values.items()]

    return {
        "present": True,
        "update_count": int(getattr(book, "update_count", 0)),
        "sequence": int(getattr(book, "sequence", 0)),
        "ts_event": int(getattr(book, "ts_event", 0)),
        "ts_init": int(getattr(book, "ts_init", 0)),
        "ts_last": int(getattr(book, "ts_last", 0)),
        "bids": levels("bids"),
        "asks": levels("asks"),
    }


class SnapshotProbeActor(pyo3.DataActor):
    def __init__(self, config: SnapshotProbeConfig) -> None:
        super().__init__(
            pyo3.DataActorConfig(  # pyright: ignore[reportAttributeAccessIssue]
                actor_id=pyo3.ActorId(str(config.component_id))
            )
        )
        self.probe_config = config
        self.instrument_id = pyo3.InstrumentId.from_str(config.instrument_id)
        self.client_id = pyo3.ClientId(config.client_id)
        self.output_path = Path(config.output_path)
        self.requested = False
        self.live_callbacks_after_request = 0
        self._records: queue.SimpleQueue[dict[str, object] | None] = queue.SimpleQueue()
        self._writer_thread: threading.Thread | None = None

    def on_start(self) -> None:
        self._writer_thread = threading.Thread(target=self._write_records, daemon=True)
        self._writer_thread.start()
        self.subscribe_book_deltas(
            self.instrument_id,
            pyo3.BookType.L2_MBP,
            client_id=self.client_id,
            managed=True,
        )
        self._record("started")
        self.clock.set_time_alert_ns(
            "snapshot-probe-request",
            self.clock.timestamp_ns() + int(self.probe_config.request_delay_sec * 1e9),
            callback=self._request_snapshot,
        )

    def on_stop(self) -> None:
        self._record("stopped")
        self.unsubscribe_book_deltas(
            self.instrument_id,
            client_id=self.client_id,
        )
        self._records.put(None)
        if self._writer_thread is not None:
            self._writer_thread.join()

    def on_book_deltas(self, deltas: object) -> None:
        if self.requested:
            self.live_callbacks_after_request += 1
        self._record(
            "live_deltas",
            delta_count=len(getattr(deltas, "deltas", ())),
            flags=str(getattr(deltas, "flags", "")),
            deltas_ts_event=int(getattr(deltas, "ts_event", 0)),
            deltas_ts_init=int(getattr(deltas, "ts_init", 0)),
        )

    def on_book(self, book: Any) -> None:
        self._record(
            "historical_received",
            data_type=type(book).__name__,
            data_ts_event=int(getattr(book, "ts_last", 0)),
            data_ts_init=int(getattr(book, "ts_init", 0)),
            live_callbacks_after_request=self.live_callbacks_after_request,
            historical_book=_book_summary(book),
        )

    def _request_snapshot(self, _event: object) -> None:
        self._record("before_request")
        self.requested = True
        started_at = time.monotonic()
        try:
            result = self.request_book_snapshot(
                self.instrument_id,
                client_id=self.client_id,
                params=(
                    {"resync_live_book": True}
                    if self.probe_config.resync_live_book
                    else None
                ),
            )
        except Exception as exc:
            self._record(
                "request_failed",
                error=repr(exc),
                latency_ms=round((time.monotonic() - started_at) * 1000, 3),
            )
            return
        self._record(
            "request_dispatched",
            result=repr(result),
            latency_ms=round((time.monotonic() - started_at) * 1000, 3),
        )

    def _record(self, event: str, **fields: object) -> None:
        try:
            book = self.cache.order_book(self.instrument_id)
        except LookupError:
            book = None
        payload = {
            "event": event,
            "recorded_at_ns": time.time_ns(),
            "instrument_id": str(self.instrument_id),
            "live_callbacks_after_request": self.live_callbacks_after_request,
            "cache_book_update_count": self.cache.book_update_count(self.instrument_id),
            "cache_book": _book_summary(book),
            **fields,
        }
        self._records.put(payload)

    def _write_records(self) -> None:
        with self.output_path.open("a", encoding="utf-8") as handle:
            while (payload := self._records.get()) is not None:
                handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe native Polymarket snapshot behavior against a managed L2 book."
    )
    parser.add_argument("instrument_id")
    parser.add_argument("--client-id", default="POLYMARKET-SNAPSHOT-PROBE")
    parser.add_argument("--duration-sec", type=float, default=15.0)
    parser.add_argument("--request-delay-sec", type=float, default=5.0)
    parser.add_argument("--resync-live-book", action="store_true")
    parser.add_argument("--output", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    module_name = __spec__.name if __spec__ is not None else "nautilus_snapshot_probe"
    instrument_id = pyo3.InstrumentId.from_str(args.instrument_id)
    output_path = Path(args.output)
    output_path.unlink(missing_ok=True)
    provider_config = pyo3.PolymarketInstrumentProviderConfig(load_ids=[instrument_id])
    data_config = pyo3.PolymarketDataClientConfig(
        instrument_config=provider_config,
        subscribe_new_markets=False,
        auto_load_missing_instruments=True,
    )
    node = (
        pyo3.LiveNode.builder(
            "SNAPSHOT-PROBE",
            pyo3.TraderId("SNAPSHOT-PROBE-001"),
            pyo3.Environment.SANDBOX,
        )
        .with_load_state(False)
        .with_save_state(False)
        .with_cache_config(pyo3.CacheConfig())
        .with_data_engine_config(pyo3.LiveDataEngineConfig(validate_data_sequence=True))
        .add_data_client(
            args.client_id,
            pyo3.PolymarketDataClientFactory(),
            data_config,
        )
        .build()
    )
    config = SnapshotProbeConfig(
        component_id="SnapshotProbe",
        instrument_id=str(instrument_id),
        client_id=args.client_id,
        output_path=str(output_path),
        request_delay_sec=args.request_delay_sec,
        resync_live_book=args.resync_live_book,
    )
    node.add_actor_from_config(
        pyo3.ImportableActorConfig(
            actor_path=f"{module_name}:SnapshotProbeActor",
            config_path=f"{module_name}:SnapshotProbeConfig",
            config=json.loads(config.json()),
        )
    )
    stop_timer = threading.Timer(
        args.duration_sec,
        os.kill,
        args=(os.getpid(), signal.SIGINT),
    )
    stop_timer.start()
    try:
        node.run()
    finally:
        stop_timer.cancel()
        node.dispose()
    print(output_path.read_text(encoding="utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
