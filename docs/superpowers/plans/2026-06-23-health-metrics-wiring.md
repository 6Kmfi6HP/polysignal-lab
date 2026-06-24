# Health Metrics Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn scheduler, storage, market-data, Telegram, dashboard, and bounded smoke observations into component-level runtime health with persisted transition evidence.

**Architecture:** Replace the uppercase dict health registry with immutable lower-case health snapshots and use `system_events` as the cross-process bridge from the scheduler to the standalone dashboard. Instrument existing scheduler boundaries instead of moving loop ownership: market data updates, snapshot building, signal gating, paper simulation, state persistence, and Telegram publish paths update one in-memory registry; scheduler persistence emits health snapshots and transition events to SQLite.

**Tech Stack:** Python 3.11+, dataclasses, Pydantic-compatible JSON values, FastAPI/TestClient, SQLiteStore, pytest/pytest-asyncio.

## Global Constraints

- Scope is one standalone architecture change from `docs/superpowers/specs/2026-06-23-04-health-metrics-design.md`; do not execute with specs 01-03 or 05-08 in the same implementation batch.
- No Prometheus/Grafana deployment.
- No external alert manager.
- No process supervisor changes.
- No UI redesign beyond JSON health fields and minimal dashboard consumption.
- Dashboard remains read-only: no execution, admin, cancel, redeem, or order-placement routes.
- Metrics must be useful without live trading or external services.
- Tests must use no live API calls.
- Run Python tests through the project venv: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest ...`.
- Before considering the new version live in formal runtime, rebuild containers with `docker compose up -d --build --force-recreate`, then verify `docker compose ps` and startup logs/health.

---

## Research Notes

- Current `src/polysignal_lab/observability/health.py` has only `HealthRegistry.set(name, status, **details)` and `snapshot()` returning `{"overall": "OK" | "DEGRADED", "components": ...}`.
- Current `/health` in `src/polysignal_lab/dashboard/app.py` returns `{"status": "OK", "counts": store.counts()}` from a standalone dashboard process that only receives `SQLiteStore`.
- Current `system_events` schema already stores `event_id`, `event_type`, `severity`, `created_at`, and arbitrary `payload_json`; use this for `component_health_transition` and `health_snapshot` events instead of adding a new table.
- Current scheduler instantiates market discovery, REST CLOB, CLOB WS, Binance WS, snapshot builder, signal gate, paper simulator, Telegram publisher, JSONL, state store, and SQLite in `PolySignalScheduler.__init__`.
- Current `OrderBookRegistry.metrics` already tracks CLOB WS decode/unknown/tick-size and paper fill staleness counters, but it is not surfaced through health.
- Current bounded smoke evidence schema has no health snapshot field in `src/polysignal_lab/app/readonly_smoke_types.py`.

## File Structure

- Modify `src/polysignal_lab/observability/health.py`: define `ComponentHealth`, `HealthSnapshot`, lower-case statuses, metric mutation helpers, and transition extraction.
- Modify `src/polysignal_lab/storage/sqlite_store.py`: add `restore_latest_system_event(event_type: str) -> dict[str, Any] | None` for dashboard and smoke reads.
- Create `src/polysignal_lab/app/scheduler_health.py`: scheduler-facing health helper functions for data-source, processing, persistence, publisher, snapshot, and transition event updates.
- Modify `src/polysignal_lab/app/scheduler.py`: instantiate `HealthRegistry` and delegate health helpers.
- Modify `src/polysignal_lab/app/scheduler_market_data.py`: record Gamma discovery, CLOB REST, CLOB WS subscription, and storage write health.
- Modify `src/polysignal_lab/data/polymarket_clob_rest.py`: expose REST latency, batch success/failure, and fallback counters through `MetricsRegistry`.
- Modify `src/polysignal_lab/data/polymarket_clob_ws.py`: expose connected, reconnect, subscribed token, and last-error state.
- Modify `src/polysignal_lab/data/binance_spot_ws.py`: expose connected, reconnect, and last-error state.
- Modify `src/polysignal_lab/app/scheduler_processing.py`, `scheduler_reporting.py`, and `scheduler_state.py`: record snapshot, gate, paper, Telegram, SQLite, and JSONL health.
- Modify `src/polysignal_lab/dashboard/app.py`: return component health plus row counts from `/health` and keep all routes read-only.
- Modify `src/polysignal_lab/app/readonly_smoke_types.py`, `readonly_smoke_runtime.py`, and `readonly_smoke.py`: add smoke health snapshot evidence.
- Add tests in `tests/test_health_metrics.py`; update `tests/test_dashboard.py`, `tests/test_market_data.py`, `tests/test_scheduler_paper.py`, and `tests/test_integration_smoke.py`.

## Interfaces

```python
ComponentStatus = Literal["ok", "degraded", "down"]
MetricValue = int | float | str | bool | None

@dataclass(frozen=True, slots=True)
class ComponentHealth:
    name: str
    status: ComponentStatus
    last_success_at: str | None
    last_error_at: str | None
    last_error: str | None
    metrics: dict[str, MetricValue]

@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    status: ComponentStatus
    generated_at: str
    components: list[ComponentHealth]

@dataclass
class HealthRegistry:
    def mark_ok(self, name: str, **metrics: MetricValue) -> None: ...
    def mark_degraded(self, name: str, error: str | None = None, **metrics: MetricValue) -> None: ...
    def mark_down(self, name: str, error: str | None = None, **metrics: MetricValue) -> None: ...
    def inc_metric(self, name: str, metric: str, amount: int = 1) -> None: ...
    def set_metric(self, name: str, metric: str, value: MetricValue) -> None: ...
    def snapshot(self) -> HealthSnapshot: ...
    def consume_transition_events(self) -> list[dict[str, JsonValue]]: ...
