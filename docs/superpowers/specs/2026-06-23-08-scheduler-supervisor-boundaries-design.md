# 08 Scheduler Supervisor Boundaries Design

**Status:** Draft for review
**Scope:** One standalone architecture change. Execute only after earlier targeted specs have stabilized; do not batch with specs 01-07.
**Goal:** Reduce `PolySignalScheduler` from a god-object into a thin supervisor over explicit services with owned lifecycle, health, and failure boundaries.

## Problem

`PolySignalScheduler` constructs and coordinates market discovery, CLOB REST/WS, Binance WS, PTB, snapshot building, signal gate, consensus, Telegram, JSONL, SQLite, paper wallet, simulator, exits, settlement, and reports. The runtime loop performs many unrelated operations serially. This creates high blast radius: a slow persistence call, feed stall, or reporting error can affect market-sensitive evaluation.

Earlier specs address specific correctness gaps. This spec is deliberately last because broad lifecycle refactoring before fixing book/freshness/paper correctness would move bugs around without reducing risk.

The refactor target is broader than the `PolySignalScheduler` class: it includes module-level runtime logic in `scheduler_runtime`, `scheduler_market_data`, `scheduler_processing`, `scheduler_reporting`, and `scheduler_state` so ownership does not remain split across hidden helper paths.

## Non-goals

- No new distributed system.
- No Redis/Kafka adoption in this spec.
- No live trading.
- No complete rewrite of scheduler in one commit.
- No UI redesign.

## Target architecture

`PolySignalScheduler` becomes a composition root and supervisor. Concrete services own their own lifecycle and health:

- `MarketUniverseService`: Gamma discovery, active/resolved market refresh, token universe.
- `BookFeedService`: CLOB REST bootstrap/reseed and WS book updates.
- `SpotFeedService`: Binance spot streams and spot history.
- `SnapshotService`: immutable normalized market snapshots.
- `SignalPipeline`: strategy compatibility, evaluation, gate, consensus.
- `PaperPortfolioService`: paper order preflight, fills, wallet, exits, settlement.
- `PublishService`: Telegram formatting/sending/audit.
- `PersistenceService`: SQLite/JSONL/state writes and restore.
- `HealthService`: component health aggregation.

This spec depends on spec 04's `ComponentHealth` contract for service health shape and aggregation semantics.

## Service contract

Each service exposes a minimal lifecycle:

```python
class RuntimeService(Protocol):
    name: str
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def health(self) -> ComponentHealth: ...
```

Services with periodic work expose explicit methods called by the supervisor, not hidden background loops unless necessary. Existing feed adapters already run reconnect loops internally; extraction must preserve supervised cancellation, restart, and health semantics for any loop that remains internal.

## Data boundaries

- Feed services publish/maintain normalized state only.
- Strategy code receives immutable `MarketSnapshot` objects.
- Paper execution consumes accepted signals and current book snapshots, not strategy internals.
- Publishing consumes formatted events/results, not raw strategy objects.
- Persistence receives domain events and snapshots; it does not own strategy decisions.

## Migration order

1. Extract `PersistenceService` wrapper around existing SQLite/JSONL/state calls, then migrate every callsite to it so no duplicate persistence control paths remain.
2. Extract `MarketUniverseService` around existing `scheduler_market_data` refresh functions.
3. Extract `BookFeedService` after spec 01 book reconciliation is complete.
4. Extract `SignalPipeline` after spec 07 readiness filtering is complete.
5. Extract `PaperPortfolioService` after spec 03 paper preflight is complete.
6. Wire health from spec 04 into every service.
7. Only then simplify `PolySignalScheduler.run()` into lifecycle orchestration.

## Acceptance criteria

- `PolySignalScheduler.__init__` no longer constructs every concrete subsystem directly; construction is grouped behind services.
- `run()` loop reads as orchestration, not business logic.
- Each service has isolated tests with fakes for external adapters.
- Slow, hung, blocking, or failing publish/report/storage paths do not block feed updates or snapshot evaluation.
- Shutdown flushes persistence and stops WebSockets deterministically.
- Existing CLI modes remain unchanged.

## Test strategy

- Unit tests per service using fake dependencies.
- Scheduler lifecycle test: start order, stop order, cancellation handling.
- Failure isolation test: slow, hung, blocking, and thrown publish/report/storage failures do not prevent snapshot evaluation in the next iteration.
- State restore/persist regression tests remain passing.
- Bounded smoke verifies same external read-only behavior.

## Rollout

This is a phased refactor, but it is still one standalone implementation project. Do not start until specs 01-07 are either complete or explicitly deferred. If only some services are extracted, the deliverable must still leave the scheduler in a coherent, tested state with no duplicate control paths.