recommendation: REJECT
verdict: FAIL
confidence: high
reportPath: /home/debian/polysignal-lab/.omo/evidence/paper-goal-verification-rerun-7.md
notepadPath: /tmp/ulw-20260709-065057.O9TjQu.md

# Paper Goal Verification Rerun 7

## originalIntent

Verify the current ULW completion state for the Nautilus paper/domain/storage refactor, without changing production or test files:

- G001: OrderBook safe slice is complete: `OrderBook.from_polymarket` removed from active production code and raw Polymarket book parsing moved to the data/app boundary.
- G002/G003: paper/converter/domain/schema/R10 completion is real: backend `PaperOrder` / `PaperFill` / `PaperPosition` / `PaperTradeResult` model classes and paper order/fill/position tables are removed or migrated; `paper_trade_results` and wallet snapshots remain only as app-local audit/projection tables.
- Latest fixes after stale reports address live settlement missing fields and malformed persisted JSON surfaces.
- G004-G014 duplicate auto-split goals are legitimately blocked/superseded, not unfinished work.

## desiredOutcome

A shippable completion package where current source, tests, manual probes, and review artifacts prove the requested paper/runtime behavior is complete, fail-closed, and not relying on stale or overfit evidence.

## constraints

- Scope: `/home/debian/polysignal-lab`.
- Read `.omo/ulw-loop/019f4394-c899-7b12-8f7d-8a7d91d2534a/brief.md`, `goals.json`, `ledger.jsonl`, both session URLs, and current evidence.
- Do not edit production or test files.
- Do not modify `@refs`, `refs`, or `docs/nautilus_reference`.
- Write only this report artifact inside the repository.

## userOutcomeReview

The implementation is still not complete from the user's perspective. The broad model/table/converter cleanup is mostly real, and G001 is adequately proven, but the current paper settlement surface still accepts invalid live monetary payloads and persists valid-looking paper trade results.

The stale blockers are only partially fixed:

- Fixed since rerun 6/security rerun 7: missing `stake_usdc` now skips settlement; malformed `system_events` and `daily_reports` restore surfaces skip bad rows; same-key malformed existing payload raises `MalformedSQLitePayloadError`.
- Still failing: explicit zero/negative money values on live settlement projections are accepted and persisted. This does not satisfy the stale code-review requirement to reject `missing/non-finite/zero-or-invalid money fields`.
- Evidence gap remains: there is no current post-security code-review artifact with `remove-ai-slops` and `programming` coverage. The latest code review artifact is `.omo/evidence/paper-code-review-rerun-6.md`, which is a FAIL report.

## goalBreakdown

### G001 OrderBook Safe Slice

Status: PASS for the safe slice.

Evidence:

- `.omo/ulw-loop/evidence/scope-decision.txt` records the scoped decision: remove the raw public Polymarket payload parser from the domain model, keep the simplified `OrderBook` container for MarketView/state assembly.
- Current `src/polysignal_lab/domain/orderbook.py:29-81` has `OrderBook` metrics/depth behavior but no `from_polymarket` parser.
- Current `src/polysignal_lab/data/orderbook_payload.py:42-69` owns public payload parsing and raises `InvalidOrderBookPayload` for malformed/non-object/missing-token payloads.
- `.omo/ulw-loop/evidence/orderbook-surface.txt` reports `verdict=pass`, `fail_closed=True`, and `unknown_metric=ws_event_unknown`.
- `.omo/ulw-loop/evidence/orderbook-focused-pytest.txt`, `orderbook-regression.txt`, and `orderbook-basedpyright.txt` record focused/regression/typecheck pass evidence.

### G002/G003 Paper / Converter / Domain / Schema / R10

Status: FAIL overall, despite substantial completed cleanup.

Completed evidence:

- `src/polysignal_lab/domain/paper_order.py`, `src/polysignal_lab/domain/paper_position.py`, and `src/polysignal_lab/nautilus_bridge/instrument_mapping.py` are deleted in the current diff.
- Current active source search found no backend `class PaperOrder`, `class PaperFill`, `class PaperPosition`, or `class PaperTradeResult`.
- Remaining backend `PaperTradeResult` usage is row-shaped: `src/polysignal_lab/domain/paper_result.py:32-56` defines `PaperTradeResultRow`.
- `src/polysignal_lab/storage/sqlite_schema.py` retains only `paper_trade_results` and `paper_wallet_snapshots` for app-local audit/projection usage; current search found no active `CREATE`/`INSERT` paths for `paper_orders`, `paper_fills`, or `paper_positions`.
- Current `src/polysignal_lab/storage/sqlite_store.py:396-417` skips malformed JSON for `paper_trade_results`, `system_events`, and `daily_reports`.
- Current `src/polysignal_lab/storage/sqlite_store.py:496-520` raises `MalformedSQLitePayloadError` for same-key malformed existing payloads.
- Fresh focused pytest passed: `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider tests/test_scheduler_settlement_resolution.py tests/test_storage_restore.py tests/test_repair_settlement_results.py tests/test_scheduler_cancelled_markets.py tests/test_telegram_bot_service.py tests/test_publish_service.py` -> `67 passed`.
- Fresh `compileall`, `git diff --check`, and protected refs/docs checks passed.

