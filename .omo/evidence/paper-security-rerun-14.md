# Paper Security Rerun 14

verdict: PASS
severity: LOW
recommendation: APPROVE
codeQualityStatus: CLEAR
reportPath: .omo/evidence/paper-security-rerun-14.md
blockers: []

## Scope

Security-only final rerun after the `paper_report.py` split. Reviewed current disk state for:

- `src/polysignal_lab/domain/paper_result.py`
- `src/polysignal_lab/domain/paper_report.py`
- `src/polysignal_lab/app/scheduler_reporting.py`
- `src/polysignal_lab/storage/sqlite_store.py`
- `src/polysignal_lab/app/services/publish_service.py`
- `tests/test_storage_restore.py`
- `tests/test_nautilus_reporting_cache_source.py`
- `tests/test_publish_service.py`
- `.omo/evidence/paper-security-rerun-13.md`
- `.omo/ulw-loop/evidence/paper-storage-timestamp-green.txt`
- `.omo/ulw-loop/evidence/paper-storage-restore-pytest.txt`
- `.omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt`

## Skill-Perspective Check

- `remove-ai-slops`: loaded and applied to production and test code. No deletion-only tests, requested-removal-only tests, tautological tests, implementation-constant mirroring, or unnecessary production extraction/parsing/normalization blocker found in this scope.
- `programming`: loaded with the Python README and applied to the `.py` review. The timestamp guard is at the storage/publish boundary, uses typed `InvalidPaperTradeResultRow`, and keeps the malformed persisted data fail-closed. No reviewed split file violates the 250 pure LOC ceiling (`paper_result.py`: 151, `paper_report.py`: 144).
- `ponytail`: active. No code changes were made; the report stays scoped to the requested security/data-safety verdict.
- Ultrawork reviewer subagent gate: not run because no `multi_agent_v1`/reviewer tool is exposed in this session. Direct review evidence is recorded below.

## Evidence Inspected

- `.omo/evidence/paper-security-rerun-13.md`: prior rerun was PASS/LOW and recorded that the previous malformed timestamp HIGH blocker was fixed.
- `.omo/ulw-loop/evidence/paper-storage-timestamp-green.txt`: targeted malformed timestamp test passed.
- `.omo/ulw-loop/evidence/paper-storage-restore-pytest.txt`: `tests/test_storage_restore.py` passed.
- `.omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt`: full pytest rerun reached `[100%]` with only two NautilusTrader pandas/NumPy deprecation warnings.

## Fresh Verification

```text
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider \
  tests/test_storage_restore.py::test_sqlite_store_skips_malformed_timestamp_paper_trade_rows \
  tests/test_nautilus_reporting_cache_source.py \
  tests/test_publish_service.py::test_publish_paper_result_rejects_invalid_payload

..........                                                               [100%]
```

```text
PYTHONDONTWRITEBYTECODE=1 uv run python - <<'PY'
...
PY

malformed_timestamp=pass
cache_protocol_guard=pass
paper_report_split=pass
```

Additional checks:

- `rg` for obvious execution/I/O/security sinks across reviewed files found no `subprocess`, `eval`, `exec`, `open`, network client, shell, pickle, or unsafe YAML usage in `paper_result.py`, `paper_report.py`, `scheduler_reporting.py`, or `publish_service.py`; the only match was existing `sqlite_store.py:137` `Path(path)`.
- `git diff --check -- src/polysignal_lab/domain/paper_result.py src/polysignal_lab/domain/paper_report.py src/polysignal_lab/app/scheduler_reporting.py tests/test_storage_restore.py tests/test_nautilus_reporting_cache_source.py` exited 0.

## Findings by Severity

### CRITICAL

None.

### HIGH

None.

### MEDIUM

None.

### LOW

- Residual broader paper/runtime type debt remains (`Any`, casts, protocols, large surrounding modules), but it is outside this security-only rerun and is not an exploitable blocker in the requested split/timestamp/cache scope.

## Security Assessment

Malformed persisted timestamps: PASS. `parse_paper_trade_result_row()` validates `opened_at` and `closed_at`, catches `ValueError` from `parse_dt()`, and raises `InvalidPaperTradeResultRow` instead of allowing raw parser exceptions to escape. `SQLiteStore.query_json("paper_trade_results")` catches `InvalidPaperTradeResultRow` and excludes malformed persisted rows, so hostile or corrupted stored rows no longer crash restore/reporting reads.

`paper_report.py` split: PASS. The new module contains row helper functions and Pydantic report/wallet models only. It introduces no file, network, subprocess, dynamic execution, deserialization, or shell surface. Existing message formatting still escapes user-visible Telegram HTML at the output boundary.

Reporting-cache fix: PASS. `_report_equity_inputs()` rejects missing or non-callable Nautilus cache protocol members before calling `account()` or `positions()`, and the focused cache regression tests pass.

## Verdict

PASS. Severity LOW. No CRITICAL, HIGH, or MEDIUM security/data-safety blocker remains in the requested scope.
