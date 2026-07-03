# Nautilus Runtime Error Isolation Design

Date: 2026-07-03
Status: Revised after spec review
Scope: Prevent project-owned Nautilus callback paths from propagating recoverable data, persistence, and side-effect failures into the live engine queue.

## Conclusion

The durable fix is to isolate recoverable parsing, persistence, and notification failures from the current legacy Nautilus `TradingNode` callback path, while keeping unclassified trading-state corruption visible as fatal.

## Current Runtime Scope

This spec targets the current project runtime built in `src/polysignal_lab/nautilus_runtime/node.py` and configured through `src/polysignal_lab/nautilus_runtime/trading_node.py` with legacy `nautilus_trader.live.node.TradingNode` / `TradingNodeConfig`.

`LiveNode` guidance from current Nautilus documentation is used only as a design constraint: Python callback bodies should stay short, deterministic, and free of fragile blocking side effects. Migrating from `TradingNode` to `LiveNode` is out of scope for this implementation cycle.

`graceful_shutdown_on_exception=True` remains enabled during this work. The goal is not to suppress Nautilus engine failures globally; the goal is to prevent project-owned callback and side-effect code from raising recoverable failures into Nautilus queue processing.

## Evidence

Recent unpushed commits show repeated local fixes in resource, subscription, market refresh, cache, and observability paths. These changes reduced individual failure modes but did not change the runtime invariant that project Python code can still raise inside Nautilus callback processing.

The latest restart path was:

1. `on_order_submitted` handled a Nautilus order event.
2. The strategy recorded a `nautilus_order` observability event.
3. The observability adapter synchronously wrote to SQLite through `insert_system_event`.
4. SQLite raised `OperationalError("database is locked")`.
5. The exception propagated into Nautilus `ExecEngine` event queue processing.
6. Because `graceful_shutdown_on_exception=True`, Nautilus initiated `ShutdownSystem`.

Other observed symptoms are related but not identical failure classes:

- `Failed to parse websocket message: INVALID OPERATION`
- `Cannot cancel an order with INITIALIZED from the matching engine`
- `Cannot calculate exchange rate: ValueError('Quote maps must not be empty')`
- repeated stale trade/quote warnings

The common mechanism is boundary leakage: external data anomalies, state-machine timing, or non-critical side effects can reach the live engine path as exceptions or error-level behavior.

## Nautilus Guidance Applied

Local `docs/nautilus_reference/` and Context7 Nautilus documentation support these constraints:

- Live callback bodies should remain short and should not perform fragile blocking work.
- `graceful_shutdown_on_exception` causes graceful shutdown on unexpected queue processing exceptions.
- Adapter boundaries should classify retryable, non-retryable, and fatal errors.
- WebSocket/network failures should be handled at the handler boundary with retry/error classification.
- Tests for live engine and execution-manager behavior should include integration or deterministic simulation style coverage, not only isolated unit tests.

## Design Goals

1. Recoverable malformed data reaching project-owned callback/object boundaries must not propagate into Nautilus queue processing.
2. Best-effort telemetry failures from SQLite, JSONL, Telegram, and health snapshots must not propagate into Nautilus queue processing.
3. Critical paper state must be persisted with durable retry or explicit degraded-state reporting; it must not be silently dropped.
4. Recoverable market-data and order-state anomalies must be recorded as health metrics and skipped locally.
5. Unclassified core/state corruption must remain fatal or explicitly controlled-shutdown eligible.
6. The implementation must be incremental and testable in small patches.

## Non-Goals

- Do not disable `graceful_shutdown_on_exception` as the primary fix.
- Do not migrate this runtime from `TradingNode` to `LiveNode` in this cycle.
- Do not modify files under `refs/`.
- Do not replace NautilusTrader or bypass its engines.
- Do not add broad catch-all blocks that silently hide trading-state corruption.
- Do not make live Polymarket execution possible in the default paper runtime.
- Do not promise to fix raw Polymarket WebSocket parser internals unless the parser is project-owned or configurable from this repo.