Blocking evidence:

- Current `src/polysignal_lab/app/_settlement_check.py:189-205` only rejects missing or non-finite `quantity`, `entry_price`, `stake`, and `outcome`; it does not reject zero or negative money fields.
- Current `src/polysignal_lab/app/_settlement_check.py:207-260` then persists a normal `WIN`/`LOSS`/`VOID` result dict, including invalid zero/negative money fields.
- Fresh direct probe:
  - `settlement_missing_stake results=0 stored=0`
  - `settlement_zero_stake results=1 stored=1`, with `stake_usdc: 0.0`, `settlement_value: 25.0`, `pnl_usdc: 25.0`, `result: 'WIN'`
  - `settlement_negative_stake results=1 stored=1`, with `stake_usdc: -1.0`, `pnl_usdc: 26.0`, `roi: -26.0`, `result: 'WIN'`
  - `settlement_zero_quantity results=1 stored=1`, with `shares: 0.0`, `settlement_value: 0.0`, `result: 'WIN'`
- Current tests cover missing and non-finite money fields at `tests/test_scheduler_settlement_resolution.py:336-401`, but not zero or negative values.
- Direct `check-no-excuse-rules.py` over the scoped settlement/storage/paper-result/touched tests reported 27 violations in 5 files, including `silent-except`, `object` annotations, oversized modules, broad exception handling, and variant `if/elif` debt. This is not the only blocker, but it prevents using the programming/slop gates as final approval evidence.

### G004-G014 Duplicate Auto-Splits

Status: BLOCKED/SUPERSEDED is structurally legitimate, but cannot rescue overall completion.

Evidence:

- `goals.json` marks G004-G014 `blocked`.
- `ledger.jsonl` entries 28-38 accepted the same steering rationale for each: "Collapse invalid auto-generated URL/constraint fragments into completed concrete stories."
- Each G004-G014 entry states the placeholder is a duplicate auto-split already covered by G001/G002/G003 evidence.

Conclusion: the duplicate/superseded classification is reasonable. The overall ULW state still fails because the concrete G002/G003 paper settlement proof is not complete.

## blockers

1. HIGH: Live settlement still persists invalid zero/negative monetary payloads.
   - Source: `src/polysignal_lab/app/_settlement_check.py:189-205` does not require `quantity`, `entry_price`, or `stake` to be positive.
   - Source: `src/polysignal_lab/app/_settlement_check.py:207-260` persists resulting rows.
   - Fresh probe reproduced persisted zero/negative `WIN` rows.
   - This leaves `.omo/evidence/paper-code-review-rerun-6.md` unresolved for its "zero-or-invalid money fields" requirement.

2. HIGH: No current code-review artifact covers the latest post-security fix state.
   - `.omo/evidence/paper-code-review-rerun-6.md` is a stale FAIL report.
   - `.omo/ulw-loop/evidence/paper-post-security-fix-summary.txt` claims fixes and tests, but it is not a code review and has no `remove-ai-slops` / `programming` reviewer coverage for the current final diff.
   - Under the final-gate criteria, direct review does not replace required report coverage.

3. MEDIUM: Slop/programming gates cannot be cited as clean.
   - Direct no-excuse scan of the scoped files reported 27 violations in 5 files.
   - The focused tests are useful behavior tests, not pure tautologies, but they omit the adversarial zero/negative money classes now proven to persist.

## directSlopAndProgrammingPass

- `remove-ai-slops` direct pass: latest tests are not deletion-only or pure implementation mirrors for missing fields/malformed JSON; however they are over-narrow for the stale blocker because they test missing/non-finite money but not zero/negative money. The production code still normalizes invalid explicit monetary payloads into durable trade results.
- `programming` direct pass: current code is fail-closed for missing money and malformed JSON in the named surfaces, but not for zero/negative money at a settlement boundary. The scoped no-excuse scan also finds unresolved maintenance debt in touched source/tests.
- Code-review report coverage: absent for current post-security fix state. The only current named code review, `.omo/evidence/paper-code-review-rerun-6.md`, explicitly blocks.

## freshChecksRun

