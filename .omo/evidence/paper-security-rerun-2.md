recommendation: REJECT
verdict: FAIL
severity: HIGH

# Paper Security Rerun 2

## originalIntent
Run a read-only focused security rerun in `/home/debian/polysignal-lab` after the incomplete-position repair fix. The user-visible deliverable is this evidence report, with PASS only if no high/critical blocker remains for the two previous HIGH findings from `.omo/evidence/paper-security-rerun.md`: incomplete persisted open position events reaching repair, and `_settle_for_repair` fabricating `0.0` money/share fields. Also confirm the prior parser/publish/dashboard/refs findings remain green.

## desiredOutcome
The shipped artifact should prove, from current code and executable evidence, that malformed/incomplete persisted paper state cannot be converted into settlement/report/publish/dashboard output, the repair path fails closed instead of fabricating money/share values, protected refs/reference docs remain untouched, and required gate/slop coverage is current enough to support approval.

## userOutcomeReview
The two focused security blockers from `.omo/evidence/paper-security-rerun.md` are resolved in the current code and current reruns:

- `SQLiteStore.restore_open_positions()` now routes position events through `_valid_position_event()`, which rejects open rows missing finite share, entry price, or stake fields before they can reach repair.
- `_settle_for_repair()` now returns `None` when `entry_price`, `shares`, or `stake_usdc` is missing/empty/non-numeric instead of defaulting those fields to `0.0`.
- Parser/publish/dashboard/refs checks are still green by current focused pytest, full pytest, artifact inspection, and refs checks.

Overall gate verdict is still FAIL/REJECT because the required programming/slop gate is not clean on the scoped touched files, and the explicit code-review artifact with `programming`/`remove-ai-slops` coverage predates the latest incomplete-position repair evidence.

## checkedArtifactPaths
- `.omo/evidence/paper-security-rerun.md`
- `.omo/evidence/paper-code-review-rerun.md`
- `.omo/evidence/paper-code-review.md`
- `.omo/evidence/paper-qa-rerun.md`
- `.omo/evidence/paper-context-rerun-2.md`
- `.omo/evidence/paper-goal-verification-rerun.md`
- `.omo/ulw-loop/evidence/paper-blockers-focused-pytest.txt`
- `.omo/ulw-loop/evidence/paper-full-pytest.txt`
- `.omo/ulw-loop/evidence/paper-blockers-manual-qa.txt`
- `.omo/ulw-loop/evidence/paper-diff-check.txt`
- `.omo/ulw-loop/evidence/paper-refs-check.txt`
- `src/polysignal_lab/storage/sqlite_store.py`
- `scripts/repair_settlement_results.py`
- `tests/test_storage_restore.py`
- `tests/test_repair_settlement_results.py`
- `/tmp/ulw-20260709-030150.oKHIvl.md`
- `/home/debian/.codex/plugins/cache/sisyphuslabs/omo/4.16.0/skills/remove-ai-slops/SKILL.md`
- `/home/debian/.codex/plugins/cache/sisyphuslabs/omo/4.16.0/skills/programming/SKILL.md`
- `/home/debian/.codex/plugins/cache/sisyphuslabs/omo/4.16.0/skills/programming/references/python/README.md`

## blockers
1. HIGH: Required programming/no-excuse gate fails on the scoped touched files.
   - Command: `uv run /home/debian/.codex/plugins/cache/sisyphuslabs/omo/4.16.0/skills/programming/scripts/python/check-no-excuse-rules.py src/polysignal_lab/storage/sqlite_store.py scripts/repair_settlement_results.py tests/test_storage_restore.py tests/test_repair_settlement_results.py`
   - Result: exit 1, `11 violation(s) in 4 file(s)`.
   - Representative findings: `scripts/repair_settlement_results.py` imports `asyncio`, has mutable dataclass `AuditReport`, uses `raise ValueError(...)`, contains an `if/elif` variant chain, is 593 pure LOC, and has broad `except Exception`; `src/polysignal_lab/storage/sqlite_store.py` is 421 pure LOC and uses generic `ValueError`; `tests/test_storage_restore.py` is 292 pure LOC.
   - Why this blocks approval: the final gate requires applying `programming` criteria and rejecting unresolved slop that creates maintenance burden in the scoped repair/storage surface.

2. HIGH: Current code-review report coverage is stale for the latest incomplete-position security fix.
   - `.omo/evidence/paper-code-review-rerun.md` has an explicit `Skill-Perspective Check` for `remove-ai-slops` and `programming`, but file timestamp is `2026-07-09 02:51:58 +0200`.
   - The previous security rerun FAIL artifact is newer: `.omo/evidence/paper-security-rerun.md` timestamp `2026-07-09 02:53:11 +0200`.
   - The current incomplete-position proof artifacts are newer still: `.omo/ulw-loop/evidence/paper-blockers-focused-pytest.txt` timestamp `2026-07-09 02:57:54 +0200`, and `.omo/ulw-loop/evidence/paper-blockers-manual-qa.txt` timestamp `2026-07-09 02:58:42 +0200`.
   - Why this blocks approval: the existing code-review approval does not explicitly cover the latest incomplete-position repair evidence; direct review supports the focused security behavior, but report coverage is not current enough for a final approve.

