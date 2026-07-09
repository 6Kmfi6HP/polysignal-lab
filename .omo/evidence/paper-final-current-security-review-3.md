# Paper Final Current Security Review 3

Verdict: CHANGES_REQUESTED
codeQualityStatus: BLOCK
recommendation: REQUEST_CHANGES
reportPath: .omo/evidence/paper-final-current-security-review-3.md
notepadPath: /tmp/ulw-20260709-135636.DzJpFe.md

## Scope

Reviewed `/home/debian/polysignal-lab` current source only. Source was not modified by this review.

Relevant files inspected:
- src/polysignal_lab/storage/sqlite_store.py
- src/polysignal_lab/paper/report_aggregates.py
- src/polysignal_lab/domain/paper_result.py
- src/polysignal_lab/domain/paper_report.py
- src/polysignal_lab/app/scheduler_reporting_sources.py
- src/polysignal_lab/paper/report.py
- src/polysignal_lab/paper/strategy_stats.py
- tests/test_storage_restore.py
- tests/test_paper_report_boundaries.py

Evidence artifacts inspected:
- .omo/evidence/paper-final-current-security-review-2.md
- .omo/ulw-loop/evidence/paper-final-security-probe.txt
- .omo/ulw-loop/evidence/paper-closed-position-state-red.txt
- .omo/ulw-loop/evidence/paper-closed-position-state-green.txt
- .omo/ulw-loop/evidence/paper-confidence-bad-red.txt
- .omo/ulw-loop/evidence/paper-confidence-bad-green.txt
- .omo/ulw-loop/evidence/paper-final-focused-pytest.txt
- .omo/ulw-loop/evidence/paper-final-full-pytest.txt
- .omo/ulw-loop/evidence/paper-final-no-excuse.txt

Protected subset check: `git status --short refs @refs docs/nautilus_reference` produced no output.

## Skill-Perspective Check

- `remove-ai-slops`: loaded and applied as a review lens. The new tests are not deletion-only tests, tautologies, or constant-mirroring tests. The confidence regression is helper-level rather than full daily-report integration, but the direct probe covered the report path. Remaining issues are not test slop; they are boundary failures.
- `programming`: loaded with the Python README and applied as a review lens. The current diff still violates the boundary/parse perspective: persisted JSON numeric fields can raise uncaught `OverflowError`, and contradictory position state is not parsed into one trustworthy state before restore.

## Verification

- Current focused run: `uv run pytest tests/test_storage_restore.py tests/test_paper_report_boundaries.py` -> 41 passed in 0.57s.
- Current full run: `uv run pytest` -> 716 passed, 2 warnings in 12.20s.
- Current scoped typecheck: `uv run basedpyright src/polysignal_lab/storage/sqlite_store.py src/polysignal_lab/paper/report_aggregates.py tests/test_storage_restore.py tests/test_paper_report_boundaries.py` -> 0 errors, 252 warnings.
- Current no-excuse rerun could not execute because `scripts/python/check-no-excuse-rules.py` is absent. Existing `.omo/ulw-loop/evidence/paper-final-no-excuse.txt` says `no violations in 18 file(s)`. Manual pure LOC check: `sqlite_store.py` 547, `report_aggregates.py` 100, `test_storage_restore.py` 837, `test_paper_report_boundaries.py` 192; the oversized source/test files have `SIZE_OK` comments.

Direct adversarial probe results:
- hostile wallet JSON with NaN/bool money: PASS, rejected.
- hostile daily/leaderboard JSON with NaN/Infinity/bool numerics: PASS, rejected.
- incomplete CLOSED position event: PASS, rejected.
- NaN/Infinity numeric helpers and execution metrics: PASS, skipped/defaulted safely.
- malformed terminal timestamp: PASS, skipped.
- valid JSON `details["confidence"] = "bad"`: PASS, bucketed low without raising.
- valid JSON huge integer numerics: FAIL, restore paths raise `OverflowError`.
- contradictory `status="OPEN"` + `is_closed=True`: FAIL, same position is restored as both open and closed.

## Requested Re-check Matrix

