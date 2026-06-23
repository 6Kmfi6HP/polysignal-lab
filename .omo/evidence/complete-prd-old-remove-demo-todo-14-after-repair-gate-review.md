recommendation: APPROVE

blockers: []

originalIntent:
- Todo 14 should remove the old demo-facing behavior by wiring paper-only TP/SL/max-hold exits into scheduler settlement/reporting, preserving cancelled/resolved settlement, keeping UNKNOWN retriable, persisting paper result/report/publish rows, and exposing only PRD result states WIN/LOSS/VOID/UNKNOWN.
- The after-repair gate specifically needed to verify that storage/publish failures no longer create false success after paper wallet/position state has been mutated.

desiredOutcome:
- Active, closed, and unknown markets with open paper positions are evaluated against current orderbook best bid for paper exits without placing real sell/order operations.
- Resolved and cancelled markets still settle through the settlement engine; UNKNOWN remains open and does not inflate report metrics.
- Paper result and daily report Telegram publish rows are durable when enabled.
- If required paper result, position, report, or enabled publish-row persistence fails, the caller does not receive normal success and partial durable rows are cleaned up.
- Daily report metrics derive from stored signals/orders/fills/rejected/results rows, preserve stale_paper_fills == 0, and keep SPLIT out of PRD-facing source output paths.

userOutcomeReview:
- CONFIRM. Current disk state satisfies the repaired Todo 14 outcome.
- `src/polysignal_lab/app/scheduler_reporting.py` now raises `SchedulerPersistenceError` from `_store_paper_result()` on required paper result, position, or enabled publish-row persistence failure. `check_settlements()` catches only that local persistence error, restores wallet cash, realized PnL, position status, position closed_at, and open-position membership, then returns no settled result for that position.
- `generate_daily_report()` now returns `None` if report publishing fails before row persistence, or if `daily_reports` / enabled `telegram_publishes` row persistence fails. Runtime only advances `last_report_date` when a non-None report is returned.
- `src/polysignal_lab/app/scheduler_reporting_storage.py` uses SQLiteStore internals only for scoped compensating deletes by `paper_trade_id`, `report_id`, and `publish_id`. It does not perform broad table cleanup.
- JSONL log writes for paper results, daily reports, and Telegram publishes occur only after required SQLite rows succeed.
- The new regression tests assert public scheduler behavior and durable rows: no returned success, open durable/in-memory position state, no result/publish/report rows, and wallet rollback. They do not merely assert private helper calls.

checkedArtifactPaths:
- `.omo/evidence/task-14-complete-prd-old-remove-demo.txt`
- `.omo/evidence/complete-prd-old-remove-demo-todo-14-code-review.md`
- `.omo/evidence/todo-14-manual-qa-notepad.md`
- `.omo/evidence/complete-prd-old-remove-demo-todo-14-gate-review.md`
- `src/polysignal_lab/app/scheduler_reporting.py`
- `src/polysignal_lab/app/scheduler_reporting_storage.py`
- `src/polysignal_lab/app/scheduler.py`
- `src/polysignal_lab/app/scheduler_runtime.py`
- `src/polysignal_lab/paper/exit_engine.py`
- `src/polysignal_lab/paper/settlement.py`
- `src/polysignal_lab/paper/report.py`
- `src/polysignal_lab/paper/wallet.py`
- `src/polysignal_lab/domain/enums.py`
- `src/polysignal_lab/domain/paper_result.py`
- `src/polysignal_lab/storage/sqlite_store.py`
- `tests/test_exit_engine.py`
- `tests/test_settlement.py`
- `tests/test_reporting.py`
- `tests/test_scheduler_reports.py`

