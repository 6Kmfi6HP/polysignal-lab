recommendation: REJECT

originalIntent:
- Todo 14 should wire paper-only TP/SL/max-hold exits into scheduler settlement, keep resolution/cancelled settlement behavior, persist paper result/position/publish rows, generate daily reports from stored rows, and expose only PRD result states WIN/LOSS/VOID/UNKNOWN.

desiredOutcome:
- Active/closed/unknown markets with open paper positions evaluate current orderbook best bid for paper exits without placing real orders.
- Resolved/cancelled markets settle to WIN/LOSS/VOID, while UNKNOWN remains retriable and does not inflate closed metrics.
- Daily report and paper result Telegram publish records are durable when the corresponding send flags are enabled.
- Daily report math follows win / closed semantics and excludes UNKNOWN from closed count, PnL, ROI, profit factor, and breakdowns.

userOutcomeReview:
- Normal-path behavior is mostly present. `PolySignalScheduler._initialize_trading_components()` initializes `PaperExitEngine` (`src/polysignal_lab/app/scheduler.py:94-103`). `check_settlements()` routes CANCELLED/RESOLVED to settlement and ACTIVE/CLOSED/UNKNOWN to paper exit evaluation with the position token book (`src/polysignal_lab/app/scheduler_reporting.py:37-86`). `PaperExitEngine.evaluate()` uses `orderbook.best_bid` and closes only paper wallet/position state (`src/polysignal_lab/paper/exit_engine.py:21-60`). Report math filters closed results through WIN/LOSS/VOID and excludes UNKNOWN (`src/polysignal_lab/paper/report.py:28-38`, `src/polysignal_lab/paper/report.py:62-64`, `src/polysignal_lab/paper/report.py:99-106`).
- The shipped artifact does not fully satisfy the storage_logging and misleading_success_output expectations. Paper exits and daily reports can be reported as successful after durable storage/publish persistence fails.

blockers:
- storage_logging / misleading_success_output: `_store_paper_result()` catches `OSError`, `sqlite3.Error`, `TypeError`, and `ValueError` after the exit engine has already marked the position closed and removed it from the paper wallet. `check_settlements()` appends the result and then calls `_store_paper_result()` (`src/polysignal_lab/app/scheduler_reporting.py:88-98`); `_store_paper_result()` logs and swallows failures from `logs.append`, `upsert_paper_position`, `insert_paper_trade_result`, publisher send, and `insert_telegram_publish` (`src/polysignal_lab/app/scheduler_reporting.py:102-119`). The paper exit mutation already happened in `PaperExitEngine.evaluate()` (`src/polysignal_lab/paper/exit_engine.py:36-60`). A storage failure therefore leaves no durable paper result/publish row, while the caller still receives a settled result and the runtime can log `Settled %d positions` (`src/polysignal_lab/app/scheduler_runtime.py:146-152`). No test or artifact covers this failure path.
- storage_logging / daily_report_publish: `generate_daily_report()` logs and swallows daily report storage failures (`src/polysignal_lab/app/scheduler_reporting.py:186-190`) and daily report publish/publish-row failures (`src/polysignal_lab/app/scheduler_reporting.py:192-199`), then returns the report (`src/polysignal_lab/app/scheduler_reporting.py:201-207`). The runtime records the report date when a non-None report is returned (`src/polysignal_lab/app/scheduler_runtime.py:155-167`), so a missing durable report or Telegram publish row may not be retried during that process. The normal-path test asserts rows when storage works, but does not prove the required persistence behavior under failure.
- report coverage gap: `.omo/evidence/complete-prd-old-remove-demo-todo-14-code-review.md` includes a slop/overfit section and normal-path SQLite assertions, but it does not explicitly cover the above storage/publish failure paths or the programming criterion against broad catch-and-continue false success at scheduler boundaries. The report is therefore not sufficient support for approval.

checkedArtifactPaths:
- `.omo/evidence/task-14-complete-prd-old-remove-demo.txt`
- `.omo/evidence/complete-prd-old-remove-demo-todo-14-code-review.md`
- `.omo/evidence/todo-14-manual-qa-notepad.md`
- `src/polysignal_lab/app/scheduler.py`
- `src/polysignal_lab/app/scheduler_reporting.py`
- `src/polysignal_lab/app/scheduler_runtime.py`
- `src/polysignal_lab/paper/exit_engine.py`
- `src/polysignal_lab/paper/settlement.py`
- `src/polysignal_lab/paper/report.py`
- `src/polysignal_lab/domain/enums.py`
- `src/polysignal_lab/domain/paper_result.py`
- `src/polysignal_lab/storage/sqlite_store.py`
- `tests/test_exit_engine.py`
- `tests/test_reporting.py`
- `tests/test_scheduler_reports.py`
- `tests/test_settlement.py`