## resolvedFocusedSecurityFindings
- Incomplete persisted open position events no longer reach repair through the storage restore path.
  - `src/polysignal_lab/storage/sqlite_store.py:53-78`: `_valid_position_event()` rejects open rows missing finite `shares`/`quantity`/`signed_qty`, `entry_price`/`avg_entry_price`, or `stake_usdc`.
  - `src/polysignal_lab/storage/sqlite_store.py:381-404`: `restore_open_positions()` consumes only `_latest_position_events()` rows, and `_latest_position_events()` skips invalid position events.
  - `tests/test_storage_restore.py:263-282`: `test_sqlite_store_excludes_incomplete_open_position_events` inserts an incomplete open event and asserts both restore paths return `[]`.

- `_settle_for_repair()` no longer fabricates missing money/share fields as `0.0`.
  - `scripts/repair_settlement_results.py:174-178`: missing `entry_price`, `shares`, or `stake_usdc` returns `None`.
  - `scripts/repair_settlement_results.py:236-243`: `_repair_float()` returns `None` for missing/empty/non-numeric values.
  - `scripts/repair_settlement_results.py:466-471`: repair rows with `result is None` are skipped, not persisted.
  - `tests/test_repair_settlement_results.py:75-104`: `test_settle_for_repair_rejects_incomplete_position_money_fields` asserts the incomplete position returns `None`.

- Prior parser/publish/dashboard/refs findings remain green.
  - `tests/test_publish_service.py::test_publish_paper_result_rejects_invalid_payload`, `tests/test_dashboard.py::test_dashboard_excludes_invalid_nautilus_projection_rows`, `tests/test_storage_restore.py::test_sqlite_store_rejects_invalid_paper_trade_rows`, and `tests/test_storage_restore.py::test_sqlite_store_rejects_incomplete_paper_trade_rows` passed in the current rerun.
  - `git diff --name-only -- refs @refs docs/nautilus_reference` returned no output.
  - `git status --short -- refs @refs docs/nautilus_reference` returned no output.

## executableEvidence
- `uv run pytest -q tests/test_storage_restore.py tests/test_repair_settlement_results.py`: exit 0, `9` tests passed by dot count.
- `uv run pytest -q tests/test_publish_service.py::test_publish_paper_result_rejects_invalid_payload tests/test_dashboard.py::test_dashboard_excludes_invalid_nautilus_projection_rows tests/test_storage_restore.py::test_sqlite_store_rejects_invalid_paper_trade_rows tests/test_storage_restore.py::test_sqlite_store_rejects_incomplete_paper_trade_rows`: exit 0, `4` tests passed.
- `uv run pytest -q`: exit 0, full suite passed with warnings only; stored `.omo/ulw-loop/evidence/paper-full-pytest.txt` shows `661 passed, 2 warnings`.
- Manual driver: `PYTHONPATH=tests uv run python - <<'PY' ... PY` printed `security_manual=pass incomplete_position_filtered=true settle_missing_money_fields=None`.
- `git diff --check`: exit 0, no output.
- `uv run basedpyright src/polysignal_lab/storage/sqlite_store.py scripts/repair_settlement_results.py tests/test_storage_restore.py tests/test_repair_settlement_results.py`: exit 0, `0 errors, 237 warnings, 0 notes`.
- `paper-blockers-focused-pytest.txt`: `46 passed, 2 warnings`.
- `paper-blockers-manual-qa.txt`: includes `repair_incomplete_position=pass` and `malformed_persisted_rows=pass`.
- `paper-diff-check.txt`: `diff_check=pass`.
- `paper-refs-check.txt`: `refs_check=pass no refs/@refs/docs/nautilus_reference changed`.

## slopAndProgrammingReview
- Direct `remove-ai-slops` pass: the focused tests are behavioral and would fail if the old security blockers returned. They are not deletion-only, tautological, or mere assertions that a requested removal happened.
- Direct `remove-ai-slops` pass: `_valid_position_event()` is the shared restore boundary and `_repair_float()` has three real call sites in `_settle_for_repair`; no unnecessary production extraction was found for the two focused security fixes.
- Direct `programming` pass: strict checker fails with 11 violations across the scoped files. These are not evidence that the two focused security behaviors are broken, but they are unresolved maintenance-burden findings under the final gate.
- Report coverage check: `.omo/evidence/paper-code-review-rerun.md` explicitly includes `programming` and `remove-ai-slops` perspectives, but it is older than the latest incomplete-position repair evidence and does not explicitly cover the newest security rerun state.

## exactEvidenceGaps
- No current post-fix code-review artifact explicitly covers the latest incomplete-position repair evidence after `.omo/evidence/paper-security-rerun.md` failed.
- No passing strict `programming`/no-excuse evidence exists for the scoped touched files.
- `basedpyright` is clean on errors but still reports 237 warnings on the scoped files.
- Stored `.omo/ulw-loop/evidence/paper-blockers-focused-pytest.txt` and `.omo/ulw-loop/evidence/paper-full-pytest.txt` do not include the exact original command line; this rerun supplied current command evidence above.

## finalVerdict
FAIL / REJECT. The two named HIGH security blockers are fixed by current source and runtime evidence, but final approval is blocked by unresolved strict programming/slop gate failures and stale code-review coverage for the latest incomplete-position repair.