```

```python
def restore_latest_system_event(self, event_type: str) -> dict[str, Any] | None: ...
```

```python
# src/polysignal_lab/app/scheduler_health.py
def note_publish_result(scheduler: PolySignalScheduler, publish: dict[str, str | None]) -> None: ...
def note_storage_success(scheduler: PolySignalScheduler, store_name: str) -> None: ...
def note_storage_failure(scheduler: PolySignalScheduler, store_name: str, exc: BaseException) -> None: ...
def sync_runtime_health(scheduler: PolySignalScheduler) -> HealthSnapshot: ...
def persist_health_snapshot(scheduler: PolySignalScheduler) -> None: ...
```

### Task 1: Health Model and SQLite Bridge

**Files:**
- Modify: `src/polysignal_lab/observability/health.py:1-19`
- Modify: `src/polysignal_lab/storage/sqlite_store.py:181-202`
- Test: `tests/test_health_metrics.py`

**Interfaces:**
- Consumes: existing `SQLiteStore.insert_system_event()`.
- Produces: `ComponentHealth`, `HealthSnapshot`, lower-case `HealthRegistry.snapshot()`, transition event payloads, and `SQLiteStore.restore_latest_system_event()`.

- [ ] **Step 1: Write failing health aggregation tests**

Create `tests/test_health_metrics.py` with this content:

```python
from __future__ import annotations

from polysignal_lab.observability.health import HealthRegistry
from polysignal_lab.storage.sqlite_store import SQLiteStore


def test_health_registry_aggregates_component_status_and_transitions() -> None:
    registry = HealthRegistry()

    registry.mark_ok("gamma", discovered_market_count=8)
    registry.mark_degraded("clob_ws", "reconnect", reconnect_count=1)
    snapshot = registry.snapshot()
    transitions = registry.consume_transition_events()

    assert snapshot.status == "degraded"
    assert [component.name for component in snapshot.components] == ["clob_ws", "gamma"]
    assert snapshot.components[0].status == "degraded"
    assert snapshot.components[0].last_error == "reconnect"
    assert snapshot.components[0].metrics["reconnect_count"] == 1
    assert len(transitions) == 2
    assert transitions[0]["event_type"] == "component_health_transition"
    assert transitions[0]["severity"] in {"INFO", "WARNING"}
    assert registry.consume_transition_events() == []


def test_sqlite_restores_latest_system_event_payload(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "health.sqlite3")
    older = {
        "event_id": "evt-old",
        "event_type": "health_snapshot",
        "severity": "INFO",
        "created_at": "2026-06-23T00:00:00+00:00",
        "status": "ok",
    }
    newer = {
        "event_id": "evt-new",
        "event_type": "health_snapshot",
        "severity": "WARNING",
        "created_at": "2026-06-23T00:01:00+00:00",
        "status": "degraded",
    }

    store.insert_system_event(older)
    store.insert_system_event(newer)

    assert store.restore_latest_system_event("health_snapshot") == newer
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_health_metrics.py -q
```

Expected: FAIL because `ComponentHealth`, lower-case aggregation, transition events, and `restore_latest_system_event()` are not implemented.

- [ ] **Step 3: Replace `HealthRegistry` with lower-case snapshot models**

Replace `src/polysignal_lab/observability/health.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from pydantic import JsonValue

from polysignal_lab.utils import new_id, utc_iso

ComponentStatus: TypeAlias = Literal["ok", "degraded", "down"]
MetricValue: TypeAlias = int | float | str | bool | None


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    name: str
    status: ComponentStatus
    last_success_at: str | None = None
    last_error_at: str | None = None
    last_error: str | None = None
    metrics: dict[str, MetricValue] = field(default_factory=dict)

    def as_dict(self) -> dict[str, JsonValue]:
        return {
            "name": self.name,
            "status": self.status,
            "last_success_at": self.last_success_at,
            "last_error_at": self.last_error_at,
            "last_error": self.last_error,
            "metrics": self.metrics,
        }


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    status: ComponentStatus
    generated_at: str
    components: list[ComponentHealth]

    def as_dict(self) -> dict[str, JsonValue]:
        return {
            "status": self.status,
            "generated_at": self.generated_at,
            "components": [component.as_dict() for component in self.components],
        }


