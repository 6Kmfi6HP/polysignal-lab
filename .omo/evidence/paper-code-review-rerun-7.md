# Paper Code Review Rerun 7

verdict: FAIL
codeQualityStatus: BLOCK
recommendation: REQUEST_CHANGES
reportPath: .omo/evidence/paper-code-review-rerun-7.md
notepadPath: /tmp/ulw-20260709-065451.0aVCq5.md
blockers:
- `src/polysignal_lab/app/_settlement_check.py:189` accepts zero-valued money fields and still returns a settled WIN result with `entry_price=0.0`, `shares=0.0`, and `stake_usdc=0.0`.
- `src/polysignal_lab/nautilus_runtime/projections.py:79` still normalizes missing Nautilus position money attributes to `0.0`, and line 87 derives `stake_usdc=0.0` from those fabricated values.
- `tests/test_settlement.py:35` is a deletion-only test that verifies a file was removed rather than behavior; it should be removed or replaced with behavior coverage.
- The listed manual QA evidence path `.omo/ulw-loop/evidence/paper-post-security-fix-manual-qa.txt` is absent, while the summary claims `manual_qa=pass`.

## CRITICAL

None.

## HIGH

1. `src/polysignal_lab/app/_settlement_check.py:189` and `src/polysignal_lab/nautilus_runtime/projections.py:79`: the stale zero-money settlement blocker is still present for zero-valued projections.

   Rerun 6 blocked because live settlement could persist `entry_price=0.0`, `shares=0.0`, and `stake_usdc=0.0`. The new guard rejects absent or non-finite fields (`_settlement_check.py:189-206`), but it does not reject zero or negative economic values. `_paper_trade_result_from_projection()` then builds a WIN result from zeros at `_settlement_check.py:235-260`.

   The adjacent projection change makes this worse: `project_position()` reads `signed_qty` and `avg_px_open` via `_float_attr()` (`projections.py:79-80`), derives `stake_usdc` (`projections.py:87`), and `_float_attr()` still uses `_to_float()` which falls back to `0.0` on missing/unparseable values (`projections.py:147-177`). A live position missing those money attributes is therefore still represented as zero money, not unknown.

   Manual probe evidence:

   - `project_position(SimpleNamespace(id='pos-missing', instrument_id='token-up', is_closed=False, ts_event='2026-06-22T00:00:00+00:00'))` returned `quantity: 0.0`, `avg_entry_price: 0.0`, and `stake_usdc: 0.0`.
   - `_paper_trade_result_from_projection({... quantity: 0.0, avg_entry_price: 0.0, stake_usdc: 0.0 ...}, outcome_value=1.0)` returned a dict with `entry_price: 0.0`, `shares: 0.0`, `stake_usdc: 0.0`, `settlement_value: 0.0`, `result: 'WIN'`.

   Tests currently miss this edge: `tests/test_scheduler_settlement_resolution.py:336-400` covers absent/NaN/inf fields, but not zero-valued money, and `tests/test_nautilus_projections.py:117-138` only asserts the happy-path derived stake.

2. `tests/test_settlement.py:35`: deletion-only test.

   `test_paper_settlement_engine_module_is_removed()` only asserts `not Path("src/polysignal_lab/paper/settlement.py").exists()` (`tests/test_settlement.py:35-38`). Under the remove-ai-slops perspective, this is a requested-removal/implementation-detail test, not behavior coverage. It can pass while settlement behavior regresses, and it adds false confidence.

3. Evidence hygiene: missing manual QA artifact.

   The user-listed path `.omo/ulw-loop/evidence/paper-post-security-fix-manual-qa.txt` does not exist. The summary file says `manual_qa=pass missing stake None; malformed system/daily []/None; idempotent typed MalformedSQLitePayloadError`, but there is no separate artifact at the requested path. I did not treat that summary line as approval evidence.

## MEDIUM

1. Strict typing remains weak in the reviewed surface.

   Fresh targeted command:

   `PYTHONDONTWRITEBYTECODE=1 uv run basedpyright src/polysignal_lab/app/_settlement_check.py src/polysignal_lab/storage/sqlite_store.py src/polysignal_lab/nautilus_runtime/projections.py src/polysignal_lab/domain/paper_result.py tests/test_settlement.py tests/test_storage_restore.py tests/test_nautilus_projections.py tests/test_scheduler_settlement_resolution.py`

   Result: `0 errors, 412 warnings, 0 notes`. The warnings include many `Any`/unknown flows in `_settlement_check.py`, `sqlite_store.py`, `paper_result.py`, and tests. This is not the immediate behavior blocker, but it violates the programming perspective and keeps the paper row boundary hard to review.

## LOW

1. Broad dirty scope remains. `git status --short` shows 71 tracked files changed plus many untracked evidence/docs/source/test files. I did not find tracked diffs under `refs` or `docs/nautilus_reference`, and no commit was requested.

## Stale Blocker Recheck

