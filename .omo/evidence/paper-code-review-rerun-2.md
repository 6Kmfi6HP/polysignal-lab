# Paper Blocker Fixes Code Review Rerun 2

codeQualityStatus: BLOCK
recommendation: REQUEST_CHANGES
reportPath: .omo/evidence/paper-code-review-rerun-2.md
blockers:
- `src/polysignal_lab/storage/sqlite_store.py:62` still lets incomplete OPEN position events through when money fields are present but required repair fields such as `opened_at` are missing, and `scripts/repair_settlement_results.py:180` then crashes before the narrowed persistence exception handler can count/skip the row.

notepadPath: /tmp/ulw-20260709-032625.xpmQ4t.md

## Scope Reviewed

- Current diff/source for:
  - `scripts/repair_settlement_results.py`
  - `src/polysignal_lab/storage/sqlite_store.py`
  - `src/polysignal_lab/domain/paper_result.py`
  - `src/polysignal_lab/app/scheduler_reporting.py`
  - `src/polysignal_lab/paper/report.py`
  - `src/polysignal_lab/app/services/publish_service.py`
  - `src/polysignal_lab/dashboard/app.py`
  - related tests in `tests/test_repair_settlement_results.py`, `tests/test_storage_restore.py`, `tests/test_reporting.py`, `tests/test_dashboard.py`, `tests/test_publish_service.py`, `tests/test_settlement.py`, and `tests/test_scheduler_settlement_resolution.py`.
- Explicit post-`.omo/evidence/paper-code-review-rerun.md` areas checked:
  - no-excuse cleanup/suppressions
  - `anyio.run`
  - typed backup/table errors
  - narrowed repair persistence exception handling
  - `_valid_position_event()` incomplete OPEN filtering
  - `_settle_for_repair()` missing money-field skip

## Skill-Perspective Check

- `remove-ai-slops` check ran by loading `/home/debian/.codex/plugins/cache/sisyphuslabs/omo/4.16.0/skills/remove-ai-slops/SKILL.md`.
- `programming` check ran by loading `/home/debian/.codex/plugins/cache/sisyphuslabs/omo/4.16.0/skills/programming/SKILL.md`, `references/python/README.md`, `references/python/error-handling.md`, and `references/python/async-anyio.md`.
- `ponytail` check ran by loading `/home/debian/.codex/plugins/cache/ponytail/ponytail/4.8.4/skills/ponytail/SKILL.md`.
- Result: the focused four-file no-excuse cleanup now passes, but the diff still violates the programming/remove-ai-slops perspective because a malformed persisted OPEN row is only partially validated at the restore boundary and can still crash repair. Full requested-scope checker output also shows remaining typed debt (`object`, `Any`, `asyncio`, oversized modules), listed below as MEDIUM/LOW where it is not the immediate blocker.

## Evidence Inspected

- `.omo/evidence/paper-code-review-rerun.md`: prior code review approved before the newest incomplete-position/security cleanup.
- `.omo/ulw-loop/evidence/paper-blockers-focused-pytest.txt`: `46 passed, 2 warnings`.
- `.omo/ulw-loop/evidence/paper-full-pytest.txt`: `661 passed, 2 warnings`.
- `.omo/ulw-loop/evidence/paper-blockers-basedpyright.txt`: `0 errors, 474 warnings, 0 notes`.
- `.omo/ulw-loop/evidence/paper-no-excuse-security-scope.txt`: `no violations in 4 file(s)`.
- `.omo/ulw-loop/evidence/paper-blockers-manual-qa.txt`: `repair_parse=pass`, `repair_incomplete_position=pass`, `cache_guard=pass`, `split_report=pass`, `malformed_persisted_rows=pass`.
- `.omo/ulw-loop/evidence/paper-diff-check.txt`: `diff_check=pass`.
- `.omo/ulw-loop/evidence/paper-refs-check.txt`: `refs_check=pass no refs/@refs/docs/nautilus_reference changed`.

## Verification Rerun

- `uv run /home/debian/.codex/plugins/cache/sisyphuslabs/omo/4.16.0/skills/programming/scripts/python/check-no-excuse-rules.py src/polysignal_lab/storage/sqlite_store.py scripts/repair_settlement_results.py tests/test_storage_restore.py tests/test_repair_settlement_results.py`: PASS, `no violations in 4 file(s)`.
- Same checker across the full requested review scope: FAIL, `91 violation(s) in 14 file(s)`, mainly `object` annotations, `src/polysignal_lab/app/services/publish_service.py:16` `asyncio`, and oversized modules.
- `uv run pytest -q tests/test_storage_restore.py tests/test_repair_settlement_results.py tests/test_publish_service.py::test_publish_paper_result_rejects_invalid_payload tests/test_dashboard.py::test_dashboard_excludes_invalid_nautilus_projection_rows tests/test_reporting.py::test_daily_report_counts_split_as_closed_without_win_loss_void`: PASS, 12 tests by dot count.
- `uv run basedpyright scripts/repair_settlement_results.py src/polysignal_lab/storage/sqlite_store.py tests/test_repair_settlement_results.py tests/test_storage_restore.py`: PASS on errors, `0 errors, 239 warnings, 0 notes`.
- `git diff --check -- <review scope>`: PASS, no output.
- `git diff --name-only -- refs @refs docs/nautilus_reference && git status --short -- refs @refs docs/nautilus_reference`: PASS, no output.

