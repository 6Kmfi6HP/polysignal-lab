# Final Review Fixes

## 2026-06-23 report reject normalization

- Finding: daily paper report aggregation used raw legacy `order.reject_reason` as `paper_rejects_by_reason` when `metrics.paper_normalized_reason` was absent.
- Fix: `PaperReportService._paper_execution_aggregates` now normalizes the metrics/raw fallback with `normalize_paper_reject_reason()` while preserving raw legacy values in `paper_rejects_by_original_reason`.
- Red: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_reporting.py -v` failed with `{'ASK_ABOVE_MAX_ENTRY': 1}` instead of `{'PAPER_ENTRY_PRICE_MOVED': 1}` for `test_daily_report_normalizes_legacy_raw_paper_reject_reason`.
- Green: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_reporting.py -v` passed with `3 passed in 0.03s`.
- Fix commit: `be25c47f6b88555ea613fa52b389ea26fc7763d7`.

## 2026-06-23 cancelled resting rejection persistence

- Finding: `tick_resting_orders()` only normalized/upserted `REJECTED` resting results; cancelled PASSIVE_GTD results with `GTD_EXPIRED` or `WALLET_INSUFFICIENT_CASH` kept the persisted paper order at `RESTING` and hid the normalized `PAPER_*` reason metrics from reports/dashboard.
- Fix: cancelled resting results that carry a reject reason now use the same normalization, paper-order upsert, wallet-snapshot insert, and strategy cancel notification path as rejected resting results.
- Red: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_scheduler_paper.py::test_cancelled_resting_gtd_expiry_is_persisted_with_normalized_reason -v` failed with `AssertionError: assert 'GTD_EXPIRED' == 'PAPER_GTD_EXPIRED'` before the production fix.
- Green: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_scheduler_paper.py tests/test_resting_orders.py -v` passed with `23 passed in 0.49s`.
- Fix commit: `5d269924067eb58643fd1ab196a72c582e5031ff`.
