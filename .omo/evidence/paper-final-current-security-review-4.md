verdict: CHANGES_REQUESTED
codeQualityStatus: BLOCK
recommendation: REQUEST_CHANGES
reportPath: .omo/evidence/paper-final-current-security-review-4.md
notepadPath: /tmp/ulw-20260709-141440.etbxAb.md

# Paper Final Current Security Review 4

## Scope

Reviewed the current `/home/debian/polysignal-lab` working tree read-only, except for this report artifact. The checkout is broadly dirty, so I treated previous reports and green evidence as untrusted and checked current source directly.

Scoped files inspected included the requested paper domain/reporting modules, scheduler reporting split, SQLite schema/store, and focused tests.

## Skill-Perspective Check

- `remove-ai-slops`: loaded and applied to production and tests. The focused tests are not deletion-only tests, tautologies, or constant-mirroring tests, but they miss a hostile numeric class that the current production helpers still crash on. That is false confidence at a security boundary.
- `programming`: loaded with the Python reference and applied. The diff still violates the parse-don't-validate / boundary-fail-closed perspective because several untrusted numeric conversion helpers call `float(...)` without catching `OverflowError`.
- `ponytail`: loaded as an over-engineering lens. The added boundary parsing is not speculative; the blocker should be fixed once in the shared numeric helpers, not with per-call guards.

## Verification

- Current focused pytest: `PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_paper_report_boundaries.py tests/test_storage_restore.py tests/test_nautilus_reporting_cache_source.py tests/test_reporting.py tests/test_strategy_stats.py -q` -> `58 passed`.
- Existing evidence inspected:
  - `.omo/ulw-loop/evidence/paper-wallet-overflow-green.txt`
  - `.omo/ulw-loop/evidence/paper-position-conflict-green.txt`
  - `.omo/ulw-loop/evidence/paper-confidence-bad-green.txt`
  - `.omo/ulw-loop/evidence/paper-closed-position-state-green.txt`
  - `.omo/ulw-loop/evidence/paper-final-security-probe.txt`
  - `.omo/ulw-loop/evidence/paper-final-focused-pytest.txt`
  - `.omo/ulw-loop/evidence/paper-final-full-pytest.txt`
  - `.omo/ulw-loop/evidence/paper-final-no-excuse.txt`
  - `.omo/ulw-loop/evidence/paper-final-basedpyright.txt`
  - `.omo/ulw-loop/evidence/paper-final-diff-check.txt`
  - `.omo/ulw-loop/evidence/paper-final-refs-check.txt`
- Direct adversarial probe against current source: `10**4000` numeric payloads raised `OverflowError` through `wallet_float`, `report_float`, `optional_float`, `confidence_bucket`, `PaperReportService.build_daily_report(...)`, and `SQLiteStore.query_json("paper_trade_results")`.

## Stale Blocker Disposition

- Incomplete `CLOSED` position restore is fixed for the stale case: `_valid_position_event()` now requires closed rows to have trustworthy side, positive money fields, and a timestamp at `src/polysignal_lab/storage/sqlite_store.py:91-100`; coverage exists at `tests/test_storage_restore.py:864-890`.
- Contradictory position state is fixed for the stale case: `OPEN + is_closed=True` and `CLOSED + is_closed=False` are rejected at `src/polysignal_lab/storage/sqlite_store.py:81-84`; coverage exists at `tests/test_storage_restore.py:893-917`.
- Nonnumeric string confidence is fixed for the stale case: `confidence_bucket()` catches `TypeError`/`ValueError` at `src/polysignal_lab/paper/report_aggregates.py:85-91`; coverage exists at `tests/test_paper_report_boundaries.py:177-178`.
- Oversized wallet count is fixed for the stale gate-review-4 case: `_valid_count_value()` bounds ints directly and parses decimal strings without a float round-trip at `src/polysignal_lab/storage/sqlite_store.py:162-178`; coverage exists at `tests/test_storage_restore.py:752-783`.

## CRITICAL

None.

## HIGH

1. Valid JSON huge integers still crash paper/report restore and reporting paths instead of failing closed.

   The prior wallet-count overflow fix was scoped to `_valid_count_value()`, but the same hostile persisted numeric class still reaches other shared helpers. `wallet_float()` calls `float(value)` for `int`/`float` inputs and catches only `ValueError` for strings at `src/polysignal_lab/domain/paper_report.py:79-91`. `trade_result_float()` has the same gap at `src/polysignal_lab/domain/paper_result.py:107-119`, and `_finite_float()` catches only `ValueError` while parsing persisted paper trade result money at `src/polysignal_lab/domain/paper_result.py:190-210`.

   The report aggregation helpers also miss the same exception: `optional_float()` catches `TypeError`/`ValueError` only at `src/polysignal_lab/paper/report_aggregates.py:71-78`, and `confidence_bucket()` catches `TypeError`/`ValueError` only at `src/polysignal_lab/paper/report_aggregates.py:85-93`. These are used by daily report construction for trade PnL/ROI, execution metrics, and calibration at `src/polysignal_lab/paper/report.py:68-71`, `src/polysignal_lab/paper/report.py:123`, and `src/polysignal_lab/paper/report.py:159-190`.

   Current direct probe results:
   - `wallet_float_huge EXCEPTION OverflowError int too large to convert to float`
   - `report_float_huge EXCEPTION OverflowError int too large to convert to float`
   - `optional_float_huge EXCEPTION OverflowError int too large to convert to float`
   - `confidence_bucket_huge EXCEPTION OverflowError int too large to convert to float`
   - `daily_report_huge_trade EXCEPTION OverflowError int too large to convert to float`
   - `query_trade_results_huge EXCEPTION OverflowError int too large to convert to float`

   This is a current security/reliability blocker because a valid JSON persisted row can crash restore/report generation rather than being rejected or defaulted. `SQLiteStore.query_json("paper_trade_results")` currently catches `json.JSONDecodeError` and `InvalidPaperTradeResultRow` only at `src/polysignal_lab/storage/sqlite_store.py:489-496`, so an `OverflowError` escapes the restore boundary.

## MEDIUM

None.

## LOW

1. The focused green tests do not exercise huge integer numerics on the shared report/trade helpers.

   Existing coverage handles booleans, non-finite strings, malformed timestamps, incomplete positions, and oversized wallet counts at `tests/test_paper_report_boundaries.py:166-214` and `tests/test_storage_restore.py:752-917`. It does not cover `10**4000` or equivalent valid JSON integers for `trade_result_float`, `_finite_float`, `optional_float`, `confidence_bucket`, or `wallet_float`, which is why the focused suite passed while the direct probe crashed.

## Final Assessment

The previous stale blockers listed in the prompt are no longer final truth, and several are genuinely fixed in the current source. Approval is still not supportable because the same persisted-payload overflow class remains active on adjacent paper reporting boundaries.

blockers: [
  "Catch or avoid OverflowError in the shared numeric boundary helpers (`wallet_float`/`report_float`, `trade_result_float`/`_finite_float`, `optional_float`, and `confidence_bucket`) so huge valid JSON integers fail closed or default consistently.",
  "Ensure `SQLiteStore.query_json(\"paper_trade_results\")` cannot leak `OverflowError` from hostile persisted trade-result payloads.",
  "Add focused adversarial coverage for huge integer numerics across persisted paper trade rows and report aggregation/accessor helpers."
]