## CRITICAL

- None.

## HIGH

1. `src/polysignal_lab/storage/sqlite_store.py:62` and `scripts/repair_settlement_results.py:125`: incomplete OPEN rows can still reach repair and crash before the narrowed persistence error handling.

   `_valid_position_event()` now rejects OPEN rows missing finite `shares`/`quantity`, `entry_price`/`avg_entry_price`, or `stake_usdc` (`src/polysignal_lab/storage/sqlite_store.py:74-79`), which fixes the named money-field gap. But the repair path also requires `opened_at` and a valid `side`: `_settle_for_repair()` calls `_position_opened_at(position)` at `scripts/repair_settlement_results.py:238`, and `_position_opened_at()` calls `datetime.fromisoformat(str(raw).replace(...))` at `scripts/repair_settlement_results.py:130`. A persisted OPEN row with valid money fields but missing `opened_at` passes `_valid_position_event()` and raises `ValueError` before the `try/except` around `_store_paper_result()` at `scripts/repair_settlement_results.py:504-509`.

   Manual reproducer:

   ```text
   valid_position_event_missing_opened_at= True
   ValueError Invalid isoformat string: 'None'
   ```

   This is not just missing test coverage: it breaks the stated fail-closed repair behavior for malformed persisted paper state. The new `test_sqlite_store_excludes_incomplete_open_position_events` covers missing money fields only (`tests/test_storage_restore.py:264-283`), so it does not catch this remaining incomplete-row path.

## MEDIUM

1. Full requested-scope programming/no-excuse check is not clean.

   The focused four-file security scope passes after the suppressions, but running the same checker over the requested review files reports `91 violation(s) in 14 file(s)`. Most are broad typed debt already visible in basedpyright warnings, but some are in touched code paths: `src/polysignal_lab/app/services/publish_service.py:16` still imports `asyncio`, `src/polysignal_lab/dashboard/app.py:1` is now 409 pure LOC, and many helpers use `object` instead of a narrower row protocol. This does not supersede the HIGH functional blocker, but it means approval should not cite the focused four-file no-excuse artifact as proof that the whole reviewed diff satisfies the programming perspective.

2. The file-level `SIZE_OK` suppressions are acceptable only for the focused safety slice, not as broad cleanup proof.

   `scripts/repair_settlement_results.py:2`, `src/polysignal_lab/storage/sqlite_store.py:1`, and `tests/test_storage_restore.py:1` have reasoned `# noqa: SIZE_OK` suppressions and the checker accepts them in the four-file security scope. They should remain visible debt, not evidence that the oversized-module concern is solved across the paper/dashboard/reporting surface.

## LOW

1. `tests/test_reporting.py:118-123` still contains a tautological enum-value set assertion.

   It does not provide behavior coverage and matches the prior review's LOW finding. The adjacent `test_daily_report_counts_split_as_closed_without_win_loss_void` at `tests/test_reporting.py:126-145` is the real SPLIT behavior test, so this is not a blocker by itself.

2. `paper-blockers-focused-pytest.txt` and `paper-full-pytest.txt` store output summaries but not the exact command lines.

   I reran focused commands above, so this is only an evidence hygiene issue for future auditability.

## Post-Rerun Fix Assessment

- `anyio.run`: fixed in `scripts/repair_settlement_results.py:655-656`; `asyncio.run` was removed from that script.
- Typed backup/table errors: `MissingBackupError` exists at `scripts/repair_settlement_results.py:87-92` and is used at `scripts/repair_settlement_results.py:430` and `scripts/repair_settlement_results.py:554`; `UnknownSQLiteTableError` exists at `src/polysignal_lab/storage/sqlite_store.py:54-59` and is used at `src/polysignal_lab/storage/sqlite_store.py:148-149`.
- Narrowed repair persistence exception handling: improved at `scripts/repair_settlement_results.py:504-509`, but incomplete-row crashes before that block remain a HIGH issue.
- `_valid_position_event()` incomplete OPEN filtering: partially fixed for money fields at `src/polysignal_lab/storage/sqlite_store.py:74-79`, incomplete for `opened_at`/`side`.
- `_settle_for_repair()` missing money-field skip: fixed at `scripts/repair_settlement_results.py:185-189` with `_repair_float()` at `scripts/repair_settlement_results.py:248-255`.
- Behavior tests: the new money-field tests are behavioral, not deletion-only or tautological. Missing `opened_at`/invalid side coverage is absent.

## Final Verdict

REQUEST_CHANGES. The money-field blocker is fixed, but incomplete OPEN position filtering is still too narrow and can crash repair on malformed persisted rows that the restore boundary currently accepts.