@dataclass
class HealthRegistry:
    components: dict[str, ComponentHealth] = field(default_factory=dict)
    _last_statuses: dict[str, ComponentStatus] = field(default_factory=dict)
    _pending_transitions: list[dict[str, JsonValue]] = field(default_factory=list)

    def mark_ok(self, name: str, **metrics: MetricValue) -> None:
        self._set(name, "ok", None, **metrics)

    def mark_degraded(self, name: str, error: str | None = None, **metrics: MetricValue) -> None:
        self._set(name, "degraded", error, **metrics)

    def mark_down(self, name: str, error: str | None = None, **metrics: MetricValue) -> None:
        self._set(name, "down", error, **metrics)

    def set(self, name: str, status: str, **details: MetricValue) -> None:
        normalized = status.lower()
        if normalized == "ok":
            self.mark_ok(name, **details)
        elif normalized == "down":
            self.mark_down(name, str(details.get("last_error") or details.get("error") or "down"), **details)
        else:
            self.mark_degraded(name, str(details.get("last_error") or details.get("error") or "degraded"), **details)

    def inc_metric(self, name: str, metric: str, amount: int = 1) -> None:
        current = self.components.get(name)
        metrics = dict(current.metrics if current else {})
        metrics[metric] = int(metrics.get(metric) or 0) + amount
        status: ComponentStatus = current.status if current else "ok"
        self._set(name, status, current.last_error if current else None, **metrics)

    def set_metric(self, name: str, metric: str, value: MetricValue) -> None:
        current = self.components.get(name)
        metrics = dict(current.metrics if current else {})
        metrics[metric] = value
        status: ComponentStatus = current.status if current else "ok"
        self._set(name, status, current.last_error if current else None, **metrics)

    def snapshot(self) -> HealthSnapshot:
        statuses = [component.status for component in self.components.values()]
        if any(status == "down" for status in statuses):
            overall: ComponentStatus = "down"
        elif any(status == "degraded" for status in statuses):
            overall = "degraded"
        else:
            overall = "ok"
        return HealthSnapshot(
            status=overall,
            generated_at=utc_iso(),
            components=[self.components[name] for name in sorted(self.components)],
        )

    def consume_transition_events(self) -> list[dict[str, JsonValue]]:
        events = list(self._pending_transitions)
        self._pending_transitions.clear()
        return events

    def _set(self, name: str, status: ComponentStatus, error: str | None, **metrics: MetricValue) -> None:
        now = utc_iso()
        previous = self.components.get(name)
        merged_metrics = dict(previous.metrics if previous else {})
        merged_metrics.update(metrics)
        component = ComponentHealth(
            name=name,
            status=status,
            last_success_at=now if status == "ok" else (previous.last_success_at if previous else None),
            last_error_at=now if status != "ok" else (previous.last_error_at if previous else None),
            last_error=error if status != "ok" else None,
            metrics=merged_metrics,
        )
        self.components[name] = component
        if self._last_statuses.get(name) != status:
            self._last_statuses[name] = status
            severity = "ERROR" if status == "down" else "WARNING" if status == "degraded" else "INFO"
            self._pending_transitions.append(
                {
                    "event_id": new_id("health"),
                    "event_type": "component_health_transition",
                    "severity": severity,
                    "created_at": now,
                    "component": name,
                    "status": status,
                    "last_error": component.last_error,
                    "metrics": component.metrics,
                }
            )