## Persistence Classification

Persistence paths must be classified before queueing behavior is implemented.

| Class | Tables / streams | Failure behavior |
| --- | --- | --- |
| `best_effort_telemetry` | `nautilus_decision`, `nautilus_order`, `nautilus_fill`, `nautilus_position`, `health_snapshot`, derived runtime metrics | May drop or coalesce under pressure. Must increment health counters. Must not raise into callbacks. |
| `durable_or_degraded` | `signals`, `rejected_signals`, strategy status, daily report telemetry | Should retry or persist through JSONL/state fallback where available. If persistence falls behind, mark degraded. No silent drop. |
| `critical_paper_state` | `orders`, `fills`, `positions`, `settlements`, wallet snapshots, `StateStore` recovery state | Must use durable retry, bounded shutdown drain, or explicit fatal/degraded transition. No silent drop. |
| `fatal_on_loss` | schema migration, schema validation, unrecoverable state-store corruption | May fail startup or trigger controlled shutdown because runtime recovery semantics are unsafe. |

The existing `NautilusEventStoreAdapter` currently routes both telemetry and critical paper state. The implementation must split behavior by classification rather than applying one best-effort policy to every table.

## Recommended Architecture

### Callback Boundary Split

Use two different boundary types rather than one broad catch-all.

#### Side-Effect Guard

The side-effect guard wraps non-critical or externally fragile work:

- observability telemetry
- JSONL append for best-effort telemetry
- Telegram notification
- health snapshot emission
- paper fill mirroring when it does not mutate critical state

Guard behavior:

- classify known transient failures as `non_critical_side_effect`;
- increment health counters;
- return control to Nautilus without raising;
- preserve enough payload metadata for later debugging.

#### Domain Transition Guard

The domain transition guard covers project-owned domain transitions only after errors have been classified.

Examples:

- unknown instrument/token mapping;
- stale market data;
- missing optional readiness input;
- non-cancelable local order state.

Guard behavior:

- `recoverable` inputs become skip + metric;
- `fatal` inputs mark heartbeat fatal and may allow controlled shutdown;
- unclassified exceptions from core strategy state mutation remain fatal until explicitly categorized.

This split preserves the invariant that side effects cannot kill the engine while avoiding a broad catch-all around core trading state.

### Input Parser and Object Boundary

The project does not currently own the raw Polymarket WebSocket parser that emits `Failed to parse websocket message: INVALID OPERATION`. The raw frame parser appears to live in the Nautilus Polymarket adapter layer.

This spec therefore defines two scopes:

1. **Project-owned object boundary:** classify and guard the objects/custom data that enter `PolySignalNativeStrategy`, `MarketViewAssembler`, `NautilusBookDataProvider`, and related runtime code.
2. **Adapter-owned raw frame boundary:** if raw WebSocket parser behavior is configurable or patchable in this repo, add a targeted adapter-boundary fix; otherwise, verify through integration tests and document as upstream/adapter behavior.

Project-owned classification results should be explicit:

- `ValidData`
- `DroppedFrame`
- `RecoverableFeedError`
- `FatalFeedError`

Expected classifications at the first project-owned boundary:

- malformed custom data or unsupported payload shape: `DroppedFrame` or `RecoverableFeedError`;
- unknown instrument/token/condition mapping: `DroppedFrame` with metrics;
- stale trade/quote: normal stale-data drop, not error;
- missing quote maps/account conversion data: readiness miss, not engine-fatal.

Raw text such as `INVALID OPERATION` should be handled in the adapter boundary if and only if this repo can control that parser. Otherwise, project-owned tests should assert that downstream runtime code remains healthy when the adapter emits recoverable error signals or resumes with later valid data.

### Persistence Classification and Queueing