- Incomplete CLOSED position blocker: FIXED for the requested missing-field case. `_valid_position_event()` now requires trustworthy side, positive finite money fields, and a timestamp for closed rows at src/polysignal_lab/storage/sqlite_store.py:87-97. Covered by tests/test_storage_restore.py:830-856 and current probe.
- Nonnumeric confidence blocker: FIXED for `"bad"`. `confidence_bucket()` catches `TypeError`/`ValueError` and non-finite values at src/polysignal_lab/paper/report_aggregates.py:85-93. Covered by tests/test_paper_report_boundaries.py:177-178 and current probe through `PaperReportService.build_daily_report(...)`.
- Hostile wallet/daily/leaderboard NaN/Infinity JSON: FIXED for the sampled NaN/Infinity/bool cases through src/polysignal_lab/storage/sqlite_store.py:146-208 and restore filters at src/polysignal_lab/storage/sqlite_store.py:504-520 and 554-583.
- Malformed terminal timestamps: FIXED. `_paper_terminal_at()` catches `ValueError` and returns `None` at src/polysignal_lab/app/scheduler_reporting_sources.py:30-43.

## CRITICAL

None.

## HIGH

1. Valid JSON with very large integer numerics can crash restore paths instead of failing closed.

   Current source catches `TypeError`/`ValueError` around `float(...)` but not `OverflowError` in the persisted JSON numeric helpers. `_row_finite_float()` catches only `ValueError` at src/polysignal_lab/storage/sqlite_store.py:108-119. `_valid_money_value()` catches `TypeError`/`ValueError` but not `OverflowError` at src/polysignal_lab/storage/sqlite_store.py:146-154. `_valid_count_value()` also performs `float(parsed)` outside a guard at src/polysignal_lab/storage/sqlite_store.py:158-165. These helpers feed wallet restore, daily report restore/leaderboard, and position restore at src/polysignal_lab/storage/sqlite_store.py:168-208, 504-520, and 522-552.

   Current direct probe inserted valid JSON containing `10 ** 4000` and observed:
   - `wallet_overflow EXCEPTION OverflowError int too large to convert to float`
   - `daily_overflow EXCEPTION OverflowError int too large to convert to float`
   - `position_overflow EXCEPTION OverflowError int too large to convert to float`

   This leaves the hostile JSON boundary crashable even though the NaN/Infinity cases pass.

2. Contradictory position state can be restored as both open and closed.

   `_valid_position_event()` derives `is_open`/`is_closed` from `status` first but does not reject a conflicting `is_closed` flag when `status` is present at src/polysignal_lab/storage/sqlite_store.py:76-90. `restore_open_positions()` returns `status == OPEN` at src/polysignal_lab/storage/sqlite_store.py:536-543, while `restore_closed_positions()` returns any row with `row.get("is_closed") is True` at src/polysignal_lab/storage/sqlite_store.py:545-552, even when `status == OPEN`.

   Current direct probe inserted one valid-money event with `status="OPEN"` and `is_closed=True`; the result was:
   - `open_ids ['pos-conflict']`
   - `closed_ids ['pos-conflict']`

   A hostile or corrupted position event can therefore contaminate both restart state surfaces.

## MEDIUM

1. Scoped typecheck still reports many boundary looseness warnings.

   `basedpyright` returned 0 errors but 252 warnings on the scoped files, mostly `Any` and private/protected test access. This is not the approval blocker by itself, but it aligns with the remaining parse-boundary issues above.

## LOW

1. Oversized scoped files remain waived.

   `src/polysignal_lab/storage/sqlite_store.py` and `tests/test_storage_restore.py` exceed the 250 pure-LOC programming/remove-ai-slops threshold but carry `SIZE_OK` comments at line 1. This is accepted as a scoped waiver for this review, not a blocker.

## Blockers

- Make all persisted JSON numeric validators fail closed on `OverflowError` and other non-representable numeric values; cover wallet, daily/leaderboard, and position restore with focused adversarial tests.
- Reject contradictory position state, or make the `is_closed` fallback apply only when `status` is absent/empty, so one latest event cannot be restored as both open and closed.

Final Status: BLOCK
