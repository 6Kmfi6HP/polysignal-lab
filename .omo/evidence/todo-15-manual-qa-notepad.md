# Todo 15 Manual QA Notepad

Happy QA:
- Scenario: SQLite restore reconstructs wallet, reports, and leaderboard from persisted temp DB rows.
- Invocation: `.venv/bin/python -m pytest tests/test_storage_restore.py::test_sqlite_store_restores_wallet_reports_and_leaderboard -q`
- Binary observable: `. [100%]`, 1 passed.
- Artifact path: `.omo/evidence/todo-15-manual-qa-notepad.md`
- Assertions covered: restored wallet `cash_balance=975.5`, `equity=1014.25`, open position `pp-open-1`, daily report `dr-restore-1`, `total_signals=7`, leaderboard `ptb_diff` PnL/win-rate values.

Failure QA:
- Scenario: corrupt schema and duplicate IDs are rejected or idempotent.
- Invocation: `.venv/bin/python -m pytest tests/test_storage_reporting_publish.py::test_schema_rejects_missing_required_columns tests/test_storage_reporting_publish.py::test_duplicate_ids_are_idempotent_or_reported -q`
- Binary observable: `.. [100%]`, 2 passed, 1 StarletteDeprecationWarning.
- Artifact path: `.omo/evidence/todo-15-manual-qa-notepad.md`
- Assertions covered: corrupt `signals` table raises `SchemaValidationError`; identical duplicate lifecycle rows keep one row each; conflicting duplicate signal ID raises `DuplicateRecordError`.

Acceptance QA:
- Scenario: required storage acceptance suite.
- Invocation: `.venv/bin/python -m pytest tests/test_storage_reporting_publish.py tests/test_storage_restore.py -q`
- Binary observable: `........... [100%]`, 11 passed, 1 StarletteDeprecationWarning.

Temp DB hygiene:
- Invocation: `find data -maxdepth 1 \( -name '*.sqlite' -o -name '*.sqlite3' \) -print`
- Binary observable: empty output after all tests.

Todo 13/14 preservation:
- Invocation: `.venv/bin/python -m pytest tests/test_scheduler_paper.py tests/test_scheduler_reports.py -q`
- Binary observable: `....... [100%]`, 7 passed.

No real trading or secret path:
- Invocation: `! rg "private_key|mnemonic|create_order|post_order|submit_order|cancel_order|ClobClient|SecureClient" src/polysignal_lab/storage src/polysignal_lab/app/scheduler_state.py tests/test_storage_reporting_publish.py tests/test_storage_restore.py tests/factories.py`
- Binary observable: exit 0, empty output.
- Note: no `.env` or dotenv file was read.

Cleanup:
- No servers, subprocesses, ports, or long-lived sessions were started.

Gate repair QA:
- Scenario: runtime `process_signal`, paper result, and daily report paths write PRD JSONL stream names, and leaderboard restore counts voids in the closed denominator.
- Invocation: `.venv/bin/python -m pytest tests/test_scheduler_paper.py::test_process_signal_writes_prd_named_telegram_jsonl_stream tests/test_scheduler_reports.py::test_paper_exit_publish_record_written tests/test_scheduler_reports.py::test_daily_report_publish_record_written tests/test_storage_restore.py::test_strategy_leaderboard_win_rate_counts_voids_as_closed -q`
- Binary observable: `.... [100%]`, 4 passed.
- Artifact path: `.omo/evidence/todo-15-manual-qa-notepad.md`
- Assertions covered: runtime-created `telegram_publishes.jsonl` for signal publish, runtime-created `paper_trade_results.jsonl` and `telegram_publishes.jsonl` for paper result publish, runtime-created `daily_reports.jsonl` and `telegram_publishes.jsonl` for daily report publish, absence of old `telegram_publish.jsonl` / `paper_results.jsonl`, and `WIN+VOID` leaderboard `win_rate == 0.5`.

Repair acceptance QA:
- Invocation: `.venv/bin/python -m pytest tests/test_storage_reporting_publish.py tests/test_storage_restore.py -q`
- Binary observable: `............ [100%]`, 12 passed, 1 StarletteDeprecationWarning.
- Invocation: `.venv/bin/python -m pytest tests/test_scheduler_paper.py tests/test_scheduler_reports.py -q`
- Binary observable: `........ [100%]`, 8 passed.
- Invocation: `PYTHONPYCACHEPREFIX=/tmp/polysignal-lab-todo15-pycache .venv/bin/python -m compileall -q src/polysignal_lab/app/scheduler_processing.py src/polysignal_lab/app/scheduler_reporting.py src/polysignal_lab/app/scheduler_state.py src/polysignal_lab/storage/sqlite_store.py tests/test_scheduler_paper.py tests/test_scheduler_reports.py tests/test_storage_restore.py tests/test_storage_reporting_publish.py`
- Binary observable: exit 0, empty output.

Repair hygiene QA:
- Invocation: `find data -maxdepth 1 \( -name '*.sqlite' -o -name '*.sqlite3' \) -print`
- Binary observable: empty output.
- Invocation: `rg -n "private[_-]?key|PRIVATE_KEY|secret[_-]?key|WALLET|create_order|submit_order|place_order|cancel_order|signed_order|signer|real trading|live trading" src/polysignal_lab/app/scheduler_processing.py src/polysignal_lab/app/scheduler_reporting.py src/polysignal_lab/app/scheduler_state.py src/polysignal_lab/storage/sqlite_store.py tests/test_scheduler_paper.py tests/test_scheduler_reports.py tests/test_storage_restore.py tests/test_storage_reporting_publish.py -g '!*.env' -g '!*.dotenv'`
- Binary observable: exit 1, empty output.
- Invocation: `rg -n "except Exception|except BaseException" src/polysignal_lab/app/scheduler_state.py src/polysignal_lab/storage/sqlite_store.py -g '!*.env' -g '!*.dotenv'`
- Binary observable: exit 1, empty output.
