# Paper Security Rerun 15

verdict: FAIL
severity: HIGH
recommendation: REQUEST_CHANGES
codeQualityStatus: BLOCK
reportPath: .omo/evidence/paper-security-rerun-15.md
blockers:
- `parse_paper_trade_result_row()` still accepts invalid non-empty `exit_mode` values such as `BROKEN`, and `SQLiteStore` persists/restores them.

## Scope

Security/data-safety-only final verdict after the scheduler split and `exit_mode` parser fix.

Reviewed current disk state for:

- `src/polysignal_lab/domain/paper_result.py`
- `src/polysignal_lab/domain/enums.py`
- `src/polysignal_lab/storage/sqlite_store.py`
- `src/polysignal_lab/domain/paper_report.py`
- `src/polysignal_lab/app/scheduler_reporting.py`
- `src/polysignal_lab/app/scheduler_reporting_build.py`
- `src/polysignal_lab/app/scheduler_reporting_sources.py`
- `src/polysignal_lab/app/scheduler_reporting_equity.py`
- `src/polysignal_lab/app/scheduler_reporting_storage.py`
- `src/polysignal_lab/app/scheduler_reporting_types.py`
- `src/polysignal_lab/app/services/publish_service.py`
- `tests/test_storage_restore.py`
- `.omo/evidence/paper-security-rerun-14.md`
- `.omo/ulw-loop/evidence/paper-storage-exit-mode-red.txt`
- `.omo/ulw-loop/evidence/paper-storage-exit-mode-green.txt`
- `.omo/ulw-loop/evidence/paper-storage-timestamp-green.txt`
- `.omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt`

## Skill-Perspective Check

- `remove-ai-slops`: loaded and applied as a review pass over production and test code. The new storage tests are not deletion-only or tautological, but the `exit_mode` coverage is underfit: it proves only missing `exit_mode` is rejected, not malformed/unknown values.
- `programming` + Python README: loaded and applied before judging tests/maintainability. Current `exit_mode` handling violates the parse-don't-validate boundary expectation because the parser keeps a raw untyped string after only checking non-emptiness.
- `ponytail`: active. No source changes were made; this report stays scoped to the requested security/data-safety verdict.
- Ultrawork plan/reviewer subagent: no `multi_agent_v1`/reviewer tool is exposed in this session, so the review was executed directly with command evidence below.

## Evidence Inspected

- `.omo/evidence/paper-security-rerun-14.md`: prior rerun was `PASS`/`LOW` for malformed timestamp and reporting split.
- `.omo/ulw-loop/evidence/paper-storage-exit-mode-red.txt`: the RED case showed a missing `exit_mode` row was incorrectly restored before the fix.
- `.omo/ulw-loop/evidence/paper-storage-exit-mode-green.txt`: the GREEN evidence is `......... [100%]`, but it does not show invalid enum-value coverage.
- `.omo/ulw-loop/evidence/paper-storage-timestamp-green.txt`: targeted malformed timestamp test passed.
- `.omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt`: full pytest reached `[100%]` with two NautilusTrader deprecation warnings.

## Fresh Verification

```text
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider \
  tests/test_nautilus_reporting_cache_source.py \
  tests/test_reporting.py \
  tests/test_storage_restore.py::test_sqlite_store_skips_malformed_timestamp_paper_trade_rows \
  tests/test_storage_restore.py::test_sqlite_store_rejects_paper_trade_rows_missing_exit_mode

................                                                         [100%]
```

```text
uv run python - <<'PY'
...
for value in ('BROKEN', 'UNKNOWN', ''):
    payload = dict(base, exit_mode=value)
    ...
PY

'BROKEN': accepted exit_mode=BROKEN
'UNKNOWN': accepted exit_mode=UNKNOWN
'': rejected invalid paper_trade_results.exit_mode: missing
```

```text
uv run python - <<'PY'
...
store.insert_paper_trade_result(dict(base, exit_mode='BROKEN'))
rows = store.query_json('paper_trade_results')
print(f'rows={len(rows)} exit_mode={rows[0]["exit_mode"] if rows else None}')
PY

rows=1 exit_mode=BROKEN
```

Additional checks:

- `git diff --check -- ...` over the reviewed parser/storage/scheduler/test paths exited 0.
- Sink scan across reviewed parser/reporting/scheduler/storage files found no new `subprocess`, `eval`, `exec`, `open`, network client, shell, pickle, or YAML load surface; only existing `SQLiteStore` path construction matched.

## Findings by Severity

### CRITICAL

None.

### HIGH

- `src/polysignal_lab/domain/paper_result.py:119` accepts malformed `exit_mode` values. The required-field loop at `paper_result.py:121-136` checks only that `exit_mode` is present/non-empty. Unlike `result` and `side`, no `ExitMode(...)` parse or `ExitMode.UNKNOWN` rejection follows. `ExitMode` has a finite domain at `src/polysignal_lab/domain/enums.py:70-75`, but ad-hoc verification shows `BROKEN` and `UNKNOWN` both pass through. Because `SQLiteStore.insert_paper_trade_result()` routes writes through this parser at `src/polysignal_lab/storage/sqlite_store.py:326-334` and `query_json("paper_trade_results")` returns parser-accepted rows at `src/polysignal_lab/storage/sqlite_store.py:400-408`, a malformed settlement mode can still be persisted and restored as a closed trade result. This fails the requested "exit_mode now fail-closed" criterion.

### MEDIUM

None.

### LOW

- The focused missing-`exit_mode` test is useful but too narrow. It would still pass if the parser continues accepting arbitrary non-empty settlement modes, which is exactly the current failure mode.

## Security Assessment

Malformed persisted timestamps: PASS. `parse_paper_trade_result_row()` validates `opened_at` and `closed_at`, catches `ValueError` from `parse_dt()`, and raises `InvalidPaperTradeResultRow`; `SQLiteStore.query_json("paper_trade_results")` skips `InvalidPaperTradeResultRow`.

`exit_mode` fail-closed: FAIL. Missing `exit_mode` is now rejected, but malformed non-empty values are accepted and restored.

Scheduler split: PASS for security neutrality in this scope. The split moves existing report collection/build/equity/storage helpers into dedicated modules and does not add a new dynamic execution, shell, file, network, or unsafe deserialization surface in the inspected paths.

## Verdict

FAIL. Severity HIGH. The prior malformed timestamp HIGH appears fixed and the scheduler split is security-neutral, but the `exit_mode` parser is not fail-closed for malformed non-empty settlement modes.
