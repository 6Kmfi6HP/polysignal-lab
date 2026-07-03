# Nautilus Runtime Error Isolation Implementation Plan

> **For agentic workers:** use subagent-driven-development; each task must write failing tests first. REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not commit after individual tasks unless the parent agent explicitly asks for commits.

**Goal:** Prevent recoverable project-owned Nautilus callback, telemetry, persistence, and readiness failures from propagating into legacy `TradingNode` queue processing while preserving fatal behavior for unclassified trading-state corruption.

**Architecture:** Keep the current legacy `nautilus_trader.live.node.TradingNode` runtime and add narrow project-owned boundaries around observability side effects, persistence classes, object classification, readiness, and cancel decisions. Best-effort telemetry becomes bounded and non-blocking; critical paper state remains durable/degraded/fatal and is never silently dropped. Callback guards are split into side-effect guards and domain-transition classification so core strategy mutation exceptions remain visible.

**Tech Stack:** Python 3.11+, pytest, SQLite `sqlite3`, standard-library `queue`/`threading`, existing `HealthRegistry`, existing Nautilus legacy `TradingNode` test stubs, local docs under `docs/nautilus_reference/developer_guide/`.

---

## File Structure

- Modify: `src/polysignal_lab/nautilus_runtime/observability.py`
  - Add persistence classification constants/types.
  - Add side-effect guard helpers.
  - Add bounded telemetry writer for best-effort Nautilus telemetry.
  - Keep critical paper-state tables on durable/degraded/fatal policy, not the telemetry drop policy.
  - Add health metrics for telemetry drops, writer backlog, SQLite lock retries, degraded persistence, and side-effect failures.
- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py`
  - Add project-owned data classification for malformed custom data and unknown mappings.
  - Guard observability/notification/mirroring calls as side effects.
  - Add readiness checks before evaluation and submission.
  - Add cancel producer gate only after the producer is identified.
- Modify: `src/polysignal_lab/nautilus_runtime/node.py`
  - Wire lifecycle start/stop for any telemetry writer created by the observability actor.
  - Keep `graceful_shutdown_on_exception=True` unchanged.
  - Add runtime regression tests around callback isolation using existing stubs.
- Modify: `src/polysignal_lab/nautilus_runtime/trading_node.py`
  - Only add config-level assertions/tests if needed for current `TradingNode` guard behavior; do not migrate to `LiveNode`.
- Modify: `src/polysignal_lab/storage/sqlite_store.py`
  - Harden connection settings with `timeout=30`, `check_same_thread=False`, `PRAGMA busy_timeout=30000`, `PRAGMA journal_mode=WAL`, and `PRAGMA synchronous=NORMAL`.
- Modify: `src/polysignal_lab/app/services/persistence_service.py`
  - Expose only small helpers needed by persistence classification or health; avoid changing persisted schema unless a test proves it is required.
- Test: `tests/test_nautilus_observability.py`
  - Persistence classification, side-effect guard, telemetry queue/drop, telemetry writer retry, critical-state failure policy.
- Test: `tests/test_nautilus_strategy_base.py`
  - Project-owned object classification, unknown mapping drops, readiness gate, callback side-effect isolation, cancel gate if producer is in strategy code.
- Test: `tests/test_nautilus_trading_node_runtime.py`
  - Runtime wiring, writer lifecycle, notification/mirroring callback isolation.
- Test: `tests/test_nautilus_node.py`
  - Legacy `TradingNode` regression coverage, startup/shutdown behavior, no live Polymarket execution regression.
- Test: `tests/test_nautilus_market_rotation.py`
  - Malformed project-owned market/custom data followed by valid data still updates runtime state.
- Test: `tests/test_storage_restore.py`
  - SQLite PRAGMA hardening and critical-state restore invariants.

## Constraints From Spec And Rules

- Do not modify files under `refs/`.
- Do not disable `graceful_shutdown_on_exception`; it must remain enabled in `build_paper_trading_node_config`.
- Do not migrate from legacy `TradingNode` to `LiveNode` in this implementation cycle.
- Do not add broad catch-all blocks around core strategy state mutation.
- Do not make live Polymarket execution possible in the default paper runtime.
- Do not use raw log-text matching as the only assertion for failure isolation; assert return behavior, stored calls, health counters, and state transitions.
- Do not commit per task unless the parent agent explicitly requests commits.

---

## Phase 1: Persistence Classification And Critical-State Tests

### Task 1: Define Persistence Classes Without Changing Runtime Behavior

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/observability.py`
- Test: `tests/test_nautilus_observability.py`

- [ ] **Step 1: Write the failing test**

Add tests that assert the table classification is explicit and separates best-effort telemetry from critical paper state:

```python
def test_nautilus_persistence_table_classification_separates_telemetry_from_critical_state() -> None:
    from polysignal_lab.nautilus_runtime.observability import (
        PersistenceClass,
        persistence_class_for_table,
    )

    assert persistence_class_for_table("nautilus_decision") is PersistenceClass.BEST_EFFORT_TELEMETRY
    assert persistence_class_for_table("nautilus_order") is PersistenceClass.BEST_EFFORT_TELEMETRY
    assert persistence_class_for_table("nautilus_fill") is PersistenceClass.BEST_EFFORT_TELEMETRY
    assert persistence_class_for_table("nautilus_position") is PersistenceClass.BEST_EFFORT_TELEMETRY
    assert persistence_class_for_table("health_snapshot") is PersistenceClass.BEST_EFFORT_TELEMETRY
    assert persistence_class_for_table("signals") is PersistenceClass.DURABLE_OR_DEGRADED
    assert persistence_class_for_table("rejected_signals") is PersistenceClass.DURABLE_OR_DEGRADED
    assert persistence_class_for_table("orders") is PersistenceClass.CRITICAL_PAPER_STATE
    assert persistence_class_for_table("fills") is PersistenceClass.CRITICAL_PAPER_STATE
    assert persistence_class_for_table("positions") is PersistenceClass.CRITICAL_PAPER_STATE
    assert persistence_class_for_table("settlements") is PersistenceClass.CRITICAL_PAPER_STATE


def test_unknown_nautilus_persistence_table_remains_fatal() -> None:
    from polysignal_lab.nautilus_runtime.observability import (
        PersistenceClass,
        persistence_class_for_table,
    )

    assert persistence_class_for_table("schema_migration") is PersistenceClass.FATAL_ON_LOSS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_nautilus_observability.py::test_nautilus_persistence_table_classification_separates_telemetry_from_critical_state tests/test_nautilus_observability.py::test_unknown_nautilus_persistence_table_remains_fatal -v`

