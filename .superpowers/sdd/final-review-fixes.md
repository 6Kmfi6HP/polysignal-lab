# Final Review Fixes

## 2026-06-23 report reject normalization

- Finding: daily paper report aggregation used raw legacy `order.reject_reason` as `paper_rejects_by_reason` when `metrics.paper_normalized_reason` was absent.
- Fix: `PaperReportService._paper_execution_aggregates` now normalizes the metrics/raw fallback with `normalize_paper_reject_reason()` while preserving raw legacy values in `paper_rejects_by_original_reason`.
- Red: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_reporting.py -v` failed with `{'ASK_ABOVE_MAX_ENTRY': 1}` instead of `{'PAPER_ENTRY_PRICE_MOVED': 1}` for `test_daily_report_normalizes_legacy_raw_paper_reject_reason`.
- Green: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_reporting.py -v` passed with `3 passed in 0.03s`.
- Fix commit: `be25c47f6b88555ea613fa52b389ea26fc7763d7`.
