# Paper Security Rerun 11

verdict: FAIL
severity: HIGH
recommendation: REQUEST_CHANGES
codeQualityStatus: BLOCK
reportPath: .omo/evidence/paper-security-rerun-11.md
notepadPath: /tmp/ulw-20260709-090235.bPxHFp.md
blockers:
  - HIGH: malformed persisted paper_trade_results timestamps raise raw ValueError during SQLite restore/query instead of failing closed.

## Scope

Security-only rerun after the reporting-cache protocol fix. Reviewed only the current reporting-cache protocol fix and the storage, settlement, and projection parser paths needed to validate data-safety. Runtime Protocol behavior is treated as security-neutral unless it creates data exposure or corruption.

## Skill-Perspective Check

- `remove-ai-slops`: loaded and applied as an overfit/slop review lens. No deletion-only tests, requested-removal-only tests, or tautological tests were found in the reviewed slice. The storage tests are behavior-shaped, but they miss one adversarial parser branch: invalid `paper_trade_results.opened_at` / `closed_at` in persisted JSON.
- `programming`: loaded with Python data modeling and error-handling references. The diff violates the parse-at-boundary/typed-error perspective in the storage parser: `parse_paper_trade_result_row` lets `parse_dt` raise raw `ValueError` instead of converting malformed persisted timestamps into `InvalidPaperTradeResultRow` or another fail-closed outcome.
- Ponytail/minimality: no extra abstraction is needed; the root issue is one parser boundary and the missing adversarial test.

## Evidence Inspected

- `.omo/evidence/paper-security-rerun-9.md`: prior PASS/NONE after zero-money and malformed-storage fixes.
- `.omo/evidence/paper-security-rerun-10.md`: prior PASS/NONE, WATCH, after post-R10 review.
- `.omo/ulw-loop/evidence/paper-r10-protocol-green.txt`: one protocol regression test passed.
- `.omo/ulw-loop/evidence/paper-post-r10-focused-rerun.txt`: 56 focused tests passed.
- `.omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt`: full pytest passed.
- `.omo/ulw-loop/evidence/paper-post-r10-basedpyright-rerun.txt`: 0 errors, 135 warnings.

Reviewer gate note: `multi_agent_v1.spawn_agent` / reviewer subagent tools are not available in this harness after tool discovery, so no child reviewer approval was obtained.

Fresh checks:

```text
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider \
  tests/test_nautilus_reporting_cache_source.py \
  tests/test_scheduler_settlement_resolution.py \
  tests/test_settlement.py \
  tests/test_nautilus_projections.py \
  tests/test_storage_restore.py

.....................................................                    [100%]
```

```text
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider \
  tests/test_nautilus_reporting_cache_source.py

........                                                                 [100%]
```

Protocol probe:

```text
no_attrs (1000.0, 1000.0, 0)
noncallable_attrs (1000.0, 1000.0, 0)
```

Malformed persisted trade-result timestamp probe:

```text
ValueError Invalid isoformat string: 'not-a-date'
```

## Findings by Severity

### CRITICAL

None.

### HIGH

- [src/polysignal_lab/domain/paper_result.py](/home/debian/polysignal-lab/src/polysignal_lab/domain/paper_result.py:127) and [src/polysignal_lab/storage/sqlite_store.py](/home/debian/polysignal-lab/src/polysignal_lab/storage/sqlite_store.py:400): malformed persisted `paper_trade_results` timestamps can still crash restore/query surfaces. `parse_paper_trade_result_row` calls `parse_dt(...)` for `opened_at` / `closed_at`, but `parse_dt` raises `ValueError` for malformed ISO text. `SQLiteStore.query_json("paper_trade_results")` catches `json.JSONDecodeError` and `InvalidPaperTradeResultRow`, not raw `ValueError`, so a single bad persisted payload raises instead of being skipped or converted to the typed parser error. This reopens the malformed-storage fail-closed guarantee for `paper_trade_results`.

### MEDIUM

None.

### LOW

- Non-blocking quality debt remains in the reviewed slice: `scheduler_reporting.py`, `_settlement_check.py`, `sqlite_store.py`, and `paper_result.py` exceed the 250 pure-LOC programming threshold, and basedpyright artifacts still report warnings. These are maintainability risks, not security/data-safety blockers for this rerun.
- The parser currently accepts zero `entry_price`, `shares`, and `stake_usdc` in persisted `paper_trade_results`. Live settlement rejects zero before persistence, so I am not treating this as the blocking issue here, but the storage boundary is weaker than the settlement boundary.

## Security Checks

### Reporting-cache protocol fix

PASS. Current code adds `_is_nautilus_reporting_cache` with callable checks at [src/polysignal_lab/app/scheduler_reporting.py](/home/debian/polysignal-lab/src/polysignal_lab/app/scheduler_reporting.py:102), and `_report_equity_inputs` falls back when the cache does not satisfy it at [src/polysignal_lab/app/scheduler_reporting.py](/home/debian/polysignal-lab/src/polysignal_lab/app/scheduler_reporting.py:279). Fresh probe shows non-callable `account` / `positions` attributes return fallback rather than raising. This is security-neutral.

### Settlement and projection money

PASS for the reviewed live-settlement path. `_projection_float` rejects non-finite values, `_paper_trade_result_from_projection` rejects missing, zero, negative, or non-finite settlement money before persistence, and invalid projection timestamps return `None`.

### Storage malformed JSON and parser safety

FAIL. Malformed JSON itself is skipped, and NaN/incomplete trade-result rows are covered by existing tests at [tests/test_storage_restore.py](/home/debian/polysignal-lab/tests/test_storage_restore.py:170) and [tests/test_storage_restore.py](/home/debian/polysignal-lab/tests/test_storage_restore.py:310). The timestamp parser branch is uncovered: malformed timestamp text raises raw `ValueError`, which escapes `SQLiteStore.query_json("paper_trade_results")`.

## Required Fix Before Approval

Convert malformed `paper_trade_results.opened_at` / `closed_at` timestamps into the typed fail-closed path, and add the narrow adversarial storage test proving a persisted row with malformed timestamp is excluded rather than crashing.

## Verdict

FAIL. Severity HIGH. Recommendation REQUEST_CHANGES. The reporting-cache protocol fix itself is security-neutral, but the current storage parser still has an exploitable data-safety fail-open/crash path for malformed persisted `paper_trade_results` timestamps.