Expected: FAIL with `ImportError` or `AttributeError` for `PersistenceClass` / `persistence_class_for_table`.

- [ ] **Step 3: Write minimal implementation**

Add this near the event-store protocol definitions in `observability.py`:

```python
from enum import Enum


class PersistenceClass(Enum):
    BEST_EFFORT_TELEMETRY = "best_effort_telemetry"
    DURABLE_OR_DEGRADED = "durable_or_degraded"
    CRITICAL_PAPER_STATE = "critical_paper_state"
    FATAL_ON_LOSS = "fatal_on_loss"


_BEST_EFFORT_TELEMETRY_TABLES = frozenset({
    "nautilus_decision",
    "nautilus_order",
    "nautilus_fill",
    "nautilus_position",
    "health_snapshot",
})
_DURABLE_OR_DEGRADED_TABLES = frozenset({"signals", "rejected_signals"})
_CRITICAL_PAPER_STATE_TABLES = frozenset({"orders", "fills", "positions", "settlements"})


def persistence_class_for_table(table: str) -> PersistenceClass:
    if table in _BEST_EFFORT_TELEMETRY_TABLES:
        return PersistenceClass.BEST_EFFORT_TELEMETRY
    if table in _DURABLE_OR_DEGRADED_TABLES:
        return PersistenceClass.DURABLE_OR_DEGRADED
    if table in _CRITICAL_PAPER_STATE_TABLES:
        return PersistenceClass.CRITICAL_PAPER_STATE
    return PersistenceClass.FATAL_ON_LOSS
```

Update `NautilusEventStoreAdapter.__init__` to derive `_best_effort_tables` from `_BEST_EFFORT_TELEMETRY_TABLES`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_nautilus_observability.py::test_nautilus_persistence_table_classification_separates_telemetry_from_critical_state tests/test_nautilus_observability.py::test_unknown_nautilus_persistence_table_remains_fatal -v`

Expected: PASS.

- [ ] **Step 5: Acceptance command**

Run: `pytest tests/test_nautilus_observability.py::test_event_store_routes_known_tables_and_rejects_unknown tests/test_nautilus_observability.py::test_nautilus_persistence_table_classification_separates_telemetry_from_critical_state -v`

Expected: PASS, proving existing routes still work and classification is explicit.

### Task 2: Prove Critical Paper State Does Not Use Telemetry Drop Policy

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/observability.py`
- Test: `tests/test_nautilus_observability.py`

- [ ] **Step 1: Write the failing test**

Add a fake persistence that locks critical state and assert the exception is not swallowed:

```python
class LockingCriticalPersistence(FakePersistence):
    def upsert_paper_order(self, order: object) -> None:
        raise sqlite3.OperationalError("database is locked")


def test_event_store_raises_on_critical_paper_state_sqlite_lock() -> None:
    adapter = NautilusEventStoreAdapter(LockingCriticalPersistence())

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        adapter.insert_json("orders", {"paper_order_id": "order-1"})
```

- [ ] **Step 2: Run test to verify it fails or documents current behavior**

Run: `pytest tests/test_nautilus_observability.py::test_event_store_raises_on_critical_paper_state_sqlite_lock -v`

Expected: PASS if current code already preserves critical failure; if FAIL, failure proves critical state is being incorrectly treated as best effort.

- [ ] **Step 3: Write minimal implementation if the test fails**

Ensure the `sqlite3.OperationalError` suppression condition checks `persistence_class_for_table(table) is PersistenceClass.BEST_EFFORT_TELEMETRY` and never suppresses `CRITICAL_PAPER_STATE`:

```python
except sqlite3.OperationalError as exc:
    if (
        persistence_class_for_table(table) is not PersistenceClass.BEST_EFFORT_TELEMETRY
        or "locked" not in str(exc).lower()
    ):
        raise
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_nautilus_observability.py::test_event_store_raises_on_critical_paper_state_sqlite_lock -v`

Expected: PASS.

- [ ] **Step 5: Acceptance command**

Run: `pytest tests/test_nautilus_observability.py::test_nautilus_event_store_keeps_runtime_callbacks_alive_when_observability_sqlite_is_locked tests/test_nautilus_observability.py::test_event_store_raises_on_critical_paper_state_sqlite_lock -v`

Expected: PASS, proving telemetry lock is isolated and critical lock remains visible.

---

## Phase 2: Side-Effect Guard And Telemetry Failure Isolation

### Task 3: Add Side-Effect Guard For ObservabilityActor Store Writes

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/observability.py`
- Test: `tests/test_nautilus_observability.py`

- [ ] **Step 1: Write the failing test**

Add a store that raises on telemetry writes and assert callbacks return while health records a side-effect failure:

```python
class FailingTelemetryStore(FakeStore):
    def insert_json(self, table: str, data: Mapping[str, object]) -> None:
        if table.startswith("nautilus_"):
            raise OSError("jsonl unavailable")
        super().insert_json(table, data)


