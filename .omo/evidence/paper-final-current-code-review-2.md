verdict: CHANGES_REQUESTED
codeQualityStatus: BLOCK
recommendation: REQUEST_CHANGES
reportPath: .omo/evidence/paper-final-current-code-review-2.md
blockers: ["SQLite paper/daily restore JSON parsing still crashes on valid JSON integers above Python's int digit limit; add boundary coverage and catch/handle that parser failure fail-closed."]

# Paper Final Current Code Review 2

Read-only final code-quality review for the current post-huge-int source. I treated prior evidence as untrusted until inspected, and I wrote only this report artifact.

## Skill-Perspective Coverage

- `remove-ai-slops`: ran. The existing huge-int tests are not deletion-only or tautological, but they are overfit to `10**4000`, which exercises `float(...)` overflow after JSON parsing. They miss a valid persisted JSON integer above Python's configured int digit limit, where `json.loads(...)` raises `ValueError` before the paper parser can fail closed. That false confidence is blocking.
- `programming` Python criteria: ran after loading the Python reference. The current code generally places numeric parsing at JSON/SQLite boundaries and uses typed `InvalidPaperTradeResultRow` for trade rows, but the JSON boundary is incomplete because plain `ValueError` from `json.loads(...)` can escape. Existing `Any`/dynamic row warnings remain non-blocking for this review because the current no-excuse check passes and the concrete blocker is runtime boundary handling.
- `ponytail` minimality: ran. The huge-int float fix is mostly placed in shared helpers rather than per-call guards. The remaining blocker should be fixed at the shared JSON decode boundary, not by adding table-specific scattered catches.

## Verification

- Source inspected: `src/polysignal_lab/domain/paper_report.py`, `src/polysignal_lab/domain/paper_result.py`, `src/polysignal_lab/paper/report_aggregates.py`, `src/polysignal_lab/paper/report.py`, `src/polysignal_lab/storage/sqlite_store.py`, `tests/test_paper_report_boundaries.py`, `tests/test_storage_restore.py`.
- Existing evidence inspected: security review 5, manual QA final 2, huge-int RED/GREEN, focused/full pytest, no-excuse, basedpyright, diff-check, and refs-check artifacts.
- Current focused pytest: `PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider tests/test_paper_report_boundaries.py tests/test_storage_restore.py -q` -> `46 passed`.
- Current no-excuse check over requested 7 files: `no violations in 7 file(s)`.
- Current adversarial parser probe: manually inserted a `paper_trade_results.payload_json` containing a valid JSON integer with 5000 digits, then called `SQLiteStore.query_json("paper_trade_results")` -> `DIGIT_LIMIT_PROBE_FAIL ValueError Exceeds the limit (4300 digits) for integer string conversion...`.

## CRITICAL

None.

## HIGH

1. Persisted JSON with a larger valid integer still crashes restore before the fail-closed parser runs.

   `SQLiteStore.query_json("paper_trade_results")` only catches `json.JSONDecodeError` and `InvalidPaperTradeResultRow` around `json.loads(row["payload_json"])` at `src/polysignal_lab/storage/sqlite_store.py:491` through `src/polysignal_lab/storage/sqlite_store.py:496`. Python can raise a plain `ValueError` while parsing a valid JSON integer whose digit count exceeds the interpreter limit. My direct probe inserted a 5000-digit `entry_price` in `payload_json`; `store.query_json("paper_trade_results")` raised `ValueError` instead of returning `[]`.

   This is the same bug class as the huge-int fix, but one layer earlier than the current tests cover. It also affects the shared daily/system restore branch that catches only `json.JSONDecodeError` at `src/polysignal_lab/storage/sqlite_store.py:501` through `src/polysignal_lab/storage/sqlite_store.py:504`, and wallet restore has the same narrow catch at `src/polysignal_lab/storage/sqlite_store.py:527` through `src/polysignal_lab/storage/sqlite_store.py:530`.

   Required before approval: add a focused regression with a persisted JSON numeric literal above the int digit limit, then make the SQLite JSON decode boundary fail closed for that parser failure.

## MEDIUM

None.

## LOW

None.

## Final Assessment

The current float-conversion huge-int failures shown in the RED artifact are fixed, and the focused suite is green. Approval is blocked because the persisted JSON boundary still leaks the same adversarial integer class before conversion helpers run.
