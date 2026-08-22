from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from queue import Empty, Full, Queue
from threading import Event, Thread
from typing import Protocol, cast

from polysignal_lab.alpha.types import AlphaDecision
from polysignal_lab.domain.signal import RejectedSignal, SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import (
    DecisionPolicy,
    RejectedDecision,
)
from polysignal_lab.nautilus_runtime.observability_persistence import (
    AcceptedSignalNotifier,
    EventStore,
    NautilusEventStoreAdapter,
    NautilusNotifierAdapter,
    ReportResultNotifier,
    PersistenceClass,
    _drop_queued_events,
    _health_mark_drop,
    _health_mark_side_effect_failure,
    _health_mark_sqlite_lock_retry,
    _health_set_backlog,
    persistence_class_for_table,
)
from polysignal_lab.nautilus_runtime.projections import (
    project_fill_event,
    project_order_event,
    project_position,
)
from polysignal_lab.observability.health import HealthRegistry
from polysignal_lab.observability.liveness_watchdog import LivenessWatchdog
from polysignal_lab.utils import utc_iso, utc_now


@dataclass(frozen=True, slots=True)
class _TelemetryEvent:
    table: str
    payload: Mapping[str, object]


# Re-exported so that existing test and application imports resolve through
# ``from polysignal_lab.nautilus_runtime.observability import ...``.
__all__ = [
    "DecisionPolicyControl",
    "EventStore",
    "NautilusEventStoreAdapter",
    "NautilusNotifierAdapter",
    "ObservabilityService",
    "PersistenceClass",
    "StrategyControl",
    "bind_runtime_observability",
    "runtime_observability",
    "persistence_class_for_table",
]

# Per-tick evaluation re-emits the same rejected decision on every market data
# event (measured ~220/s during entry windows, ~1GB/day across SQLite + JSONL).
# Identical rejection records within this window are suppressed; accepted
# decisions are never suppressed.
REPEAT_SUPPRESS_TTL_SEC = 60.0
DAILY_REPORT_CHECK_INTERVAL_SEC = 60.0
STRATEGY_STATUS_REFRESH_INTERVAL_SEC = 60.0

# Importable Strategy/Actor configs are JSON-only and cannot carry the process
# ObservabilityService. CLI/runtime binds the live instance before strategies
# construct so host_init can resolve it.
_runtime_observability: ObservabilityService | None = None


# NOTE: a plain callable (not a Protocol) so common callables — e.g.
# ``requests.append`` and lambdas — are accepted by the type checker while the
# call site still enforces ``(datetime) -> None``.
DailyReportNotifier = Callable[[datetime], None]


def bind_runtime_observability(service: ObservabilityService | None) -> None:
    """Bind or clear the process-local ObservabilityService for Importable hosts."""
    global _runtime_observability
    _runtime_observability = service


def runtime_observability() -> ObservabilityService | None:
    """Return the process-local ObservabilityService, if bound."""
    return _runtime_observability


