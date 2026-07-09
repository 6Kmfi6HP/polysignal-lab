# Paper Nautilus Alignment Code Review

codeQualityStatus: BLOCK
recommendation: REQUEST_CHANGES
reportPath: .omo/evidence/paper-code-review.md

## Scope Reviewed

- Current dirty worktree in `/home/debian/polysignal-lab`.
- Focused on the paper/Nautilus row-alignment refactor and parent edits in:
  - `tests/test_scheduler_cancelled_markets.py`
  - `tests/test_scheduler_settlement_resolution.py`
  - `src/polysignal_lab/app/_settlement_check.py`
  - `src/polysignal_lab/app/scheduler_reporting.py`
  - `src/polysignal_lab/domain/paper_result.py`
  - `src/polysignal_lab/storage/sqlite_store.py`
  - `scripts/repair_settlement_results.py`

## Skill-Perspective Check

- Ran the required `remove-ai-slops` perspective by loading `/home/debian/.codex/plugins/cache/sisyphuslabs/omo/4.16.0/skills/remove-ai-slops/SKILL.md`.
- Ran the required `programming` perspective by loading `/home/debian/.codex/plugins/cache/sisyphuslabs/omo/4.16.0/skills/programming/SKILL.md` and `references/python/README.md`.
- Violations found:
  - `programming`: the refactor relies on `object`, `Any`, and `cast` in scheduler/reporting boundaries and fails basedpyright.
  - `remove-ai-slops`: production row parsing/normalization and broad dict conversion add maintenance cost, while tests do not cover the repair backfill path that now emits invalid rows.
  - Focused scheduler tests were not deletion-only and were not obviously tautological; the dict row assertions in the two named tests match the stated new row-access contract.

## Evidence

- `git diff --check && .venv/bin/python -m compileall -q src tests`: PASS.
- `.venv/bin/pytest -q tests/test_scheduler_cancelled_markets.py tests/test_scheduler_settlement_resolution.py`: PASS, 7 tests.
- `.venv/bin/pytest -q`: PASS in the current worktree.
- `.venv/bin/basedpyright src/polysignal_lab/app/_settlement_check.py src/polysignal_lab/app/scheduler_reporting.py tests/test_scheduler_cancelled_markets.py tests/test_scheduler_settlement_resolution.py`: FAIL, 41 errors / 243 warnings.
- `.venv/bin/basedpyright src/polysignal_lab/domain/paper_result.py src/polysignal_lab/paper/report.py src/polysignal_lab/signal_layer/formatter.py scripts/repair_settlement_results.py`: FAIL, 11 errors / 173 warnings.
- Existing evidence under `.omo/ulw-loop/evidence/paper-*.txt` was inspected; the stored full-pytest evidence is now consistent with current pytest, but the stored basedpyright evidence is still failing.

## CRITICAL

- None.

## HIGH

1. `scripts/repair_settlement_results.py:205` returns a repaired settlement dict without `paper_trade_id`, but `src/polysignal_lab/domain/paper_result.py:90` requires `paper_trade_id` and `src/polysignal_lab/storage/sqlite_store.py:278` parses before inserting. I reproduced `_settle_for_repair(...)` and `parse_paper_trade_result_row(...)`; it fails with `invalid paper_trade_results.paper_trade_id: missing`. The backfill path at `scripts/repair_settlement_results.py:480` will catch the failure and count it, so the offline settlement repair cannot actually persist repaired trade results.

2. The refactor leaves scheduler/reporting APIs typed as `object` while dereferencing scheduler services directly, and the focused type gate is red. Examples: `src/polysignal_lab/app/_settlement_check.py:74`, `src/polysignal_lab/app/_settlement_check.py:262`, `src/polysignal_lab/app/_settlement_check.py:285`, `src/polysignal_lab/app/scheduler_reporting.py:207`, `src/polysignal_lab/app/scheduler_reporting.py:420`, and `src/polysignal_lab/app/scheduler_reporting.py:461`. This violates the programming skill's no-`object` boundary rule and leaves real attribute-access errors rather than a typed scheduler protocol.

