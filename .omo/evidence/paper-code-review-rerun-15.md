# Paper Code Review Rerun 15

## Verdict

- codeQualityStatus: BLOCK
- recommendation: REQUEST_CHANGES
- reportPath: `.omo/evidence/paper-code-review-rerun-15.md`
- PASS/FAIL: FAIL

## Scope Reviewed

- `src/polysignal_lab/app/scheduler_reporting.py`
- `src/polysignal_lab/app/scheduler_reporting_types.py`
- `src/polysignal_lab/app/scheduler_reporting_sources.py`
- `src/polysignal_lab/app/scheduler_reporting_equity.py`
- `src/polysignal_lab/app/scheduler_reporting_build.py`
- `src/polysignal_lab/domain/paper_result.py`
- `src/polysignal_lab/domain/paper_report.py`
- `tests/test_nautilus_reporting_cache_source.py`
- `tests/test_storage_restore.py`
- `src/polysignal_lab/app/FOLDER_INDEX.md`
- `src/polysignal_lab/domain/FOLDER_INDEX.md`
- `PROJECT_INDEX.md`
- Requested evidence under `.omo/ulw-loop/evidence/`

Adjacent path inspected for parser impact: `src/polysignal_lab/storage/sqlite_store.py`, because `query_json("paper_trade_results")` and `insert_paper_trade_result()` route through `parse_paper_trade_result_row()`.

## Skill-Perspective Check

Ran. I loaded and applied:

- `remove-ai-slops`: checked oversized modules, deletion-only or tautological tests, implementation-mirroring tests, unnecessary production parsing/normalization, and scope drift.
- `programming` plus Python and code-smells references: checked strict typing, parse-at-boundary behavior, typed errors, no untyped escape hatches, and the 250 pure LOC ceiling.
- `ponytail`: checked for needless abstraction and avoidable hand-rolled complexity.

The diff still violates the `remove-ai-slops` and `programming` perspectives: the replacement trade-result parser is hand-rolled production parsing and still does not preserve the old typed model boundary. The scheduler LOC and compatibility export blockers are fixed.

## Findings

### CRITICAL

None.

### HIGH

1. `src/polysignal_lab/domain/paper_result.py:119` still accepts malformed trade-result rows that the removed `PaperTradeResult` Pydantic model rejected.

   Current `parse_paper_trade_result_row()` requires `exit_mode` presence at lines 121-134 but never validates it against `ExitMode`, even though `ExitMode` is imported at line 29. It also omits `market_slug` from the required field list while `PaperTradeResultRow` declares it at line 72 and the old model required it. Live probe result:

   ```text
   market_slug ACCEPTED None
   exit_mode ACCEPTED BROKEN
   ```

   This is still a parser-parity regression at the storage boundary. `SQLiteStore.query_json("paper_trade_results")` trusts this parser at `src/polysignal_lab/storage/sqlite_store.py:400`, so persisted malformed settlement rows can still pass restore/query surfaces as valid.

### MEDIUM

1. `tests/test_storage_restore.py:379` covers only missing `exit_mode`, not invalid `exit_mode` or missing `market_slug`.

   The added test is useful and not tautological, but it is underfit relative to the parser boundary it is supposed to protect. It would pass while the parser accepts `exit_mode="BROKEN"` and rows with no `market_slug`, which is exactly the remaining defect above.

2. The scheduler split clears the hard size blocker but leaves strict-typing debt and private cross-module imports.

   Live basedpyright returned `0 errors, 142 warnings`. The relevant warnings include private sibling imports in `src/polysignal_lab/app/scheduler_reporting.py:14-17` and `src/polysignal_lab/app/scheduler_reporting_build.py:14-20`, plus `Any`/unknown-type warnings in the reporting and paper report modules. This is not a HIGH blocker by itself because the requested commands have zero type errors, but it remains maintainability debt under the loaded `programming` perspective.

