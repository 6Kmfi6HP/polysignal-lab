# Post-Final-Fix Paper Reporting/Storage Refactor Code Review

Verdict: FAIL

codeQualityStatus: BLOCK
recommendation: REQUEST_CHANGES

Skill-perspective check: ran. Loaded and applied `programming` with Python reference, `remove-ai-slops`, `refactor`, and `ponytail`. The diff violates the programming/remove-ai-slops/ponytail perspectives because boolean numeric coercion still exists in shared paper reporting helpers, and a modified paper-reporting test module is over the 250 pure-LOC no-excuse limit.

## CRITICAL

None.

## HIGH

1. Boolean numeric coercion remains in the paper reporting shared row helpers.

Evidence:
- `src/polysignal_lab/domain/paper_result.py:107` defines `trade_result_float`.
- `src/polysignal_lab/domain/paper_result.py:109` accepts `bool` because `bool` is an `int` subclass.
- `src/polysignal_lab/domain/paper_result.py:110` converts `True` to `1.0` and `False` to `0.0`.
- `src/polysignal_lab/paper/report.py:68` uses `trade_result_float` for report total PnL.
- `src/polysignal_lab/paper/report.py:69` uses `trade_result_float` for average ROI.
- `src/polysignal_lab/paper/report.py:116` emits the coerced value into `DailyReport.total_pnl_usdc`.
- `src/polysignal_lab/paper/strategy_stats.py:41` uses the same helper for strategy leaderboard PnL.
- `src/polysignal_lab/paper/strategy_stats.py:42` uses the same helper for strategy leaderboard ROI.
- `src/polysignal_lab/paper/report_aggregates.py:84` and `src/polysignal_lab/paper/report_aggregates.py:85` also coerce boolean confidence through `float(confidence or 0.0)`.
- `src/polysignal_lab/domain/paper_report.py:78` through `src/polysignal_lab/domain/paper_report.py:81` preserve the same bool-to-float pattern for report/wallet display helpers.

Current runtime proof:

```text
trade_result_float_bool_true= 1.0
trade_result_float_bool_false= 0.0
report_total_pnl_usdc= 1.0
report_average_roi= 0.0
calibration_keys= ['ptb_diff|BTC|5m|high']
```

Impact: the storage insert/restore tests reject boolean money rows, but `PaperReportService` and `build_strategy_leaderboard_rows` still accept direct row mappings and silently turn boolean numeric fields into money/ROI. That fails the requested "no bool coercion remains in paper report/storage scope" criterion and leaves the behavior unlocked by tests.

2. The current no-excuse scope omits a modified paper-reporting test file that violates the oversized-module rule.

Evidence:
- `git diff --numstat` shows `tests/test_reporting.py` is modified with `43` additions and `18` deletions.
- `tests/test_reporting.py:251` adds `test_daily_report_normalizes_legacy_raw_paper_reject_reason`.
- `tests/test_reporting.py:278` adds `test_daily_report_counts_cancelled_rejects_with_reasons`.
- Running the no-excuse checker over the current paper report/storage review scope including this modified file fails:

```text
/home/debian/polysignal-lab/tests/test_reporting.py:1:1: [oversized-module] 262 pure LOC (limit: 250) - split by responsibility
1 violation(s) in 8 file(s)
```

Impact: the provided `paper-final-no-excuse.txt` passes only the 15-file scoped set that excludes `tests/test_reporting.py`. Since this file is actually modified in the paper reporting boundary, the no-excuse gate is incomplete for the current review scope.

## MEDIUM

1. Import ownership is not fully coherent after the extraction.

Evidence:
- `src/polysignal_lab/paper/strategy_stats.py:9` imports private `_is_closed_result` from `polysignal_lab.paper.report`.
- `src/polysignal_lab/paper/report.py:32` imports `is_closed_result as _is_closed_result` from the actual concept module.

Impact: `strategy_stats.py` now depends on a private alias re-exported through `report.py` instead of importing the concept directly from `report_aggregates.py`. This is a small boundary leak, not the main blocker.

## LOW

1. Type strictness remains weak in the new row-based surface.

Evidence:
- `uv run basedpyright` over the reviewed files returns `0 errors, 296 warnings, 0 notes`.
- Warnings include explicit `Any` in `src/polysignal_lab/domain/paper_result.py`, `src/polysignal_lab/paper/report.py`, `src/polysignal_lab/paper/report_aggregates.py`, `src/polysignal_lab/paper/report_rejections.py`, and `src/polysignal_lab/storage/sqlite_store.py`.

Impact: this is consistent with the current dynamic row-boundary refactor, so I am not making it a blocker by itself. It still violates the strict programming perspective and keeps the boundary harder to reason about.

## Verified Passing Evidence

- Focused behavior tests passed: `uv run pytest tests/test_storage_restore.py::test_sqlite_store_rejects_boolean_money_paper_trade_rows tests/test_storage_restore.py::test_sqlite_store_excludes_open_position_events_with_boolean_money tests/test_paper_report_boundaries.py tests/test_reporting.py::test_daily_report_aggregates_paper_execution_quality tests/test_reporting.py::test_daily_report_normalizes_legacy_raw_paper_reject_reason tests/test_reporting.py::test_daily_report_counts_cancelled_rejects_with_reasons tests/test_paper_calibration.py::test_calibration_buckets_use_signal_confidence_from_paper_flow` -> `8 passed`.
- Evidence artifacts inspected under `.omo/ulw-loop/evidence/`: paper bool-money red/green, report-boundaries red/green, final focused/full pytest, final no-excuse, basedpyright, compileall, diff-check, refs-check, import-rg, loc, scope-note.
- `uv run /home/debian/.codex/plugins/cache/sisyphuslabs/omo/4.16.0/skills/programming/scripts/python/check-no-excuse-rules.py` over the provided 15-file final scope reports `no violations in 15 file(s)`.
- `uv run python -m compileall -q` over reviewed source/tests passed.
- `git diff --check` over reviewed source/tests passed.
- `git diff --name-only -- refs docs/nautilus_reference` produced no protected-path changes.
- `rg` found no remaining `report_helpers` imports in `src`/`tests`.

## Blockers

- Fix boolean numeric coercion in the shared report helpers used by paper reports and strategy stats, then add a focused regression proving boolean result money/ROI/confidence does not become `1.0` or `0.0` in report output.
- Include `tests/test_reporting.py` in the no-excuse scope or move the new paper rejection tests into a smaller focused module so the modified test surface stays under 250 pure LOC.

## Recommendation

REQUEST_CHANGES. The storage-specific bool money fix is green, but the reporting side still has a live bool-to-money path and the scoped no-excuse evidence misses a modified oversized test file.
