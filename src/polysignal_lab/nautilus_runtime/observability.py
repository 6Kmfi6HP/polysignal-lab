from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, replace
from enum import Enum
from queue import Empty, Full, Queue
from threading import Event, Thread
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from polysignal_lab.alpha.types import AlphaDecision
from polysignal_lab.domain.signal import RejectedSignal, SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor
from polysignal_lab.observability.health import HealthRegistry
from polysignal_lab.utils import utc_iso
from polysignal_lab.nautilus_runtime.projections import (
    project_fill_event,
    project_order_event,
    project_position,
)


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
    def upsert_paper_order(self, order: object) -> None: ...
    def insert_paper_fill(self, fill: object) -> None: ...
    def upsert_paper_position(self, position: object) -> None: ...
    def insert_paper_trade_result(self, result: object) -> None: ...
    def insert_system_event(self, event: dict[str, object]) -> None: ...
    def append_log(self, stream: str, payload: object) -> None: ...


class Publisher(Protocol):
    async def send(self, message: str, message_type: str, signal_id: str | None = None) -> object: ...


class AcceptedSignalNotifier(Protocol):
    def __call__(self, signal: SignalCandidate, stake_usdc: float) -> None: ...






@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    table: str
    payload: Mapping[str, object]


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
        self._routes: dict[str, Callable[[dict[str, object]], None]] = {
            "signals": persistence.insert_signal,
            "rejected_signals": persistence.insert_rejected_signal,
            "settlements": persistence.insert_paper_trade_result,
            "health_snapshot": persistence.insert_system_event,
            "system_events": persistence.insert_system_event,
            "nautilus_decision": persistence.insert_system_event,
            "nautilus_order": persistence.insert_system_event,
            "nautilus_fill": persistence.insert_system_event,
            "nautilus_position": persistence.insert_system_event,
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
        self._append_log: Callable[[str, object], None] | None = persistence.append_log
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


class ObservabilityActor:
    """Receives typed events and writes them to SQLite + JSONL + health registry.

    Reuses existing PersistenceService patterns without Nautilus runtime dependency.
    """

    def __init__(
        self,
        store: EventStore | None = None,
        health: HealthRegistry | None = None,
        notifier: Notifier | None = None,
        accepted_signal_notifier: AcceptedSignalNotifier | None = None,
        telemetry_queue_size: int = 1024,
        telemetry_autostart: bool = False,
        telemetry_sqlite_lock_retries: int = 3,
        telemetry_retry_backoff_sec: float = 0.01,
    ) -> None:
        self.store: EventStore | None = store
        self.health: HealthRegistry = health or HealthRegistry()
        self.notifier: Notifier | None = notifier
        self.accepted_signal_notifier: AcceptedSignalNotifier | None = (
            accepted_signal_notifier
        )
        self._event_count: int = 0
        self._recent_rejections: dict[tuple[object, ...], float] = {}
        self._telemetry_queue: Queue[TelemetryEvent] = Queue(maxsize=telemetry_queue_size)
        self._telemetry_sqlite_lock_retries: int = telemetry_sqlite_lock_retries
        self._telemetry_retry_backoff_sec: float = telemetry_retry_backoff_sec
        self._telemetry_stop: Event = Event()
        self._telemetry_thread: Thread | None = None
        if telemetry_autostart:
            self.start()

    @property
    def event_count(self) -> int:
        return self._event_count

    def _suppress_repeat(self, key: tuple[object, ...]) -> bool:
        now = time.monotonic()
        last = self._recent_rejections.get(key)
        if last is not None and now - last < REPEAT_SUPPRESS_TTL_SEC:
            return True
        if len(self._recent_rejections) > 4096:
            cutoff = now - REPEAT_SUPPRESS_TTL_SEC
            self._recent_rejections = {
                k: t for k, t in self._recent_rejections.items() if t >= cutoff
            }
        self._recent_rejections[key] = now
        return False

    def _mark_side_effect_failure(self, *, kind: str, error: BaseException) -> None:
        component = self.health.components.get("observability_actor")
        current = 0 if component is None else int(
            component.metrics.get("non_critical_side_effect_failures", 0) or 0
        )
        self.health.mark_degraded(
            "observability_actor",
            str(error),
            side_effect_kind=kind,
            non_critical_side_effect_failures=current + 1,
        )
        component = self.health.components["observability_actor"]
        metrics = dict(component.metrics)
        metrics["error"] = str(error)
        self.health.components["observability_actor"] = replace(component, metrics=metrics)

    def _set_telemetry_backlog_metric(self) -> None:
        component = self.health.components.get("observability_actor")
        if component is None:
            self.health.set_metric(
                "observability_actor",
                "telemetry_writer_backlog",
                self._telemetry_queue.qsize(),
            )
            return
        metrics = dict(component.metrics)
        metrics["telemetry_writer_backlog"] = self._telemetry_queue.qsize()
        self.health.components["observability_actor"] = replace(component, metrics=metrics)

    def _mark_telemetry_drop(self, count: int = 1, reason: str = "telemetry queue full") -> None:
        component = self.health.components.get("observability_actor")
        current = 0 if component is None else int(
            component.metrics.get("telemetry_queue_drops", 0) or 0
        )
        self.health.mark_degraded(
            "observability_actor",
            reason,
            telemetry_queue_drops=current + count,
            telemetry_writer_backlog=self._telemetry_queue.qsize(),
        )

    def _drop_queued_telemetry(self, reason: str) -> None:
        dropped = 0
        while True:
            try:
                _ = self._telemetry_queue.get_nowait()
            except Empty:
                break
            self._telemetry_queue.task_done()
            dropped += 1
        if dropped:
            self._mark_telemetry_drop(count=dropped, reason=reason)
        else:
            self._set_telemetry_backlog_metric()

    def _mark_sqlite_lock_retry(self, table: str) -> None:
        component = self.health.components.get("observability_actor")
        current = 0 if component is None else int(
            component.metrics.get("sqlite_lock_retries", 0) or 0
        )
        self.health.set_metric(
            "observability_actor",
            "sqlite_lock_retries",
            current + 1,
        )
        component = self.health.components["observability_actor"]
        metrics = dict(component.metrics)
        metrics["sqlite_lock_retry_table"] = table
        self.health.components["observability_actor"] = replace(component, metrics=metrics)

    def _insert_best_effort(self, table: str, payload: Mapping[str, object]) -> None:
        if self.store is None:
            return
        try:
            if isinstance(self.store, NautilusEventStoreAdapter):
                self.store.insert_json(table, payload, suppress_best_effort_locks=False)
            else:
                self.store.insert_json(table, payload)
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower():
                raise
            self._mark_side_effect_failure(kind=table, error=exc)
        except (OSError, sqlite3.Error) as exc:
            self._mark_side_effect_failure(kind=table, error=exc)

    def _write_telemetry_event(self, event: TelemetryEvent) -> None:
        attempts = 0
        while True:
            try:
                self._insert_best_effort(event.table, event.payload)
                return
            except sqlite3.OperationalError as exc:
                if (
                    "locked" not in str(exc).lower()
                    or attempts >= self._telemetry_sqlite_lock_retries
                ):
                    self._mark_side_effect_failure(kind=event.table, error=exc)
                    return
                attempts += 1
                self._mark_sqlite_lock_retry(event.table)
                time.sleep(self._telemetry_retry_backoff_sec)

    def _enqueue_best_effort(self, table: str, payload: Mapping[str, object]) -> None:
        if self.store is None:
            return
        try:
            self._telemetry_queue.put_nowait(TelemetryEvent(table=table, payload=dict(payload)))
        except Full:
            self._mark_telemetry_drop()
            return
        self._set_telemetry_backlog_metric()

    def drain_telemetry_once(self) -> bool:
        try:
            event = self._telemetry_queue.get_nowait()
        except Empty:
            self._set_telemetry_backlog_metric()
            return False
        try:
            self._write_telemetry_event(event)
        finally:
            self._telemetry_queue.task_done()
            self._set_telemetry_backlog_metric()
        return True

    def _run_telemetry_writer(self) -> None:
        while not self._telemetry_stop.is_set() or not self._telemetry_queue.empty():
            if not self.drain_telemetry_once():
                _ = self._telemetry_stop.wait(0.1)

    def start(self) -> None:
        if self._telemetry_thread is not None and self._telemetry_thread.is_alive():
            return
        self._telemetry_stop.clear()
        self._telemetry_thread = Thread(
            target=self._run_telemetry_writer,
            name="polysignal-telemetry-writer",
            daemon=True,
        )
        self._telemetry_thread.start()

    def stop(self) -> None:
        self._telemetry_stop.set()
        thread = self._telemetry_thread
        if thread is not None:
            thread.join(timeout=5.0)
        self._telemetry_thread = None
        self._drop_queued_telemetry("telemetry writer stopped before draining")

    # -- Event recording --

    def record_decision(self, decision: AlphaDecision, accepted: bool) -> None:
        self._event_count += 1
        if self.store is None:
            return
        if not accepted and self._suppress_repeat((
            "decision",
            decision.strategy,
            decision.market_id,
            decision.side.value,
            tuple(decision.reason_codes),
        )):
            return
        self._enqueue_best_effort("nautilus_decision", {
            "ts": utc_iso(),
            "strategy": decision.strategy,
            "asset": decision.asset,
            "timeframe": decision.timeframe,
            "market_id": decision.market_id,
            "market_slug": decision.market_slug,
            "condition_id": decision.condition_id,
            "token_id": decision.token_id,
            "side": decision.side.value,
            "confidence": decision.confidence,
            "accepted": accepted,
            "reason_codes": list(decision.reason_codes),
            "seconds_to_close": decision.seconds_to_close,
            "data_freshness_ms": decision.data_freshness_ms,
            "metrics": dict(decision.metrics),
        })

    def record_signal(self, signal: SignalCandidate) -> None:
        self._event_count += 1
        if self.store is None:
            return
        self.store.insert_json("signals", signal.model_dump(mode="json"))


    def record_rejected_decision(self, rejected: object) -> None:
        self._event_count += 1
        candidate = getattr(rejected, "candidate", None)
        if self.store is None or not isinstance(candidate, SignalCandidate):
            return
        reason_code = str(getattr(rejected, "reason_code", ""))
        if self._suppress_repeat((
            "rejected",
            candidate.strategy,
            candidate.market_id,
            candidate.side.value,
            reason_code,
        )):
            return
        self.store.insert_json(
            "rejected_signals",
            RejectedSignal(
                candidate=candidate,
                gate_name="nautilus_decision_policy",
                reason_code=reason_code,
                details=dict(getattr(rejected, "detail", {}) or {}),
            ).model_dump(),
        )






    def record_health_snapshot(self) -> None:
        self._event_count += 1
        if self.store is None:
            return
        snapshot = self.health.snapshot()
        self._enqueue_best_effort("health_snapshot", {
            "ts": snapshot.generated_at,
            "status": snapshot.status,
            "components": [c.as_dict() for c in snapshot.components],
        })

    def record_event(self, table: str, data: Mapping[str, object]) -> None:
        self._event_count += 1
        if self.store is None:
            return
        if persistence_class_for_table(table) is PersistenceClass.BEST_EFFORT_TELEMETRY:
            self._enqueue_best_effort(table, data)
            return
        self.store.insert_json(table, data)

    def record_nautilus_order_event(self, event: object) -> None:
        self.record_event("nautilus_order", project_order_event(event))

    def record_nautilus_fill_event(self, event: object) -> None:
        self.record_event("nautilus_fill", project_fill_event(event))

    def record_nautilus_position(self, position: object) -> None:
        self.record_event("nautilus_position", project_position(position))

    def notify_accepted_signal(
        self,
        signal: SignalCandidate,
        stake_usdc: float,
    ) -> None:
        if self.accepted_signal_notifier is None:
            return
        try:
            self.accepted_signal_notifier(signal, stake_usdc)
        except Exception as exc:
            self._mark_side_effect_failure(kind="accepted_signal_notifier", error=exc)



    # -- Notifications --

    async def notify_startup(
        self,
        strategy_names: Sequence[str] = (),
        *,
        sandbox_book_type: str = "L2_MBP",
    ) -> None:
        msg = (
            f"Nautilus runtime started — {len(strategy_names)} strategies loaded — "
            f"sandbox_book_type={sandbox_book_type}"
        )
        self.health.mark_ok(
            "observability_actor",
            sandbox_book_type=sandbox_book_type,
        )
        if self.notifier is None:
            return
        await self.notifier.send(msg, "startup")

    async def notify_shutdown(self) -> None:
        if self.notifier is None:
            return
        await self.notifier.send("🛑 Nautilus runtime shutdown", "shutdown")

    async def notify_daily_report(self, summary: str) -> None:
        if self.notifier is None:
            return
        await self.notifier.send(summary, "daily_report")


class StrategyControl(Protocol):
    """Protocol for runtime strategy control used by Telegram."""

    def set_strategy_enabled(self, name: str, enabled: bool) -> None: ...
    def is_strategy_enabled(self, name: str) -> bool: ...
    def status_payload(self) -> dict[str, object]: ...


class DecisionPolicyControl:
    """Adapts DecisionPolicyActor to StrategyControl protocol."""
    def __init__(self, policy: DecisionPolicyActor) -> None:
        self._policy: DecisionPolicyActor = policy

    def set_strategy_enabled(self, name: str, enabled: bool) -> None:
        self._policy.set_strategy_enabled(name, enabled)

    def is_strategy_enabled(self, name: str) -> bool:
        return name not in self._policy.disabled_strategies

    def status_payload(self) -> dict[str, object]:
        return {
            "disabled_strategies": sorted(str(s) for s in self._policy.disabled_strategies),
        }