def test_observability_actor_isolates_best_effort_telemetry_write_failure() -> None:
    actor = ObservabilityActor(store=FailingTelemetryStore())

    actor.record_decision(_decision(), accepted=True)

    component = actor.health.components["observability_actor"]
    assert component.status == "degraded"
    assert component.metrics["non_critical_side_effect_failures"] == 1
    assert actor.event_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_nautilus_observability.py::test_observability_actor_isolates_best_effort_telemetry_write_failure -v`

Expected: FAIL because `record_decision` currently propagates store exceptions or does not mark health.

- [ ] **Step 3: Write minimal implementation**

Add a private helper and use it only for best-effort telemetry calls such as `record_decision`, `record_health_snapshot`, and `record_event` when `persistence_class_for_table(table)` is best effort:

```python
def _mark_side_effect_failure(self, *, kind: str, error: BaseException) -> None:
    component = self.health.components.get("observability_actor")
    current = 0 if component is None else int(component.metrics.get("non_critical_side_effect_failures", 0))
    self.health.mark_down(
        "observability_actor",
        error=str(error),
        side_effect_kind=kind,
        non_critical_side_effect_failures=current + 1,
    )


def _insert_best_effort(self, table: str, payload: Mapping[str, object]) -> None:
    if self.store is None:
        return
    try:
        self.store.insert_json(table, payload)
    except (OSError, sqlite3.Error) as exc:
        self._mark_side_effect_failure(kind=table, error=exc)
```

Keep durable and critical methods using direct `store.insert_json` until later durable/degraded behavior is implemented.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_nautilus_observability.py::test_observability_actor_isolates_best_effort_telemetry_write_failure -v`

Expected: PASS.

- [ ] **Step 5: Acceptance command**

Run: `pytest tests/test_nautilus_observability.py::test_record_decision_writes_to_nautilus_decision_stream tests/test_nautilus_observability.py::test_observability_actor_isolates_best_effort_telemetry_write_failure -v`

Expected: PASS.

### Task 4: Guard Notification And Paper-Fill Mirror Side Effects

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/observability.py`
- Test: `tests/test_nautilus_observability.py`

- [ ] **Step 1: Write the failing test**

Add tests for sync callback side effects:

```python
def test_observability_actor_isolates_accepted_signal_notifier_failure() -> None:
    signal = SignalCandidate.build(
        strategy="test", asset="BTC", timeframe="5m", market_id="m1", market_slug="s1",
        condition_id="c1", token_id="t1", side=Side.UP, confidence=0.8,
        entry_reference_price=0.5, max_entry_price=0.55,
        seconds_to_close=120, data_freshness_ms=100, reason_codes=["EDGE"], metrics={},
    )
    actor = ObservabilityActor(
        accepted_signal_notifier=lambda _signal, _stake: (_ for _ in ()).throw(RuntimeError("telegram failed"))
    )

    actor.notify_accepted_signal(signal, 10.0)

    component = actor.health.components["observability_actor"]
    assert component.status == "degraded"
    assert component.metrics["non_critical_side_effect_failures"] == 1


