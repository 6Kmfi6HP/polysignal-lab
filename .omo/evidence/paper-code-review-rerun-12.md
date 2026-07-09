# Paper Code Review Rerun 12

Verdict: PASS
codeQualityStatus: WATCH
recommendation: APPROVE
reportPath: .omo/evidence/paper-code-review-rerun-12.md
blockers: []

Reviewed at: 2026-07-09T09:39:00+02:00
Notepad: /tmp/ulw-20260709-093823.KsH1SC.md

## Scope Inspected

- `src/polysignal_lab/app/scheduler_reporting.py`
- `tests/test_nautilus_reporting_cache_source.py`
- `src/polysignal_lab/domain/paper_result.py`
- `tests/test_storage_restore.py`
- `src/polysignal_lab/storage/sqlite_store.py` because it is the restore/query caller of the paper-trade parser
- `.omo/ulw-loop/evidence/paper-r10-protocol-callable-red.txt`
- `.omo/ulw-loop/evidence/paper-r10-protocol-callable-green.txt`
- `.omo/ulw-loop/evidence/paper-storage-timestamp-red.txt`
- `.omo/ulw-loop/evidence/paper-storage-timestamp-green.txt`
- `.omo/ulw-loop/evidence/paper-storage-restore-pytest.txt`
- `.omo/ulw-loop/evidence/paper-post-r10-focused-rerun.txt`
- `.omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt`
- `.omo/ulw-loop/evidence/paper-post-r10-basedpyright-rerun.txt`
- `.omo/ulw-loop/evidence/paper-post-r10-diff-check.txt`

## Skill-Perspective Check

Ran. I loaded/consulted:

- `remove-ai-slops`: checked tests and production code for deletion-only tests, tautological assertions, implementation-mirroring, needless data extraction/parsing, over-defensive handling, and scope drift.
- `programming` plus Python `README.md`, `error-handling.md`, and `code-smells.md`: checked typed errors, no raw `ValueError` leakage, `Any`/cast escape hatches, oversized files, parse-at-boundary shape, and test relevance.
- Ponytail mode was active from the developer instructions: checked whether the fixes stayed at the smallest useful seam.

Result: no CRITICAL or HIGH violation remains. The diff still carries LOW/WATCH programming debt from explicit `Any`, casts, and oversized source files, but those do not block the two reviewed fixes.

## CRITICAL

None.

## HIGH

None.

## MEDIUM

None.

## LOW

1. `src/polysignal_lab/domain/paper_result.py:88` and `src/polysignal_lab/domain/paper_result.py:142` still use `Mapping[str, Any]` plus a forced `TypedDict` cast after runtime parsing. This violates the strict programming preference against untyped escape hatches, but the parser now raises `InvalidPaperTradeResultRow` and the restore path tests cover malformed numeric, missing-field, malformed-JSON, and malformed-timestamp rows.

2. `src/polysignal_lab/app/scheduler_reporting.py:40` and `src/polysignal_lab/app/scheduler_reporting.py:102` add local protocols and a runtime cache type guard. This is more type scaffolding than Ponytail would normally prefer, but it is not a blocker: the guard is the shared boundary that prevents malformed cache objects from reaching direct `account()` / `positions()` calls.

3. Source files remain oversized by the programming/code-smells perspective: `src/polysignal_lab/app/scheduler_reporting.py` measured 456 pure LOC, `src/polysignal_lab/domain/paper_result.py` 272 pure LOC, and `src/polysignal_lab/storage/sqlite_store.py` 470 pure LOC. `sqlite_store.py` has a `SIZE_OK` marker; the other two should be split before further growth, but this is residual structural debt rather than a blocker for the reviewed regressions.

## Prior Blocker Status

Resolved.

- Callable cache blocker: `src/polysignal_lab/app/scheduler_reporting.py:102-107` now verifies that the cache satisfies the runtime protocol and has callable `account` and `positions` attributes before `src/polysignal_lab/app/scheduler_reporting.py:305` and `src/polysignal_lab/app/scheduler_reporting.py:324` call them.
- Callable cache tests: `tests/test_nautilus_reporting_cache_source.py:147-160` covers missing attributes, non-callable `account`, and non-callable `positions`.
- Callable cache evidence: `.omo/ulw-loop/evidence/paper-r10-protocol-callable-red.txt` shows the pre-fix `TypeError: 'int' object is not callable`; `.omo/ulw-loop/evidence/paper-r10-protocol-callable-green.txt` shows the same test passing.
- Malformed timestamp blocker: `src/polysignal_lab/domain/paper_result.py:127-138` catches `parse_dt` `ValueError` and converts it to `InvalidPaperTradeResultRow`.
- Malformed timestamp restore handling: `src/polysignal_lab/storage/sqlite_store.py:400-408` skips `paper_trade_results` rows that raise `json.JSONDecodeError` or `InvalidPaperTradeResultRow`.
- Malformed timestamp tests: `tests/test_storage_restore.py:233-262` covers both `opened_at` and `closed_at` malformed payload timestamps.
- Malformed timestamp evidence: `.omo/ulw-loop/evidence/paper-storage-timestamp-red.txt` shows the pre-fix raw `ValueError`; `.omo/ulw-loop/evidence/paper-storage-timestamp-green.txt` shows the test passing.

## remove-ai-slops / Overfit Review

The two new regression tests are not deletion-only and do not merely verify removals. They exercise observable behavior: malformed cache objects fall back to the starting-equity tuple, and malformed persisted paper-trade timestamps are excluded from restore/query output instead of raising raw parser exceptions.

The tests are not tautological. Reverting the callable guard reproduces the red `TypeError`, and reverting the timestamp exception conversion reproduces the red `ValueError`. The direct SQLite insertion in `tests/test_storage_restore.py` is appropriate for corrupt persisted rows that cannot be created through the validated public insert path.

No unnecessary production normalization was added for these two fixes. The new parser boundary is required because persisted SQLite JSON is untrusted at restore time.

## Verification

- Inspected all listed evidence artifacts. Artifact paths are present and contain RED/GREEN or PASS output.
- Re-ran focused tests: `uv run pytest tests/test_nautilus_reporting_cache_source.py tests/test_storage_restore.py -q` -> `24 passed`.
- Re-ran full suite: `uv run pytest -q` -> full suite passed with only Nautilus/Pandas deprecation warnings.
- Re-ran scoped typecheck: `uv run basedpyright src/polysignal_lab/app/scheduler_reporting.py tests/test_nautilus_reporting_cache_source.py src/polysignal_lab/domain/paper_result.py tests/test_storage_restore.py src/polysignal_lab/storage/sqlite_store.py` -> `0 errors, 261 warnings, 0 notes`.
- Re-ran diff check: `git diff --check -- src/polysignal_lab/app/scheduler_reporting.py tests/test_nautilus_reporting_cache_source.py src/polysignal_lab/domain/paper_result.py tests/test_storage_restore.py src/polysignal_lab/storage/sqlite_store.py` -> exit 0, no output.
- Manual driver: with `PYTHONPATH=tests`, malformed cache shapes returned `(1000.0, 1000.0, 0)` and a persisted paper-trade row with `opened_at="not-a-date"` was skipped by `query_json("paper_trade_results")`.

## Final

Both previous blockers are cleared. No CRITICAL or HIGH findings remain.