- `curl -fsS --max-time 5` for both session URLs succeeded:
  - `http://localhost:8082/api/v1/sessions/cursor:75ed7e5d-2fc1-4c44-a82c-2ccaa776d23d/md`
  - `http://localhost:8082/api/v1/sessions/omp:019f42fc-2a08-7000-9de6-3f3b86dc8562/md`
- Local session files also exist:
  - `/tmp/ulw-cursor-75ed7e5d.md`
  - `/tmp/ulw-omp-019f42fc.md`
- Focused pytest: `67 passed`, 2 external Nautilus deprecation warnings.
- Direct manual probe:
  - missing stake: PASS, no result/store call.
  - malformed `system_events`: PASS, `[]` / no open positions / `None`.
  - malformed `daily_reports`: PASS, `[]` / empty leaderboard.
  - same-id malformed existing payload: PASS, typed `MalformedSQLitePayloadError`.
  - zero/negative settlement money: FAIL, persisted normal result rows.
- `git diff --check`: PASS.
- `git status --short -- refs @refs docs/nautilus_reference`: no output.
- `git diff --name-only -- refs @refs docs/nautilus_reference`: no output.
- `compileall` on inspected production files: PASS.
- `check-no-excuse-rules.py` on scoped source/tests: FAIL, 27 violations.

## checkedArtifactPaths

- `.omo/ulw-loop/019f4394-c899-7b12-8f7d-8a7d91d2534a/brief.md`
- `.omo/ulw-loop/019f4394-c899-7b12-8f7d-8a7d91d2534a/goals.json`
- `.omo/ulw-loop/019f4394-c899-7b12-8f7d-8a7d91d2534a/ledger.jsonl`
- `/tmp/ulw-cursor-75ed7e5d.md`
- `/tmp/ulw-omp-019f42fc.md`
- `.omo/ulw-loop/evidence/scope-decision.txt`
- `.omo/ulw-loop/evidence/orderbook-from-polymarket-rg.txt`
- `.omo/ulw-loop/evidence/orderbook-focused-pytest.txt`
- `.omo/ulw-loop/evidence/orderbook-surface.txt`
- `.omo/ulw-loop/evidence/orderbook-regression.txt`
- `.omo/ulw-loop/evidence/orderbook-basedpyright.txt`
- `.omo/ulw-loop/evidence/paper-models-rg.txt`
- `.omo/ulw-loop/evidence/paper-schema-rg.txt`
- `.omo/ulw-loop/evidence/node-r10-rg.txt`
- `.omo/ulw-loop/evidence/paper-settlement-focused-pytest.txt`
- `.omo/ulw-loop/evidence/paper-full-pytest.txt`
- `.omo/ulw-loop/evidence/paper-post-security-fix-summary.txt`
- `.omo/ulw-loop/evidence/paper-post-security-fix-focused-pytest.txt`
- `.omo/ulw-loop/evidence/paper-post-security-fix-system-python-focused-pytest.txt`
- `.omo/ulw-loop/evidence/paper-post-security-fix-full-pytest.txt`
- `.omo/ulw-loop/evidence/paper-post-security-fix-basedpyright.txt`
- `.omo/ulw-loop/evidence/paper-post-security-fix-compileall.txt`
- `.omo/ulw-loop/evidence/paper-post-security-fix-diff-check.txt`
- `.omo/ulw-loop/evidence/paper-post-security-fix-refs-check.txt`
- `.omo/evidence/paper-goal-verification-rerun-6.md`
- `.omo/evidence/paper-code-review-rerun-6.md`
- `.omo/evidence/paper-security-rerun-7.md`
- `docs/architecture-nautilus-alignment.md`
- `src/polysignal_lab/domain/orderbook.py`
- `src/polysignal_lab/data/orderbook_payload.py`
- `src/polysignal_lab/app/_settlement_check.py`
- `src/polysignal_lab/storage/sqlite_store.py`
- `src/polysignal_lab/storage/sqlite_schema.py`
- `src/polysignal_lab/domain/paper_result.py`
- `tests/test_scheduler_settlement_resolution.py`
- `tests/test_storage_restore.py`

## exactEvidenceGaps

- Missing current code-review approval after `.omo/ulw-loop/evidence/paper-post-security-fix-summary.txt`.
- Missing adversarial tests for live settlement zero/negative `quantity`, `entry_price`, and `stake_usdc`.
- Current source does not reject zero/negative live monetary values before persisting paper trade results.
- Scoped programming/no-excuse scan is not clean, so the final proof bundle cannot claim clean programming/slop gates.

## finalRecommendation

REJECT / FAIL. G001 is complete and G004-G014 are legitimate duplicate auto-split blocks, but current G002/G003 paper completion is not approvable: invalid zero/negative live settlement monetary payloads still persist as normal paper trade results, and required current code-review coverage is missing.

<verdict>FAIL</verdict>
