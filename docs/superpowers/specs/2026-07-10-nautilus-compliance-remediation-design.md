# Nautilus Compliance Remediation Design

## Goal

Resolve the confirmed P0/P1 Nautilus compliance defects while preserving Nautilus as the sole owner of market data, order lifecycle, execution, cache, portfolio, and positions.

## Scope

- Make Docker's no-argument runtime select Nautilus and retire scheduler execution mode.
- Restore the Python 3.11 host-agnostic alpha import boundary.
- Replace the unsafe partial batch-arbitration change with deterministic, pair-safe, fail-closed behavior.
- Make replay-sensitive alpha timing derive from event time end-to-end.
- Prevent synchronous crypto-price HTTP from running in `MarketRotationActor`.
- Add focused regression tests and run default, bridge, static, and full-suite verification.

Directly related cleanup only: remove obsolete alpha wall-clock helpers and prevent external mutation of VWAP trade-history snapshots.

## Non-goals

- No replacement of `LiveNode`, Cache, Portfolio, SQLite projections, or the existing strategy lifecycle model.
- No distributed SQLite/JSONL transaction.
- No migration to `TradingNode` or a new MessageBus/RPC arbitration framework.
- No unrelated refactoring of scheduler-named reporting modules.

## Design

### Runtime selection

`docker-entrypoint.sh` defaults to `nautilus`. The `scheduler` selector exits with a retirement error before creating an execution loop. Dashboard, test, smoke, and shell modes remain unchanged.

### Alpha/runtime boundary

`alpha` stops re-exporting runtime order-plan types. `OrderSubmissionPlan` and the compatibility alias remain runtime-only. A clean Python 3.11 environment must import both `polysignal_lab` and `polysignal_lab.alpha` without importing `nautilus_trader`.

### Arbitration

The current per-core batch pre-filter is unsafe because it suppresses paired legs and fails open. The repaired flow is:

1. Convert each decision into a candidate using the same freshness policy as normal evaluation.
2. Evaluate normal pre-arbitration eligibility (manual/dependency disable and gate validation) before a candidate may suppress another.
3. Treat decisions sharing a non-empty `pair_id` as an atomic group: their UP/DOWN legs are never conflict-suppressed against one another.
4. Arbitrate only eligible non-paired competing candidates using stable configuration priority, not callback list position.
5. Submit survivors through the existing `DecisionPipeline` and `NativeDecisionSink` path.
6. If batch preparation or arbitration raises, record degradation and submit no decisions from that batch.

Cross-callback aggregation is not silently invented. The implementation must state and test the actual evaluation batch boundary; independently delivered signals remain subject to the existing per-decision policy until an explicit aggregation design is approved.

### Logical time

A shared strict timestamp conversion accepts only positive Unix nanoseconds and produces timezone-aware UTC `datetime`. Event projection uses it rather than ambient wall clock. `MarketViewAssembler` accepts an explicit event-derived `created_at` at runtime call sites where one is available; absent source time is rejected for replay-sensitive paths rather than fabricated. Alpha cores use `view.created_at`; obsolete `_utc_now()` helpers are removed.

### Actor network safety

The native market-rotation path rejects `use_crypto_price_api=True` before constructing a fallback that can execute HTTP. Metadata, anchor, and existing CustomData sources stay supported. A future network-backed PTB source must publish results through a worker/data-client boundary.

## Acceptance criteria

1. No-argument Docker entrypoint invokes Nautilus; `scheduler` exits without execution.
2. Paired UP/DOWN legs with the same `pair_id` reach normal submission; conflicting non-paired candidates remain suppressible.
3. Batch errors submit zero orders and record health/degradation.
4. Invalid candidates cannot suppress valid candidates; ordering cannot alter configured precedence.
5. Unix-nanosecond events are projected deterministically; invalid event time fails closed.
6. Python 3.11 import of `polysignal_lab.alpha` succeeds without Nautilus installed.
7. Native Actor never invokes crypto-price synchronous HTTP.
8. Focused tests, Python 3.11 boundary checks, Python 3.12 Nautilus bridge tests, full suite, Ruff, safety scan, and `git diff --check` pass.