Replace direct synchronous best-effort telemetry writes from callbacks with a bounded queue. Do not put all persistence classes behind the same drop policy.

Callback behavior for best-effort telemetry:

1. Build an immutable payload.
2. Attempt non-blocking enqueue.
3. Increment dropped/coalesced metrics if the queue is full.
4. Return to Nautilus immediately.

Writer behavior:

1. A single background writer drains telemetry queue items.
2. It writes JSONL and SQLite serially.
3. It reports write failures through health metrics.
4. It retries transient SQLite lock failures with bounded backoff.

Critical paper state behavior:

1. Route through a separate durable path or priority queue.
2. Do not silently drop on full queues.
3. On sustained failure, mark persistence degraded and either drain during controlled shutdown or raise a classified fatal state-loss condition.
4. Preserve existing restart/recovery semantics through wallet snapshots and `StateStore`.

JSONL failure behavior must be explicit:

- telemetry JSONL failures are side-effect failures;
- critical state JSONL failures may be tolerated only if SQLite/state recovery remains durable;
- simultaneous SQLite and JSONL failures for critical state must become degraded or fatal, not silent success.

### SQLite Hardening

Update `SQLiteStore` initialization:

- use `sqlite3.connect(..., timeout=30, check_same_thread=False)`;
- set `PRAGMA busy_timeout=30000`;
- set `PRAGMA journal_mode=WAL`;
- set `PRAGMA synchronous=NORMAL`;
- keep transactions short.

Acceptance for this section:

- a new connection reports `PRAGMA journal_mode` as `wal`;
- `PRAGMA busy_timeout` reports `30000`;
- a locked-write regression test proves transient lock handling follows the classified queue policy.

If contention remains, split storage:

- `paper_state.sqlite3` for critical business state;
- `observability.sqlite3` for high-frequency runtime telemetry.

The split is an escalation step, not required before lock metrics prove the single database remains a bottleneck.

### Order State Gate

Prevent invalid cancel attempts from reaching the matching engine, but first locate the actual cancel producer.

Investigation step:

- identify the project call site that emits cancel requests or stop-time cancel behavior;
- confirm whether the `INITIALIZED` cancel originates from project code, Nautilus matching engine shutdown behavior, or adapter/order lifecycle timing.

Implementation rule after call-site confirmation:

- `INITIALIZED` is not cancelable;
- IOC/FOK orders generally should not be canceled after submission unless a later state proves cancellation is valid;
- cancel is allowed only for known cancelable states such as `SUBMITTED`, `ACCEPTED`, and `PARTIALLY_FILLED`;
- state gate decisions emit metrics and structured reasons.

Do not introduce a generic cancel-gate API until the cancel producer is identified.

### Readiness Gate

Treat missing market/account conversion data as readiness failures at `MarketView` construction and strategy evaluation boundaries.

Rules:

- Nautilus readiness is `MarketView`-level readiness, distinct from legacy scheduler `StrategyReadiness`.
- Each Nautilus strategy must declare the fields it needs: up/down books, spot data, price-to-beat data, account conversion data, or other inputs.
- Missing optional data becomes skip + metric when the strategy can safely skip.
- Missing required data prevents order submission.
- Missing quote maps/account conversion data should not trigger an account-state fatal path from project code.

## Testing Strategy

### Unit Tests

- Project-owned parser/object boundary classifies malformed custom data as recoverable or dropped.
- Unknown instrument/token mapping is dropped with metrics.
- Side-effect guard prevents telemetry SQLite lock from raising into callbacks.
- Side-effect guard handles telemetry JSONL `OSError` without raising into callbacks.
- Telemetry queue drops/coalesces high-frequency events when full and increments counters.
- Critical paper state queue/full behavior is durable, degraded, or fatal, never silent drop.
- SQLite initialization reports WAL mode and `busy_timeout=30000`.
- Cancel gate refuses `INITIALIZED` orders after the actual cancel producer is located.
- Readiness gate skips evaluation when required `MarketView` fields are missing.

