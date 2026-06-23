# 04 Health and Metrics Wiring Design

**Status:** Draft for review
**Scope:** One standalone architecture change. Do not execute with specs 01-03 or 05-08 in the same implementation batch.
**Goal:** Turn existing logs and isolated observability helpers into actionable runtime health for scheduler, dashboard, smoke evidence, and operations.

## Problem

PolySignal has a dict-based `HealthRegistry` that reports uppercase `OK`/`DEGRADED` values and a `MetricsRegistry`, but the long-running scheduler mostly logs failures and continues. Dashboard `/health` is currently counts-only/basic-state oriented, not component health for Gamma, CLOB WS, Binance WS, Telegram, SQLite, or paper execution. This makes no-signal periods hard to distinguish from data-source failure.

Current-state caveats this spec intentionally changes:

- The new `ComponentHealth`/`HealthSnapshot` contract replaces or extends the existing uppercase dict health contract; callers must not assume both shapes are equivalent.
- `MetricsRegistry` exists today, but it is not wired into scheduler or dashboard health.
- `system_events` has schema/API support, but runtime paths do not yet write component transition events.

## Non-goals

- No Prometheus/Grafana deployment in this spec.
- No external alert manager.
- No process supervisor changes.
- No UI redesign beyond JSON health fields and minimal dashboard consumption.

## Target behavior

1. Every major component reports status: `ok`, `degraded`, or `down`.
2. Health includes last success time, last error, and core lag/counter metrics.
3. Dashboard `/health` returns degraded status when any critical component is degraded.
4. Bounded smoke evidence schema adds a health snapshot field.
5. Scheduler writes important component transitions to SQLite `system_events`.
6. Metrics are useful without requiring live trading or external services.

## Components to instrument

- Gamma market discovery: last success, last failure, discovered market count.
- CLOB REST: batch books success/failure, fallback count, latency.
- CLOB WS: connected, reconnect count, subscribed token count, stale token count, invalid event count.
- Binance WS: connected, reconnect count, per-asset spot lag.
- Snapshot builder: build count, failure count, max freshness lag.
- Signal gate: accepted count, rejected count by reason.
- Paper simulator: fills, rejects by reason, wallet snapshot count.
- SQLite/JSONL: write failures, last successful write.
- Telegram publisher: sent, dry-run, failed, retry failures.

## Proposed model

```python
@dataclass(frozen=True, slots=True)
class ComponentHealth:
    name: str
    status: Literal["ok", "degraded", "down"]
    last_success_at: str | None
    last_error_at: str | None
    last_error: str | None
    metrics: dict[str, int | float | str | bool | None]
```

`HealthRegistry.snapshot()` returns:

```python
@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    status: Literal["ok", "degraded", "down"]
    generated_at: str
    components: list[ComponentHealth]
```

## Severity rules

- `down`: scheduler cannot build valid snapshots because a required feed is unavailable or storage cannot persist critical state.
- `degraded`: system can run but signal quality is impaired, e.g. CLOB WS reconnecting while REST fallback works, Telegram failed in dry-run-safe mode, or high rejected stale counts.
- `ok`: recent success within configured threshold and no critical error.

## Acceptance criteria

- `/health` shows component-level statuses, not only row counts.
- A simulated Binance stale condition changes health to degraded/down according to config.
- A CLOB WS reconnect increments counters and is visible in health.
- Gate rejection counts by reason are observable.
- Component transition events are written through existing `system_events` schema/API paths when possible and shown in health.
- Existing dashboard read-only boundary remains intact.

## Test strategy

- Unit tests for health aggregation severity.
- Scheduler component tests using fake registries/feed failures.
- Dashboard API test for `/health` shape and degraded status.
- Smoke evidence test that the schema includes the health snapshot field.

## Rollout

1. Define health snapshot model and registry API.
2. Wire instrumentation in scheduler paths with minimal code movement.
3. Extend dashboard `/health` JSON.
4. Add smoke evidence field.
5. Later specs may consume these metrics for stricter gates; this spec only observes and reports.