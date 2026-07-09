"""
Input: __future__, sqlite3, time, dataclasses, queue, collections.abc, enum, typing, polysignal_lab.observability.health, polysignal_lab.utils, polysignal_lab.domain.signal
Output: persistence_class_for_table, PersistenceClass, PersistenceWriter, Publisher, AcceptedSignalNotifier, EventStore, Notifier, NautilusEventStoreAdapter, NautilusNotifierAdapter, _health_set_backlog, _health_mark_drop, _health_mark_side_effect_failure, _health_mark_sqlite_lock_retry, _drop_queued_events
Pos: Observability persistence routing — enums, protocols, adapters, and shared health metric helpers

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from enum import Enum
from queue import Empty, Queue
from typing import Protocol

from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.observability.health import HealthRegistry
from polysignal_lab.utils import utc_iso


class PersistenceClass(Enum):
    BEST_EFFORT_TELEMETRY = "best_effort_telemetry"
    DURABLE_OR_DEGRADED = "durable_or_degraded"
    FATAL_ON_LOSS = "fatal_on_loss"


_BEST_EFFORT_TELEMETRY_TABLES = frozenset({
    "nautilus_decision",
    "nautilus_order",
    "nautilus_fill",
    "nautilus_position",
    "health_snapshot",
})
_DURABLE_OR_DEGRADED_TABLES = frozenset({"signals", "rejected_signals"})


def persistence_class_for_table(table: str) -> PersistenceClass:
    if table in _BEST_EFFORT_TELEMETRY_TABLES:
        return PersistenceClass.BEST_EFFORT_TELEMETRY
    if table in _DURABLE_OR_DEGRADED_TABLES:
        return PersistenceClass.DURABLE_OR_DEGRADED
    return PersistenceClass.FATAL_ON_LOSS


class PersistenceWriter(Protocol):
    def insert_signal(self, signal: object) -> None: ...
    def insert_rejected_signal(self, rejected: object) -> None: ...
    def insert_paper_trade_result(self, result: object) -> None: ...
    def insert_system_event(self, event: dict[str, object]) -> None: ...
    def append_log(self, stream: str, payload: object) -> None: ...


class Publisher(Protocol):
    async def send(self, message: str, message_type: str, signal_id: str | None = None) -> object: ...


class AcceptedSignalNotifier(Protocol):
    def __call__(self, signal: SignalCandidate, stake_usdc: float) -> None: ...


class EventStore(Protocol):
    """Protocol for storing observability events."""

    def insert_json(self, table: str, data: Mapping[str, object]) -> None: ...
    def insert_many_json(self, table: str, rows: Sequence[Mapping[str, object]]) -> None: ...


class Notifier(Protocol):
    """Protocol for sending notifications."""

    async def send(self, message: str, msg_type: str = "") -> None: ...


def _event_identity(payload: Mapping[str, object]) -> str:
    for key in (
        "event_id",
        "trade_id",
        "paper_fill_id",
        "client_order_id",
        "paper_order_id",
        "position_id",
        "paper_position_id",
    ):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _system_event_id(table: str, payload: Mapping[str, object]) -> str:
    created_at = str(payload.get("created_at", ""))
    identity = _event_identity(payload)
    if identity:
        return f"{table}:{identity}:{created_at}"
    return f"{table}:{created_at}"


class NautilusEventStoreAdapter:
    """Adapts a PersistenceService-like object to the EventStore protocol."""

    def __init__(self, persistence: PersistenceWriter) -> None:
        self.persistence: PersistenceWriter = persistence
        insert_system_event = getattr(persistence, "insert_system_event", lambda payload: None)
        self._routes: dict[str, Callable[[dict[str, object]], None]] = {
            "signals": persistence.insert_signal,
            "rejected_signals": persistence.insert_rejected_signal,
            "settlements": getattr(persistence, "insert_paper_trade_result", insert_system_event),
            "health_snapshot": insert_system_event,
            "system_events": insert_system_event,
            "nautilus_decision": insert_system_event,
            "nautilus_order": insert_system_event,
            "nautilus_fill": insert_system_event,
            "nautilus_position": insert_system_event,
        }
        self._streams: dict[str, str] = {
            "signals": "signals",
            "rejected_signals": "rejected_signals",
            "settlements": "paper_trade_results",
            "health_snapshot": "system_events",
            "system_events": "system_events",
            "nautilus_decision": "nautilus_decisions",
            "nautilus_order": "nautilus_orders",
            "nautilus_fill": "nautilus_fills",
            "nautilus_position": "nautilus_positions",
        }
        self._append_log: Callable[[str, object], None] | None = getattr(persistence, "append_log", None)
        self._best_effort_tables: set[str] = set(_BEST_EFFORT_TELEMETRY_TABLES)

    def insert_json(
        self,
        table: str,
        data: Mapping[str, object],
        *,
        suppress_best_effort_locks: bool = True,
    ) -> None:
        route = self._routes.get(table)
        if route is None:
            raise ValueError(f"Unknown Nautilus event table: {table}")
        payload = dict(data)
        if table == "health_snapshot":
            _ = payload.setdefault("event_type", "health_snapshot")
            _ = payload.setdefault("severity", "info")
            created_at = payload.get("ts") or utc_iso()
            _ = payload.setdefault("created_at", created_at)
            _ = payload.setdefault("event_id", _system_event_id("health_snapshot", payload))
        elif table.startswith("nautilus_"):
            _ = payload.setdefault("event_type", table)
            _ = payload.setdefault("severity", "info")
            created_at = payload.get("ts") or utc_iso()
            _ = payload.setdefault("created_at", created_at)
            _ = payload.setdefault("event_id", _system_event_id(table, payload))
        try:
            route(payload)
        except sqlite3.OperationalError as exc:
            if (
                table not in self._best_effort_tables
                or "locked" not in str(exc).lower()
                or not suppress_best_effort_locks
            ):
                raise
        if self._append_log is not None:
            self._append_log(self._streams[table], payload)

    def insert_many_json(self, table: str, rows: Sequence[Mapping[str, object]]) -> None:
        for row in rows:
            self.insert_json(table, row)


class NautilusNotifierAdapter:
    """Adapts a publisher (e.g. TelegramPublisher) to the Notifier protocol."""

    def __init__(self, publisher: Publisher) -> None:
        self.publisher: Publisher = publisher

    async def send(self, message: str, msg_type: str = "") -> None:
        _ = await self.publisher.send(message, msg_type)


# Per-tick evaluation re-emits the same rejected decision on every market data
# event (measured ~220/s during entry windows, ~1GB/day across SQLite + JSONL).
# Identical rejection records within this window are suppressed; accepted
# decisions are never suppressed.
REPEAT_SUPPRESS_TTL_SEC = 60.0


# ── Shared health metric helpers ──────────────────────────────────────────────
# These helpers are used by both ObservabilityActor and TelemetryWriter to
# update the same observability_actor component in the health registry.


def _health_set_backlog(health: HealthRegistry, backlog: int) -> None:
    """Update the telemetry_writer_backlog metric on the health component."""
    component = health.components.get("observability_actor")
    if component is None:
        health.set_metric(
            "observability_actor",
            "telemetry_writer_backlog",
            backlog,
        )
        return
    metrics = dict(component.metrics)
    metrics["telemetry_writer_backlog"] = backlog
    health.components["observability_actor"] = replace(component, metrics=metrics)


def _health_mark_drop(
    health: HealthRegistry,
    backlog: int,
    count: int = 1,
    reason: str = "telemetry queue full",
) -> None:
    component = health.components.get("observability_actor")
    current = 0 if component is None else int(
        component.metrics.get("telemetry_queue_drops", 0) or 0
    )
    health.mark_degraded(
        "observability_actor",
        reason,
        telemetry_queue_drops=current + count,
        telemetry_writer_backlog=backlog,
    )


def _health_mark_side_effect_failure(
    health: HealthRegistry,
    *,
    kind: str,
    error: BaseException,
) -> None:
    component = health.components.get("observability_actor")
    current = 0 if component is None else int(
        component.metrics.get("non_critical_side_effect_failures", 0) or 0
    )
    health.mark_degraded(
        "observability_actor",
        str(error),
        side_effect_kind=kind,
        non_critical_side_effect_failures=current + 1,
    )
    component = health.components["observability_actor"]
    metrics = dict(component.metrics)
    metrics["error"] = str(error)
    health.components["observability_actor"] = replace(component, metrics=metrics)


def _health_mark_sqlite_lock_retry(health: HealthRegistry, table: str) -> None:
    component = health.components.get("observability_actor")
    current = 0 if component is None else int(
        component.metrics.get("sqlite_lock_retries", 0) or 0
    )
    health.set_metric(
        "observability_actor",
        "sqlite_lock_retries",
        current + 1,
    )
    component = health.components["observability_actor"]
    metrics = dict(component.metrics)
    metrics["sqlite_lock_retry_table"] = table
    health.components["observability_actor"] = replace(component, metrics=metrics)


def _drop_queued_events(
    health: HealthRegistry,
    queue: Queue,
    reason: str,
) -> None:
    dropped = 0
    while True:
        try:
            _ = queue.get_nowait()
        except Empty:
            break
        queue.task_done()
        dropped += 1
    if dropped:
        _health_mark_drop(health, queue.qsize(), count=dropped, reason=reason)
    else:
        _health_set_backlog(health, queue.qsize())
