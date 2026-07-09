# Paper Final Current Security Review 2

Verdict: CHANGES_REQUESTED
codeQualityStatus: BLOCK
recommendation: REQUEST_CHANGES
reportPath: .omo/evidence/paper-final-current-security-review-2.md
notepadPath: /tmp/ulw-20260709-133718.yAqIPi.md

## Scope

Reviewed current working tree only. Source was not modified by this review.

Requested files:
- src/polysignal_lab/storage/sqlite_store.py
- src/polysignal_lab/domain/paper_result.py
- src/polysignal_lab/domain/paper_report.py
- src/polysignal_lab/paper/report_aggregates.py
- src/polysignal_lab/app/scheduler_reporting_sources.py
- tests/test_storage_restore.py
- tests/test_paper_report_boundaries.py

Current scoped diff/status:
- Modified tracked files: src/polysignal_lab/domain/paper_result.py, src/polysignal_lab/storage/sqlite_store.py, tests/test_storage_restore.py.
- Untracked scoped files: src/polysignal_lab/domain/paper_report.py, src/polysignal_lab/paper/report_aggregates.py, src/polysignal_lab/app/scheduler_reporting_sources.py, tests/test_paper_report_boundaries.py.
- Protected subset check: `git status --short refs @refs docs/nautilus_reference` produced no output.

## Skill-Perspective Check

- `remove-ai-slops`: loaded and applied. The added tests are mostly adversarial behavior tests, not deletion-only tests or tautologies. Two gaps remain: no incomplete CLOSED-position restore test, and the confidence test only covers bool while nonnumeric valid JSON still crashes reporting.
- `programming`: loaded with Python README plus data-modeling/error-handling references. The diff violates this perspective in two places: a storage boundary still passes unparsed incomplete CLOSED rows through, and reporting uses an unguarded `float(...)` on untrusted `details["confidence"]`.
- `ponytail`: loaded and applied. The boundary parsing is not speculative, but the remaining issue should be fixed at the shared helpers rather than per caller.

## Verification

- Existing evidence inspected:
  - .omo/evidence/paper-final-current-security-review.md
  - .omo/ulw-loop/evidence/paper-final-focused-pytest.txt
  - .omo/ulw-loop/evidence/paper-final-full-pytest.txt
  - .omo/ulw-loop/evidence/paper-final-no-excuse.txt
  - .omo/ulw-loop/evidence/paper-final-debug-audit.md
- Current focused run: `uv run pytest tests/test_storage_restore.py tests/test_paper_report_boundaries.py` -> 39 passed in 0.59s.
- Current full run: `uv run pytest` -> 715 passed, 2 warnings in 12.03s.
- Current scoped typecheck: `uv run basedpyright <scoped files>` -> 0 errors, 386 warnings.
- Direct adversarial probe:
  - valid JSON hostile wallet payload rejected: PASS
  - valid JSON hostile daily report payload rejected: PASS
  - valid JSON hostile strategy leaderboard rejected: PASS
  - NaN/Infinity report helpers and execution metrics default/skip safely: PASS
  - malformed terminal timestamp skipped: PASS
  - incomplete CLOSED position rejected: FAIL; restore returned the row
  - nonnumeric confidence in trade details: FAIL; `PaperReportService.build_daily_report(...)` raised `ValueError`

## Requested Re-check Matrix

- Valid JSON hostile wallet snapshot payloads: PASS. `restore_latest_wallet_snapshot()` rejects non-dict or semantically invalid payloads at src/polysignal_lab/storage/sqlite_store.py:500, with bool/non-finite money rejected by src/polysignal_lab/storage/sqlite_store.py:142 and wallet payload validation at src/polysignal_lab/storage/sqlite_store.py:164. Covered by tests/test_storage_restore.py:718.
- Valid JSON hostile daily report/leaderboard payloads: PASS. `query_json("daily_reports")` skips invalid payloads at src/polysignal_lab/storage/sqlite_store.py:481 and src/polysignal_lab/storage/sqlite_store.py:490; `restore_strategy_leaderboard()` is downstream of `restore_daily_reports()` at src/polysignal_lab/storage/sqlite_store.py:557. Covered by tests/test_storage_restore.py:752.
- NaN/Infinity report numeric helpers/execution metrics: PASS for the requested helpers/metrics. `wallet_float()` rejects bool and non-finite values at src/polysignal_lab/domain/paper_report.py:79; `report_float()` delegates to it at src/polysignal_lab/domain/paper_report.py:95; execution metrics use `optional_float()` from src/polysignal_lab/paper/report_aggregates.py:71 at src/polysignal_lab/paper/report.py:159 and src/polysignal_lab/paper/report.py:162. Covered by tests/test_paper_report_boundaries.py:177 and tests/test_paper_report_boundaries.py:184.
- Malformed terminal timestamps: PASS. `_paper_terminal_at()` catches `ValueError` and returns None at src/polysignal_lab/app/scheduler_reporting_sources.py:30; report collection skips None at src/polysignal_lab/app/scheduler_reporting_sources.py:248. Covered by tests/test_paper_report_boundaries.py:228.