commandsRun:
- `find . -path './.venv' -prune -o -path './.git' -prune -o -name AGENTS.md -print` -> no repo-scoped AGENTS.md found.
- `.venv/bin/python -m pytest tests/test_exit_engine.py tests/test_settlement.py tests/test_reporting.py tests/test_scheduler_reports.py -q` -> PASS, 11 passed.
- `.venv/bin/python -m pytest tests/test_exit_engine.py::test_take_profit_stop_loss_and_max_hold_exits tests/test_reporting.py::test_daily_report_includes_strategy_win_rate_and_pnl -q` -> PASS, 2 passed.
- `.venv/bin/python -m pytest tests/test_settlement.py::test_unknown_outcome_does_not_inflate_win_rate tests/test_scheduler_reports.py::test_daily_report_publish_record_written -q` -> PASS, 2 passed.
- `.venv/bin/python -m pytest tests/test_scheduler_reports.py::test_paper_exit_storage_failure_rolls_back_and_returns_no_success tests/test_scheduler_reports.py::test_paper_exit_publish_row_failure_rolls_back_without_closed_rows tests/test_scheduler_reports.py::test_daily_report_publish_row_failure_returns_no_report -q` -> PASS, 3 passed.
- `PYTHONPYCACHEPREFIX=$(mktemp -d) .venv/bin/python -m compileall -q src/polysignal_lab/app/scheduler_reporting.py src/polysignal_lab/app/scheduler_reporting_storage.py tests/test_scheduler_reports.py` -> PASS, temp pycache removed.
- `rg -n "SecureClient|AsyncSecureClient|ClobClient\\(|create_order|post_order|submit_order|cancel_order|cancel_all|redeem_positions|private_key|sell" src/polysignal_lab/app/scheduler.py src/polysignal_lab/app/scheduler_runtime.py src/polysignal_lab/app/scheduler_reporting.py src/polysignal_lab/app/scheduler_reporting_storage.py src/polysignal_lab/paper tests/test_exit_engine.py tests/test_settlement.py tests/test_reporting.py tests/test_scheduler_reports.py` -> no matches, expected `rg` exit 1.
- `rg -n "SPLIT" src tests` -> only protective assertions in `tests/test_settlement.py:80` and `tests/test_reporting.py:105`.
- `find . -path './.git' -prune -o -path './.venv' -prune -o -path './.pytest_cache' -prune -o -path './.mypy_cache' -prune -o \( -name '*.sqlite' -o -name '*.sqlite3' -o -name '*.db' -o -name '*.db-journal' -o -name '*.sqlite-journal' \) -print` -> no repo runtime SQLite artifacts found.
- `ps -eo pid=,comm=,args= | awk '$2 != "zsh" && $2 != "awk" && $0 ~ /pytest/ {print}'` -> no long-lived pytest processes.
- `ps -eo pid=,comm=,args= | awk '$2 != "zsh" && $2 != "awk" && ($0 ~ /polysignal_lab/ || $0 ~ /run_scheduler/ || $0 ~ /uvicorn.*polysignal/ || $0 ~ /gunicorn.*polysignal/) {print}'` -> no long-lived app processes after compileall completed.
- Pure LOC: `scheduler_reporting.py 229`, `scheduler_reporting_storage.py 48`, `tests/test_scheduler_reports.py 197`; all below the 250 pure LOC ceiling.

adversarialClasses:
- dirty_worktree: Present. `git status --short` shows many unrelated modified/deleted/untracked files and the reviewed Todo 14 files are untracked. Review was scoped to current disk state for Todo 14 and directly relevant runtime/support files; no unrelated files were reverted.
- stale_state: Current on-disk code was inspected through Codegraph and shell artifacts, then all required tests were rerun from current disk.
- misleading_success_output: Pass. Paper persistence failure raises a local error, rolls back in-memory state, and does not append/return success. Daily report persistence failure returns `None`, so runtime does not mark the report generated.
- paper_exit_no_real_sell: Pass. Scoped trading-term grep found no authenticated client/order-placement/private-key/sell terms; inspected exit path only mutates `PaperWallet` and `PaperPosition`.
- settlement_states: Pass. `TradeResultStatus` is WIN/LOSS/VOID/UNKNOWN only; UNKNOWN settlement leaves the position open and wallet exposure intact.
- report_math: Pass. Report service filters closed metrics and breakdowns to WIN/LOSS/VOID and excludes UNKNOWN; scheduler report test verifies stored row counts, PnL, breakdowns, and `stale_paper_fills == 0`.
- storage_logging: Pass. Required SQLite rows are persisted before JSONL append; failure tests cover result-row, publish-row, and report publish-row false-success cases. Code inspection covers `insert_daily_report` failure via the same storage-error return-None branch.
- no_real_trading: Pass.
- programming_quality: Pass for this repair scope. Files remain below 250 pure LOC; no new broad false-success catch remains in the repaired persistence boundary.
- remove_ai_slops_overfit: Pass. Tests assert observable scheduler outputs and durable SQLite rows, not implementation-only helper calls. No unnecessary production abstraction, parsing layer, or deletion-only tautological test was introduced.
- env_secrecy: Pass. No `.env` or dotenv files were read.
- cleanup: Pass. No repo SQLite runtime artifacts or long-lived pytest/app processes remained after verification.

exactEvidenceGaps:
- No unresolved blocker. The only residual limitation is that cleanup after an SQLite failure is compensating and best-effort if SQLite itself also fails during cleanup; however, the caller still receives no normal success, and the helper is scoped to the affected IDs.