commandsRun:
- `.venv/bin/python -m pytest tests/test_exit_engine.py tests/test_settlement.py tests/test_reporting.py tests/test_scheduler_reports.py -q` -> PASS, 8 passed.
- `.venv/bin/python -m pytest tests/test_exit_engine.py::test_take_profit_stop_loss_and_max_hold_exits tests/test_reporting.py::test_daily_report_includes_strategy_win_rate_and_pnl -q` -> PASS, 2 passed.
- `.venv/bin/python -m pytest tests/test_settlement.py::test_unknown_outcome_does_not_inflate_win_rate tests/test_scheduler_reports.py::test_daily_report_publish_record_written -q` -> PASS, 2 passed.
- `PYTHONPYCACHEPREFIX=$(mktemp -d) .venv/bin/python -m compileall -q src/polysignal_lab/app/scheduler.py src/polysignal_lab/app/scheduler_reporting.py src/polysignal_lab/paper/report.py tests/test_exit_engine.py tests/test_reporting.py tests/test_scheduler_reports.py tests/test_settlement.py` -> PASS.
- `rg -n "SecureClient|AsyncSecureClient|ClobClient\\(|create_order|post_order|submit_order|cancel_order|cancel_all|redeem_positions|private_key|sell" src/polysignal_lab/app src/polysignal_lab/paper tests/test_exit_engine.py tests/test_settlement.py tests/test_reporting.py tests/test_scheduler_reports.py` -> no matches, exit 1.
- `rg -n "SPLIT" src tests` -> only protective assertions in `tests/test_settlement.py:80` and `tests/test_reporting.py:105`.
- `find . -path './.git' -prune -o -path './.venv' -prune -o -path './.mypy_cache' -prune -o -path './.pytest_cache' -prune -o \( -name '*.sqlite' -o -name '*.sqlite3' -o -name '*.db' \) -print` -> no repo runtime sqlite artifacts found.
- `pgrep -af pytest` -> no long-lived pytest process found.
- `pgrep -af 'polysignal_lab|run_scheduler|uvicorn.*polysignal|gunicorn.*polysignal'` -> no long-lived Polysignal app process found.

adversarialClasses:
- dirty_worktree: Present. `git status --short` shows many modified/deleted/untracked files beyond Todo 14. Scoped review focused on the listed Todo 14 files plus directly relevant runtime support.
- stale_state: Required tests were rerun from current disk and passed. Source inspection used current on-disk Codegraph reads plus direct shell reads for artifacts.
- misleading_success_output: Blocked. Storage/publish failures can be swallowed after paper state mutation, while success-like return/logging continues.
- paper_exit_no_real_sell: Pass for scoped grep and code path. No real trading/order-placement/private-key/sell terms found in the touched runtime/paper/test scope; exit engine only mutates paper wallet/position.
- settlement_states: Pass. `TradeResultStatus` is WIN/LOSS/VOID/UNKNOWN only (`src/polysignal_lab/domain/enums.py:38-42`), UNKNOWN settlement leaves the position open (`src/polysignal_lab/paper/settlement.py:20-22`, `src/polysignal_lab/paper/settlement.py:63-67`).
- report_math: Pass for inspected normal path. UNKNOWN is excluded from closed metrics and breakdowns in `PaperReportService`.
- storage_logging: Blocked by swallowed persistence failures in paper result and daily report paths.
- no_real_trading: Pass for scoped grep and inspected call path.
- programming_quality: Blocked by catch-and-continue behavior that hides required durable persistence failures. Other Todo 14 touched files stay below the 250 pure LOC ceiling.
- remove_ai_slops_overfit: Tests are mostly public-behavior and SQLite-row oriented, not private-helper-only. The gap is missing failure coverage for storage/publish persistence and broad catch false success.
- env_secrecy: No `.env` or dotenv files were read.
- cleanup: No repo sqlite runtime artifacts or long-lived pytest/Polysignal app processes found after verification.

exactEvidenceGaps:
- No test simulates `logs.append`, `sqlite.upsert_paper_position`, `sqlite.insert_paper_trade_result`, or `sqlite.insert_telegram_publish` failure during `_store_paper_result()` after the exit engine closes the wallet position.
- No test simulates `insert_daily_report` or `insert_telegram_publish` failure during `generate_daily_report()` with `send_daily_report` enabled.
- Executor evidence claims persisted rows in the happy path, but does not prove failure behavior cannot produce missing durable rows with successful return values.
