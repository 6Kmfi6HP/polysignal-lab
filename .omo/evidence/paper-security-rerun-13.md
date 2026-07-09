# Paper Security Rerun 13

verdict: PASS
severity: LOW
recommendation: APPROVE
codeQualityStatus: CLEAR
reportPath: .omo/evidence/paper-security-rerun-13.md
blockers: []

## Scope

Security-only rerun after the malformed persisted timestamp fix. Reviewed:

- `src/polysignal_lab/domain/paper_result.py`
- `src/polysignal_lab/storage/sqlite_store.py`
- `src/polysignal_lab/app/scheduler_reporting.py`
- `tests/test_storage_restore.py`
- `tests/test_nautilus_reporting_cache_source.py`
- `.omo/evidence/paper-security-rerun-12.md`
- `.omo/ulw-loop/evidence/paper-storage-timestamp-red.txt`
- `.omo/ulw-loop/evidence/paper-storage-timestamp-green.txt`
- `.omo/ulw-loop/evidence/paper-storage-restore-pytest.txt`
- `.omo/ulw-loop/evidence/paper-post-r10-focused-rerun.txt`
- `.omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt`

## Skill-Perspective Check

- `remove-ai-slops`: loaded and applied to production and test changes. No deletion-only, tautological, requested-removal-only, or implementation-constant-mirroring test blocker found. The timestamp test inserts hostile persisted rows and checks observable restore/query behavior.
- `programming`: loaded with Python README and applied as the strict Python boundary/type-safety lens. The malformed timestamp path now parses at the storage boundary and converts `ValueError` into typed `InvalidPaperTradeResultRow`; no new untyped escape hatch or needless abstraction is a security blocker for this rerun.
- Ponytail: active. No production/test edits were made by this reviewer; the minimal fix shape is sufficient.

## Evidence Inspected

- Prior HIGH blocker in `.omo/evidence/paper-security-rerun-12.md`: malformed persisted `paper_trade_results.opened_at` / `closed_at` raised raw `ValueError`.
- RED evidence in `.omo/ulw-loop/evidence/paper-storage-timestamp-red.txt`: targeted malformed timestamp test failed with `ValueError: Invalid isoformat string: 'not-a-date'`.
- GREEN evidence in `.omo/ulw-loop/evidence/paper-storage-timestamp-green.txt`: same targeted test passed.
- Focused storage evidence in `.omo/ulw-loop/evidence/paper-storage-restore-pytest.txt`: `tests/test_storage_restore.py` passed.
- Focused post-R10 evidence in `.omo/ulw-loop/evidence/paper-post-r10-focused-rerun.txt`: 57 tests passed.
- Full post-R10 evidence in `.omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt`: full suite reached 100% with only NautilusTrader pandas/NumPy deprecation warnings.

## Fresh Verification

```text
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider tests/test_storage_restore.py tests/test_nautilus_reporting_cache_source.py
........................                                                 [100%]
```

Direct malformed `opened_at` and `closed_at` persisted-row probe:

```text
[]
```

Full suite:

```text
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider
100% complete; 2 NautilusTrader pandas/NumPy deprecation warnings
```

## Findings by Severity

### CRITICAL

None.

### HIGH

None.

### MEDIUM

None.

### LOW

- Residual type/size debt remains in the broader touched paper/runtime area (`Any`, casts, large modules), but it is pre-existing/broader cleanup debt and not an exploitable security or data-safety blocker for this final malformed timestamp rerun.

## Security Assessment

Malformed persisted timestamps: PASS. `parse_paper_trade_result_row` now catches `ValueError` from `parse_dt` for `opened_at` / `closed_at` and raises `InvalidPaperTradeResultRow` instead. `SQLiteStore.query_json("paper_trade_results")` catches `InvalidPaperTradeResultRow` and excludes the malformed row, so a hostile persisted audit row no longer crashes restore/reporting reads.

Reporting-cache boundary: PASS. `_report_equity_inputs` still rejects missing or non-callable cache protocol members before calling the Nautilus cache methods, and the regression coverage remains green.

Data-safety posture: PASS. The reviewed restore path now fails closed for malformed JSON, malformed required fields, malformed timestamps, and invalid position events. No remaining HIGH/CRITICAL exploit path was found in the requested scope.

## Verdict

PASS. Severity LOW. No exploitable security/data-safety blockers remain in the requested scope.