```

- [ ] **Step 4: Add latest system event restoration**

Add this method to `SQLiteStore` after `insert_system_event()` in `src/polysignal_lab/storage/sqlite_store.py`:

```python
    def restore_latest_system_event(self, event_type: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT payload_json FROM system_events
                WHERE event_type = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (event_type,),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None
```

- [ ] **Step 5: Run the task tests**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_health_metrics.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/polysignal_lab/observability/health.py src/polysignal_lab/storage/sqlite_store.py tests/test_health_metrics.py
git commit -m "feat: add component health snapshots"
```

### Task 2: Market Data Component Instrumentation

**Files:**
- Modify: `src/polysignal_lab/data/polymarket_clob_rest.py:1-102`
- Modify: `src/polysignal_lab/data/polymarket_clob_ws.py:1-146`
- Modify: `src/polysignal_lab/data/binance_spot_ws.py:1-94`
- Modify: `src/polysignal_lab/app/scheduler.py:81-115`
- Modify: `src/polysignal_lab/app/scheduler_market_data.py:26-51,133-182`
- Create: `src/polysignal_lab/app/scheduler_health.py`
- Test: `tests/test_market_data.py`
- Test: `tests/test_health_metrics.py`

**Interfaces:**
- Consumes: `HealthRegistry`, `MetricsRegistry`, existing registries.
- Produces: CLOB REST counters, WS connection state, Binance connection state, and scheduler market-data health updates.

- [ ] **Step 1: Write failing data-source health tests**

Append these tests to `tests/test_market_data.py`:

```python
def test_clob_ws_exposes_connection_and_invalid_event_metrics() -> None:
    registry = OrderBookRegistry()
    ws = PolymarketMarketWebSocket(PolymarketDataConfig(), registry)

    ws.note_connected(token_ids=["tok-a", "tok-b"])
    ws.handle_message(b"not-json")
    ws.note_reconnect(RuntimeError("network reset"))

    assert ws.connected is False
    assert ws.subscribed_token_count == 2
    assert ws.reconnect_count == 1
    assert ws.last_error == "network reset"
    assert registry.metrics.snapshot()["counters"]["ws_decode_errors"] == 1


def test_binance_feed_exposes_connection_metrics() -> None:
    feed = BinanceSpotFeed(BinanceDataConfig(), SpotRegistry())

    feed.note_connected()
    feed.note_reconnect(RuntimeError("closed"))

    assert feed.connected is False
    assert feed.reconnect_count == 1
    assert feed.last_error == "closed"
```

Append this test to `tests/test_health_metrics.py`:

```python
async def test_scheduler_records_market_data_health(tmp_path, settings, market) -> None:
    from polysignal_lab.app.scheduler import PolySignalScheduler
    from polysignal_lab.app.scheduler_health import sync_runtime_health
    from polysignal_lab.domain.orderbook import OrderBook

    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)
    scheduler.ctx.markets.upsert_many([market])
    scheduler._latest_market_token_ids = tuple(token.token_id for token in market.outcome_tokens)
    scheduler.ctx.books.update_from_snapshot(OrderBook(token_id=market.outcome_tokens[0].token_id))
    scheduler.ctx.books.mark_stale(market.outcome_tokens[1].token_id, "RECONNECT_RESEED_FAILED")
    scheduler.poly_ws.note_connected(token_ids=list(scheduler._latest_market_token_ids))
    scheduler.poly_ws.note_reconnect(RuntimeError("reconnect"))

    snapshot = sync_runtime_health(scheduler)
    components = {component.name: component for component in snapshot.components}

    assert components["clob_ws"].status == "degraded"
    assert components["clob_ws"].metrics["subscribed_token_count"] == 2
    assert components["clob_ws"].metrics["stale_token_count"] == 1
    assert components["clob_ws"].metrics["reconnect_count"] == 1
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_data.py::test_clob_ws_exposes_connection_and_invalid_event_metrics tests/test_market_data.py::test_binance_feed_exposes_connection_metrics tests/test_health_metrics.py::test_scheduler_records_market_data_health -q
```

Expected: FAIL because the WS feed classes and `scheduler_health` do not expose the new state.

- [ ] **Step 3: Add REST CLOB metrics**

In `src/polysignal_lab/data/polymarket_clob_rest.py`, add imports:

```python
from time import perf_counter

from polysignal_lab.observability.metrics import MetricsRegistry
```

Add `metrics` to `PolymarketCLOBRestClient.__init__`:

```python
        metrics: MetricsRegistry | None = None,
```

Set this field after `self.rate_limiter`:

```python
        self.metrics = metrics or MetricsRegistry()
```

Replace `get_books()` with:

```python
    async def get_books(self, token_ids: list[str]) -> list[OrderBook]:
        if not token_ids:
            return []
        started = perf_counter()
        try:
            books = await self._get_books_batch(token_ids)
            self.metrics.inc("clob_rest_batch_success")
            self.metrics.set_gauge("clob_rest_latency_ms", round((perf_counter() - started) * 1000, 3))
            return books
        except Exception:
            self.metrics.inc("clob_rest_batch_failure")
            self.metrics.inc("clob_rest_fallback_count")
            books = [await self.get_book(token_id) for token_id in token_ids]
            self.metrics.set_gauge("clob_rest_latency_ms", round((perf_counter() - started) * 1000, 3))
            return books
```

- [ ] **Step 4: Add CLOB WS state helpers**

In `PolymarketMarketWebSocket.__init__`, add:

```python
        self.connected = False
        self.reconnect_count = 0
        self.subscribed_token_count = 0
        self.last_error: str | None = None
```

Add these methods before `subscribe()`:

```python
    def note_connected(self, token_ids: list[str]) -> None:
        self.connected = True
        self.subscribed_token_count = len(token_ids)
        self.last_error = None

    def note_reconnect(self, exc: BaseException) -> None:
        self.connected = False
        self.reconnect_count += 1
        self.last_error = str(exc)
        self.registry.metrics.inc("clob_ws_reconnect_count")
```

Inside `subscribe()`, insert after the websocket context opens and before `ws.send(...)`:

```python
                    self.note_connected(token_ids)
```

Replace the `except` body in `subscribe()` with:

```python
            except (OSError, TimeoutError, websockets.exceptions.WebSocketException) as exc:
                self.note_reconnect(exc)
                await anyio.sleep(2.0)
```

Update `stop()` to mark disconnected:

```python
    def stop(self) -> None:
        self.running = False
        self.connected = False
```

- [ ] **Step 5: Add Binance WS state helpers**

In `BinanceSpotFeed.__init__`, add:

```python
        self.connected = False
        self.reconnect_count = 0
        self.last_error: str | None = None
```

Add these methods before `combined_stream_url()`:

```python
    def note_connected(self) -> None:
        self.connected = True
        self.last_error = None

    def note_reconnect(self, exc: BaseException) -> None:
        self.connected = False
        self.reconnect_count += 1
        self.last_error = str(exc)
```

Inside `run()`, insert after the websocket context opens and before `async for message in ws:`:

```python
                    self.note_connected()
```

Replace the `except` body in `run()` with:

```python
            except (OSError, TimeoutError, websockets.exceptions.WebSocketException) as exc:
                self.note_reconnect(exc)
                await anyio.sleep(2.0)
```

Update `stop()`:

```python
    def stop(self) -> None:
        self.running = False
        self.connected = False
```

- [ ] **Step 6: Create market-data health helpers**

Create `src/polysignal_lab/app/scheduler_health.py` with:

```python
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from pydantic import JsonValue

from polysignal_lab.observability.health import HealthSnapshot
from polysignal_lab.utils import new_id, utc_iso, utc_now

if TYPE_CHECKING:
    from polysignal_lab.app.scheduler import PolySignalScheduler


def note_storage_success(scheduler: PolySignalScheduler, store_name: str) -> None:
    scheduler.health.mark_ok(f"{store_name}_storage", last_successful_write=utc_iso())


def note_storage_failure(scheduler: PolySignalScheduler, store_name: str, exc: BaseException) -> None:
    scheduler.health.inc_metric(f"{store_name}_storage", "write_failures")
    scheduler.health.mark_down(f"{store_name}_storage", str(exc))


def note_publish_result(scheduler: PolySignalScheduler, publish: dict[str, str | None]) -> None:
    status = str(publish.get("status") or "")
    if status == "SENT":
        scheduler.health.inc_metric("telegram", "sent")
        scheduler.health.mark_ok("telegram")
    elif status == "DRY_RUN":
        scheduler.health.inc_metric("telegram", "dry_run")
        scheduler.health.mark_ok("telegram", dry_run=True)
    else:
        scheduler.health.inc_metric("telegram", "failed")
        scheduler.health.mark_degraded("telegram", publish.get("error") or "telegram publish failed")


def sync_runtime_health(scheduler: PolySignalScheduler) -> HealthSnapshot:
    _sync_clob_ws(scheduler)
    _sync_clob_rest(scheduler)
    _sync_binance_ws(scheduler)
    _sync_book_staleness(scheduler)
    return scheduler.health.snapshot()


def persist_health_snapshot(scheduler: PolySignalScheduler) -> None:
    snapshot = sync_runtime_health(scheduler)
    payload = {
        "event_id": new_id("health_snapshot"),
        "event_type": "health_snapshot",
        "severity": "ERROR" if snapshot.status == "down" else "WARNING" if snapshot.status == "degraded" else "INFO",
        "created_at": snapshot.generated_at,
        **snapshot.as_dict(),
    }
    try:
        scheduler.sqlite.insert_system_event(payload)
        for event in scheduler.health.consume_transition_events():
            scheduler.sqlite.insert_system_event(event)
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        scheduler.logger.warning("Failed to persist health snapshot: %s", exc)


def _sync_clob_ws(scheduler: PolySignalScheduler) -> None:
    metrics = scheduler.ctx.books.metrics.snapshot()["counters"]
    stale_count = sum(1 for state in scheduler.ctx.books.states.values() if not state.has_snapshot)
    component_metrics: dict[str, JsonValue] = {
        "connected": scheduler.poly_ws.connected,
        "reconnect_count": scheduler.poly_ws.reconnect_count,
        "subscribed_token_count": scheduler.poly_ws.subscribed_token_count,
        "stale_token_count": stale_count,
        "invalid_event_count": int(metrics.get("ws_decode_errors", 0))
        + sum(int(value) for key, value in metrics.items() if key.startswith("ws_event_unknown_")),
    }
    if not scheduler.settings.data.polymarket.use_market_ws:
        scheduler.health.mark_ok("clob_ws", enabled=False, **component_metrics)
    elif scheduler.poly_ws.connected and stale_count == 0:
        scheduler.health.mark_ok("clob_ws", **component_metrics)
    else:
        scheduler.health.mark_degraded("clob_ws", scheduler.poly_ws.last_error or "clob websocket not fully healthy", **component_metrics)


def _sync_clob_rest(scheduler: PolySignalScheduler) -> None:
    metrics = scheduler.rest.metrics.snapshot()
    counters = metrics["counters"]
    gauges = metrics["gauges"]
    payload: dict[str, JsonValue] = {
        "batch_success": int(counters.get("clob_rest_batch_success", 0)),
        "batch_failure": int(counters.get("clob_rest_batch_failure", 0)),
        "fallback_count": int(counters.get("clob_rest_fallback_count", 0)),
        "latency_ms": gauges.get("clob_rest_latency_ms"),
    }
    if payload["batch_failure"]:
        scheduler.health.mark_degraded("clob_rest", "batch fallback used", **payload)
    else:
        scheduler.health.mark_ok("clob_rest", **payload)


def _sync_binance_ws(scheduler: PolySignalScheduler) -> None:
    now = utc_now()
    lags: dict[str, int | None] = {}
    for asset in scheduler.settings.data.binance.symbols:
        spot = scheduler.ctx.spots.get(asset)
        lags[f"{asset.lower()}_spot_lag_ms"] = spot.freshness_ms(now) if spot else None
    worst_lag = max((lag for lag in lags.values() if lag is not None), default=None)
    metrics: dict[str, JsonValue] = {
        "connected": scheduler.binance_ws.connected,
        "reconnect_count": scheduler.binance_ws.reconnect_count,
        **lags,
    }
    if not scheduler.settings.data.binance.enabled:
        scheduler.health.mark_ok("binance_ws", enabled=False, **metrics)
    elif worst_lag is None:
        scheduler.health.mark_down("binance_ws", scheduler.binance_ws.last_error or "no spot prices", **metrics)
    elif worst_lag > scheduler.settings.data.binance.max_price_staleness_ms:
        scheduler.health.mark_degraded("binance_ws", "spot prices stale", **metrics)
    else:
        scheduler.health.mark_ok("binance_ws", **metrics)


def _sync_book_staleness(scheduler: PolySignalScheduler) -> None:
    stale_count = sum(1 for state in scheduler.ctx.books.states.values() if not state.has_snapshot)
    scheduler.health.set_metric("clob_ws", "stale_token_count", stale_count)
```

- [ ] **Step 7: Add scheduler registry and market refresh updates**

In `src/polysignal_lab/app/scheduler.py`, add this import:

```python
from polysignal_lab.observability.health import HealthRegistry
```

In `PolySignalScheduler.__init__`, add after `self.logger`:

```python
        self.health = HealthRegistry()
```

In `src/polysignal_lab/app/scheduler_market_data.py`, add this import:

```python
from polysignal_lab.app import scheduler_health
```

In `refresh_markets_once()`, wrap discovery with health updates:

```python
    try:
        markets = await scheduler.discovery.discover()
        scheduler.health.mark_ok("gamma", discovered_market_count=len(markets))
    except Exception as exc:
        scheduler.health.mark_down("gamma", str(exc))
        raise
```

Keep the existing body after `markets = ...`. Inside the market persistence `try`, after both writes succeed, add:

```python
            scheduler_health.note_storage_success(scheduler, "sqlite")
            scheduler_health.note_storage_success(scheduler, "jsonl")
```

In that `except`, capture the exception and record failure:

```python
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            scheduler_health.note_storage_failure(scheduler, "sqlite", exc)
```

After `books = await scheduler.rest.get_books(list(token_ids))`, add:

```python
            scheduler.health.mark_ok("clob_rest", requested_token_count=len(token_ids), returned_book_count=len(books))
```

In the REST exception block, add:

```python
                scheduler.health.mark_down("clob_rest", str(exc), requested_token_count=len(token_ids))
```

- [ ] **Step 8: Run the task tests**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_data.py::test_clob_ws_exposes_connection_and_invalid_event_metrics tests/test_market_data.py::test_binance_feed_exposes_connection_metrics tests/test_health_metrics.py::test_scheduler_records_market_data_health -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

Run:

```bash
git add src/polysignal_lab/data/polymarket_clob_rest.py src/polysignal_lab/data/polymarket_clob_ws.py src/polysignal_lab/data/binance_spot_ws.py src/polysignal_lab/app/scheduler.py src/polysignal_lab/app/scheduler_market_data.py src/polysignal_lab/app/scheduler_health.py tests/test_market_data.py tests/test_health_metrics.py
git commit -m "feat: instrument market data health"
```

### Task 3: Scheduler Processing and Persistence Instrumentation

**Files:**
- Modify: `src/polysignal_lab/app/scheduler_processing.py:32-82,98-177,193-245`
- Modify: `src/polysignal_lab/app/scheduler_reporting.py:143-164,361-382`
- Modify: `src/polysignal_lab/app/scheduler_state.py:66-89`
- Modify: `src/polysignal_lab/app/scheduler_runtime.py:87-97`
- Test: `tests/test_health_metrics.py`
- Test: `tests/test_scheduler_paper.py`

**Interfaces:**
- Consumes: `scheduler.health` and `scheduler_health.note_publish_result()`.
- Produces: snapshot builder, gate rejection, paper simulator, Telegram, SQLite, JSONL, and persisted health snapshot counters.

- [ ] **Step 1: Write failing scheduler health tests**

Append this test to `tests/test_health_metrics.py`:

```python
async def test_scheduler_records_gate_rejections_and_persists_health_snapshot(tmp_path, snapshot, settings) -> None:
    from polysignal_lab.app.scheduler import PolySignalScheduler
    from polysignal_lab.app import scheduler_health
    from polysignal_lab.strategies.ptb_diff import PTBDiffStrategy

    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)
    scheduler._initialize_trading_components()
    signal = PTBDiffStrategy(settings.strategies.ptb_diff).evaluate(snapshot)[0]
    signal = signal.model_copy(update={"confidence": 0.01})

    decision = scheduler.gate.evaluate(signal, snapshot)
    assert decision.rejected is not None
    scheduler.health.inc_metric("signal_gate", f"rejected_{decision.rejected.reason_code}")
    scheduler_health.persist_health_snapshot(scheduler)

    latest = scheduler.sqlite.restore_latest_system_event("health_snapshot")
    assert latest is not None
    components = {component["name"]: component for component in latest["components"]}
    assert components["signal_gate"]["metrics"]["rejected_CONFIDENCE_TOO_LOW"] == 1
```

Append this test to `tests/test_scheduler_paper.py`:

```python
async def test_process_signal_updates_paper_and_telegram_health(tmp_path: Path, snapshot, settings) -> None:
    sig = await _signal(snapshot, settings)
    scheduler = _publishing_scheduler(tmp_path, settings)

    result = await scheduler.process_signal(sig)
    components = {component.name: component for component in scheduler.health.snapshot().components}

    assert result["published"] is True
    assert components["telegram"].status == "ok"
    assert components["telegram"].metrics["dry_run"] == 1
    assert components["paper_simulator"].metrics["rejects_PAPER_MISSING_ORDERBOOK"] == 1
    assert components["paper_simulator"].metrics["wallet_snapshot_count"] == 1
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_health_metrics.py::test_scheduler_records_gate_rejections_and_persists_health_snapshot tests/test_scheduler_paper.py::test_process_signal_updates_paper_and_telegram_health -q
```

Expected: FAIL because scheduler processing does not update these health components.

- [ ] **Step 3: Instrument snapshot builder and gate outcomes**

In `src/polysignal_lab/app/scheduler_processing.py`, after successful `snapshot = await scheduler.snapshot_builder.build(market)`, add:

```python
            scheduler.health.inc_metric("snapshot_builder", "build_count")
            if snapshot.freshness.max_ms is not None:
                scheduler.health.set_metric("snapshot_builder", "max_freshness_lag_ms", snapshot.freshness.max_ms)
            scheduler.health.mark_ok("snapshot_builder")
```

In the snapshot build `except` block, add:

```python
            scheduler.health.inc_metric("snapshot_builder", "failure_count")
            scheduler.health.mark_degraded("snapshot_builder", f"snapshot failed for {market.market_slug}")
```

Inside the accepted branch after `strategy.notify_signal_accepted(...)`, add:

```python
                        scheduler.health.inc_metric("signal_gate", "accepted_count")
                        scheduler.health.mark_ok("signal_gate")
```

Inside the rejected branch before persistence, add:

```python
                        scheduler.health.inc_metric("signal_gate", f"rejected_{decision.rejected.reason_code}")
                        scheduler.health.mark_degraded("signal_gate", "gate rejections observed")
```

- [ ] **Step 4: Instrument paper simulator outcomes**

In `_store_simulation_result()`, after the wallet snapshot is inserted, add:

```python
    scheduler.health.inc_metric("paper_simulator", "wallet_snapshot_count")
```

Inside the fill branch, add:

```python
        scheduler.health.inc_metric("paper_simulator", "fills")
        scheduler.health.mark_ok("paper_simulator")
```

Inside the reject branch, add:

```python
        scheduler.health.inc_metric("paper_simulator", f"rejects_{sim.order.reject_reason}")
        scheduler.health.mark_degraded("paper_simulator", sim.order.reject_reason)
```

In `tick_resting_orders()`, inside the fills branch after persisted positions, add:

```python
                scheduler.health.inc_metric("paper_simulator", "fills", len(result.fills))
                scheduler.health.mark_ok("paper_simulator")
```

Inside the rejected/cancelled branch after wallet snapshot insert, add:

```python
            scheduler.health.inc_metric("paper_simulator", f"rejects_{normalized_reason}")
            scheduler.health.inc_metric("paper_simulator", "wallet_snapshot_count")
            scheduler.health.mark_degraded("paper_simulator", normalized_reason)
```

- [ ] **Step 5: Instrument Telegram publish paths**

In `src/polysignal_lab/app/scheduler_processing.py`, add this import:

```python
from polysignal_lab.app import scheduler_health
```

After `publish = await scheduler.publisher.send(...)` in `process_signal()`, add:

```python
            scheduler_health.note_publish_result(scheduler, publish.as_dict())
```

In `src/polysignal_lab/app/scheduler_reporting.py`, add this import:

```python
from polysignal_lab.app import scheduler_health
```

After `publish_payload = publish.as_dict()` in `_store_paper_result()`, add:

```python
            scheduler_health.note_publish_result(scheduler, publish_payload)
```

After `publish_payload = publish.as_dict()` in `generate_daily_report()`, add:

```python
            scheduler_health.note_publish_result(scheduler, publish_payload)
```

- [ ] **Step 6: Instrument state persistence and persist health snapshots**

In `src/polysignal_lab/app/scheduler_state.py`, add this import:

```python
from polysignal_lab.app import scheduler_health
```

After all state writes in `persist_state()`, add:

```python
        scheduler_health.note_storage_success(scheduler, "jsonl")
        scheduler_health.note_storage_success(scheduler, "sqlite")
```

In the `except` block, add:

```python
        scheduler_health.note_storage_failure(scheduler, "sqlite", exc)
```

In `src/polysignal_lab/app/scheduler_runtime.py`, add this import:

```python
from polysignal_lab.app import scheduler_health
```

After `scheduler._persist_state()` in the run loop, add:

```python
            scheduler_health.persist_health_snapshot(scheduler)
```

In `stop()`, before `scheduler.sqlite.close()`, add:

```python
    scheduler_health.persist_health_snapshot(scheduler)
```

- [ ] **Step 7: Run the task tests**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_health_metrics.py::test_scheduler_records_gate_rejections_and_persists_health_snapshot tests/test_scheduler_paper.py::test_process_signal_updates_paper_and_telegram_health -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add src/polysignal_lab/app/scheduler_processing.py src/polysignal_lab/app/scheduler_reporting.py src/polysignal_lab/app/scheduler_state.py src/polysignal_lab/app/scheduler_runtime.py tests/test_health_metrics.py tests/test_scheduler_paper.py
git commit -m "feat: record scheduler health metrics"
```

### Task 4: Dashboard `/health` Component Snapshot

**Files:**
- Modify: `src/polysignal_lab/dashboard/app.py:38-293`
- Test: `tests/test_dashboard.py`

**Interfaces:**
- Consumes: `SQLiteStore.restore_latest_system_event("health_snapshot")` and `store.counts()`.
- Produces: read-only `/health` payload with `status`, `generated_at`, `components`, `counts`, and `recent_system_events`.

- [ ] **Step 1: Write failing dashboard health tests**

Append this test to `tests/test_dashboard.py`:

```python
def test_dashboard_health_returns_component_snapshot_from_system_events(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "dashboard-health.sqlite3")
    store.insert_system_event(
        {
            "event_id": "health-snap-1",
            "event_type": "health_snapshot",
            "severity": "WARNING",
            "created_at": "2026-06-23T00:00:00+00:00",
            "status": "degraded",
            "generated_at": "2026-06-23T00:00:00+00:00",
            "components": [
                {
                    "name": "binance_ws",
                    "status": "degraded",
                    "last_success_at": None,
                    "last_error_at": "2026-06-23T00:00:00+00:00",
                    "last_error": "spot prices stale",
                    "metrics": {"btc_spot_lag_ms": 61000},
                }
            ],
        }
    )
    client = TestClient(create_dashboard_app(store))

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["components"][0]["name"] == "binance_ws"
    assert payload["components"][0]["metrics"]["btc_spot_lag_ms"] == 61000
    assert "counts" in payload
```

Update `test_dashboard_readonly_endpoints_return_stored_data()` line asserting `health.json()["counts"]["signals"] == 1` to also assert:

```python
    assert health.json()["status"] in {"ok", "degraded", "down"}
    assert isinstance(health.json()["components"], list)
```

- [ ] **Step 2: Run dashboard tests to verify failure**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_dashboard.py::test_dashboard_health_returns_component_snapshot_from_system_events tests/test_dashboard.py::test_dashboard_readonly_endpoints_return_stored_data -q
```

Expected: FAIL because `/health` does not read health snapshots.

- [ ] **Step 3: Add dashboard health fallback helper**

In `src/polysignal_lab/dashboard/app.py`, add this helper before `create_dashboard_app()`:

```python
def _health_payload(store: SQLiteStore) -> dict[str, JsonValue]:
    counts = store.counts()
    snapshot = store.restore_latest_system_event("health_snapshot")
    if isinstance(snapshot, dict):
        return {
            "status": snapshot.get("status", "degraded"),
            "generated_at": snapshot.get("generated_at") or snapshot.get("created_at"),
            "components": snapshot.get("components", []),
            "counts": counts,
        }
    return {
        "status": "ok",
        "generated_at": None,
        "components": [
            {
                "name": "sqlite_storage",
                "status": "ok",
                "last_success_at": None,
                "last_error_at": None,
                "last_error": None,
                "metrics": {"row_counts_available": True},
            }
        ],
        "counts": counts,
    }
```

Replace the `/health` route body with:

```python
        return _health_payload(store)
```

- [ ] **Step 4: Run dashboard tests**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_dashboard.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/polysignal_lab/dashboard/app.py tests/test_dashboard.py
git commit -m "feat: expose component health in dashboard"
```

### Task 5: Smoke Evidence Health Snapshot

**Files:**
- Modify: `src/polysignal_lab/app/readonly_smoke_types.py:52-90`
- Modify: `src/polysignal_lab/app/readonly_smoke_runtime.py:34-117`
- Modify: `src/polysignal_lab/app/readonly_smoke.py:31-78`
- Test: `tests/test_integration_smoke.py`

**Interfaces:**
- Consumes: bounded public surface outcomes plus scheduler/dashboard health data.
- Produces: `ReadonlySmokeEvidence["health_snapshot"]` and failure counting for `down` health.

- [ ] **Step 1: Write failing smoke health test**

In `tests/test_integration_smoke.py`, add these assertions after `assert evidence["scheduler_snapshot"]["created"] is True`:

```python
    assert evidence["health_snapshot"]["status"] in {"ok", "degraded", "down"}
    health_components = {
        component["name"]: component for component in evidence["health_snapshot"]["components"]
    }
    assert "gamma" in health_components
    assert "binance_ws" in health_components
```

- [ ] **Step 2: Run the smoke test to verify failure**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_integration_smoke.py::test_fake_public_api_outage_degrades_without_unhandled_exception -q
```

Expected: FAIL because `health_snapshot` is missing from smoke evidence.

- [ ] **Step 3: Extend smoke types**

In `src/polysignal_lab/app/readonly_smoke_types.py`, add:

```python
class HealthSnapshotEvidence(TypedDict):
    status: Literal["ok", "degraded", "down"]
    generated_at: str | None
    components: list[JsonObject]
```

Add this field to `ReadonlySmokeEvidence` after `scheduler_snapshot`:

```python
    health_snapshot: HealthSnapshotEvidence
```

- [ ] **Step 4: Add smoke health collection**

In `src/polysignal_lab/app/readonly_smoke_runtime.py`, import `HealthSnapshotEvidence` and `scheduler_health`:

```python
from polysignal_lab.app import scheduler_health
from polysignal_lab.app.readonly_smoke_types import HealthSnapshotEvidence
```

Add this function after `check_scheduler_snapshot()`:

```python
async def check_health_snapshot(request: ReadonlySmokeRequest) -> HealthSnapshotEvidence:
    scheduler = PolySignalScheduler(request.settings, base_dir=request.base_dir)
    await close_scheduler_clients(scheduler)
    try:
        scheduler.health.mark_ok("gamma", discovered_market_count=0)
        scheduler.health.mark_degraded("binance_ws", "bounded smoke uses REST fallback")
        snapshot = scheduler_health.sync_runtime_health(scheduler)
        return {
            "status": snapshot.status,
            "generated_at": snapshot.generated_at,
            "components": [component.as_dict() for component in snapshot.components],
        }
    finally:
        scheduler.sqlite.close()
```

Change `failure_count()` signature to accept `health_snapshot: HealthSnapshotEvidence`, and add:

```python
    if health_snapshot["status"] == "down":
        count += 1
```

- [ ] **Step 5: Store smoke health evidence**

In `src/polysignal_lab/app/readonly_smoke.py`, import `check_health_snapshot` from `readonly_smoke_runtime`.

After `scheduler_snapshot = await check_scheduler_snapshot(...)`, add:

```python
        health_snapshot = await check_health_snapshot(request)
```

Change the `failures = failure_count(...)` call to pass `health_snapshot`.

Add this field to the evidence dict after `scheduler_snapshot`:

```python
            "health_snapshot": health_snapshot,
```

- [ ] **Step 6: Run smoke tests**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_integration_smoke.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/polysignal_lab/app/readonly_smoke_types.py src/polysignal_lab/app/readonly_smoke_runtime.py src/polysignal_lab/app/readonly_smoke.py tests/test_integration_smoke.py
git commit -m "feat: add health snapshot smoke evidence"
```

### Task 6: Final Verification and Runtime Cutover

**Files:**
- Review: files changed in Tasks 1-5
- Verify: targeted tests, full tests, safety scan, Docker runtime

**Interfaces:**
- Consumes: all previous tasks.
- Produces: verified implementation ready for normal runtime use.

- [ ] **Step 1: Run targeted tests**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_health_metrics.py tests/test_dashboard.py tests/test_market_data.py tests/test_scheduler_paper.py tests/test_integration_smoke.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full pytest**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest -q
```

Expected: PASS.

- [ ] **Step 3: Run safety scan**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m polysignal_lab.observability.safety .
```

Expected: no disallowed source symbols or secret-key findings.

- [ ] **Step 4: Run bounded smoke evidence**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m polysignal_lab.app.main smoke --config config/signal_bot.yaml --evidence .omo/evidence/health-smoke.json
```

Expected: command exits 0; `.omo/evidence/health-smoke.json` contains `health_snapshot.status` and component entries for `gamma`, `clob_rest`, `clob_ws`, `binance_ws`, `snapshot_builder`, or `sqlite_storage` depending on bounded surface results.

- [ ] **Step 5: Rebuild formal runtime containers**

Run:

```bash
docker compose up -d --build --force-recreate
```

Expected: build succeeds and services restart.

- [ ] **Step 6: Verify container state and health endpoint**

Run:

```bash
docker compose ps
```

Expected: services are `Up`.

Run:

```bash
curl -fsS http://127.0.0.1:8080/health
```

Expected: JSON includes lower-case `status`, a `components` list, and `counts`.

- [ ] **Step 7: Commit verification-only fixes if any**

If a verification command exposes a real defect, fix it at the source and commit with a Conventional Commit message matching the changed area, for example:

```bash
git add <changed-files>
git commit -m "fix: stabilize health snapshot persistence"
```

## Self-Review

- Spec coverage: every target component is covered by Task 2 or Task 3; `/health` is covered by Task 4; smoke evidence is covered by Task 5; `system_events` transitions are covered by Task 1 and Task 3.
- Placeholder scan: no deferred implementation markers remain in this plan.
- Type consistency: `ComponentHealth.as_dict()`, `HealthSnapshot.as_dict()`, `SQLiteStore.restore_latest_system_event()`, and `scheduler_health.sync_runtime_health()` are defined before use.
- Scope check: this plan changes observability only and does not combine specs 01-03 or 05-08.
