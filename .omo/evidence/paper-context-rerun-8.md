# paper-context-rerun-8

## Conclusion

I did not find codebase, docs, git, or session evidence that contradicts the current completion state for the Nautilus alignment work.

## What I checked

- Git history around the Nautilus refactor commits, including the recent cleanup chain.
- `docs/architecture-nautilus-alignment.md`.
- The two requested local session transcripts.
- Current code references for:
  - `PaperOrder`
  - `PaperFill`
  - `PaperPosition`
  - `PaperTradeResult`
  - `OrderBook`
  - `from_polymarket`
  - `paper_trade_results`
  - `paper_wallet_snapshots`

## Findings

### 1. The old Paper* domain models are already removed from the backend

- `src/polysignal_lab/domain/paper_result.py` no longer defines a `PaperTradeResult` model.
- The file now exposes row-oriented helpers and `TypedDict` payloads for `paper_trade_results` and `paper_wallet_snapshots`.
- `src/polysignal_lab/domain/paper_order.py` and `src/polysignal_lab/domain/paper_position.py` are no longer present in the repo.

This means the earlier R1 deletion work is not contradicted by the current tree.

### 2. The retained SQLite paper tables are expected, not accidental leftovers

`src/polysignal_lab/storage/sqlite_schema.py` explicitly documents both tables as application-local storage:

- `paper_trade_results` is annotated as an application-local settlement audit table.
- `paper_wallet_snapshots` is annotated as an application-local portfolio projection snapshot table.

The same schema file still includes them in `ALLOWED_TABLES`, `REQUIRED_COLUMNS`, and `COUNT_TABLES`, which confirms they are intentionally retained.

Supporting usage also remains in:

- `src/polysignal_lab/app/services/persistence_service.py`
- `src/polysignal_lab/app/_settlement_check.py`
- `src/polysignal_lab/app/scheduler_reporting.py`
- `src/polysignal_lab/dashboard/app.py`
- `scripts/repair_settlement_results.py`

### 3. Architecture docs match the retention

`docs/architecture-nautilus-alignment.md` says:

- `PaperOrder` / `PaperFill` should eventually be replaced, but only as part of the paper execution alignment phase.
- `PaperPosition` may be kept for dashboard/report serialization if needed.
- The document does not describe `paper_trade_results` or `paper_wallet_snapshots` as deletion targets.

So the docs support keeping the tables as audit / projection storage, not deleting them as shadow state.

### 4. Session context does not contradict completion

The requested session transcript still shows the earlier staged refactor path:

- first the converter/domain deletions,
- then the storage split,
- then `PaperTradeResult`-related consumers,
- then smaller cleanup items.

Nothing in the transcript proves that `paper_trade_results` or `paper_wallet_snapshots` were meant to be dropped entirely. The later discussion around settlement repair explicitly treats `paper_trade_results` as a durable backfill/audit target.

### 5. `OrderBook` / `from_polymarket` are separate from this table question

The architecture doc still marks `OrderBook` / `from_polymarket()` as a later boundary alignment item. That is orthogonal to the paper audit tables and does not imply those tables should be deleted.

## Answer to the deletion question

`paper_trade_results` and `paper_wallet_snapshots` are expected app-local audit / projection tables, not a missed deletion.

## Residual note

The frontend still has `PaperOrder` / `PaperPosition` / `PaperTradeResult` API types under `frontend/src/lib/api/types.ts`, but that is a separate SPA contract and does not conflict with the backend backend-domain cleanup.

