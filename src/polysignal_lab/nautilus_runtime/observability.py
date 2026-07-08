"""
Input: __future__, __future__.annotations, time, collections.abc, polysignal_lab.alpha.types, polysignal_lab.domain.signal, polysignal_lab.nautilus_runtime.decision_policy, polysignal_lab.observability.health, polysignal_lab.utils, polysignal_lab.nautilus_runtime.projections
Output: PersistenceClass, persistence_class_for_table, PersistenceWriter, Publisher, AcceptedSignalNotifier, EventStore, Notifier, NautilusEventStoreAdapter, NautilusNotifierAdapter, ObservabilityActor, StrategyControl, DecisionPolicyControl, REPEAT_SUPPRESS_TTL_SEC
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Protocol

from polysignal_lab.alpha.types import AlphaDecision
from polysignal_lab.domain.signal import RejectedSignal, SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor
from polysignal_lab.nautilus_runtime.observability_persistence import (
    AcceptedSignalNotifier,
    NautilusEventStoreAdapter,
    NautilusNotifierAdapter,
    PersistenceClass,
    _health_mark_side_effect_failure,
    persistence_class_for_table,
)
from polysignal_lab.nautilus_runtime.projections import (
    project_fill_event,
    project_order_event,
    project_position,
)
from polysignal_lab.nautilus_runtime.telemetry_writer import TelemetryWriter
from polysignal_lab.observability.health import HealthRegistry
from polysignal_lab.utils import utc_iso

# Re-exported so that existing test and application imports resolve through
# ``from polysignal_lab.nautilus_runtime.observability import ...``.
__all__ = [
    "DecisionPolicyControl",
    "NautilusEventStoreAdapter",
    "NautilusNotifierAdapter",
    "ObservabilityService",
    "PersistenceClass",
    "StrategyControl",
    "persistence_class_for_table",
]

# Per-tick evaluation re-emits the same rejected decision on every market data
# event (measured ~220/s during entry windows, ~1GB/day across SQLite + JSONL).
# Identical rejection records within this window are suppressed; accepted
# decisions are never suppressed.
REPEAT_SUPPRESS_TTL_SEC = 60.0


class ObservabilityService:
    """Receives typed events and writes them to SQLite + JSONL + health registry.

    Reuses existing PersistenceService patterns without Nautilus runtime dependency.
    """

    def __init__(
        self,
        store: NautilusEventStoreAdapter | None = None,
        health: HealthRegistry | None = None,
        notifier: NautilusNotifierAdapter | None = None,
        accepted_signal_notifier: AcceptedSignalNotifier | None = None,
        telemetry_queue_size: int = 1024,
        telemetry_autostart: bool = False,
        telemetry_sqlite_lock_retries: int = 3,
        telemetry_retry_backoff_sec: float = 0.01,
    ) -> None:
        self.store: NautilusEventStoreAdapter | None = store
        self.health: HealthRegistry = health or HealthRegistry()
        self.notifier: NautilusNotifierAdapter | None = notifier
        self.accepted_signal_notifier: AcceptedSignalNotifier | None = (
            accepted_signal_notifier
        )
        self._event_count: int = 0
        self._recent_rejections: dict[tuple[object, ...], float] = {}

        self._telemetry_writer: TelemetryWriter | None = None
        if store is not None:
            self._telemetry_writer = TelemetryWriter(
                health=self.health,
                insert_best_effort=self._insert_best_effort,
                queue_size=telemetry_queue_size,
                sqlite_lock_retries=telemetry_sqlite_lock_retries,
                retry_backoff_sec=telemetry_retry_backoff_sec,
                autostart=telemetry_autostart,
            )

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

    # ── Telemetry writer lifecycle ──────────────────────────────────────────────

    def start(self) -> None:
        if self._telemetry_writer is not None:
            self._telemetry_writer.start()

    def stop(self) -> None:
        if self._telemetry_writer is not None:
            self._telemetry_writer.stop()

    def drain_telemetry_once(self) -> bool:
        if self._telemetry_writer is None:
            return False
        return self._telemetry_writer.drain_once()

    def _enqueue_best_effort(self, table: str, payload: Mapping[str, object]) -> None:
        if self._telemetry_writer is None:
            return
        self._telemetry_writer.enqueue(table, payload)

    def _insert_best_effort(
        self, table: str, payload: Mapping[str, object]
    ) -> None:
        """Callback used by TelemetryWriter for the actual store write."""
        if self.store is None:
            return
        if isinstance(self.store, NautilusEventStoreAdapter):
            self.store.insert_json(table, payload, suppress_best_effort_locks=False)
        else:
            self.store.insert_json(table, payload)

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
            _health_mark_side_effect_failure(
                self.health, kind="accepted_signal_notifier", error=exc,
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

    def skip_reason_for(self, name: str) -> str | None:
        return self._policy._skip_reason_for(name)
