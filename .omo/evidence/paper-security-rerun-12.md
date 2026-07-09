# Paper Security Rerun 12

verdict: FAIL
severity: HIGH
recommendation: REQUEST_CHANGES
codeQualityStatus: BLOCK
reportPath: .omo/evidence/paper-security-rerun-12.md
blockers:
  - HIGH: malformed persisted `paper_trade_results.opened_at` / `closed_at` timestamps still raise raw `ValueError` during SQLite restore/query instead of failing closed.

## Scope

Narrow security rerun after the callable reporting-cache protocol-boundary fix. Reviewed the reporting-cache boundary in `scheduler_reporting.py` and only the settlement/storage/projection evidence needed to verify the prior data-safety blocker.

## Skill-Perspective Check

- `remove-ai-slops`: loaded and applied as an overfit/slop review lens. The callable-cache regression is behavioral and not tautological. Storage coverage still misses the adversarial persisted `paper_trade_results` malformed timestamp branch, giving false confidence for malformed-storage safety.
- `programming`: loaded with Python README, type-patterns, and data-modeling references. The callable protocol boundary is acceptable for the reporting path, but the storage parser still violates fail-closed boundary handling because raw `ValueError` escapes from timestamp parsing.
- Ponytail: active. No extra abstraction is needed; the remaining blocker is one parser-boundary catch/typed-error conversion plus one adversarial test.

## Evidence Inspected

- `src/polysignal_lab/app/scheduler_reporting.py:102`: `_is_nautilus_reporting_cache` now requires the runtime protocol and callable `account` / `positions` attributes.
- `src/polysignal_lab/app/scheduler_reporting.py:279`: `_report_equity_inputs` falls back when the cache fails that guard.
- `tests/test_nautilus_reporting_cache_source.py:147`: regression covers missing and non-callable cache attributes.
- `src/polysignal_lab/domain/paper_result.py:127`: `parse_paper_trade_result_row` calls `parse_dt` for `opened_at` / `closed_at`.
- `src/polysignal_lab/storage/sqlite_store.py:400`: `query_json("paper_trade_results")` catches `json.JSONDecodeError` and `InvalidPaperTradeResultRow`, but not raw `ValueError`.
- `.omo/evidence/paper-security-rerun-11.md`: prior HIGH finding for malformed persisted trade-result timestamps.
- `.omo/ulw-loop/evidence/paper-r10-protocol-callable-red.txt` and `.omo/ulw-loop/evidence/paper-r10-protocol-callable-green.txt`: callable cache fix red/green artifacts.

## Fresh Verification

```text
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider tests/test_nautilus_reporting_cache_source.py
........                                                                 [100%]
```

```text
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider \
  tests/test_storage_restore.py \
  tests/test_scheduler_settlement_resolution.py \
  tests/test_settlement.py \
  tests/test_nautilus_projections.py
.............................................                            [100%]
```

Callable malformed-cache probe:

```text
SimpleNamespace (1000.0, 1000.0, 0)
SimpleNamespace (1000.0, 1000.0, 0)
SimpleNamespace (1000.0, 1000.0, 0)
```

Malformed persisted timestamp probe:

```text
ValueError Invalid isoformat string: 'not-a-date'
```

## Findings by Severity

### CRITICAL

None.

### HIGH

- `src/polysignal_lab/domain/paper_result.py:127` and `src/polysignal_lab/storage/sqlite_store.py:400`: malformed persisted `paper_trade_results` timestamps still crash restore/query paths. A bad row with `payload_json.opened_at = "not-a-date"` reaches `parse_dt(...)`, which raises `ValueError`. `SQLiteStore.query_json("paper_trade_results")` does not convert that into `InvalidPaperTradeResultRow` or skip it, so one malformed persisted settlement-audit row can break reporting/restore surfaces. This is a data-safety fail-closed issue and remains blocking.

### MEDIUM

None.

### LOW

- The reviewed files still carry broader type/size debt (`Any`, casts, large modules). These are not security blockers for this rerun.

## Security Checks

Reporting-cache protocol boundary: PASS. Malformed cache objects with missing or non-callable `account` / `positions` now return `(1000.0, 1000.0, 0)` instead of raising. Direct helper calls are security-neutral after the caller-side guard.

Settlement/projection money checks: PASS for the focused tests inspected. The rerun did not find a fresh exploitable issue in the settlement/projection path.

Storage malformed timestamp safety: FAIL. Existing focused tests pass, but the direct adversarial probe proves the malformed timestamp branch is still uncovered and still raises raw `ValueError`.

## Required Fix Before Approval

Convert malformed `paper_trade_results.opened_at` / `closed_at` timestamp parsing into the typed fail-closed path, and add a narrow storage test proving a persisted row with malformed timestamp is excluded instead of crashing.

## Verdict

FAIL. Severity HIGH. The callable protocol-boundary fix is good, but the current storage parser still has an exploitable data-safety crash path for malformed persisted settlement audit timestamps.
