# Paper Safety Code Review Rerun 4

<verdict>FAIL</verdict>

codeQualityStatus: BLOCK
recommendation: REQUEST_CHANGES
reportPath: /home/debian/polysignal-lab/.omo/evidence/paper-code-review-rerun-4.md
confidence: high

blocking_issues:
- `src/polysignal_lab/app/_settlement_check.py:177-239` and `src/polysignal_lab/app/_settlement_check.py:245-255` still allow a live settlement projection with no trustworthy side and no parseable opened timestamp to become a persisted paper result. The helper returns `Side.UP` as the final fallback and uses `closed_at` as `opened_at` when no timestamp parses.

## Scope Reviewed

- Directly inspected current diff and source for:
  - `src/polysignal_lab/storage/sqlite_store.py`
  - `scripts/repair_settlement_results.py`
  - `src/polysignal_lab/dashboard/app.py`
  - `tests/test_storage_restore.py`
  - `tests/test_repair_settlement_results.py`
  - `tests/test_dashboard.py`
- Also inspected changed adjacent paper paths where the same side/timestamp safety invariant can still be bypassed:
  - `src/polysignal_lab/app/_settlement_check.py`
  - `src/polysignal_lab/publish/telegram_bot.py`

## Skill-Perspective Check

- Ran the required perspective check by loading `remove-ai-slops` and `programming`; also loaded the Python README and code-smells reference.
- `remove-ai-slops`: target tests are not deletion-only, tautological, or pure implementation mirrors. The remaining issue is production fabrication of missing data.
- `programming`: the target storage/repair/dashboard rerun scope passes no-excuse and has zero basedpyright errors, but the live settlement projection path still violates parse-don't-validate/fail-closed expectations by inventing side and timestamp values.

## Evidence Checked

- Stored artifacts inspected:
  - `.omo/ulw-loop/evidence/paper-blockers-focused-pytest.txt`: `55 passed, 2 warnings`.
  - `.omo/ulw-loop/evidence/paper-full-pytest.txt`: `670 passed, 2 warnings`.
  - `.omo/ulw-loop/evidence/paper-blockers-basedpyright.txt`: `0 errors, 587 warnings, 0 notes`.
  - `.omo/ulw-loop/evidence/paper-no-excuse-security-scope.txt`: `no violations in 6 file(s)`.
  - `.omo/ulw-loop/evidence/paper-blockers-manual-qa.txt`: includes `repair_missing_side=pass`, `dashboard_missing_side=pass`, `dashboard_invalid_opened_at=pass`, `storage_missing_side=pass`, and `storage_invalid_opened_at=pass`.
- Direct reruns:
  - `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider tests/test_storage_restore.py tests/test_dashboard.py tests/test_repair_settlement_results.py`: PASS, 29 tests.
  - `PYTHONDONTWRITEBYTECODE=1 uv run .../check-no-excuse-rules.py src/polysignal_lab/storage/sqlite_store.py scripts/repair_settlement_results.py src/polysignal_lab/dashboard/app.py tests/test_storage_restore.py tests/test_repair_settlement_results.py tests/test_dashboard.py`: PASS, `no violations in 6 file(s)`.
  - `PYTHONDONTWRITEBYTECODE=1 uv run basedpyright src/polysignal_lab/storage/sqlite_store.py scripts/repair_settlement_results.py src/polysignal_lab/dashboard/app.py tests/test_storage_restore.py tests/test_repair_settlement_results.py tests/test_dashboard.py`: PASS on errors, `0 errors, 412 warnings, 0 notes`.
  - `git diff --check`: PASS.
- Manual probes:
  - `_try_settle_projection(...)` with a cancelled market, unknown token, missing side, and valid timestamp returned a result with `side == "UP"`.
  - `_try_settle_projection(...)` with a cancelled market, valid side/token, and no opened timestamp returned a result whose `opened_at` was the new `closed_at` timestamp.
  - `_position_display_payload(...)` with no side returns `side == "UP"`.

## CRITICAL

None.

## HIGH

1. `src/polysignal_lab/app/_settlement_check.py:177-239`, `src/polysignal_lab/app/_settlement_check.py:245-255`: live settlement projection still fabricates missing paper position safety fields.

   `_paper_trade_result_from_projection()` accepts a projection dict, computes a result, and `_try_settle_projection()` persists it through `_store_projection_result()`. If the projection lacks a trustworthy side and token lookup fails, `_projection_side()` returns `Side.UP`. If no `opened_at`, `ts`, or `created_at` parses, the result uses `closed_at` as `opened_at`.

   This is the same class of paper safety bug as the fixed storage/repair/dashboard blockers: malformed or incomplete position state can become a valid-looking result instead of failing closed. The regenerated evidence does not cover this path.

   Required fix: fail closed when side cannot be derived from an explicit `UP`/`DOWN` or a verified market token, and fail closed when the first present opened timestamp is missing or malformed. Add focused regression coverage for both cases.

## MEDIUM

1. `src/polysignal_lab/publish/telegram_bot.py:668-693`: open-position display normalization still defaults missing `side` to `UP` and fills missing money fields with `0.0`.

   The current `PersistenceService.restore_open_positions()` path filters these rows before Telegram display, so this is not the primary blocker. It is still a changed paper-facing helper carrying the same fabrication pattern, and it has no missing-side regression test.

2. `src/polysignal_lab/dashboard/app.py:27`: the dashboard change widens `JsonValue` to `Any`.

   The scoped no-excuse check passes and basedpyright has zero errors, but the target typecheck still reports many `Any` warnings. This is typed debt, not the approval blocker.

## LOW

1. The storage, repair, and dashboard fixes for the previously reported blockers are present and covered:
   - `SQLiteStore._valid_position_event()` now requires `UP`/`DOWN` side for open rows and validates the first present timestamp.
   - `_latest_position_events()` selects the latest raw event per position before validation.
   - `_settle_for_repair()` returns `None` for missing/invalid side and timestamp inputs.
   - Dashboard projection returns empty side when unresolved and filters invalid side/timestamp payloads.

## Final Verdict

FAIL. The requested storage/repair/dashboard blockers are fixed, but the current paper safety refactor still has a blocking live settlement path that can create a valid paper result from missing side or missing opened timestamp data.
