# Todo 14 Manual QA Notepad

## Happy Scenario
- Scenario: TP/SL/max-hold exits and daily report strategy/PnL math.
- Invocation: `.venv/bin/python -m pytest tests/test_exit_engine.py::test_take_profit_stop_loss_and_max_hold_exits tests/test_reporting.py::test_daily_report_includes_strategy_win_rate_and_pnl -q`
- Output summary: `.. [100%]`
- Binary observable: exit code 0.
- Assertions covered: TAKE_PROFIT/STOP_LOSS/MAX_HOLD_TIME, WIN/LOSS states, paper exit price from best bid, wallet open-position count zero, closed position status, report signals/orders/fills/rejections/open/closed counts, win/loss/void counts, win rate, PnL, ROI, profit factor, strategy/asset/timeframe breakdowns, no SPLIT in report message.

## Failure Scenario
- Scenario: UNKNOWN outcome remains retriable and daily report Telegram publish row is persisted.
- Invocation: `.venv/bin/python -m pytest tests/test_settlement.py::test_unknown_outcome_does_not_inflate_win_rate tests/test_scheduler_reports.py::test_daily_report_publish_record_written -q`
- Output summary: `.. [100%]`
- Binary observable: exit code 0.
- Assertions covered: UNKNOWN result, open position remains OPEN, wallet exposure remains open, UNKNOWN excluded from closed report count/PnL/win rate inflation, daily report row persisted, Telegram publish row persisted as `("daily_report", "DRY_RUN")`, stale paper fills remains 0.

## Full Acceptance
- Scenario: complete Todo 14 acceptance suite.
- Invocation: `.venv/bin/python -m pytest tests/test_exit_engine.py tests/test_settlement.py tests/test_reporting.py tests/test_scheduler_reports.py -q`
- Output summary: `........... [100%]`
- Binary observable: exit code 0, 11 tests passed.

## Storage False-Success Repair
- Scenario: paper exit result storage failure, paper publish-row persistence failure after TP evaluation, and daily report publish-row persistence failure.
- Invocation: `.venv/bin/python -m pytest tests/test_scheduler_reports.py::test_paper_exit_storage_failure_rolls_back_and_returns_no_success tests/test_scheduler_reports.py::test_paper_exit_publish_row_failure_rolls_back_without_closed_rows tests/test_scheduler_reports.py::test_daily_report_publish_row_failure_returns_no_report -q`
- Output summary: `... [100%]`
- Binary observable: exit code 0, 3 tests passed.
- Assertions covered: failed paper result/publish-row storage returns no settled result, creates no `paper_trade_results`, keeps persisted `paper_positions` OPEN, creates no Telegram publish row, restores in-memory position/wallet state; failed daily report publish-row persistence returns `None` and creates no `daily_reports` or Telegram publish rows.

## Safety Checks
- No real trading grep: no matches for authenticated client/order-placement/private-key/sell terms in touched runtime scope.
- SPLIT grep: only protective test assertions in `tests/test_settlement.py` and `tests/test_reporting.py`.
- Compileall: `.venv/bin/python -m compileall -f src/polysignal_lab/app/scheduler_reporting.py src/polysignal_lab/app/scheduler_reporting_storage.py tests/test_scheduler_reports.py` exited 0.
- Cleanup: no long-lived processes started; pytest tmp paths used for DB/log artifacts.
