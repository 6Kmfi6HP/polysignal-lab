recommendation: REJECT
verdict: FAIL
severity: HIGH

# Paper Security Rerun 3

## originalIntent
Run a focused read-only security/safety rerun in `/home/debian/polysignal-lab` after the latest fixes. Approval requires current source, diff, tests, manual QA, no-excuse output, refs checks, and code-review coverage to prove no high/critical blocker remains for malformed/incomplete persisted paper state becoming settlement/report/publish/dashboard output, repair-path `0.0` fabrication, SQL/destructive scope, secrets, and protected refs/reference docs.

## desiredOutcome
The user-visible outcome should be a current evidence artifact with `recommendation: APPROVE` only if malformed/incomplete persisted paper rows fail closed across settlement/report/publish/dashboard surfaces, the repair path does not fabricate missing money/share fields, destructive SQL is bounded, no secrets are introduced, `refs`/`@refs`/`docs/nautilus_reference` are untouched, and the required `programming` + `remove-ai-slops` coverage is current and supported.

## userOutcomeReview
Reject. The latest storage/repair no-excuse blocker is fixed, and repair missing-money `0.0` fabrication appears resolved. However, a high dashboard blocker remains: an incomplete persisted `nautilus_position` system event missing `entry_price`, `shares`, and `stake_usdc` is filtered out of `SQLiteStore.restore_open_positions()` but still appears in `/api/positions`.

This means malformed/incomplete persisted paper state can still become dashboard output. Existing focused tests pass because they cover unknown status and `NaN`, not the missing-money-field class that previously blocked approval.

## blockers
1. HIGH: Incomplete persisted paper position events still become dashboard output.
   - Source: `src/polysignal_lab/dashboard/app.py:293-301` validates present numeric fields but explicitly skips missing `entry_price`, `shares`, and `stake_usdc`.
   - Source: `src/polysignal_lab/dashboard/app.py:447-467` reads raw `system_events` and applies `_valid_position_payload()`, not the stricter `SQLiteStore.restore_open_positions()` / `_valid_position_event()` boundary.
   - Manual proof:
     - Command inserted a persisted `event_type='nautilus_position'` row with `status='OPEN'`, `is_closed=False`, `paper_position_id`, `market_id`, and `token_id`, but no money/share fields.
     - Output: `restore_open_positions= []`
     - Output: `dashboard_status= 200`
     - Output: `/api/positions` returned `pos-incomplete-dashboard`.
   - Existing tests are overfit for this class: `tests/test_dashboard.py::test_dashboard_excludes_invalid_nautilus_projection_rows` covers `status='BROKEN'` plus `shares='NaN'`, but not missing numeric fields.

2. Approval evidence gap: no fresh code-review artifact covers the latest security-scoped evidence.
   - Existing `.omo/evidence/paper-code-review-rerun.md` timestamp: `2026-07-09 02:51:58 +0200`.
   - Latest requested security evidence timestamps are newer: rerun-2 at `03:12`, no-excuse/focused pytest at `03:18`, manual QA at `03:20`.
   - `.omo/evidence/paper-code-review-rerun-2.md` is absent, and `find .omo/evidence -name 'paper*review*'` showed no newer paper code-review artifact.
   - The old code review also did not list `src/polysignal_lab/dashboard/app.py` or the latest storage/dashboard incomplete-row class in scope.

## resolvedOrNonBlocking
- Repair missing-money fabrication: `scripts/repair_settlement_results.py:185-189` returns `None` when `entry_price`, `shares`, or `stake_usdc` is missing, and `tests/test_repair_settlement_results.py::test_settle_for_repair_rejects_incomplete_position_money_fields` passes.
- Storage restore path: `src/polysignal_lab/storage/sqlite_store.py:62-87` rejects incomplete open position events, and `tests/test_storage_restore.py::test_sqlite_store_excludes_incomplete_open_position_events` passes.
- Trade result parser/publish path: `parse_paper_trade_result_row()` rejects missing/unknown/non-finite/negative required fields, `SQLiteStore.query_json("paper_trade_results")` filters invalid persisted result rows, and `PublishService.publish_paper_result()` parses before sending.
- No-excuse scope: direct rerun of `uv run /home/debian/.codex/plugins/cache/sisyphuslabs/omo/4.16.0/skills/programming/scripts/python/check-no-excuse-rules.py src/polysignal_lab/storage/sqlite_store.py scripts/repair_settlement_results.py tests/test_storage_restore.py tests/test_repair_settlement_results.py` returned `no violations in 4 file(s)`.
- Basedpyright artifact: `0 errors, 474 warnings, 0 notes`; warnings are treated as non-blocking unless they create actual high/critical risk.
- SQL/destructive scope: scan found parameterized `DELETE FROM daily_reports WHERE report_id = ?` and expected market upsert only. No unbounded destructive SQL found in scoped files.
- Secrets: hardcoded secret assignment scan found no matches.
- Protected refs/docs: `git diff --name-only -- refs @refs docs/nautilus_reference` and `git status --short -- refs @refs docs/nautilus_reference` returned no output.

