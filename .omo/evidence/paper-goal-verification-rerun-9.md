recommendation: REJECT
verdict: FAIL
confidence: high
reportPath: /home/debian/polysignal-lab/.omo/evidence/paper-goal-verification-rerun-9.md
notepadPath: /tmp/ulw-20260709-075503.Gj8bMu.md

# Paper Goal Verification Rerun 9

## originalIntent

Verify the current paper/Nautilus ULW completion state after the post-zero-money approvals, read-only except for this report:

- G001 OrderBook safe slice is complete.
- G002/G003 paper/converter/domain/schema/R10 completion is real.
- G004-G014 are legitimately blocked or superseded duplicate auto-splits.
- Rerun 8's missing-artifact blockers may be treated as stale only if current artifacts and current source support completion.

## desiredOutcome

A user-visible PASS/FAIL report grounded in the current approval reports, current `.omo/ulw-loop` evidence, current goals/ledger, current tests index, and current source, including a direct remove-ai-slops/programming pass and exact evidence gaps.

## constraints

- Repository: `/home/debian/polysignal-lab`.
- Read-only for production/test/source files; only this report path was written.
- Required artifact set inspected: current approval reports, post-zero-money evidence, post-final-index evidence, `tests/FOLDER_INDEX.md`, current source, `.omo/ulw-loop/019f4394-c899-7b12-8f7d-8a7d91d2534a/goals.json`, and `.omo/ulw-loop/019f4394-c899-7b12-8f7d-8a7d91d2534a/ledger.jsonl`.
- Root-level `goals.json` and `ledger.jsonl` do not exist; the durable goal files are under `.omo/ulw-loop/019f4394-c899-7b12-8f7d-8a7d91d2534a/`.

## userOutcomeReview

FAIL. The prior rerun-8 missing-artifact blockers are now satisfied at the artifact level: `.omo/evidence/paper-code-review-rerun-8.md` is PASS/APPROVE, `.omo/evidence/paper-security-rerun-9.md` is PASS/APPROVE, `.omo/evidence/paper-qa-rerun-8.md` is PASS, and those files were written after `.omo/ulw-loop/evidence/paper-post-zero-money-full-pytest.txt`.

Current source still blocks approval. The R10 completion claim is contradicted by `src/polysignal_lab/app/scheduler_reporting.py`: current lines 296-302 use `getattr(nautilus_cache, "account", None)` and `getattr(nautilus_cache, "positions", None)` instead of the direct `nautilus_cache.account()` / `nautilus_cache.positions()` calls recorded in `.omo/ulw-loop/evidence/node-r10-rg.txt`. The current diff also adds `test_report_equity_inputs_ignores_incomplete_cache`, which pins the same defensive incomplete-cache path rather than proving a user-visible paper outcome.

## goalBreakdown

### G001 OrderBook Safe Slice

Status: PASS.

Evidence:
- `.omo/ulw-loop/019f4394-c899-7b12-8f7d-8a7d91d2534a/goals.json` marks G001 complete with orderbook-focused pytest, surface, regression, basedpyright, and final gate evidence.
- `src/polysignal_lab/domain/orderbook.py` has no `from_polymarket` method.
- `src/polysignal_lab/data/orderbook_payload.py` owns `parse_order_book_payload()` and `InvalidOrderBookPayload`.
- `.omo/ulw-loop/evidence/orderbook-surface.txt` reports `verdict=pass`, `fail_closed=True`.
- `.omo/ulw-loop/evidence/orderbook-regression.txt` reports `summary=101 passed`.

### G002/G003 Paper / Converter / Domain / Schema / R10

Status: FAIL.

Evidence supporting partial completion:
- Goals G002 and G003 are marked complete in `goals.json`.
- `rg` found no active `class PaperOrder`, `class PaperFill`, `class PaperPosition`, `class PaperTradeResult`, `order_converter`, `position_converter`, `CREATE TABLE paper_orders`, `CREATE TABLE paper_fills`, `CREATE TABLE paper_positions`, or `OrderBook.from_polymarket` in `src`/`tests`.
- `src/polysignal_lab/storage/sqlite_schema.py` keeps only `paper_trade_results` and `paper_wallet_snapshots` as app-local audit/projection tables.
- `src/polysignal_lab/app/_settlement_check.py` rejects missing, non-finite, zero, or negative settlement money before row creation.
- `src/polysignal_lab/nautilus_runtime/projections.py` preserves missing Nautilus quantity/avg price/stake as `None`.
- Fresh focused pytest run passed: `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider tests/test_nautilus_reporting_cache_source.py tests/test_settlement.py tests/test_scheduler_settlement_resolution.py tests/test_nautilus_projections.py tests/test_storage_restore.py` -> `53 passed`.

