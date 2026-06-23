# Task 4 Report: Scheduler propagation and execution-quality surfaces

## Status
DONE

## Red/green evidence
- RED 1: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_scheduler_reports.py::test_daily_report_publish_record_written -v` failed before implementation. The first observed failure was `assert report.total_signals == 2` with `0 == 2`, caused by the daily report querying UTC `created_at` dates using the configured local report date. This blocked the brief's new aggregate assertions until the same scheduler path used a configured-timezone UTC day window.
- GREEN 1: same scheduler test passed after scheduler propagated raw `paper_orders` / `paper_fills` payloads, execution assumptions, and used the configured daily window.
- RED 2: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_dashboard.py::test_dashboard_exposes_paper_execution_quality -v` failed with `404` for `/api/paper-orders`.
- GREEN 2: same dashboard test passed after adding `/api/paper-orders`, latest-report execution summary HTML, reject reason rows, and nav link.
- RED 3: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_storage_reporting_publish.py::test_formatter_result_and_daily_messages_are_paper_only -v` failed because the daily message did not contain `Orders  ` / `Rejects ` / `ExecLag `.
- GREEN 3: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_storage_reporting_publish.py::test_formatter_result_and_daily_messages_are_paper_only tests/test_reporting.py::test_daily_report_includes_strategy_win_rate_and_pnl -v` passed: 2 passed, 1 Starlette/httpx deprecation warning.
- Slice: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_reporting.py tests/test_scheduler_reports.py tests/test_storage_reporting_publish.py tests/test_dashboard.py -v` passed: 21 passed, 1 Starlette/httpx deprecation warning.
- Final slice after commits: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_reporting.py tests/test_scheduler_reports.py tests/test_storage_reporting_publish.py tests/test_dashboard.py -v` passed: 21 passed, 1 Starlette/httpx deprecation warning.

## Files changed
- `src/polysignal_lab/app/scheduler_reporting.py`
- `src/polysignal_lab/dashboard/app.py`
- `src/polysignal_lab/signal_layer/formatter.py`
- `tests/test_scheduler_reports.py`
- `tests/test_dashboard.py`
- `tests/test_storage_reporting_publish.py`
- `.superpowers/sdd/task-4-report.md`

## Tests run
- `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_scheduler_reports.py::test_daily_report_publish_record_written -v`
- `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_dashboard.py::test_dashboard_exposes_paper_execution_quality -v`
- `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_storage_reporting_publish.py::test_formatter_result_and_daily_messages_are_paper_only -v`
- `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_storage_reporting_publish.py::test_formatter_result_and_daily_messages_are_paper_only tests/test_reporting.py::test_daily_report_includes_strategy_win_rate_and_pnl -v`
- `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_reporting.py tests/test_scheduler_reports.py tests/test_storage_reporting_publish.py tests/test_dashboard.py -v`
- Final post-commit rerun: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_reporting.py tests/test_scheduler_reports.py tests/test_storage_reporting_publish.py tests/test_dashboard.py -v`

## Commit SHA(s)
- `79a8b2d` — `feat: surface paper execution quality`
- `9108ccd` — `docs: record task 4 report`

## Self-review notes
- Scheduler now sends raw order/fill JSON rows and the configured fill-model/data staleness assumptions into `PaperReportService.build_daily_report(...)`.
- Scheduler daily queries now use the configured app timezone to compute a UTC day window for stored UTC timestamps; this preserves the local report date while avoiding empty daily aggregates around UTC/local date boundaries.
- Dashboard overview returns the persisted latest report with aggregate fields, `/api/paper-orders` is status-filterable and bounded, and the HTML summary exposes fills, rejects, average execution lag, and reject reasons.
- Telegram daily report keeps the compact paper-only format and adds order count, reject summary, and average execution lag.
- The only warning observed is the existing Starlette/httpx `TestClient` deprecation warning.

## DST local-day window fix

### Red/green evidence
- RED: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_scheduler_reports.py::test_daily_report_uses_next_local_midnight_for_dst_day -v` failed before implementation with the Europe/Berlin 2026-03-29 day window ending at `2026-03-29T23:00:00Z` instead of `2026-03-29T22:00:00Z`.
- GREEN: same targeted DST test passed after computing the next local midnight before converting to UTC: 1 passed.
- COVERING: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_scheduler_reports.py -v` passed: 6 passed.
- SLICE: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_reporting.py tests/test_scheduler_reports.py tests/test_storage_reporting_publish.py tests/test_dashboard.py -v` passed: 22 passed, 1 existing Starlette/httpx deprecation warning.

### Commit SHA
- `b4cdfcba21ec92a6837177a8cd8a85c5b1542b9a` — `fix: handle dst daily report window`

### Notes
- `generate_daily_report` now computes `day_end` from the next configured-timezone local midnight, so DST-short and DST-long local report days use the correct UTC bounds.
