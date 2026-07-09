# Paper Final Current Security Review

Verdict: CHANGES_REQUESTED
codeQualityStatus: BLOCK
recommendation: REQUEST_CHANGES
reportPath: .omo/evidence/paper-final-current-security-review.md

## Scope

Reviewed the current working tree for the requested paper/reporting/storage boundary files:

- `src/polysignal_lab/storage/sqlite_store.py`
- `src/polysignal_lab/domain/paper_result.py`
- `src/polysignal_lab/domain/paper_report.py`
- `src/polysignal_lab/paper/report.py`
- `src/polysignal_lab/paper/report_aggregates.py`
- `src/polysignal_lab/paper/report_rejections.py`
- `src/polysignal_lab/app/scheduler_reporting_build.py`
- `src/polysignal_lab/app/scheduler_reporting_sources.py`
- `tests/test_storage_restore.py`
- `tests/test_paper_report_boundaries.py`

Protected `refs`, `@refs`, and `docs/nautilus_reference` were not modified. Source was not modified by this review. Current source changed while this review was running; stale findings were revalidated after the latest observed source mtimes around 2026-07-09 13:29 local time.

## Skill-Perspective Check

- `remove-ai-slops` consulted: yes, loaded from `/home/debian/.codex/plugins/cache/sisyphuslabs/omo/4.16.1/skills/remove-ai-slops/SKILL.md`. Current tests are adversarial behavior tests, not deletion-only tests, tautologies, or tests that merely assert a requested removal. The remaining violation is missing adversarial coverage for incomplete `CLOSED` position restores.
- `programming` consulted: yes, loaded from `/home/debian/.codex/plugins/cache/sisyphuslabs/omo/4.16.1/skills/programming/SKILL.md`, plus the Python README. Current finite-number parsing is now applied in the trade/report/wallet/daily paths, but the closed-position restore boundary still passes unparsed JSON dictionaries through as valid domain state.
- Diff/perspective result: no needless production extraction/parsing was found in the current boundary fixes; the new validation is at storage/reporting boundaries. `sqlite_store.py` and `tests/test_storage_restore.py` are oversized but carry `SIZE_OK` comments; not the approval blocker for this scoped security review.

## Verification

- Existing evidence inspected:
  - `.omo/ulw-loop/evidence/paper-final-focused-pytest.txt`
  - `.omo/ulw-loop/evidence/paper-final-full-pytest.txt`
  - `.omo/ulw-loop/evidence/paper-final-debug-audit.md`
  - `.omo/ulw-loop/evidence/paper-storage-closed-wallet-green.txt`
  - `.omo/ulw-loop/evidence/paper-report-boundaries-green.txt`
- Current focused run: `pytest tests/test_storage_restore.py tests/test_paper_report_boundaries.py` -> `39 passed in 0.44s`.
- Current full run: plain `pytest` fails in the system Python because `nautilus_trader` is absent; `uv run pytest` is the project runner and passed with `714 passed, 2 warnings in 10.83s`.
- Current adversarial probes:
  - Valid-JSON hostile daily reports with bool/NaN/Infinity now restore as `[]` and leaderboard as `[]`.
  - Direct report inputs with non-finite PnL/ROI/depth now default to `0.0`/`None`.
  - Incomplete closed-position restore still returns a row:
    `[{..., 'paper_position_id': 'pos-closed-incomplete', 'status': 'CLOSED'}]`.

## CRITICAL

None.

## HIGH

1. `restore_closed_positions()` still accepts incomplete `CLOSED` position events as valid restored state.

   Current `_valid_position_event()` only requires side, positive money fields, and a timestamp when `is_open` is true (`src/polysignal_lab/storage/sqlite_store.py:81-93`). For non-open rows, it only rejects money fields if they are present and invalid (`src/polysignal_lab/storage/sqlite_store.py:94-101`). `restore_closed_positions()` then returns any latest event whose status is `CLOSED` or `is_closed is True` (`src/polysignal_lab/storage/sqlite_store.py:541-548`).

   I revalidated with the current source by inserting a persisted `nautilus_position` event containing only `paper_position_id`, `status=CLOSED`, `is_closed=True`, and metadata. `restore_closed_positions()` returned that incomplete row instead of failing closed. That violates the requested missing side/timestamp and malformed persisted-row checks, and it can expose an un-settleable position as restored state.

   Existing tests cover closed rows with zero money when those fields are present (`tests/test_storage_restore.py:622-654`) but do not cover a `CLOSED` row with side/money/timestamps absent. This is a real gap, not a stale prior finding.

## MEDIUM

None.

## LOW

1. Plain `pytest` is misleading in this checkout because it uses the system Python and fails on missing `nautilus_trader`; the verified project command is `uv run pytest`. This is not a product defect, but future evidence artifacts should include the exact runner.

## Requested Case Matrix

- bool-as-number: PASS for paper trade rows, open/closed position money when present, report helpers, execution metrics, wallet/daily restore payloads, and rejection reasons.
- NaN/inf: PASS for paper trade rows, report helpers, execution metrics, wallet restore, and daily report/leaderboard restore.
- zero/negative money: PASS for paper trade rows and position money fields when present; BLOCKED for closed positions with required money fields absent.
- missing/invalid side/timestamps: PASS for open positions and paper trade rows; BLOCKED for closed positions with side/timestamps absent.
- malformed JSON in wallet snapshots/trade rows: PASS.
- non-string rejection reasons: PASS.
- malformed persisted rows crash/query/fabricate-money surfaces: BLOCKED for incomplete `CLOSED` position rows returned by `restore_closed_positions()`.

## Blockers

- Add fail-closed validation for `CLOSED`/`is_closed=True` position events so `restore_closed_positions()` rejects rows missing required side, positive money fields, and a valid closed/open timestamp set.
- Add a focused adversarial test for a persisted incomplete closed position event, parallel to the existing open-position missing timestamp/side and closed-position zero-money tests.

