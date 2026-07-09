# paper-context-rerun-9

Status: WORKING

Verdict: PASS

## Scope

Read-only context mining for final Nautilus alignment completion. I inspected:

- `/tmp/ulw-cursor-75ed7e5d.md`
- `/tmp/ulw-omp-019f42fc.md`
- `docs/architecture-nautilus-alignment.md`
- `.omo/ulw-loop/019f4394-c899-7b12-8f7d-8a7d91d2534a/brief.md`
- `.omo/ulw-loop/019f4394-c899-7b12-8f7d-8a7d91d2534a/goals.json`
- `.omo/ulw-loop/019f4394-c899-7b12-8f7d-8a7d91d2534a/ledger.jsonl`
- Current source, current `.omo/evidence`, `.omo/ulw-loop/evidence`, and git history searches.

No source or test files were edited.

## Conclusion

I found no current source/docs/session contradiction that blocks final completion for R1/R2/R3/R10 or the G001 OrderBook safe slice.

The only apparent contradiction is stale evidence: `.omo/evidence/paper-goal-verification-rerun-9.md` says R10 is blocked because `scheduler_reporting.py` still uses dynamic cache-reader `getattr`. Current source now has direct `nautilus_cache.account()` and `nautilus_cache.positions()` calls, and `.omo/evidence/paper-qa-rerun-9/reporting-cache.txt` captures that direct-method proof. Treat that older FAIL report as superseded by current source plus the newer R10 QA receipt.

## Explicit Questions

### Are `paper_trade_results` and `paper_wallet_snapshots` consistent with R3?

Yes. Retaining both is consistent with the R3 app-local audit/projection-table decision.

Evidence:

- `brief.md:5-8` says prior agents completed the paper/converter/schema/R10 list and specifically kept `paper_trade_results` / `paper_wallet_snapshots` as app-local audit tables.
- `goals.json:101-110` records the same decision as completed verification evidence.
- `docs/architecture-nautilus-alignment.md:296-310` targets `PaperOrder` / `PaperFill` / `PaperPosition` alignment with Nautilus types, not deletion of settlement audit or portfolio projection tables.
- Current `src/polysignal_lab/storage/sqlite_schema.py:70-98` explicitly comments `paper_trade_results` as application-local settlement audit and `paper_wallet_snapshots` as application-local portfolio projection snapshots.
- Current `src/polysignal_lab/storage/sqlite_store.py:326-344` only inserts parsed result rows and wallet snapshots; `restore_open_positions()` / `restore_closed_positions()` reconstruct positions from Nautilus `system_events` at `sqlite_store.py:433-463`, not from legacy `paper_positions`.

So these two tables are not Nautilus order/position shadow storage. They are app-local audit/projection surfaces.

### Does any first-link task remain genuinely unfinished after G001?

No. The first-link "unfinished" item was the OrderBook safe slice, and G001 completed that slice.

Evidence:

- `brief.md:7-18` identifies the only explicit deferred item as OrderBook domain model removal/migration and narrows the goal to the smallest safe slice if full removal is unsafe.
- `docs/architecture-nautilus-alignment.md:497-516` labels full order-book state replacement as long-term/high-risk, with the immediate success criterion that `OrderBook.from_polymarket()` be removed as unreferenced dead code.
- Current `src/polysignal_lab/domain/orderbook.py:24-81` retains only `BookLevel` / simplified `OrderBook` metrics/depth behavior and has no `from_polymarket`.
- Current `src/polysignal_lab/data/orderbook_payload.py:42-101` owns raw public CLOB order-book parsing and fail-closed token validation.
- REST/WS surfaces call the boundary parser at `src/polysignal_lab/data/polymarket_clob_rest.py:85-112` and `src/polysignal_lab/data/polymarket_clob_ws.py:90-97`.
- `.omo/evidence/orderbook-final-gate-review.md:1-9` approves the corrected state with no blockers.
- `.omo/evidence/orderbook-final-qa-recheck.md:31-34` confirms the missing pytest-summary and refs-receipt QA blockers were repaired.

G004-G014 in `goals.json` remain marked blocked, but their steering text says they are duplicate auto-split fragments already covered by G001/G002/G003. They are not genuine unfinished implementation stories.

## R1/R2/R3/R10 Cross-check

- R1/R2: Current searches found no active backend `class PaperOrder`, `class PaperFill`, `class PaperPosition`, `class PaperTradeResult`, `paper_order_from_row`, `paper_position_from_row`, `order_converter`, or `position_converter` definitions/imports in active source. Frontend TypeScript `Paper*` names are API contract names, not backend domain models.
- R3: Current schema has no `CREATE TABLE paper_orders`, `paper_fills`, or `paper_positions`; the remaining `paper_trade_results` and `paper_wallet_snapshots` are explicitly app-local.
- R10: Current `src/polysignal_lab/app/scheduler_reporting.py:296` calls `nautilus_cache.account()` directly and `:315` calls `nautilus_cache.positions()` directly. `.omo/evidence/paper-qa-rerun-9/reporting-cache.txt:1-8` records 7 passing cache-source tests plus the direct-method `rg` receipt.
- Git history (`git log -S/-G`) confirms these areas were repeatedly changed through the Nautilus cleanup chain, but current uncommitted source/evidence is the decisive state.

## Contradictions Found

1. Stale contradiction: `.omo/evidence/paper-goal-verification-rerun-9.md:31-64` reports R10 as FAIL because it saw dynamic cache-reader lookup. Current source and `.omo/evidence/paper-qa-rerun-9/reporting-cache.txt:1-8` supersede that.
2. Non-blocking doc drift: `docs/architecture-nautilus-alignment.md:479-480` still lists `order_converter.py` / `position_converter.py` as proposed Phase 3 files. That is old proposal text, not current implementation truth; the current code has removed those converter surfaces.

## Missed Blocking Requirement

None found.

The completion package should not cite `.omo/evidence/paper-goal-verification-rerun-9.md` as current truth without noting it is stale. If a final gate requires the latest goal-verification artifact itself to be PASS, rerun that verifier after the current R10 direct-call state. That is an artifact-hygiene follow-up, not a missed implementation requirement.

## Cleanup Receipt

No product process, server, browser, tmux session, container, or bound port was spawned. The only workspace write for this assignment was `.omo/evidence/paper-context-rerun-9.md`.

<verdict>PASS</verdict>