def test_observability_actor_isolates_paper_fill_mirror_failure() -> None:
    actor = ObservabilityActor(
        paper_fill_mirror=lambda _payload: (_ for _ in ()).throw(RuntimeError("mirror failed"))
    )

    actor.mirror_nautilus_paper_fill({"paper_fill_id": "fill-1"})

    component = actor.health.components["observability_actor"]
    assert component.status == "degraded"
    assert component.metrics["non_critical_side_effect_failures"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_nautilus_observability.py::test_observability_actor_isolates_accepted_signal_notifier_failure tests/test_nautilus_observability.py::test_observability_actor_isolates_paper_fill_mirror_failure -v`

Expected: FAIL because notifier/mirror exceptions currently propagate.

- [ ] **Step 3: Write minimal implementation**

Wrap only the explicit non-critical side-effect callbacks:

```python
def notify_accepted_signal(self, signal: SignalCandidate, stake_usdc: float) -> None:
    if self.accepted_signal_notifier is None:
        return
    try:
        self.accepted_signal_notifier(signal, stake_usdc)
    except Exception as exc:
        self._mark_side_effect_failure(kind="accepted_signal_notifier", error=exc)


def notify_nautilus_paper_fill(self, payload: dict[str, object]) -> None:
    if self.paper_fill_notifier is None:
        return
    try:
        self.paper_fill_notifier(dict(payload))
    except Exception as exc:
        self._mark_side_effect_failure(kind="paper_fill_notifier", error=exc)


def mirror_nautilus_paper_fill(self, payload: dict[str, object]) -> None:
    if self.paper_fill_mirror is None:
        return
    try:
        self.paper_fill_mirror(dict(payload))
    except Exception as exc:
        self._mark_side_effect_failure(kind="paper_fill_mirror", error=exc)
```

Do not wrap core strategy calls in `native_strategy.py` with this broad `Exception` guard.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_nautilus_observability.py::test_observability_actor_isolates_accepted_signal_notifier_failure tests/test_nautilus_observability.py::test_observability_actor_isolates_paper_fill_mirror_failure -v`

Expected: PASS.

- [ ] **Step 5: Acceptance command**

Run: `pytest tests/test_nautilus_observability.py::test_notifier_adapter_sends_in_thread tests/test_nautilus_observability.py::test_observability_actor_isolates_accepted_signal_notifier_failure tests/test_nautilus_observability.py::test_observability_actor_isolates_paper_fill_mirror_failure -v`

Expected: PASS.

### Task 5: Add Bounded Best-Effort Telemetry Queue

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/observability.py`
- Modify: `src/polysignal_lab/nautilus_runtime/node.py`
- Test: `tests/test_nautilus_observability.py`
- Test: `tests/test_nautilus_trading_node_runtime.py`

- [ ] **Step 1: Write the failing test**

Add tests for non-blocking enqueue and queue drops:

```python
def test_best_effort_telemetry_queue_drops_when_full_and_marks_health() -> None:
    store = FakeStore()
    actor = ObservabilityActor(store=store, telemetry_queue_size=1, telemetry_autostart=False)

    actor.record_decision(_decision(market_id="m1"), accepted=True)
    actor.record_decision(_decision(market_id="m2"), accepted=True)

    component = actor.health.components["observability_actor"]
    assert component.status == "degraded"
    assert component.metrics["telemetry_queue_drops"] == 1
    assert component.metrics["telemetry_writer_backlog"] == 1
    assert store.tables == {}


def test_best_effort_telemetry_writer_drains_queued_events() -> None:
    store = FakeStore()
    actor = ObservabilityActor(store=store, telemetry_queue_size=8, telemetry_autostart=False)

    actor.record_decision(_decision(), accepted=True)
    actor.drain_telemetry_once()

    assert len(store.tables["nautilus_decision"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_nautilus_observability.py::test_best_effort_telemetry_queue_drops_when_full_and_marks_health tests/test_nautilus_observability.py::test_best_effort_telemetry_writer_drains_queued_events -v`

Expected: FAIL because constructor arguments and queue methods do not exist.

- [ ] **Step 3: Write minimal implementation**

Add a bounded queue of immutable telemetry items. The implementation can be standard-library only:

```python
from dataclasses import dataclass
from queue import Full, Queue
from threading import Event, Thread


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    table: str
    payload: Mapping[str, object]


def _enqueue_best_effort(self, table: str, payload: Mapping[str, object]) -> None:
    event = TelemetryEvent(table=table, payload=dict(payload))
    try:
        self._telemetry_queue.put_nowait(event)
    except Full:
        self._mark_telemetry_drop()
```

Implement `drain_telemetry_once()`, `start()`, `stop()`, and a single background writer thread. Use the queue for best-effort tables only. Keep direct writes for durable/critical tables.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_nautilus_observability.py::test_best_effort_telemetry_queue_drops_when_full_and_marks_health tests/test_nautilus_observability.py::test_best_effort_telemetry_writer_drains_queued_events -v`

Expected: PASS.

- [ ] **Step 5: Acceptance command**

Run: `pytest tests/test_nautilus_observability.py::test_record_decision_writes_to_nautilus_decision_stream tests/test_nautilus_observability.py::test_best_effort_telemetry_writer_drains_queued_events tests/test_nautilus_observability.py::test_best_effort_telemetry_queue_drops_when_full_and_marks_health -v`

Expected: PASS. If existing immediate-write tests fail because telemetry is now queued, update those tests to call `actor.drain_telemetry_once()` before inspecting store rows.

### Task 6: Retry Telemetry SQLite Locks Without Callback Propagation

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/observability.py`
- Test: `tests/test_nautilus_observability.py`

- [ ] **Step 1: Write the failing test**

Add a store that fails once with SQLite lock and then succeeds:

```python
class FlakyLockedTelemetryStore(FakeStore):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def insert_json(self, table: str, data: Mapping[str, object]) -> None:
        self.calls += 1
        if self.calls == 1:
            raise sqlite3.OperationalError("database is locked")
        super().insert_json(table, data)


def test_telemetry_writer_retries_transient_sqlite_lock() -> None:
    store = FlakyLockedTelemetryStore()
    actor = ObservabilityActor(store=store, telemetry_queue_size=8, telemetry_autostart=False)

    actor.record_decision(_decision(), accepted=True)
    actor.drain_telemetry_once()

    assert store.calls == 2
    assert len(store.tables["nautilus_decision"]) == 1
    component = actor.health.components["observability_actor"]
    assert component.metrics["sqlite_lock_retries"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_nautilus_observability.py::test_telemetry_writer_retries_transient_sqlite_lock -v`

Expected: FAIL because bounded retry metrics are not implemented.

- [ ] **Step 3: Write minimal implementation**

In the telemetry writer path, retry only `sqlite3.OperationalError` containing `locked`, with a small bounded retry count for tests and a short backoff:

```python
def _write_telemetry_event(self, event: TelemetryEvent) -> None:
    attempts = 0
    while True:
        try:
            self._insert_best_effort(event.table, event.payload)
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempts >= self._telemetry_sqlite_lock_retries:
                self._mark_side_effect_failure(kind=event.table, error=exc)
                return
            attempts += 1
            self._mark_sqlite_lock_retry(event.table)
            time.sleep(self._telemetry_retry_backoff_sec)
```

If `_insert_best_effort` currently swallows SQLite errors, split the code so writer retry sees SQLite lock errors before the final side-effect degradation.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_nautilus_observability.py::test_telemetry_writer_retries_transient_sqlite_lock -v`

Expected: PASS.

- [ ] **Step 5: Acceptance command**

Run: `pytest tests/test_nautilus_observability.py::test_nautilus_event_store_keeps_runtime_callbacks_alive_when_observability_sqlite_is_locked tests/test_nautilus_observability.py::test_telemetry_writer_retries_transient_sqlite_lock -v`

Expected: PASS.

---

## Phase 3: SQLite PRAGMA Hardening

### Task 7: Harden SQLiteStore Connection Settings

**Files:**
- Modify: `src/polysignal_lab/storage/sqlite_store.py`
- Test: `tests/test_storage_restore.py`

- [ ] **Step 1: Write the failing test**

Add a PRAGMA verification test:

```python
def test_sqlite_store_uses_wal_and_busy_timeout(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "pragma.sqlite3")
    try:
        journal_mode = store._conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = store._conn.execute("PRAGMA busy_timeout").fetchone()[0]
        synchronous = store._conn.execute("PRAGMA synchronous").fetchone()[0]
    finally:
        store.close()

    assert str(journal_mode).lower() == "wal"
    assert busy_timeout == 30000
    assert int(synchronous) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_storage_restore.py::test_sqlite_store_uses_wal_and_busy_timeout -v`

Expected: FAIL because `busy_timeout` and WAL are not set.

- [ ] **Step 3: Write minimal implementation**

Change `SQLiteStore.__init__` only:

```python
self._conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
self._conn.row_factory = sqlite3.Row
self._conn.execute("PRAGMA busy_timeout=30000")
self._conn.execute("PRAGMA journal_mode=WAL")
self._conn.execute("PRAGMA synchronous=NORMAL")
self.migrate()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_storage_restore.py::test_sqlite_store_uses_wal_and_busy_timeout -v`

Expected: PASS.

- [ ] **Step 5: Acceptance command**

Run: `pytest tests/test_storage_restore.py -v`

Expected: PASS.

---

## Phase 4: Project-Owned Object Boundary Classification

### Task 8: Classify Malformed Project-Owned Custom Data Without Raising

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py`
- Test: `tests/test_nautilus_strategy_base.py`

- [ ] **Step 1: Write the failing test**

Add a classifier test using a fake strategy fixture already present in `tests/test_nautilus_strategy_base.py`:

```python
def test_native_strategy_drops_unknown_project_owned_data_with_metric(strategy) -> None:
    observed: list[tuple[str, object]] = []
    strategy.progress_callback = lambda phase: observed.append((phase, None))

    strategy.on_data(object())

    assert ("dropped_frame", None) in observed
```

If the fixture name differs, use the existing helper that constructs `PolySignalNativeStrategy` with fake core, registry, sidecar, and assembler.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_nautilus_strategy_base.py::test_native_strategy_drops_unknown_project_owned_data_with_metric -v`

Expected: FAIL because unknown data currently falls through to assembler/update/evaluate behavior without classification.

- [ ] **Step 3: Write minimal implementation**

Add explicit classification names and a small function:

```python
class DataBoundaryClassification(Enum):
    VALID_DATA = "ValidData"
    DROPPED_FRAME = "DroppedFrame"
    RECOVERABLE_FEED_ERROR = "RecoverableFeedError"
    FATAL_FEED_ERROR = "FatalFeedError"


def classify_project_owned_data(data: object) -> DataBoundaryClassification:
    if isinstance(data, (
        PolySignalSpotData,
        PolySignalPriceToBeatData,
        PolySignalMarketMetaData,
        PolySignalMarketUniverseData,
    )):
        return DataBoundaryClassification.VALID_DATA
    if getattr(data, "condition_id", None) is None:
        return DataBoundaryClassification.DROPPED_FRAME
    return DataBoundaryClassification.VALID_DATA
```

At the start of `on_data`, call the classifier and return on `DROPPED_FRAME` after `_note_runtime_progress("dropped_frame")`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_nautilus_strategy_base.py::test_native_strategy_drops_unknown_project_owned_data_with_metric -v`

Expected: PASS.

- [ ] **Step 5: Acceptance command**

Run: `pytest tests/test_nautilus_strategy_base.py -k "on_data or project_owned or dropped" -v`

Expected: PASS for the selected tests.

### Task 9: Drop Unknown Instrument Mapping With Metrics

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py`
- Test: `tests/test_nautilus_strategy_base.py`

- [ ] **Step 1: Write the failing test**

Add a test for market data callbacks with unknown instrument IDs:

```python
def test_native_strategy_unknown_quote_tick_instrument_is_dropped_with_metric(strategy) -> None:
    phases: list[str] = []
    strategy.progress_callback = phases.append

    strategy.on_quote_tick(SimpleNamespace(instrument_id="unknown.POLYMARKET", bid_price=0.1, ask_price=0.2))

    assert "dropped_frame" in phases
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_nautilus_strategy_base.py::test_native_strategy_unknown_quote_tick_instrument_is_dropped_with_metric -v`

Expected: FAIL because the method currently returns silently with no metric/progress signal.

- [ ] **Step 3: Write minimal implementation**

In `_update_book_from_quote_tick`, `_update_book_from_order_book`, `_update_book_from_deltas`, and `_update_trade_from_tick`, add `_note_runtime_progress("dropped_frame")` before returns caused by unknown `instrument_id`, missing `token_id`, or missing `condition_id`:

```python
if token_id is None or condition_id is None:
    self._note_runtime_progress("dropped_frame")
    return None
```

Do not catch exceptions from `_domain_order_book` yet; malformed book conversion can be classified in a later task if tests prove it recoverable.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_nautilus_strategy_base.py::test_native_strategy_unknown_quote_tick_instrument_is_dropped_with_metric -v`

Expected: PASS.

- [ ] **Step 5: Acceptance command**

Run: `pytest tests/test_nautilus_strategy_base.py -k "unknown or dropped or quote_tick" -v`

Expected: PASS.

---

## Phase 5: Readiness Gate

### Task 10: Skip Evaluation When MarketView Required Inputs Are Missing

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py`
- Test: `tests/test_nautilus_strategy_base.py`

- [ ] **Step 1: Write the failing test**

Add a test where the assembler returns a market view missing required book/account conversion data and the core must not be called:

```python
def test_native_strategy_readiness_gate_skips_missing_required_market_view_inputs(strategy) -> None:
    calls: list[object] = []
    strategy.core.evaluate = lambda view: calls.append(view) or []
    strategy.assembler.build = lambda _condition_id: SimpleNamespace(
        condition_id="condition-btc-5m",
        up_book=None,
        down_book=None,
        spot=None,
        price_to_beat=None,
    )
    phases: list[str] = []
    strategy.progress_callback = phases.append

    strategy.evaluate_condition("condition-btc-5m")

    assert calls == []
    assert "readiness_miss" in phases
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_nautilus_strategy_base.py::test_native_strategy_readiness_gate_skips_missing_required_market_view_inputs -v`

Expected: FAIL because `core.evaluate` is called or because no readiness metric is emitted.

- [ ] **Step 3: Write minimal implementation**

Add a readiness predicate that requires both books and treats missing quote/account conversion inputs as skip, not fatal:

```python
def _market_view_ready(view: MarketView) -> bool:
    try:
        _ = view.book_for(Side.UP)
        _ = view.book_for(Side.DOWN)
    except (AttributeError, ValueError):
        return False
    return True
```

Use it in `evaluate_condition` and in the fill-decision branch before `_handle_decision`:

```python
if not _market_view_ready(view):
    self._note_runtime_progress("readiness_miss")
    return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_nautilus_strategy_base.py::test_native_strategy_readiness_gate_skips_missing_required_market_view_inputs -v`

Expected: PASS.

- [ ] **Step 5: Acceptance command**

Run: `pytest tests/test_nautilus_strategy_base.py -k "readiness or evaluate_condition" -v`

Expected: PASS.

### Task 11: Prevent Order Submission When Readiness Becomes Missing After Decision

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py`
- Test: `tests/test_nautilus_strategy_base.py`

- [ ] **Step 1: Write the failing test**

Add a test where an approved decision receives a view whose side book is missing:

```python
def test_native_strategy_does_not_submit_when_approved_decision_view_lacks_book(strategy, approved_decision) -> None:
    submitted: list[object] = []
    strategy._submit_approved = lambda approved, *, view: submitted.append((approved, view))
    view = SimpleNamespace(book_for=lambda _side: (_ for _ in ()).throw(ValueError("Quote maps must not be empty")))

    strategy._handle_decision(approved_decision.decision, view)

    assert submitted == []
```

Use the existing approved-decision helper if present; otherwise construct a policy result through the existing decision-policy fixtures in `tests/test_nautilus_strategy_base.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_nautilus_strategy_base.py::test_native_strategy_does_not_submit_when_approved_decision_view_lacks_book -v`

Expected: FAIL because `_submit_approved` or `view.book_for` exception propagates.

- [ ] **Step 3: Write minimal implementation**

At the start of `_handle_decision`, before policy evaluation or submission, skip when `_market_view_ready(view)` is false:

```python
if not _market_view_ready(view):
    self._note_runtime_progress("readiness_miss")
    return
```

Keep the existing `ValueError` catch around `_submit_approved` for mapping failures.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_nautilus_strategy_base.py::test_native_strategy_does_not_submit_when_approved_decision_view_lacks_book -v`

Expected: PASS.

- [ ] **Step 5: Acceptance command**

Run: `pytest tests/test_nautilus_strategy_base.py -k "readiness or submit" -v`

Expected: PASS.

---

## Phase 6: Cancel Producer Investigation And Targeted Gate

### Task 12: Locate Cancel Producer Before Adding A Gate

**Files:**
- Inspect only: `src/polysignal_lab/nautilus_runtime/native_strategy.py`
- Inspect only: `src/polysignal_lab/nautilus_runtime/node.py`
- Inspect only: `src/polysignal_lab/nautilus_runtime/trading_node.py`
- Inspect only: `src/polysignal_lab/nautilus_runtime/native_order.py`
- Inspect only: `src/polysignal_lab/alpha/*_core.py`
- Test: no production-code changes in this task unless a project-owned producer is found

- [ ] **Step 1: Run the investigation command**

Run: `rg "cancel_order|cancel_all|cancel\(|submit_order|TimeInForce|GTD|IOC|FOK" src/polysignal_lab tests -n`

Expected: output identifies whether cancel requests originate in project code, Nautilus shutdown behavior, or adapter/order lifecycle behavior.

- [ ] **Step 2: Record the result in the task handoff notes**

If no project-owned call site emits cancel requests, record this exact conclusion for the parent agent: `No project-owned cancel producer was found; INITIALIZED cancel likely originates from Nautilus matching-engine shutdown/order lifecycle behavior and should not receive a speculative project gate.`

If a project-owned call site is found, record the exact file, function, and state object used to decide cancelability.

- [ ] **Step 3: Add a failing test only if a project-owned cancel producer is found**

For a producer in `native_strategy.py`, add:

```python
def test_cancel_gate_refuses_initialized_orders_before_cancel_request(strategy) -> None:
    calls: list[object] = []
    strategy.cancel_order = lambda order: calls.append(order)
    order = SimpleNamespace(status="INITIALIZED", client_order_id="C-001")

    strategy._cancel_order_if_allowed(order, reason="test")

    assert calls == []
```

- [ ] **Step 4: Run test to verify it fails if the producer exists**

Run: `pytest tests/test_nautilus_strategy_base.py::test_cancel_gate_refuses_initialized_orders_before_cancel_request -v`

Expected: FAIL if the helper does not exist or if cancellation is attempted.

- [ ] **Step 5: Write minimal implementation only if the producer exists**

Add a local predicate at the producer, not a generic API:

```python
_CANCELABLE_ORDER_STATES = frozenset({"SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED"})


def _order_status_text(order: object) -> str:
    status = getattr(order, "status", None)
    return str(getattr(status, "value", status) or "")


def _order_is_cancelable(order: object) -> bool:
    return _order_status_text(order) in _CANCELABLE_ORDER_STATES
```

Use this predicate immediately before the identified cancel call and emit `_note_runtime_progress("cancel_gate_skip")` when blocked.

- [ ] **Step 6: Run test to verify it passes if implemented**

Run: `pytest tests/test_nautilus_strategy_base.py::test_cancel_gate_refuses_initialized_orders_before_cancel_request -v`

Expected: PASS.

- [ ] **Step 7: Acceptance command**

If a gate was implemented, run: `pytest tests/test_nautilus_strategy_base.py -k "cancel" -v`.

If no producer was found, run: `rg "cancel_order|cancel_all|cancel\(" src/polysignal_lab/nautilus_runtime src/polysignal_lab/alpha -n` and include the output summary in the handoff.

Expected: either targeted gate tests pass, or investigation evidence shows no project-owned producer exists.

---

## Phase 7: Integration And Runtime Regression Tests

### Task 13: Verify Callback Telemetry Lock Does Not Propagate Through Native Strategy Order Event

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py` only if prior guard wiring missed this path
- Test: `tests/test_nautilus_strategy_base.py`

- [ ] **Step 1: Write the failing test**

Add an observability fake that raises from `record_nautilus_order_event` and assert `on_order_submitted` still calls core:

```python
def test_order_submitted_observability_failure_does_not_block_core_event(strategy) -> None:
    core_calls: list[object] = []
    strategy.core.on_order_submitted = lambda event: core_calls.append(event)
    strategy.observability = SimpleNamespace(
        record_nautilus_order_event=lambda _event: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked"))
    )

    strategy.on_order_submitted(SimpleNamespace(client_order_id="C-001", tags=[]))

    assert len(core_calls) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_nautilus_strategy_base.py::test_order_submitted_observability_failure_does_not_block_core_event -v`

Expected: FAIL because `_record_nautilus_order` currently lets observability exceptions propagate.

- [ ] **Step 3: Write minimal implementation**

Guard only observability side effects in `native_strategy.py`:

```python
def _record_nautilus_order(self, event: object, metrics: Mapping[str, object]) -> None:
    if self.observability is None:
        return
    try:
        self.observability.record_nautilus_order_event(_projection_order_event(event, metrics))
    except (OSError, sqlite3.Error):
        self._note_runtime_progress("telemetry_side_effect_failed")
```

Apply the same pattern to `_record_nautilus_fill`, `_record_nautilus_position`, `_record_decision`, `_record_rejected`, and `_record_signal` only for persistence/telemetry exceptions. Do not catch exceptions from `_call_core`, `core.evaluate`, or `_submit_approved` beyond existing classified `ValueError` mapping failures.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_nautilus_strategy_base.py::test_order_submitted_observability_failure_does_not_block_core_event -v`

Expected: PASS.

- [ ] **Step 5: Acceptance command**

Run: `pytest tests/test_nautilus_strategy_base.py -k "order_submitted or observability or telemetry" -v`

Expected: PASS.

### Task 14: Verify Malformed Project-Owned Data Followed By Valid Data Still Updates State

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py` only if prior classification missed this path
- Test: `tests/test_nautilus_market_rotation.py` or `tests/test_nautilus_strategy_base.py`

- [ ] **Step 1: Write the failing test**

Add a regression test that sends malformed custom data then valid market metadata:

```python
def test_malformed_project_owned_data_does_not_poison_later_valid_market_metadata(strategy) -> None:
    strategy.on_data(object())

    strategy.on_data(PolySignalMarketMetaData(
        market_id="market-1",
        market_slug="btc-updown-5m-market-1",
        condition_id="condition-1",
        asset="BTC",
        timeframe="5m",
        start_ts_ns=1,
        end_ts_ns=2,
        up_token_id="up-1",
        down_token_id="down-1",
        ts_event=11,
        ts_init=12,
    ))

    assert strategy.registry.by_condition("condition-1") is not None
```

- [ ] **Step 2: Run test to verify it fails if classification is incomplete**

Run: `pytest tests/test_nautilus_strategy_base.py::test_malformed_project_owned_data_does_not_poison_later_valid_market_metadata -v`

Expected: FAIL before project-owned malformed data is isolated, or PASS if Task 8 already covered the path.

- [ ] **Step 3: Write minimal implementation if needed**

Ensure `on_data` returns immediately for `DROPPED_FRAME` and does not mutate `_market_epoch`, `_active_condition_ids`, registry, sidecar, or assembler.

```python
if classify_project_owned_data(data) is DataBoundaryClassification.DROPPED_FRAME:
    self._note_runtime_progress("dropped_frame")
    return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_nautilus_strategy_base.py::test_malformed_project_owned_data_does_not_poison_later_valid_market_metadata -v`

Expected: PASS.

- [ ] **Step 5: Acceptance command**

Run: `pytest tests/test_nautilus_strategy_base.py tests/test_nautilus_market_rotation.py -k "malformed or metadata or dropped" -v`

Expected: PASS.

### Task 15: Verify Runtime Wiring Starts And Stops Telemetry Writer

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/node.py`
- Modify: `src/polysignal_lab/nautilus_runtime/observability.py`
- Test: `tests/test_nautilus_trading_node_runtime.py`

- [ ] **Step 1: Write the failing test**

Add a runtime test with a fake observability actor exposing `start` and `stop`:

```python
async def test_run_nautilus_cli_async_starts_and_stops_observability_writer(monkeypatch) -> None:
    calls: list[str] = []

    class FakeObservability:
        def start(self) -> None:
            calls.append("start")

        def stop(self) -> None:
            calls.append("stop")

        async def notify_startup(self, strategy_names=(), **kwargs):
            calls.append("startup")

        async def notify_shutdown(self):
            calls.append("shutdown")

    class FakeTradingNode:
        def run(self):
            return None

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    async def fake_build(settings=None):
        _ = settings
        return SimpleNamespace(
            node=FakeTradingNode(),
            websocket_tasks=[],
            scheduler=SimpleNamespace(
                stop=_noop,
                settings=_runtime_settings_stub(
                    markets=SimpleNamespace(refresh_interval_sec=60),
                    runtime=SimpleNamespace(nautilus=SimpleNamespace(paper_engine="nautilus_matching", matching_accuracy_mode="depth_l2")),
                ),
            ),
            observability=FakeObservability(),
            components={"strategies": []},
        )

    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node.build_nautilus_runtime", fake_build)
    monkeypatch.setattr("asyncio.to_thread", lambda fn, *args: fn(*args))

    await run_nautilus_cli_async()

    assert calls[0] == "start"
    assert "stop" in calls
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_nautilus_trading_node_runtime.py::test_run_nautilus_cli_async_starts_and_stops_observability_writer -v`

Expected: FAIL because the runtime does not call observability start/stop.

- [ ] **Step 3: Write minimal implementation**

In both async and sync runtime wrappers, call optional `start` after bundle creation and optional `stop` in `finally`:

```python
starter = getattr(bundle.observability, "start", None)
if callable(starter):
    starter()
...
stopper = getattr(bundle.observability, "stop", None)
if callable(stopper):
    stopper()
```

Place `stop()` before scheduler stop so queued telemetry has a chance to drain while persistence is still open.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_nautilus_trading_node_runtime.py::test_run_nautilus_cli_async_starts_and_stops_observability_writer -v`

Expected: PASS.

- [ ] **Step 5: Acceptance command**

Run: `pytest tests/test_nautilus_trading_node_runtime.py -k "observability or run_nautilus_cli_async" -v`

Expected: PASS.

### Task 16: Final Targeted Regression Suite

**Files:**
- Test only: `tests/test_nautilus_observability.py`
- Test only: `tests/test_nautilus_strategy_base.py`
- Test only: `tests/test_nautilus_trading_node_runtime.py`
- Test only: `tests/test_nautilus_node.py`
- Test only: `tests/test_nautilus_market_rotation.py`
- Test only: `tests/test_storage_restore.py`

- [ ] **Step 1: Run observability and persistence regressions**

Run: `pytest tests/test_nautilus_observability.py tests/test_storage_restore.py -v`

Expected: PASS.

- [ ] **Step 2: Run native strategy boundary regressions**

Run: `pytest tests/test_nautilus_strategy_base.py -v`

Expected: PASS.

- [ ] **Step 3: Run runtime node regressions**

Run: `pytest tests/test_nautilus_trading_node_runtime.py tests/test_nautilus_node.py -v`

Expected: PASS.

- [ ] **Step 4: Run market-rotation regressions**

Run: `pytest tests/test_nautilus_market_rotation.py -v`

Expected: PASS.

- [ ] **Step 5: Run acceptance-focused combined command**

Run: `pytest tests/test_nautilus_observability.py tests/test_nautilus_strategy_base.py tests/test_nautilus_trading_node_runtime.py tests/test_nautilus_node.py tests/test_nautilus_market_rotation.py tests/test_storage_restore.py -v`

Expected: PASS. This command is the minimum local acceptance suite for the spec.

---

## Acceptance Criteria Coverage

- Malformed or unsupported project-owned callback/object data does not propagate into Nautilus queue processing: covered by Tasks 8, 9, 13, and 14.
- Telemetry SQLite lock, JSONL `OSError`, or notifier exception returns without propagation and reports health: covered by Tasks 3, 4, 5, 6, and 13.
- Critical paper state persistence failure is durable/degraded/fatal and never silently dropped: covered by Tasks 1 and 2; future durable retry/degraded escalation must keep these tests green.
- Invalid cancel attempts are blocked before the matching engine after producer identification: covered by Task 12 with a targeted gate only if a project-owned producer exists.
- Missing required readiness data skips evaluation or order submission instead of fatal account-state paths: covered by Tasks 10 and 11.
- SQLite connections verify WAL mode and `busy_timeout=30000`: covered by Task 7.
- Health metrics distinguish dropped data, recoverable parser errors, telemetry queue drops, writer backlog, SQLite lock retries, degraded persistence, and fatal runtime errors: covered by Tasks 3, 5, 6, 8, 9, 10, and 13.
- Tests cover each failure class without relying on fragile log text matching: covered by all task-specific assertions and Task 16.

## Known Blockers And Investigation Notes

- The initial workspace has uncommitted changes in `src/polysignal_lab/nautilus_runtime/observability.py`, `tests/test_nautilus_observability.py`, and an untracked revised spec. Implementers must inspect current diffs before editing and must not revert unrelated user changes.
- The current branch may be `main`; verify with `git status --short --branch` before implementation. If on `main`, use the parent agent's chosen isolation strategy before SDD execution.
- A quick repository search found no project-owned Nautilus runtime call to `cancel_order` or `cancel_all`; `cancel` matches are mostly task/timer cancellation, alpha-core notification methods, and legacy paper executor paths. Task 12 keeps the cancel gate as an investigation-gated step rather than speculative production code.
- Raw Polymarket WebSocket text such as `INVALID OPERATION` appears adapter-owned unless a controllable parser path is found in this repo; this plan guards project-owned object boundaries and does not promise an upstream parser fix.

## Recommended First SDD Task

Start with Task 1, `Define Persistence Classes Without Changing Runtime Behavior`. It is the smallest low-risk step, establishes the invariant that later queueing must respect, and reduces restart risk before any asynchronous writer or callback guard is added.