Blocking contradiction:
- `.omo/ulw-loop/evidence/node-r10-rg.txt` records R10 completion as direct `nautilus_cache.account()` and `nautilus_cache.positions()` calls.
- Current `src/polysignal_lab/app/scheduler_reporting.py:296-302` uses dynamic `getattr` reader lookup and an incomplete-cache fallback.
- `git diff -- src/polysignal_lab/app/scheduler_reporting.py tests/test_nautilus_reporting_cache_source.py` shows the current diff adds `_ReportScheduler` protocol scaffolding plus the incomplete-cache test, not a direct R10 collapse.
- Focused basedpyright over the R10 files still has `0 errors, 36 warnings`, including unused imports, explicit `Any`, private imports, and dynamic `getattr` warnings. This is not clean programming evidence for the R10 slice.

### G004-G014 Duplicate Auto-Splits

Status: BLOCKED/SUPERSEDED AS PLACEHOLDERS, but not enough for overall PASS.

Evidence:
- `goals.json` marks G004-G014 `blocked`.
- Each blocked goal records the same steering reason: "Collapse invalid auto-generated URL/constraint fragments into completed concrete stories."
- Their objectives are constraints or duplicates of G001/G002/G003 criteria, not separate implementation stories.
- Because G002/G003 currently fails on R10, the duplicate/superseded status is legitimate structurally but does not rescue the overall goal.

## approvalArtifacts

- `.omo/evidence/paper-code-review-rerun-8.md`: PASS/APPROVE, blockers empty, but scoped to the zero-money fix. It explicitly says the branch still has typed debt and minor test metadata/slop.
- `.omo/evidence/paper-security-rerun-9.md`: PASS/APPROVE for the security rerun and zero-money/malformed storage surfaces.
- `.omo/evidence/paper-qa-rerun-8.md`: PASS with focused pytest, system pytest, direct probes, protected refs/docs check, and evidence non-empty check.
- `.omo/evidence/paper-context-rerun-8.md`: no contradiction for backend domain/table cleanup.
- `.omo/evidence/paper-goal-verification-rerun-8.md`: its missing code-review/security artifact blockers are stale now, but its functional claims depended on stale R10 evidence.

## directSlopAndProgrammingPass

- `remove-ai-slops`: FAIL for current R10 scope. The current diff adds/pins an incomplete-cache fallback test (`test_report_equity_inputs_ignores_incomplete_cache`) that mirrors defensive implementation rather than proving a paper user outcome. It also leaves deletion-only tests in `tests/test_nautilus_exit_policy.py`; those are outside the paper settlement fix but show the final report coverage is not a whole-test-suite slop pass.
- `programming`: FAIL for current R10 scope. `scheduler_reporting.py` still relies on `Any`, private imports, unused imported helpers, and dynamic `getattr` around the cache readers. This conflicts with the claimed "R10 getattr collapse" and the programming rules' typed-boundary/smallest-correct-change criteria.
- Report coverage check: FAIL. The current code-review/security approvals cover the zero-money/security slice, not the current R10 contradiction or incomplete-cache slop.

## blockers

1. HIGH: R10 completion is contradicted by current source.
   - Expected evidence: `.omo/ulw-loop/evidence/node-r10-rg.txt` records direct `nautilus_cache.account()` / `nautilus_cache.positions()`.
   - Current source: `src/polysignal_lab/app/scheduler_reporting.py:296-302` uses `getattr` reader lookup and an incomplete-cache fallback.

2. HIGH: Current approval artifacts do not cover the R10 regression/slop.
   - `.omo/evidence/paper-code-review-rerun-8.md` and `.omo/evidence/paper-security-rerun-9.md` are valid post-zero approvals, but their reviewed surface is the zero-money/security fix.
   - Neither approval reconciles the stale `node-r10-rg.txt` claim with current `scheduler_reporting.py`.