- Live settlement missing money fields as zero: FAIL. Direct absent-field tests now pass, but zero-valued projections still produce durable-looking WIN results, and `project_position()` still fabricates zeros for missing numeric attributes.
- Malformed JSON handling for `system_events`, `daily_reports`, and idempotence: PASS. `SQLiteStore.query_json()` skips malformed `system_events` and `daily_reports` payloads (`sqlite_store.py:409-416`), `restore_latest_system_event()` catches malformed latest event payloads (`sqlite_store.py:391-394`), and `_insert_idempotent()` raises `MalformedSQLitePayloadError` for a malformed existing same-key payload (`sqlite_store.py:510-517`). Tests cover these cases at `tests/test_storage_restore.py:233-307`.

## Skill-Perspective Check

- `remove-ai-slops`: ran by loading the full skill. The current diff violates this perspective through a deletion-only test (`tests/test_settlement.py:35-38`) and production normalization that still turns unknown money into zero (`projections.py:79-87`, `_settlement_check.py:189-260`). The malformed JSON tests are meaningful behavior tests, not tautological removal checks.
- `programming`: ran by loading the full skill plus Python README, code-smells, data-modeling, type-patterns, and error-handling references. The zero-money path violates parse-don't-validate/fail-closed boundary discipline. The `basedpyright` warning count records typed debt but not a typecheck failure.
- `review-work`: loaded and considered. I did not run its 5-agent gate because this assignment is a single read-only code-quality review artifact, and no `multi_agent` tool is available in this toolset.
- `ponytail-review`: loaded and applied as the over-engineering lens. The deletion-only test is the main cut candidate.

## Evidence Inspected

- Previous blocker report: `.omo/evidence/paper-code-review-rerun-6.md` said `_paper_trade_result_from_projection()` still fabricated zero money fields into a WIN row.
- Current source inspected:
  - `src/polysignal_lab/app/_settlement_check.py:42-52`, `182-260`
  - `src/polysignal_lab/nautilus_runtime/projections.py:76-87`, `147-177`
  - `src/polysignal_lab/storage/sqlite_store.py:72-101`, `379-417`, `496-526`
  - `src/polysignal_lab/domain/paper_result.py:88-156`
  - `tests/test_settlement.py:35-113`
  - `tests/test_storage_restore.py:204-307`, `372-517`
  - `tests/test_scheduler_settlement_resolution.py:336-400`
  - `tests/test_nautilus_projections.py:117-138`
- Existing evidence inspected:
  - `.omo/ulw-loop/evidence/paper-post-security-fix-summary.txt`: claims focused/full/type/manual/compile/diff/refs pass.
  - `.omo/ulw-loop/evidence/paper-post-security-fix-focused-pytest.txt`: `44 passed`.
  - `.omo/ulw-loop/evidence/paper-post-security-fix-system-python-focused-pytest.txt`: `44 passed`.
  - `.omo/ulw-loop/evidence/paper-post-security-fix-full-pytest.txt`: full suite pass.
  - `.omo/ulw-loop/evidence/paper-post-security-fix-basedpyright.txt`: `0 errors`.
  - `.omo/ulw-loop/evidence/paper-post-security-fix-diff-check.txt`: pass.
  - `.omo/ulw-loop/evidence/paper-post-security-fix-refs-check.txt`: pass.
  - `.omo/ulw-loop/evidence/paper-post-security-fix-compileall.txt`: pass.
  - `.omo/ulw-loop/evidence/paper-post-security-fix-manual-qa.txt`: missing.

## Fresh Commands Run

- `git status --short`
- `git diff --name-only`
- `git diff --stat`
- `git diff --check`: passed.
- `git diff --name-only -- refs docs/nautilus_reference`: no output.
- `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider tests/test_settlement.py tests/test_storage_restore.py tests/test_nautilus_projections.py tests/test_scheduler_settlement_resolution.py`: `41 passed`.
- `PYTHONDONTWRITEBYTECODE=1 uv run basedpyright src/polysignal_lab/app/_settlement_check.py src/polysignal_lab/storage/sqlite_store.py src/polysignal_lab/nautilus_runtime/projections.py src/polysignal_lab/domain/paper_result.py tests/test_settlement.py tests/test_storage_restore.py tests/test_nautilus_projections.py tests/test_scheduler_settlement_resolution.py`: `0 errors, 412 warnings, 0 notes`.
- `PYTHONDONTWRITEBYTECODE=1 uv run python -m compileall -q src/polysignal_lab/app/_settlement_check.py src/polysignal_lab/storage/sqlite_store.py src/polysignal_lab/nautilus_runtime/projections.py src/polysignal_lab/domain/paper_result.py`: passed.
- Manual projection probe for `project_position()` missing money attributes: returned zero money fields.
- Manual settlement probe for zero money projection: returned a WIN result with all money fields zero.

## Verdict

FAIL. The malformed JSON blocker is fixed, but the live settlement money blocker is only partially fixed: absent/NaN fields are rejected, while zero-valued money fields still settle as valid-looking WIN rows and the projection layer still fabricates those zeros from missing attributes.
