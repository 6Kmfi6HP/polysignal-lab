# Paper Code Review Rerun 14

## Verdict

- codeQualityStatus: BLOCK
- recommendation: REQUEST_CHANGES
- reportPath: `.omo/evidence/paper-code-review-rerun-14.md`
- PASS/FAIL: FAIL

## Scope Reviewed

- `src/polysignal_lab/domain/paper_result.py`
- `src/polysignal_lab/domain/paper_report.py`
- `src/polysignal_lab/domain/FOLDER_INDEX.md`
- `PROJECT_INDEX.md`
- `src/polysignal_lab/app/scheduler_reporting.py`
- `tests/test_nautilus_reporting_cache_source.py`
- `tests/test_storage_restore.py`
- Requested evidence under `.omo/ulw-loop/evidence/`

Additional adjacent inspection: `src/polysignal_lab/storage/sqlite_store.py`, because the requested gate was specifically after the storage timestamp fix.

## Skill-Perspective Check

Ran. I loaded and applied:

- `remove-ai-slops`: checked for oversized modules, deletion-only/tautological tests, implementation-mirroring tests, unnecessary parsing/normalization, and scope drift.
- `programming` plus Python reference: checked strict typing, no `object`/`Any` escape hatches, parse-at-boundary behavior, typed errors, and the 250 pure LOC ceiling.
- `ponytail`: checked for needless abstraction and over-engineering.

The diff violates the programming/remove-ai-slops perspective: `scheduler_reporting.py` remains oversized, and the custom trade-result parser no longer enforces all fields the replaced Pydantic model required.

## Findings

### CRITICAL

None.

### HIGH

1. `src/polysignal_lab/app/scheduler_reporting.py:1` remains an oversized production module at 456 pure LOC.

   The specific `paper_result.py` split cleared the previous `paper_result.py >250` blocker (`paper_result.py` is 151 pure LOC and `paper_report.py` is 144), but the reviewed production scope still contains a modified 456 pure LOC module with no `SIZE_OK` waiver. The loaded `programming` and `remove-ai-slops` criteria treat `>250` pure LOC as a defect requiring a split by responsibility. This means the size blocker is not fully cleared for the reviewed changed production surface.

2. `src/polysignal_lab/domain/paper_result.py:98` accepts malformed trade-result rows missing fields that the removed `PaperTradeResult` model required.

   `parse_paper_trade_result_row()` checks required fields at lines 100-112, but omits at least `exit_mode` and `market_slug` even though `PaperTradeResultRow` declares `exit_mode` at line 56 and `ExitMode` is imported at line 29. A live probe confirmed `parse_paper_trade_result_row()` accepts a row with `exit_mode` deleted and returns a row without `exit_mode`. The test named “missing fields required by the old model” only deletes `signal_id`, `side`, and `opened_at` in `tests/test_storage_restore.py:342`, so it does not catch this boundary regression.

### MEDIUM

1. Re-export compatibility works at runtime but is not clean for type-checking.

   `paper_result.py` imports `DailyReport` and `PaperWalletSnapshot` from `paper_report.py` at `src/polysignal_lab/domain/paper_result.py:17`, and runtime imports continue to work. However, basedpyright reports that `DailyReport` and `PaperWalletSnapshot` are “not exported from module `polysignal_lab.domain.paper_result`” at import sites such as `src/polysignal_lab/app/scheduler_reporting.py:31` and `tests/test_storage_restore.py:22`. If these names are meant to be compatibility re-exports, the export surface should be explicit enough that the checker agrees.

2. The requested files still carry strict-typing debt.

   The no-excuse checker reported 35 violations across the requested files, mostly `object` annotations in `scheduler_reporting.py` and `paper_report.py`. These are not all immediate behavior regressions, but they are contrary to the loaded `programming` perspective and explain the high basedpyright warning count.

### LOW

1. The workspace is heavily dirty and `src/polysignal_lab/domain/paper_report.py` is untracked.

   This does not by itself block the code-quality verdict, but it means the review is against working-tree state rather than a committed patch.

## Test and Evidence Review

Requested evidence inspected:

- `.omo/ulw-loop/evidence/paper-post-split-loc.txt`: reports `paper_result.py pure LOC: 151`, `paper_report.py pure LOC: 144`.
- `.omo/ulw-loop/evidence/paper-post-split-focused-pytest.txt`: 9 passed.
- `.omo/ulw-loop/evidence/paper-r10-protocol-callable-red.txt`: expected RED for non-callable cache protocol.
- `.omo/ulw-loop/evidence/paper-r10-protocol-callable-green.txt`: expected GREEN for the same.
- `.omo/ulw-loop/evidence/paper-storage-timestamp-red.txt`: expected RED for malformed timestamp.
- `.omo/ulw-loop/evidence/paper-storage-timestamp-green.txt`: expected GREEN for malformed timestamp.
- `.omo/ulw-loop/evidence/paper-storage-restore-pytest.txt`: 16 passed.
- `.omo/ulw-loop/evidence/paper-post-r10-focused-rerun.txt`: 57 passed.
- `.omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt`: full suite passed.
- `.omo/ulw-loop/evidence/paper-post-r10-basedpyright-rerun.txt`: 0 errors, 249 warnings.
- `.omo/ulw-loop/evidence/paper-post-r10-diff-check.txt`: `git diff --check` PASS.

Live verification rerun:

- `uv run pytest tests/test_nautilus_reporting_cache_source.py tests/test_storage_restore.py -q`: 24 passed.
- `uv run basedpyright src/polysignal_lab/domain/paper_result.py src/polysignal_lab/domain/paper_report.py src/polysignal_lab/app/scheduler_reporting.py tests/test_nautilus_reporting_cache_source.py tests/test_storage_restore.py`: 0 errors, 138 warnings.
- `git diff --check`: passed.
- Pure LOC check: `paper_result.py` 151, `paper_report.py` 144, `scheduler_reporting.py` 456, `test_nautilus_reporting_cache_source.py` 131, `test_storage_restore.py` 511 with `# noqa: SIZE_OK`.

## Test Relevance / Slop Review

- The RED/GREEN tests for callable Nautilus cache protocol are relevant and not deletion-only.
- The malformed timestamp RED/GREEN tests are relevant and protect the storage timestamp fix.
- The storage restore tests are mostly behavioral, but the “missing fields required by the old model” test is underfit: it does not cover `exit_mode` or `market_slug`, so it gives false confidence about parser parity.
- I did not find deletion-only tests or tests that merely assert a requested removal.

## Blockers

1. Split or explicitly justify `src/polysignal_lab/app/scheduler_reporting.py` so the reviewed production scope no longer contains an unwaived 456 pure LOC module.
2. Restore parser parity for required trade-result fields, at minimum validating `exit_mode` and `market_slug`, and add a behavioral test that fails when those fields are missing or invalid.
3. If compatibility re-exports are intentional, make them explicit enough that basedpyright no longer reports `DailyReport`/`PaperWalletSnapshot` as non-exported from `paper_result.py`; otherwise update import sites to use `paper_report.py`.

## Final Status

FAIL. The split cleared the specific `paper_result.py` size count, and the focused/full evidence is green, but code-quality blockers remain.
