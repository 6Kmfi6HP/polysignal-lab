<verdict>FAIL</verdict>
severity: HIGH
codeQualityStatus: BLOCK
recommendation: REQUEST_CHANGES
reportPath: /home/debian/polysignal-lab/.omo/evidence/paper-security-rerun-4.md

# Paper Security Rerun 4

## Scope
Read-only security review of the latest paper safety closure in `/home/debian/polysignal-lab`.

Focused files inspected:
- `src/polysignal_lab/storage/sqlite_store.py`
- `src/polysignal_lab/dashboard/app.py`
- `scripts/repair_settlement_results.py`
- `src/polysignal_lab/domain/paper_result.py`
- `tests/test_dashboard.py`
- `tests/test_storage_restore.py`
- `tests/test_repair_settlement_results.py`

Evidence inspected:
- `.omo/ulw-loop/evidence/paper-blockers-manual-qa.txt`
- `.omo/ulw-loop/evidence/paper-no-excuse-security-scope.txt`
- `.omo/ulw-loop/evidence/paper-full-pytest.txt`
- `.omo/ulw-loop/evidence/paper-blockers-focused-pytest.txt`
- `.omo/ulw-loop/evidence/paper-diff-check.txt`
- `.omo/ulw-loop/evidence/paper-refs-check.txt`
- `.omo/ulw-loop/evidence/paper-blockers-basedpyright.txt`

## Findings By Severity

### CRITICAL
None.

### HIGH
1. Malformed persisted OPEN position rows with an invalid `opened_at` can still pass storage restore, appear in `/api/positions`, and then be silently skipped by repair.
   - `src/polysignal_lab/storage/sqlite_store.py:74-80` accepts an OPEN position when any of `opened_at`, `ts`, or `created_at` parses. `src/polysignal_lab/storage/sqlite_store.py:106-117` continues after an invalid earlier timestamp, so a row with `opened_at="not-a-date"` and valid `created_at` is treated as valid.
   - `scripts/repair_settlement_results.py:125-135` chooses `opened_at or ts or created_at`; when `opened_at` is present but malformed, it returns `None` without trying the valid fallback timestamp.
   - `scripts/repair_settlement_results.py:459-468` consumes `restore_open_positions()` and silently skips rows where `_position_in_range()` returns `False`, so this malformed row reaches the repair path but cannot be repaired.
   - `src/polysignal_lab/dashboard/app.py:294-307` only checks that `opened_at` is non-empty, not parseable. `src/polysignal_lab/dashboard/app.py:449-470` returns such rows from `/api/positions`.
   - Manual proof: an in-memory `nautilus_position` row with `status=OPEN`, finite `entry_price`/`shares`/`stake_usdc`, `opened_at="not-a-date"`, and valid `created_at` produced `restore_open_positions=[...]`, `/api/positions` returned the row, while repair `_position_opened_at=None` and `_position_in_range=False`.

### MEDIUM
None.

### LOW
None security-blocking. Skill-perspective note: `programming` and `remove-ai-slops` checks ran. A direct no-excuse rerun over the user-scoped files also reported non-security `paper_result.py` type/size violations, while the supplied no-excuse artifact reports `no violations in 6 file(s)`. This is not the security blocker; the HIGH timestamp fail-open path above is.

## blocking_issues
- HIGH: Align storage, dashboard, and repair timestamp parsing so an invalid primary payload timestamp cannot pass storage/dashboard while becoming un-settleable in repair. Add a regression for `opened_at="not-a-date"` with a valid `created_at` fallback or reject that row consistently.

## Verification
- Focused pytest rerun: `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider tests/test_dashboard.py::test_dashboard_excludes_incomplete_open_position_rows tests/test_storage_restore.py::test_sqlite_store_excludes_open_position_events_without_timestamp tests/test_storage_restore.py::test_sqlite_store_excludes_incomplete_open_position_events tests/test_repair_settlement_results.py::test_settle_for_repair_rejects_incomplete_position_money_fields tests/test_storage_restore.py::test_sqlite_store_rejects_invalid_paper_trade_rows tests/test_storage_restore.py::test_sqlite_store_rejects_incomplete_paper_trade_rows` -> `6 passed`.
- Supplied full pytest artifact: `.omo/ulw-loop/evidence/paper-full-pytest.txt` -> `664 passed, 2 warnings`.
- Supplied manual QA artifact: `.omo/ulw-loop/evidence/paper-blockers-manual-qa.txt` includes `dashboard_incomplete_positions=pass` and `storage_missing_timestamp=pass`, but it does not cover invalid primary timestamp with valid fallback timestamp.
- Protected refs check artifact: `.omo/ulw-loop/evidence/paper-refs-check.txt` -> no `refs`, `@refs`, or `docs/nautilus_reference` changes.