3. `src/polysignal_lab/app/scheduler_reporting.py:231` and `src/polysignal_lab/app/scheduler_reporting.py:250` call `nautilus_cache.account()` and `nautilus_cache.positions()` unconditionally even though the function accepts `object`. I reproduced `_report_equity_inputs_from_nautilus_cache(object(), starting_equity=100.0)` and it raises `AttributeError: 'object' object has no attribute 'account'`. The named scheduler tests still construct placeholder caches at `tests/test_scheduler_settlement_resolution.py:72` and `tests/test_scheduler_cancelled_markets.py:97`, but there is no regression test covering the daily-report path with that shape.

## MEDIUM

1. `src/polysignal_lab/paper/report.py:354` does not handle `TradeResultStatus.SPLIT`, while `src/polysignal_lab/domain/paper_result.py:105` explicitly accepts persisted `SPLIT` rows. basedpyright flags `src/polysignal_lab/paper/report.py:361` because `assert_never` can receive `TradeResultStatus.SPLIT`; at runtime a stored split row can crash report generation instead of being counted or skipped consistently.

2. `src/polysignal_lab/storage/sqlite_store.py:350` silently drops invalid `paper_trade_results` rows on read by catching `InvalidPaperTradeResultRow` and continuing at `src/polysignal_lab/storage/sqlite_store.py:354`. These are app-local audit tables, so hiding persisted audit rows during reads can create false-clean reports and makes repair/debugging harder. If strict parsing is required, failure should be explicit at the boundary being repaired, not silently normalized away in generic query access.

3. Scope control is weak for a reviewable Nautilus/paper alignment diff: `git diff --stat` shows 65 tracked files changed plus unrelated untracked orderbook/parser/docs/evidence files. This materially raises regression risk and makes it hard to prove the paper refactor independently, even though current pytest is green.

## LOW

1. Self-reference headers are stale or missing. `src/polysignal_lab/app/scheduler_reporting.py:1` omits several current imports introduced by the refactor, and new untracked files such as `src/polysignal_lab/nautilus_bridge/enum_parser.py:1`, `src/polysignal_lab/nautilus_runtime/node_builder_components.py:1`, and `tests/test_nautilus_enum_parser.py:1` have no project self-reference header at all.

2. Frontend `PaperOrder` / `PaperPosition` TypeScript interfaces remain under `frontend/src/lib/api/types.ts:79` and `frontend/src/lib/api/types.ts:103`. This may be intentional API naming, but if the goal is removal of custom paper classes across all surfaces, the frontend contract still uses the old names.

## Focused Test Notes

- `tests/test_scheduler_cancelled_markets.py:174` and `tests/test_scheduler_cancelled_markets.py:175` correctly changed from object attributes to dict row access.
- `tests/test_scheduler_settlement_resolution.py:113`, `tests/test_scheduler_settlement_resolution.py:159`, and `tests/test_scheduler_settlement_resolution.py:221` use `trade_result_status(...)` rather than stale object attributes.
- `tests/test_scheduler_settlement_resolution.py:174` removed the prior `# type: ignore[union-attr]` and no new `# type: ignore` was found in these focused tests.
- Missing coverage remains for the repair backfill row shape and daily-report cache guard behavior.

## Blockers

- Add a valid `paper_trade_id`/schema-complete row in `scripts/repair_settlement_results.py` before calling `_store_paper_result`, and cover the repair backfill path with a test that would fail on the current missing ID.
- Replace the `object` scheduler/cache boundaries with typed protocols or explicit unions and get the focused basedpyright gates to zero errors.
- Restore guard behavior or typed cache requirements around `nautilus_cache.account()` / `positions()` and add a regression test for absent/placeholder cache methods.
- Decide and encode the intended behavior for persisted `SPLIT` trade results in `PaperReportService`.
