# Paper Safety Closure Code Review Rerun 3

<verdict>FAIL</verdict>

codeQualityStatus: BLOCK
recommendation: REQUEST_CHANGES
reportPath: /home/debian/polysignal-lab/.omo/evidence/paper-code-review-rerun-3.md
confidence: high

blocking_issues:
- `src/polysignal_lab/storage/sqlite_store.py:62-88`, `scripts/repair_settlement_results.py:141-204`, and `src/polysignal_lab/dashboard/app.py:235-307` still accept/fabricate a missing OPEN position `side` as `UP`, so incomplete OPEN rows can still be restored, repaired, and displayed with invented trade direction.

## Scope Reviewed

- Current git status/diff for the paper safety closure, with focused inspection of:
  - `src/polysignal_lab/storage/sqlite_store.py`
  - `tests/test_storage_restore.py`
  - `scripts/repair_settlement_results.py`
  - `src/polysignal_lab/dashboard/app.py`
  - `src/polysignal_lab/domain/paper_result.py`
  - `src/polysignal_lab/nautilus_runtime/projections.py`
  - related tests and evidence artifacts.
- Specific functions assessed: `_valid_position_event`, `_row_timestamp`, `_latest_position_events`, and the new direct SQL test.

## Skill-Perspective Check

- `remove-ai-slops` check ran by loading `/home/debian/.codex/plugins/cache/sisyphuslabs/omo/4.16.0/skills/remove-ai-slops/SKILL.md`.
- `programming` check ran by loading `/home/debian/.codex/plugins/cache/sisyphuslabs/omo/4.16.0/skills/programming/SKILL.md` and `references/python/README.md`.
- Result: the new direct SQL timestamp test is relevant and not tautological, but the diff still violates both perspectives because production code keeps a hidden data-fabrication default (`side` -> `UP`) at restore/repair/dashboard boundaries and tests do not cover it.

## Evidence Checked

- Inspected artifacts:
  - `.omo/ulw-loop/evidence/paper-blockers-focused-pytest.txt`: `49 passed, 2 warnings`.
  - `.omo/ulw-loop/evidence/paper-full-pytest.txt`: `664 passed, 2 warnings`.
  - `.omo/ulw-loop/evidence/paper-blockers-basedpyright.txt`: `0 errors, 575 warnings, 0 notes`.
  - `.omo/ulw-loop/evidence/paper-no-excuse-security-scope.txt`: `no violations in 6 file(s)`.
  - `.omo/ulw-loop/evidence/paper-blockers-manual-qa.txt`: includes `storage_missing_timestamp=pass`.
- Reran focused checks:
  - `git diff --check -- src/polysignal_lab/storage/sqlite_store.py tests/test_storage_restore.py scripts/repair_settlement_results.py src/polysignal_lab/dashboard/app.py`: PASS.
  - `uv run .../check-no-excuse-rules.py src/polysignal_lab/storage/sqlite_store.py tests/test_storage_restore.py scripts/repair_settlement_results.py src/polysignal_lab/dashboard/app.py tests/test_repair_settlement_results.py tests/test_dashboard.py`: PASS, `no violations in 6 file(s)`.
  - `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider tests/test_storage_restore.py::test_sqlite_store_excludes_open_position_events_without_timestamp tests/test_storage_restore.py::test_sqlite_store_excludes_incomplete_open_position_events tests/test_dashboard.py::test_dashboard_excludes_incomplete_open_position_rows tests/test_repair_settlement_results.py::test_settle_for_repair_uses_event_timestamp_when_opened_at_missing`: PASS, `4 passed`.
- Manual probe:
  - An OPEN `nautilus_position` row with id, money fields, and timestamp but no `side` is returned by `SQLiteStore.restore_open_positions()`.

## CRITICAL

None.

## HIGH

1. `src/polysignal_lab/storage/sqlite_store.py:62-88`, `scripts/repair_settlement_results.py:141-204`, `src/polysignal_lab/dashboard/app.py:235-307`: incomplete OPEN rows missing trade direction still pass through and are defaulted to `UP`.

   `_valid_position_event()` now correctly requires finite money fields and `_row_timestamp()` for OPEN rows, but it never requires a valid `side` or a market/token-derived equivalent. The repair script then calls `_position_side()`, which uses `position.get("side", Side.UP.value)` and proceeds with `Side.UP` when the field is absent. The dashboard has the same fabrication path: `_resolve_side()` returns `UP` as a final fallback, and `_valid_position_payload()` does not validate the side at all.

   This leaves the prior incomplete-OPEN-row class only partially closed. A missing/invalid direction is no longer a crash, but it is worse for data correctness: it can persist or display a synthetic `UP` trade result for a `DOWN` token.

   Required fix before approval: fail closed on missing/invalid side, or derive side from a verified market/token mapping. Do not default unknown direction to `UP` in restore/repair/dashboard safety paths. Add a regression test with a timestamped, money-complete OPEN row missing `side` that proves the row is excluded or safely derived.

## MEDIUM

1. `src/polysignal_lab/storage/sqlite_store.py:406-420`: `_latest_position_events()` filters invalid rows before choosing the latest event per position.

   If a valid OPEN event is followed by a malformed OPEN event for the same position, the malformed latest event is skipped and the older valid event remains restorable. For a fail-closed restore boundary, the latest raw event should determine current state; an invalid latest event should not resurrect stale state without an explicit policy.

   Required follow-up: choose the latest raw event per position first, then validate that latest payload, or document and test the "latest valid snapshot wins" policy.

## LOW

1. `tests/test_storage_restore.py:286-317`: the new direct SQL timestamp test is the right shape for persisted-corruption coverage, but it is too narrow to close the whole incomplete OPEN class.

   It proves missing payload timestamps are excluded, even when the DB `created_at` column exists. It does not cover missing/invalid `side`, nor an invalid latest row after an earlier valid row.

## Positive Findings

- `_row_timestamp()` is small, scoped, and does not normalize malformed timestamps into defaults.
- The direct SQL test is not deletion-only or tautological; it exercises an adversarial persisted row that the public insert API would not create.
- Focused pytest, no-excuse, diff-check, and inspected full-suite artifacts are green.

## Final Verdict

FAIL. The timestamp blocker is fixed, but the paper safety closure still allows incomplete OPEN position rows through by fabricating missing side as `UP`.
