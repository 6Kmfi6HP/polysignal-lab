# Todo 14 Self-Review

## Paper-Only Exits
- `PolySignalScheduler._initialize_trading_components()` now owns a `PaperExitEngine` built from `settings.paper_trading.exit_model`.
- `scheduler_reporting.check_settlements()` evaluates open paper positions against `scheduler.ctx.books.get(position.token_id)` for active/closed/unknown markets, so TP/SL/max-hold use the current orderbook best bid.
- Exit results call `PaperWallet.close_position()` through the paper exit engine only. No CLOB secure client, private key, submit/cancel/redeem, or order-placement path was introduced.
- Grep proof: no matches for `SecureClient|AsyncSecureClient|ClobClient\(|create_order|post_order|submit_order|cancel_order|cancel_all|redeem_positions|private_key|sell` in the touched runtime scope.

## Settlement States
- Hold-to-resolution settlement remains routed through `PaperSettlementEngine` for CANCELLED and RESOLVED markets.
- CANCELLED markets settle VOID and close/refund positions.
- RESOLVED markets with missing outcome classify UNKNOWN in the settlement engine, remain retriable, and are not persisted as a closed scheduler result.
- PRD-facing state set is protected by tests as exactly `{"WIN", "LOSS", "VOID", "UNKNOWN"}`. `SPLIT` appears only in protective test assertions.

## Report Math
- Daily report metrics now derive closed metrics from WIN/LOSS/VOID only.
- UNKNOWN results are excluded from closed count, win rate denominator, PnL, ROI average, profit factor, and strategy/asset/timeframe breakdowns.
- Win rate follows PRD `win / closed` semantics, so VOID closed outcomes remain visible in the denominator.
- Tests assert stored counts for signals, paper orders, fills, rejected orders, open/closed positions, win/loss/void counts, PnL/ROI, profit factor, and breakdown rows.

## Storage And Publish Records
- Paper exits and settlements append `paper_results`, upsert `paper_positions`, insert `paper_trade_results`, and, when enabled, write `telegram_publishes`.
- Daily reports append `daily_reports`, insert `daily_reports`, and, when enabled, write a `telegram_publishes` row with `message_type == "daily_report"`.
- Scheduler tests assert the durable SQLite rows rather than relying on return values alone.

## Storage False-Success Repair
- Gate reviewer `019eedee-7432-7fb2-abe4-498b95d345e6` identified two catch-and-continue false-success paths: paper result persistence after `PaperExitEngine.evaluate()` mutates wallet/position state, and daily report persistence/publish-row failures after building a report.
- Paper result success contract is now explicit: a normal settled result is returned only after required durable SQLite rows succeed (`paper_trade_results`, updated `paper_positions`, and enabled `telegram_publishes`). `_store_paper_result()` raises `SchedulerPersistenceError` on required persistence failure, and `check_settlements()` catches only that local exception, restores the captured wallet/position state, logs the failure, and does not append/return the result.
- Paper persistence now writes the enabled publish row before `paper_trade_results` and writes the updated `paper_positions` row last. That order lets failure cleanup remove partial result/publish rows while leaving the pre-existing durable position OPEN if publish-row or result persistence fails.
- The paper rollback tests force `insert_paper_trade_result` and `insert_telegram_publish` to raise after the TP exit path would close the position. They assert `results == []`, no `paper_trade_results`, persisted `paper_positions` remains `OPEN`, no Telegram publish row, position status/closed_at restored, wallet open count restored, and cash/realized PnL unchanged where applicable.
- Daily report success contract is now explicit: when `send_daily_report` is enabled, both `daily_reports` and the required Telegram publish row must persist before `generate_daily_report()` returns a report. If either required row fails, the function returns `None`, preventing runtime from advancing `last_report_date`.
- The daily report false-success test forces `insert_telegram_publish` to raise and asserts `report is None`, no `daily_reports`, and no `telegram_publishes`.
- Cleanup helpers are scoped to `scheduler_reporting_storage.py` and remove partial SQLite rows for the affected persistence attempts; JSONL log writes happen only after required SQLite rows succeed.

## Slop And Overfit Risks
- New tests target public domain/scheduler behavior and SQLite rows, not private helper internals.
- No broad refactor was performed in shared dirty files.
- The new failure tests monkeypatch the existing SQLite adapter methods that define the durable-write contract; they do not assert private helper names or implementation order.
- Touched pure LOC is below 250 for each file after repair: `scheduler_reporting.py` 229, `scheduler_reporting_storage.py` 48, `test_scheduler_reports.py` 197.
- BDD comments in new tests were intentional Given/When/Then markers required by the Python test discipline.
