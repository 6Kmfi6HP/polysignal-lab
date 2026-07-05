# Task 7 Report: Nautilus observability/reporting projection-only boundary

## Status
DONE

## Scope Completed
- Added `test_nautilus_observability_has_no_paper_model_recording_api` to `tests/test_nautilus_platform_boundary.py` with the Task 7 forbidden-token boundary assertions.
- Verified `src/polysignal_lab/nautilus_runtime/observability.py` has no remaining paper model recording API imports, methods, or mirror/notifier symbols covered by the Task 7 boundary.
- Verified `tests/test_nautilus_observability.py` has no remaining tests calling removed local paper recording APIs.
- Replaced `generate_daily_report()` Nautilus order/fill fallback so it reads `scheduler.nautilus_cache_reader.read_orders()` / `read_fills()` and filters projection rows to the report day using `ts`/`created_at` timestamps.
- Left existing `scheduler.nautilus_cache_reader.read_positions()` reporting path in place for open-position/equity projection reporting.
- Removed the persisted `system_events` `_query_nautilus_projection_rows()` fallback from `scheduler_reporting.py`.
- Retargeted the scheduler report test to prove report-day order/fill counts and intent buckets come from live Nautilus cache reader projections, that prior-day projection rows are filtered out, and that drained same-day persisted `system_events` Nautilus events are ignored.

## Verification
- RED check before implementation: `uv run pytest tests/test_scheduler_reports.py::test_daily_report_uses_nautilus_cache_reader_projection_rows -q` failed with `assert report.paper_orders == 1` while the old persisted-system-events fallback ignored `scheduler.nautilus_cache_reader` rows.
- Boundary test: `uv run pytest tests/test_nautilus_platform_boundary.py::test_nautilus_observability_has_no_paper_model_recording_api -q` passed.
- Task 7 test command: `uv run pytest tests/test_nautilus_platform_boundary.py::test_nautilus_observability_has_no_paper_model_recording_api tests/test_nautilus_observability.py tests/test_scheduler_reports.py -q` passed: `47 passed`.
- Compile command: `uv run python -m py_compile src/polysignal_lab/nautilus_runtime/observability.py src/polysignal_lab/app/scheduler_reporting.py` passed with no output.
- Targeted grep checks found no Task 7 forbidden observability tokens, no removed paper recording API calls in `tests/test_nautilus_observability.py`, and no `_query_nautilus_projection_rows` / deleted Nautilus execution/matching/orchestrator imports in `scheduler_reporting.py`.

## Concerns
- Worktree contains pre-existing unrelated changes outside Task 7 scope (`.superpowers/sdd/progress.md`, task 1/4/5/6 reports, and an untracked plan file). They were not modified for Task 7 and should not be included in the Task 7 commit.
