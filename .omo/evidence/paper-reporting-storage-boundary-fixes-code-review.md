# Paper Reporting/Storage Boundary Code Review

Verdict: FAIL
codeQualityStatus: BLOCK
recommendation: REQUEST_CHANGES
reportPath: `.omo/evidence/paper-reporting-storage-boundary-fixes-code-review.md`

## Scope And Evidence

Reviewed current working tree under `/home/debian/polysignal-lab` for the paper reporting/storage boundary fixes. No product files were edited.

Evidence inspected:

- `.omo/ulw-loop/evidence/paper-bool-money-red.txt`: red tests reproduced boolean trade money and restored-position money failures.
- `.omo/ulw-loop/evidence/paper-bool-money-green.txt`: green focused rerun passed.
- `.omo/ulw-loop/evidence/paper-report-boundaries-red.txt`: red tests reproduced boolean depth averaging and non-string reject reason crash.
- `.omo/ulw-loop/evidence/paper-report-boundaries-green.txt`: green focused rerun passed.
- `.omo/ulw-loop/evidence/paper-final-focused-pytest.txt`: focused suite artifact passed.
- `.omo/ulw-loop/evidence/paper-final-full-pytest.txt`: full suite artifact reached 100%.
- `.omo/ulw-loop/evidence/paper-final-basedpyright.txt`: `0 errors, 443 warnings, 0 notes`.
- `.omo/ulw-loop/evidence/paper-final-refs-check.txt`: `PASS no protected refs/docs/nautilus_reference changes`.

Independent commands run:

```text
PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider -q \
  tests/test_storage_restore.py::test_sqlite_store_rejects_boolean_money_paper_trade_rows \
  tests/test_storage_restore.py::test_sqlite_store_excludes_open_position_events_with_boolean_money \
  tests/test_storage_restore.py::test_sqlite_store_rejects_zero_money_paper_trade_rows \
  tests/test_storage_restore.py::test_sqlite_store_excludes_open_position_events_with_zero_money \
  tests/test_storage_restore.py::test_sqlite_store_skips_malformed_payload_paper_trade_rows \
  tests/test_storage_restore.py::test_sqlite_store_skips_malformed_system_events \
  tests/test_storage_restore.py::test_sqlite_store_skips_malformed_daily_reports \
  tests/test_paper_report_boundaries.py \
  tests/test_reporting.py::test_daily_report_normalizes_legacy_raw_paper_reject_reason \
  tests/test_reporting.py::test_daily_report_counts_cancelled_rejects_with_reasons
=> 11 passed

PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider -q
=> full suite passed, 2 third-party deprecation warnings

PYTHONDONTWRITEBYTECODE=1 uv run basedpyright \
  src/polysignal_lab/domain/paper_result.py \
  src/polysignal_lab/storage/sqlite_store.py \
  src/polysignal_lab/paper/report.py \
  src/polysignal_lab/paper/report_aggregates.py \
  src/polysignal_lab/paper/report_rejections.py \
  tests/test_paper_report_boundaries.py \
  tests/test_storage_restore.py
=> 0 errors, 290 warnings, 0 notes

git diff --check
=> exit 0

git status --short -- refs @refs docs/nautilus_reference
git diff --name-only -- refs @refs docs/nautilus_reference
=> no output
```

Skill-perspective check: ran. I loaded and applied `omo:remove-ai-slops` and `omo:programming` before judging test relevance and maintainability. The tests are not deletion-only, tautological, or implementation-mirroring for the covered scenarios. The diff still has boundary coverage gaps and one small scope-drift issue noted below. Programming strictness remains weak in the changed area (`Any`/raw dict warnings), but the blocking problems below are concrete data-integrity failures, not style-only warnings.

## CRITICAL

None.

## HIGH

