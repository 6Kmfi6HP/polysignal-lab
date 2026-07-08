"""
Input: __future__, sqlite3, time, dataclasses, queue, threading, collections.abc, polysignal_lab.observability.health
Output: TelemetryEvent, TelemetryWriter
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from queue import Empty, Full, Queue
from threading import Event, Thread

from polysignal_lab.nautilus_runtime.observability_persistence import (
    _drop_queued_events,
    _health_mark_side_effect_failure,
    _health_mark_drop,
    _health_mark_sqlite_lock_retry,
    _health_set_backlog,
)
from polysignal_lab.observability.health import HealthRegistry


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    table: str
    payload: Mapping[str, object]


class TelemetryWriter:
    """Background SQLite writer with lock retries for best-effort telemetry."""

    def __init__(
        self,
        *,
        health: HealthRegistry,
        insert_best_effort: Callable[[str, Mapping[str, object]], None],
        queue_size: int = 1024,
        sqlite_lock_retries: int = 3,
        retry_backoff_sec: float = 0.01,
        autostart: bool = False,
    ) -> None:
        self._health = health
        self._insert_best_effort = insert_best_effort
        self._sqlite_lock_retries = sqlite_lock_retries
        self._retry_backoff_sec = retry_backoff_sec
        self._queue: Queue[TelemetryEvent] = Queue(maxsize=queue_size)
        self._stop = Event()
        self._thread: Thread | None = None
        if autostart:
            self.start()

    def enqueue(self, table: str, payload: Mapping[str, object]) -> None:
        try:
            self._queue.put_nowait(TelemetryEvent(table=table, payload=dict(payload)))
        except Full:
            _health_mark_drop(self._health, self._queue.qsize())
            return
        _health_set_backlog(self._health, self._queue.qsize())

    def drain_once(self) -> bool:
        try:
            event = self._queue.get_nowait()
        except Empty:
            _health_set_backlog(self._health, self._queue.qsize())
            return False
        try:
            self._write_event(event)
        finally:
            self._queue.task_done()
            _health_set_backlog(self._health, self._queue.qsize())
        return True

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(
            target=self._run,
            name="polysignal-telemetry-writer",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5.0)
        self._thread = None
        _drop_queued_events(self._health, self._queue, "telemetry writer stopped before draining")

    def _run(self) -> None:
        while not self._stop.is_set() or not self._queue.empty():
            if not self.drain_once():
                _ = self._stop.wait(0.1)

    def _write_event(self, event: TelemetryEvent) -> None:
        attempts = 0
        while True:
            try:
                self._insert_best_effort(event.table, event.payload)
                return
            except sqlite3.OperationalError as exc:
                if (
                    "locked" not in str(exc).lower()
                    or attempts >= self._sqlite_lock_retries
                ):
                    _health_mark_side_effect_failure(
                        self._health, kind=event.table, error=exc
                    )
                    return
                attempts += 1
                _health_mark_sqlite_lock_retry(self._health, event.table)
                time.sleep(self._retry_backoff_sec)
            except Exception as exc:
                _health_mark_side_effect_failure(
                    self._health, kind=event.table, error=exc
                )
                return