## CRITICAL

None.

## HIGH

1. `restore_closed_positions()` still accepts incomplete CLOSED position events as restored state.

   `_valid_position_event()` only requires side, positive money fields, and a timestamp when `is_open` is true at src/polysignal_lab/storage/sqlite_store.py:81. For CLOSED rows, missing `shares`, `entry_price`, `stake_usdc`, `side`, `opened_at`, and `closed_at` are all allowed because the later loop only rejects fields that are present and invalid at src/polysignal_lab/storage/sqlite_store.py:94. `restore_closed_positions()` then returns any latest row with `status == CLOSED` or `is_closed is True` at src/polysignal_lab/storage/sqlite_store.py:541.

   Current direct probe inserted a valid JSON `nautilus_position` event with only `paper_position_id`, metadata, `status="CLOSED"`, and `is_closed=True`; `restore_closed_positions()` returned that incomplete row. Existing tests cover incomplete OPEN rows at tests/test_storage_restore.py:566 and CLOSED rows with zero money when fields are present at tests/test_storage_restore.py:622, but they do not cover CLOSED rows with required fields absent.

2. Hostile valid JSON `details["confidence"]` can crash daily report generation.

   `calibration_breakdown()` passes `trade_result_details(result).get("confidence")` directly into `confidence_bucket()` at src/polysignal_lab/paper/report_aggregates.py:24. `confidence_bucket()` then calls `float(confidence or 0.0)` before any `ValueError` guard at src/polysignal_lab/paper/report_aggregates.py:85. `PaperReportService.build_daily_report()` always builds calibration breakdowns for closed results at src/polysignal_lab/paper/report.py:123, so a persisted trade result with valid JSON `{"details": {"confidence": "bad"}}` raises `ValueError`.

   Current direct probe confirmed the crash: `ValueError: could not convert string to float: 'bad'`. The test added at tests/test_paper_report_boundaries.py:173 only covers boolean confidence and gives false confidence for this broader hostile JSON boundary.

## MEDIUM

1. Scoped basedpyright is green on errors but not clean on the programming perspective.

   The scoped command returned 0 errors and 386 warnings. The most relevant warnings are untyped boundary surfaces and unnecessary casts in src/polysignal_lab/app/scheduler_reporting_sources.py:13, src/polysignal_lab/app/scheduler_reporting_sources.py:36, and src/polysignal_lab/app/scheduler_reporting_sources.py:193. This is not the approval blocker by itself, but it confirms the current boundary split is still type-loose.

## LOW

1. Oversized files remain deliberately waived.

   src/polysignal_lab/storage/sqlite_store.py is 543 pure LOC and tests/test_storage_restore.py is 813 pure LOC. Both carry `SIZE_OK` comments at src/polysignal_lab/storage/sqlite_store.py:1 and tests/test_storage_restore.py:1. This is accepted as a scoped-waiver risk, not a blocker for this review.

## Blockers

- Tighten `_valid_position_event()` or the closed-position restore path so CLOSED / `is_closed=True` rows require trustworthy side, positive finite money fields, and valid timestamp state before `restore_closed_positions()` can return them.
- Add an adversarial storage restore test for an incomplete CLOSED position event with required fields absent.
- Make `confidence_bucket()` or its caller fail closed for nonnumeric `details["confidence"]` values and add a focused test using a valid JSON hostile string value.

Final Status: BLOCK