class ObservabilityService:
    """Receives typed events and routes them by durability and retention policy.

    Reuses existing PersistenceService patterns without Nautilus runtime dependency.
    """

    def __init__(
        self,
        store: EventStore | None = None,
        health: HealthRegistry | None = None,
        notifier: NautilusNotifierAdapter | None = None,
        accepted_signal_notifier: AcceptedSignalNotifier | None = None,
        report_result_notifier: ReportResultNotifier | None = None,
        daily_report_notifier: DailyReportNotifier | None = None,
        daily_report_now: Callable[[], datetime] = utc_now,
        monotonic_clock: Callable[[], float] = time.monotonic,
        telemetry_queue_size: int = 1024,
        telemetry_autostart: bool = False,
        telemetry_sqlite_lock_retries: int = 3,
        telemetry_retry_backoff_sec: float = 0.01,
        liveness_watchdog: LivenessWatchdog | None = None,
    ) -> None:
        self.store: EventStore | None = store
        self.health: HealthRegistry = health or HealthRegistry()
        self.notifier: NautilusNotifierAdapter | None = notifier
        self.liveness_watchdog: LivenessWatchdog | None = liveness_watchdog
        self.accepted_signal_notifier: AcceptedSignalNotifier | None = (
            accepted_signal_notifier
        )
        self.report_result_notifier: ReportResultNotifier | None = (
            report_result_notifier
        )
        self.daily_report_notifier: DailyReportNotifier | None = daily_report_notifier
        self._daily_report_now = daily_report_now
        self._monotonic_clock = monotonic_clock
        self._next_daily_report_check = 0.0
        self._event_count: int = 0
        self._recent_rejections: dict[tuple[object, ...], float] = {}
        self._strategy_statuses: dict[
            tuple[str, str, str], tuple[str, str | None, float]
        ] = {}
        # Best-effort telemetry queue lives on ObservabilityService (no TelemetryWriter).
        self._telemetry_queue: Queue[_TelemetryEvent] | None = None
        self._telemetry_stop = Event()
        self._telemetry_thread: Thread | None = None
        self._sqlite_lock_retries = telemetry_sqlite_lock_retries
        self._retry_backoff_sec = telemetry_retry_backoff_sec
        if store is not None:
            self._telemetry_queue = Queue(maxsize=telemetry_queue_size)
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

    # ── Best-effort telemetry outbox (node-owned, not per-callback threads) ───

    def start(self) -> None:
        # Started before the telemetry guard below: the watchdog must run even
        # when there is no event store to drain.
        if self.liveness_watchdog is not None:
            self.liveness_watchdog.start()
        if self._telemetry_queue is None and self.daily_report_notifier is None:
            return
        if self._telemetry_thread is not None and self._telemetry_thread.is_alive():
            return
        self._telemetry_stop.clear()
        self._next_daily_report_check = 0.0
        self._telemetry_thread = Thread(
            target=self._telemetry_run,
            name="polysignal-telemetry-outbox",
            daemon=True,
        )
        self._telemetry_thread.start()

    def stop(self) -> None:
        if self.liveness_watchdog is not None:
            self.liveness_watchdog.stop()
        self._telemetry_stop.set()
        thread = self._telemetry_thread
        if thread is not None:
            thread.join(timeout=5.0)
        self._telemetry_thread = None
        if self._telemetry_queue is not None:
            _drop_queued_events(
                self.health,
                self._telemetry_queue,
                "telemetry outbox stopped before draining",
            )

    def drain_telemetry_once(self) -> bool:
        if self._telemetry_queue is None:
            return False
        try:
            event = self._telemetry_queue.get_nowait()
        except Empty:
            _health_set_backlog(self.health, self._telemetry_queue.qsize())
            return False
        try:
            self._write_telemetry_event(event)
        finally:
            self._telemetry_queue.task_done()
            _health_set_backlog(self.health, self._telemetry_queue.qsize())
        return True

    def _enqueue_best_effort(self, table: str, payload: Mapping[str, object]) -> None:
        if self._telemetry_queue is None:
            return
        try:
            self._telemetry_queue.put_nowait(
                _TelemetryEvent(table=table, payload=dict(payload))
            )
        except Full:
            _health_mark_drop(self.health, self._telemetry_queue.qsize())
            return
        _health_set_backlog(self.health, self._telemetry_queue.qsize())

    def _telemetry_run(self) -> None:
        while not self._telemetry_stop.is_set() or (
            self._telemetry_queue is not None and not self._telemetry_queue.empty()
        ):
            self._poll_daily_report()
            if not self.drain_telemetry_once():
                _ = self._telemetry_stop.wait(0.1)

    def _poll_daily_report(self) -> bool:
        now = self._monotonic_clock()
        if now < self._next_daily_report_check:
            return False
        self.request_daily_report(self._daily_report_now())
        self._next_daily_report_check = now + DAILY_REPORT_CHECK_INTERVAL_SEC
        return True

    def _write_telemetry_event(self, event: _TelemetryEvent) -> None:
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
                        self.health, kind=event.table, error=exc
                    )
                    return
                attempts += 1
                _health_mark_sqlite_lock_retry(self.health, event.table)
                time.sleep(self._retry_backoff_sec)
            except Exception as exc:
                _health_mark_side_effect_failure(
                    self.health, kind=event.table, error=exc
                )
                return

    def _insert_best_effort(self, table: str, payload: Mapping[str, object]) -> None:
        if self.store is None:
            return
        _ = self.store.insert_json(table, payload, suppress_best_effort_locks=False)

    # -- Event recording --

    def record_decision(self, decision: AlphaDecision, accepted: bool) -> None:
        self._event_count += 1
        if self.store is None:
            return
        if not accepted and self._suppress_repeat(
            (
                "decision",
                decision.strategy,
                decision.market_id,
                decision.side.value,
                tuple(decision.reason_codes),
            )
        ):
            return
        self._enqueue_best_effort(
            "nautilus_decision",
            {
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
            },
        )

    def record_signal(self, signal: SignalCandidate) -> None:
        self._event_count += 1
        if self.store is None:
            return
        self.store.insert_json("signals", signal.model_dump(mode="json"))

    def record_rejected_decision(self, rejected: RejectedDecision) -> None:
        self._event_count += 1
        candidate = rejected.publish
        if self.store is None or candidate is None:
            return
        reason_code = rejected.reason_code
        if self._suppress_repeat(
            (
                "rejected",
                candidate.strategy,
                candidate.market_id,
                candidate.side.value,
                reason_code,
            )
        ):
            return
        self.store.insert_json(
            "rejected_signals",
            RejectedSignal(
                candidate=candidate,
                gate_name="nautilus_decision_policy",
                reason_code=reason_code,
                details=dict(rejected.detail),
            ).model_dump(),
        )

    def record_health_snapshot(self) -> None:
        self._event_count += 1
        if self.store is None:
            return
        snapshot = self.health.snapshot()
        self._enqueue_best_effort(
            "health_snapshot",
            {
                "ts": snapshot.generated_at,
                "status": snapshot.status,
                "components": [c.as_dict() for c in snapshot.components],
            },
        )

    def query_report_open_positions(self) -> list[Mapping[str, object]]:
        store = self.store
        query = getattr(store, "query_report_open_positions", None)
        if not callable(query):
            return []
        rows = cast(list[Mapping[str, object]], query())
        return rows

    def record_event(self, table: str, data: Mapping[str, object]) -> bool:
        self._event_count += 1
        if self.store is None:
            return False
        if persistence_class_for_table(table) is PersistenceClass.BEST_EFFORT_TELEMETRY:
            self._enqueue_best_effort(table, data)
            return True
        return self.store.insert_json(table, data)

    def record_nautilus_order_event(
        self,
        event: object,
        metrics: Mapping[str, object] | None = None,
    ) -> None:
        self.record_event("nautilus_order", project_order_event(event, metrics=metrics))

    def record_nautilus_fill_event(
        self,
        event: object,
        metrics: Mapping[str, object] | None = None,
    ) -> None:
        self.record_event("nautilus_fill", project_fill_event(event, metrics=metrics))

    def record_nautilus_position(self, position: object) -> None:
        self.record_event("nautilus_position", project_position(position))

    def record_strategy_status(
        self,
        *,
        strategy: str,
        asset: str,
        timeframe: str,
        ready: bool,
        reason: str | None,
    ) -> None:
        status = "active" if ready else "missing_data"
        effective_reason = None if ready else reason
        self.record_strategy_status_value(
            strategy=strategy,
            asset=asset,
            timeframe=timeframe,
            status=status,
            reason=effective_reason,
        )

    def record_strategy_status_value(
        self,
        *,
        strategy: str,
        asset: str,
        timeframe: str,
        status: str,
        reason: str | None,
    ) -> None:
        key = (strategy, asset, timeframe)
        now = self._monotonic_clock()
        current = (status, reason)
        previous = self._strategy_statuses.get(key)
        if (
            previous is not None
            and previous[:2] == current
            and now - previous[2] < STRATEGY_STATUS_REFRESH_INTERVAL_SEC
        ):
            return
        created = self.record_event(
            "strategy_status",
            {
                "strategy": strategy,
                "asset": asset,
                "timeframe": timeframe,
                "status": status,
                "reason": reason,
            },
        )
        if created:
            self._strategy_statuses[key] = (*current, now)

    def record_strategy_stopped(self, strategy: str) -> None:
        for (current_strategy, asset, timeframe), _status in tuple(
            self._strategy_statuses.items()
        ):
            if current_strategy != strategy:
                continue
            self.record_strategy_status_value(
                strategy=strategy,
                asset=asset,
                timeframe=timeframe,
                status="inactive",
                reason="strategy_stopped",
            )

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
            _health_mark_side_effect_failure(
                self.health,
                kind="accepted_signal_notifier",
                error=exc,
            )

    def notify_report_result(self, result: Mapping[str, object]) -> None:
        if self.report_result_notifier is None:
            return
        trade_id = result.get("report_result_id")
        if trade_id not in (None, "") and self._suppress_repeat(
            ("report_result_notify", str(trade_id))
        ):
            return
        try:
            self.report_result_notifier(result)
        except Exception as exc:
            _health_mark_side_effect_failure(
                self.health,
                kind="report_result_notifier",
                error=exc,
            )

    def request_daily_report(self, framework_time: datetime) -> None:
        if self.daily_report_notifier is None:
            return
        try:
            self.daily_report_notifier(framework_time)
        except Exception as exc:
            _health_mark_side_effect_failure(
                self.health,
                kind="daily_report_notifier",
                error=exc,
            )

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
    def skip_reason_for(self, name: str) -> str | None: ...


class DecisionPolicyControl:
    """Adapts DecisionPolicy to StrategyControl protocol."""

    def __init__(self, policy: DecisionPolicy) -> None:
        self._policy: DecisionPolicy = policy

    def set_strategy_enabled(self, name: str, enabled: bool) -> None:
        self._policy.set_strategy_enabled(name, enabled)

    def is_strategy_enabled(self, name: str) -> bool:
        return name not in self._policy.disabled_strategies

    def status_payload(self) -> dict[str, object]:
        return {
            "disabled_strategies": sorted(
                str(s) for s in self._policy.disabled_strategies
            ),
        }

    def skip_reason_for(self, name: str) -> str | None:
        if name in self._policy.disabled_strategies:
            return "manual_disabled"
        return None