3. MEDIUM: Direct slop pass found unresolved test slop.
   - `tests/test_nautilus_reporting_cache_source.py` now includes an implementation-shaped incomplete-cache test.
   - `tests/test_nautilus_exit_policy.py` still contains deletion-only module-removal tests; not paper-specific, but not clean whole-suite slop evidence either.

## freshChecksRun

- `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider tests/test_settlement.py tests/test_scheduler_settlement_resolution.py tests/test_nautilus_projections.py tests/test_storage_restore.py` -> `45 passed`.
- `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider tests/test_nautilus_reporting_cache_source.py tests/test_settlement.py tests/test_scheduler_settlement_resolution.py tests/test_nautilus_projections.py tests/test_storage_restore.py` -> `53 passed`.
- `PYTHONDONTWRITEBYTECODE=1 uv run basedpyright src/polysignal_lab/app/scheduler_reporting.py tests/test_nautilus_reporting_cache_source.py` -> `0 errors, 36 warnings, 0 notes`.
- `git diff --check` -> pass.
- `rg` source searches for removed Paper* model/converter/table names and `OrderBook.from_polymarket` -> no active blocking definitions/calls.
- `rg` slop scan for `module_is_removed`, `is_removed`, and `Path(...).exists()` in relevant tests -> deletion-only tests remain in `tests/test_nautilus_exit_policy.py`.

## checkedArtifactPaths

- `.omo/evidence/paper-code-review-rerun-8.md`
- `.omo/evidence/paper-security-rerun-9.md`
- `.omo/evidence/paper-qa-rerun-8.md`
- `.omo/evidence/paper-context-rerun-8.md`
- `.omo/evidence/paper-goal-verification-rerun-8.md`
- `.omo/ulw-loop/019f4394-c899-7b12-8f7d-8a7d91d2534a/brief.md`
- `.omo/ulw-loop/019f4394-c899-7b12-8f7d-8a7d91d2534a/goals.json`
- `.omo/ulw-loop/019f4394-c899-7b12-8f7d-8a7d91d2534a/ledger.jsonl`
- `.omo/ulw-loop/evidence/orderbook-surface.txt`
- `.omo/ulw-loop/evidence/orderbook-regression.txt`
- `.omo/ulw-loop/evidence/paper-models-rg.txt`
- `.omo/ulw-loop/evidence/paper-schema-rg.txt`
- `.omo/ulw-loop/evidence/node-r10-rg.txt`
- `.omo/ulw-loop/evidence/paper-post-zero-money-focused-pytest.txt`
- `.omo/ulw-loop/evidence/paper-post-zero-money-full-pytest.txt`
- `.omo/ulw-loop/evidence/paper-post-zero-money-manual-qa.txt`
- `.omo/ulw-loop/evidence/paper-post-zero-money-basedpyright.txt`
- `.omo/ulw-loop/evidence/paper-post-final-index-focused-pytest.txt`
- `.omo/ulw-loop/evidence/paper-post-final-index-rg.txt`
- `tests/FOLDER_INDEX.md`
- `tests/test_nautilus_reporting_cache_source.py`
- `tests/test_nautilus_exit_policy.py`
- `src/polysignal_lab/domain/orderbook.py`
- `src/polysignal_lab/data/orderbook_payload.py`
- `src/polysignal_lab/app/scheduler_reporting.py`
- `src/polysignal_lab/app/_settlement_check.py`
- `src/polysignal_lab/nautilus_runtime/projections.py`
- `src/polysignal_lab/storage/sqlite_schema.py`
- `src/polysignal_lab/storage/sqlite_store.py`

## exactEvidenceGaps

- No current artifact proves R10 against current `src/polysignal_lab/app/scheduler_reporting.py`.
- No current approval report reconciles the stale `node-r10-rg.txt` direct-call evidence with the current `getattr` implementation.
- No current whole-scope remove-ai-slops/programming review covers the R10 diff and the incomplete-cache test.
- Root-level `goals.json` / `ledger.jsonl` are absent; only the `.omo/ulw-loop/...` goal files were available.

## finalRecommendation

REJECT / FAIL. G001 passes and the paper model/converter/schema/zero-money parts of G002/G003 are substantially complete, with G004-G014 legitimately blocked/superseded as duplicate placeholders. The overall package cannot pass because current source contradicts the claimed R10 completion and the post-zero approvals do not cover that contradiction.

<verdict>FAIL</verdict>