## slopAndProgrammingReview
- `programming`: the previously failing scoped no-excuse gate now passes. Remaining basedpyright warnings are not approval blockers by themselves under this task's warning policy.
- `remove-ai-slops`: direct overfit/slop pass rejects the current dashboard coverage as incomplete. It verifies one malformed-row shape but misses the missing-field shape that the user's security criterion names.
- Production slop check: `_valid_position_event()` is correctly placed for restore/repair, but dashboard duplicates a weaker validator instead of reusing the same fail-closed boundary. This creates false confidence and maintenance risk in a user-facing output surface.
- Code-review report coverage: the existing report includes `programming` and `remove-ai-slops` headings, but it is stale and unsupported for the latest dashboard/security evidence.

## checkedArtifactPaths
- `.omo/evidence/paper-security-rerun-2.md`
- `.omo/evidence/paper-security-rerun.md`
- `.omo/evidence/paper-security-review.md`
- `.omo/evidence/paper-code-review-rerun.md`
- `.omo/evidence/paper-code-review.md`
- `.omo/ulw-loop/evidence/paper-blockers-focused-pytest.txt`
- `.omo/ulw-loop/evidence/paper-full-pytest.txt`
- `.omo/ulw-loop/evidence/paper-blockers-basedpyright.txt`
- `.omo/ulw-loop/evidence/paper-no-excuse-security-scope.txt`
- `.omo/ulw-loop/evidence/paper-blockers-manual-qa.txt`
- `.omo/ulw-loop/evidence/paper-diff-check.txt`
- `.omo/ulw-loop/evidence/paper-refs-check.txt`
- `src/polysignal_lab/storage/sqlite_store.py`
- `scripts/repair_settlement_results.py`
- `src/polysignal_lab/domain/paper_result.py`
- `src/polysignal_lab/app/_settlement_check.py`
- `src/polysignal_lab/app/scheduler_reporting.py`
- `src/polysignal_lab/app/services/publish_service.py`
- `src/polysignal_lab/dashboard/app.py`
- `tests/test_storage_restore.py`
- `tests/test_repair_settlement_results.py`
- `tests/test_dashboard.py`
- `tests/test_publish_service.py`
- `/home/debian/.codex/plugins/cache/sisyphuslabs/omo/4.16.0/skills/remove-ai-slops/SKILL.md`
- `/home/debian/.codex/plugins/cache/sisyphuslabs/omo/4.16.0/skills/programming/SKILL.md`
- `/home/debian/.codex/plugins/cache/sisyphuslabs/omo/4.16.0/skills/programming/references/python/README.md`
- `/tmp/ulw-20260709-032631.soOVyo.md`

## executableEvidence
- `uv run pytest -q tests/test_dashboard.py::test_dashboard_excludes_invalid_nautilus_projection_rows tests/test_storage_restore.py::test_sqlite_store_excludes_incomplete_open_position_events tests/test_repair_settlement_results.py::test_settle_for_repair_rejects_incomplete_position_money_fields tests/test_publish_service.py::test_publish_paper_result_rejects_invalid_payload` -> `4 passed`.
- Manual dashboard reproducer -> storage restore excluded the incomplete row, but `/api/positions` returned it.
- `git diff --check` -> exit 0, no output.
- `paper-blockers-focused-pytest.txt` -> `46 passed, 2 warnings`.
- `paper-full-pytest.txt` -> `661 passed, 2 warnings`.
- `paper-no-excuse-security-scope.txt` and direct rerun -> `no violations in 4 file(s)`.
- `paper-blockers-manual-qa.txt` -> `repair_incomplete_position=pass`, `malformed_persisted_rows=pass`.
- `paper-diff-check.txt` -> `diff_check=pass`.
- `paper-refs-check.txt` -> `refs_check=pass no refs/@refs/docs/nautilus_reference changed`.

## exactEvidenceGaps
- No current code-review artifact explicitly covers the latest no-excuse/focused/manual evidence after rerun-2.
- No test or manual QA artifact covers incomplete persisted `nautilus_position` dashboard rows missing `entry_price`, `shares`, and `stake_usdc`.
- `paper-no-excuse-security-scope.txt` covers four scoped files only; it does not cover `src/polysignal_lab/dashboard/app.py`, where the remaining high blocker lives.

## finalVerdict
FAIL / REJECT. High paper safety blockers are not gone.
