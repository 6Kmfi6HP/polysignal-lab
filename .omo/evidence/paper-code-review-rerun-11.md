# Paper Code Review Rerun 11

Verdict: PASS
codeQualityStatus: WATCH
recommendation: APPROVE
reportPath: .omo/evidence/paper-code-review-rerun-11.md
blockers: []

Reviewed at: 2026-07-09T09:27:26+02:00
Scope inspected:
- src/polysignal_lab/app/scheduler_reporting.py
- tests/test_nautilus_reporting_cache_source.py
- .omo/ulw-loop/evidence/paper-r10-protocol-callable-red.txt
- .omo/ulw-loop/evidence/paper-r10-protocol-callable-green.txt
- .omo/ulw-loop/evidence/paper-r10-reporting-cache-pytest.txt
- .omo/ulw-loop/evidence/paper-post-r10-focused-rerun.txt
- .omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt
- .omo/ulw-loop/evidence/paper-post-r10-basedpyright-rerun.txt
- .omo/ulw-loop/evidence/paper-post-r10-rg-rerun.txt
- .omo/ulw-loop/evidence/paper-post-r10-diff-check.txt

Notepad: /tmp/ulw-20260709-092211.LbTPiV.md

## Skill-Perspective Check

Ran. I loaded/consulted:
- remove-ai-slops: checked production and tests for overfit/slop, deletion-only tests, tautological assertions, implementation-mirroring, and needless production complexity.
- programming + Python reference: checked strict typing, protocol boundary, untyped escape hatches, oversized module risk, and test shape.
- ponytail active perspective: checked whether the fix is minimal and avoids speculative abstraction.

Result: no blocking violation for this narrow callable-boundary fix. Residual strict-typing/module-size debt remains low severity below.

## CRITICAL

None.

## HIGH

None.

## MEDIUM

None.

## LOW

1. src/polysignal_lab/app/scheduler_reporting.py:47 keeps explicit `Any` in protocol return types; additional explicit `Any` appears at lines 125, 239, and 367. The direct callable-boundary fix is correct, and basedpyright reports 0 errors, but this still violates the strict programming skill preference for no untyped escape hatches.

2. src/polysignal_lab/app/scheduler_reporting.py is still oversized at 456 pure LOC. The file was already oversized before this rerun baseline (415 pure LOC from `git show HEAD:`), so this is structural debt rather than a blocker for the narrow callable fix.

## Verification

- Direct cache calls are scoped correctly: `rg` found `nautilus_cache.account()` only at src/polysignal_lab/app/scheduler_reporting.py:305 and `nautilus_cache.positions()` only at src/polysignal_lab/app/scheduler_reporting.py:324, both inside `_report_equity_inputs_from_nautilus_cache`.
- Boundary guard is present: `_report_equity_inputs` checks `_is_nautilus_reporting_cache` before delegating at src/polysignal_lab/app/scheduler_reporting.py:279-290.
- Runtime protocol guard checks callability: src/polysignal_lab/app/scheduler_reporting.py:102-107 requires `account` and `positions` to be callable.
- Tests cover malformed present-but-non-callable attributes: tests/test_nautilus_reporting_cache_source.py:147-160 includes `account=123` and `positions=[]`.
- Inspected red evidence: `.omo/ulw-loop/evidence/paper-r10-protocol-callable-red.txt` shows the pre-fix TypeError on `account=123`.
- Inspected green evidence: `.omo/ulw-loop/evidence/paper-r10-protocol-callable-green.txt` and `.omo/ulw-loop/evidence/paper-r10-reporting-cache-pytest.txt` show the callable protocol test passing.
- Inspected refreshed evidence: focused pytest, full pytest, basedpyright, rg, and diff-check artifacts show pass / 0 errors / no whitespace errors.
- Re-ran targeted pytest: `uv run pytest tests/test_nautilus_reporting_cache_source.py -q` -> 8 passed.
- Re-ran basedpyright on scoped files: `uv run basedpyright src/polysignal_lab/app/scheduler_reporting.py tests/test_nautilus_reporting_cache_source.py` -> 0 errors, 25 warnings.
- Re-ran diff check on scoped files: `git diff --check -- src/polysignal_lab/app/scheduler_reporting.py tests/test_nautilus_reporting_cache_source.py` -> no output, exit 0.
- Manual invalid-cache driver returned `(1000.0, 1000.0, 0)` for missing attributes, non-callable `account`, and non-callable `positions`.

## remove-ai-slops / overfit review

The new test is not deletion-only and does not merely verify a removal. It exercises observable behavior of `_report_equity_inputs`: malformed cache shapes return the baseline equity tuple instead of crashing. It is not tautological because reverting the guard reproduces the TypeError shown in the red evidence.

No unnecessary parsing/extraction/normalization was added for this specific boundary. The callable TypeGuard is production logic at the trust boundary between a loose scheduler object and the helper that directly invokes cache methods.

## Final

Previous blockers are cleared. No CRITICAL or HIGH findings remain.