1. Closed restored positions with zero money still pass restore filtering.

   The zero-money guard in [`src/polysignal_lab/storage/sqlite_store.py:99`](/home/debian/polysignal-lab/src/polysignal_lab/storage/sqlite_store.py:99) only rejects zero when `is_open` is true:

   ```python
   if parsed is None or parsed < 0.0 or (is_open and parsed == 0.0):
       return False
   ```

   That means `restore_closed_positions()` accepts CLOSED position events where `shares`, `entry_price`, or `stake_usdc` is `0.0`. These are still restored paper-position money fields and should fail closed under the stated zero/boolean money boundary requirement.

   Exact probe:

   ```text
   inserted three nautilus_position events with status=CLOSED, is_closed=True,
   and one of shares/entry_price/stake_usdc set to 0.0

   store.restore_open_positions() => []
   len(store.restore_closed_positions()) => 3
   ids => ['pos-closed-zero-shares', 'pos-closed-zero-entry_price', 'pos-closed-zero-stake_usdc']
   ```

   Existing tests only cover OPEN zero/boolean position events in [`tests/test_storage_restore.py:588`](/home/debian/polysignal-lab/tests/test_storage_restore.py:588) and [`tests/test_storage_restore.py:622`](/home/debian/polysignal-lab/tests/test_storage_restore.py:622), so this path is not locked.

2. Malformed JSON still crashes wallet snapshot restore.

   `query_json()` now skips malformed JSON for `paper_trade_results`, `system_events`, and `daily_reports` at [`src/polysignal_lab/storage/sqlite_store.py:407`](/home/debian/polysignal-lab/src/polysignal_lab/storage/sqlite_store.py:407), but `restore_latest_wallet_snapshot()` still calls `json.loads()` directly at [`src/polysignal_lab/storage/sqlite_store.py:438`](/home/debian/polysignal-lab/src/polysignal_lab/storage/sqlite_store.py:438).

   Exact probe:

   ```text
   inserted paper_wallet_snapshots row with payload_json='{not-json'
   store.restore_latest_wallet_snapshot()
   => JSONDecodeError: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)
   ```

   This is still a paper storage/reporting restore boundary. `telegram_bot.py` consumes this restore path via `wallet = self.persistence.restore_latest_wallet_snapshot() or {}` at [`src/polysignal_lab/publish/telegram_bot.py:621`](/home/debian/polysignal-lab/src/polysignal_lab/publish/telegram_bot.py:621), so a corrupt wallet row can still crash a reporting surface instead of failing closed.

## MEDIUM

1. Unrelated unknown-table exception semantics changed without coverage.

   `_build_query()` changed from `ValueError` to a new `UnknownSQLiteTableError` at [`src/polysignal_lab/storage/sqlite_store.py:65`](/home/debian/polysignal-lab/src/polysignal_lab/storage/sqlite_store.py:65) and [`src/polysignal_lab/storage/sqlite_store.py:186`](/home/debian/polysignal-lab/src/polysignal_lab/storage/sqlite_store.py:186). I found no tests or callers that require this change. It is not part of the listed paper money/reject/malformed JSON blockers and is minor scope drift.

## LOW

1. Type strictness remains weak in changed boundary code.

   Focused `basedpyright` reports `0 errors` but many warnings, including `Any` and unknown dict plumbing in changed files. This is not the blocker here because the current boundary has to parse JSON payloads, but it does violate the strict programming perspective and should not expand further.

## Protected Paths

Protected path status is clear:

```text
git status --short -- refs @refs docs/nautilus_reference
git diff --name-only -- refs @refs docs/nautilus_reference
=> no output
```

## Slop/Test Review

The new/changed tests are behavior-shaped for the covered cases:

- Boolean trade money insert and persisted-row query fail closed.
- Zero trade money insert and persisted-row query fail closed.
- Boolean/zero OPEN position restore fail closed.
- Malformed JSON for trade results, system events, and daily reports is skipped.
- Boolean `paper_available_depth_usdc` is ignored.
- Non-string reject reasons do not crash and normalize to `PAPER_FILL_REJECTED`.
- Existing reject mappings and cancelled-with-reason semantics are preserved.

No deletion-only tests, tautologies, prompt-string tests, or constants-only mirror tests found in the reviewed boundary tests. The problem is missing adversarial coverage for CLOSED zero-money position restore and wallet snapshot malformed JSON.

## Blockers

- Reject zero `shares`, `entry_price`, and `stake_usdc` for all restored position events where those fields are present, not only open positions.
- Make `restore_latest_wallet_snapshot()` fail closed on malformed `payload_json`, with focused regression coverage.

Final recommendation: REQUEST_CHANGES.
