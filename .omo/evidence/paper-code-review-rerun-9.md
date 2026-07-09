# Paper Code Review Rerun 9

verdict: FAIL
codeQualityStatus: BLOCK
recommendation: REQUEST_CHANGES
reportPath: .omo/evidence/paper-code-review-rerun-9.md
blockers:
- `src/polysignal_lab/app/scheduler_reporting.py:274`, `:296`, `:315`: incomplete `nautilus_cache` objects still crash daily-report equity collection, and `tests/test_nautilus_reporting_cache_source.py` does not cover that requested fallback.

## CRITICAL

None.

## HIGH

1. `src/polysignal_lab/app/scheduler_reporting.py:274`, `:296`, `:315`: `_report_equity_inputs()` casts any non-None `scheduler.nautilus_cache` to `_NautilusReportingCache`, then `_report_equity_inputs_from_nautilus_cache()` calls `nautilus_cache.account()` and `nautilus_cache.positions()` unguarded. A partial cache object still raises instead of falling back to `(starting_equity, starting_equity, 0)`.

   Direct focused probe run during review:

   ```text
   uv run python - <<'PY'
   from types import SimpleNamespace
   from polysignal_lab.app.scheduler_reporting import _report_equity_inputs
   scheduler = SimpleNamespace(
       settings=SimpleNamespace(paper_trading=SimpleNamespace(starting_balance_usdc=1000.0)),
       nautilus_cache=SimpleNamespace(),
   )
   try:
       print(_report_equity_inputs(scheduler))
   except Exception as exc:
       print(type(exc).__name__, str(exc))
   PY
   ```

   Output:

   ```text
   AttributeError 'types.SimpleNamespace' object has no attribute 'account'
   ```

   This is current post-R10 correctness risk because the assignment explicitly called out the prior incomplete-cache fallback test. The existing tests cover no cache at all (`tests/test_nautilus_reporting_cache_source.py:139-153`), but not a present cache missing the account/positions readers.

## MEDIUM

None blocking for this rerun. The inspected basedpyright evidence still reports warnings in the reviewed surface, but the user explicitly marked existing pyright warnings nonblocking unless caused by this fix and likely a bug. The HIGH issue above is behavior-proven, not just a type warning.

## LOW

1. `tests/test_nautilus_reporting_cache_source.py:122-136`: `test_report_equity_inputs_uses_account_balance_for_non_numeric_portfolio_equity` does not actually create a non-numeric portfolio; it creates no portfolio. This is test metadata/slop, not the blocker, but it makes the fallback coverage look broader than it is.

## Prior Blockers

- Dynamic account/positions lookup for complete caches: fixed for complete cache objects. Current code reads `account()` at `scheduler_reporting.py:296` and `positions()` at `scheduler_reporting.py:315`; `.omo/ulw-loop/evidence/paper-post-r10-rg-rerun.txt` confirms those call sites.
- Incomplete-cache fallback: not fixed. The direct probe above crashes with `AttributeError`, and the focused test file lacks a partial-cache regression.

## Evidence Inspected

- `.omo/ulw-loop/evidence/paper-post-r10-focused-rerun.txt`: 55 passed.
- `.omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt`: full-suite evidence says passed; inspected only, not rerun.
- `.omo/ulw-loop/evidence/paper-post-r10-basedpyright-rerun.txt`: 0 errors, 135 warnings.
- `.omo/ulw-loop/evidence/paper-post-r10-rg-rerun.txt`: direct `account()`/`positions()` evidence.
- Source/test files inspected: `src/polysignal_lab/app/scheduler_reporting.py`, `tests/test_nautilus_reporting_cache_source.py`, `src/polysignal_lab/app/_settlement_check.py`, `src/polysignal_lab/nautilus_runtime/projections.py`, `src/polysignal_lab/storage/sqlite_store.py`.
- Focused command run by this review: `uv run pytest tests/test_nautilus_reporting_cache_source.py -q` -> 7 passed. No full suite was run by this review.

## Skill Perspective Check

- `remove-ai-slops`: consulted full skill. Violation found: the test surface gives false confidence for the requested incomplete-cache fallback; it is not deletion-only or tautological, but it omits the edge named by the blocker and one test name overstates what it covers.
- `programming`: consulted full skill plus Python README. Violation found: the current fix uses an unchecked Protocol cast and unguarded method calls at a runtime boundary, producing a real `AttributeError` for a partial cache object.
- `ponytail`: consulted full skill. The minimal correct fix should stay local to the reporting cache seam; no new abstraction is justified.