### Integration Tests

- Simulate malformed project-owned callback data followed by valid data; valid data still reaches market state.
- Simulate SQLite lock during telemetry order callbacks; no exception propagates into Nautilus queue processing.
- Simulate JSONL append failure for telemetry; callback returns and health reports telemetry degradation.
- Simulate simultaneous SQLite and JSONL failure for critical paper state; runtime marks degraded or fatal according to the persistence classification.
- Simulate callback exceptions in notification and non-critical mirroring; runtime heartbeat continues.
- Simulate high-frequency order/fill telemetry events; writer backlog is bounded and health reports degradation.

### Runtime Verification

- Run targeted pytest modules for observability, native strategy, trading node runtime, storage, and market rotation.
- Rebuild and restart only `polysignal-lab`.
- Confirm container health is `healthy`.
- Confirm injected project-owned telemetry and malformed-object failures do not produce `Unexpected exception` or `ShutdownSystem`.
- Confirm health metrics expose dropped/recovered parser events, telemetry queue drops, writer backlog, SQLite lock retries, and fatal runtime errors.

## Implementation Sequence

1. Classify persistence paths and add tests for best-effort telemetry, durable/degraded state, and fatal-on-loss state.
2. Add side-effect guard tests around observability, JSONL, notification, and non-critical mirroring failures.
3. Implement best-effort telemetry queue and single writer.
4. Implement critical paper state durable/degraded behavior separately from telemetry drop behavior.
5. Harden SQLite connection settings and add PRAGMA verification tests.
6. Add project-owned parser/object boundary classification utilities and tests.
7. Add readiness gate definitions at `MarketView` / strategy evaluation boundaries.
8. Locate cancel producer; then add the minimal order-state predicate before that producer.
9. Add integration tests proving classified malformed data and telemetry persistence failures do not propagate into Nautilus queue processing.
10. Re-evaluate whether `graceful_shutdown_on_exception=True` remains appropriate after boundaries are in place.

## Acceptance Criteria

The design is complete when all of the following are true:

- Given a project-owned callback/object boundary, malformed or unsupported data is classified and does not propagate into Nautilus queue processing.
- Given a telemetry SQLite lock, telemetry JSONL `OSError`, or notifier exception, the callback returns without propagating and health reports the failure.
- Given critical paper state persistence failure, the runtime follows durable retry, explicit degraded state, or classified fatal shutdown; it never silently drops state.
- Invalid cancel attempts are blocked before reaching the matching engine after the cancel producer is identified.
- Missing required readiness data skips evaluation or order submission instead of entering a fatal account-state path from project code.
- SQLite connections verify WAL mode and `busy_timeout=30000`.
- Health metrics distinguish dropped data, recoverable parser errors, telemetry queue drops, writer backlog, SQLite lock retries, degraded persistence, and fatal runtime errors.
- Tests cover each failure class without relying on fragile log text matching.

## Risks and Tradeoffs

- Bounded queues may drop non-critical telemetry under stress. This is acceptable only for `best_effort_telemetry`.
- Critical state needs stronger handling than telemetry. If the same implementation mechanism is reused, it must still enforce separate policies.
- Catching recoverable errors at the boundary can hide bugs if metrics are ignored. Health counters and regression tests are required.
- Splitting SQLite databases increases operational complexity and should wait for lock metrics showing single-database contention remains material.
- Raw Polymarket WebSocket parser behavior may live outside this repo. The project can guard downstream object boundaries, but upstream parser fixes may require adapter patching or dependency upgrades.

## Approved Direction

Proceed with the revised architecture: legacy `TradingNode`-scoped error isolation, side-effect and domain-transition boundary split, persistence classification, telemetry queueing, critical paper state durability, SQLite hardening, project-owned parser/object classification, targeted order state gating, and `MarketView` readiness gating.