3. `tests/test_storage_restore.py:1` is 535 pure LOC with a `SIZE_OK` waiver.

   The tests are mostly behavioral and relevant, so I am not treating this as a blocker. Still, the file now spans several behavior clusters: trade-result row parsing, malformed JSON, position restore filtering, daily report restore, leaderboard restore, and SQLite pragmas. The waiver should not become a default place to append every storage regression.

### LOW

1. `src/polysignal_lab/app/FOLDER_INDEX.md:16` and `src/polysignal_lab/app/FOLDER_INDEX.md:18` list `readonly_smoke.py` twice.

   This is index hygiene only and does not affect the code-quality verdict for the requested blocker fixes.

## Prior Blocker Verification

- `scheduler_reporting.py >250 pure LOC`: fixed. Live LOC check: `scheduler_reporting.py` 33, `scheduler_reporting_types.py` 57, `scheduler_reporting_sources.py` 236, `scheduler_reporting_equity.py` 81, `scheduler_reporting_build.py` 94.
- missing `exit_mode` accepted: fixed for the missing-field case. Live focused test passed: `uv run pytest tests/test_storage_restore.py::test_sqlite_store_rejects_paper_trade_rows_missing_exit_mode -q`.
- compatibility re-exports not exported: fixed at runtime and typecheck no longer reports non-exported `DailyReport`/`PaperWalletSnapshot`. Live import probe printed `DailyReport PaperWalletSnapshot`.

## Test and Evidence Review

Requested evidence inspected:

- `.omo/ulw-loop/evidence/paper-post-scheduler-split-loc.txt`: reports split production files below 250 pure LOC.
- `.omo/ulw-loop/evidence/paper-storage-exit-mode-red.txt`: shows the missing-exit-mode test failed before the fix.
- `.omo/ulw-loop/evidence/paper-storage-exit-mode-green.txt`: shows the missing-exit-mode test passed after the fix.
- `.omo/ulw-loop/evidence/paper-post-scheduler-split-focused-pytest.txt`: 10 passed.
- `.omo/ulw-loop/evidence/paper-post-scheduler-split-basedpyright.txt`: 0 errors, 142 warnings.
- `.omo/ulw-loop/evidence/paper-post-r10-focused-rerun.txt`: 58 passed.
- `.omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt`: full suite passed.
- `.omo/ulw-loop/evidence/paper-post-r10-diff-check.txt`: `git diff --check` passed.

Live verification run:

- `uv run pytest tests/test_nautilus_reporting_cache_source.py tests/test_storage_restore.py -q`: 25 passed.
- `uv run basedpyright src/polysignal_lab/app/scheduler_reporting.py src/polysignal_lab/app/scheduler_reporting_types.py src/polysignal_lab/app/scheduler_reporting_sources.py src/polysignal_lab/app/scheduler_reporting_equity.py src/polysignal_lab/app/scheduler_reporting_build.py src/polysignal_lab/domain/paper_result.py src/polysignal_lab/domain/paper_report.py tests/test_nautilus_reporting_cache_source.py tests/test_storage_restore.py`: 0 errors, 142 warnings.
- `git diff --check`: passed.
- Live parser probe: invalid `exit_mode` and missing `market_slug` were accepted.

## Test Relevance / Slop Review

- The scheduler reporting cache tests are behavioral and relevant; I did not find deletion-only or tautological assertions there.
- The missing-`exit_mode` RED/GREEN test is relevant but underfit.
- The custom parser is the remaining slop risk: it is production parsing replacing a typed Pydantic boundary and has already drifted from the old model contract.
- I did not find tests that merely verify a requested deletion.

## Blockers

1. Restore trade-result parser parity for `exit_mode` and `market_slug`: reject invalid `exit_mode` values and reject rows missing `market_slug`, or route through a typed model that enforces the same contract.
2. Add behavioral tests that fail when `exit_mode` is invalid and when `market_slug` is missing.

## Final Status

FAIL. The scheduler split, missing-`exit_mode` case, and compatibility re-exports are fixed, but a HIGH parser-boundary blocker remains.
