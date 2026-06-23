# Todo 15 After Repair Gate Review

recommendation: APPROVE

## originalIntent

Todo 15 was to make storage, SQLite, and audit logs complete and restorable for the PRD lifecycle. The user-visible outcome is that runtime storage can be trusted across restarts: audit lifecycle records use the accepted stream/table names, schemas are validated, duplicate immutable audit IDs are safe, wallet/open positions/reports/leaderboard restore from SQLite rows, tests use temp DBs, and no real-trading or secret path is introduced.

## desiredOutcome

- JSONL and SQLite cover: `signals`, `rejected_signals`, `paper_orders`, `paper_fills`, `paper_positions`, `paper_trade_results`, `paper_wallet_snapshots`, `daily_reports`, `telegram_publishes`, `system_events`.
- Runtime scheduler paths write PRD JSONL stream names, not only test-defined direct appends.
- `SQLiteStore.migrate()` rejects corrupt existing schemas missing required columns.
- Duplicate immutable audit IDs are idempotent only for identical payloads and explicitly fail for conflicting payloads.
- Restore helpers reconstruct latest wallet snapshot, open positions, daily reports, and strategy leaderboard from persisted SQLite rows.
- Leaderboard win rate uses `wins / closed_positions`, so voids remain in the closed denominator.
- Tests use `tmp_path` and leave `data/` free of sqlite/sqlite3 artifacts.
- Todo 13/14 storage/report false-success behavior remains intact.

## userOutcomeReview

CONFIRM. The four prior rejection reasons are repaired on current disk.

Runtime stream names now use `telegram_publishes` and `paper_trade_results` in scheduler production paths. The focused tests exercise `process_signal`, paper exit result publication, and daily report publication through real scheduler methods, and assert the old `telegram_publish.jsonl` and `paper_results.jsonl` files are absent.

`SQLiteStore.restore_strategy_leaderboard()` now computes `win_rate` as `win_count / closed_positions`, and the added `WIN + VOID == 0.5` test passes against a real temp SQLite `DailyReport` row.

The production-disconnected JSONL coverage is no longer the only proof for the disputed stream names. It remains as generic `JSONLStore`/state coverage, while runtime-connected tests cover the repaired paths.

The broad `except Exception` issue in the requested `scheduler_state.py` and `sqlite_store.py` scope is clean. Broad catches still exist in `scheduler_processing.py`, but they are inherited scheduler boundary behavior outside the specific Todo 15 repair blocker; I am carrying them as non-blocking residual risk for this gate.

## blockers

None.

## checkedArtifactPaths

- `.omo/plans/complete-prd-old-remove-demo.md`
- `.omo/evidence/task-15-complete-prd-old-remove-demo.txt`
- `.omo/evidence/complete-prd-old-remove-demo-todo-15-code-review.md`
- `.omo/evidence/complete-prd-old-remove-demo-todo-15-gate-review.md`
- `.omo/evidence/todo-15-manual-qa-notepad.md`
- `src/polysignal_lab/app/scheduler_processing.py`
- `src/polysignal_lab/app/scheduler_reporting.py`
- `src/polysignal_lab/app/scheduler_reporting_storage.py`
- `src/polysignal_lab/app/scheduler_state.py`
- `src/polysignal_lab/storage/jsonl_store.py`
- `src/polysignal_lab/storage/sqlite_schema.py`
- `src/polysignal_lab/storage/sqlite_store.py`
- `tests/test_scheduler_paper.py`
- `tests/test_scheduler_reports.py`
- `tests/test_storage_restore.py`
- `tests/test_storage_reporting_publish.py`

## commandsRun

- `.venv/bin/python -m pytest tests/test_storage_reporting_publish.py tests/test_storage_restore.py -q`
  - Result: pass, `12 passed`, one inherited Starlette/httpx deprecation warning.
- `.venv/bin/python -m pytest tests/test_storage_restore.py::test_sqlite_store_restores_wallet_reports_and_leaderboard -q`
  - Result: pass, `1 passed`.
- `.venv/bin/python -m pytest tests/test_storage_reporting_publish.py::test_schema_rejects_missing_required_columns tests/test_storage_reporting_publish.py::test_duplicate_ids_are_idempotent_or_reported -q`
  - Result: pass, `2 passed`, one inherited Starlette/httpx deprecation warning.
- `.venv/bin/python -m pytest tests/test_scheduler_paper.py tests/test_scheduler_reports.py -q`
  - Result: pass, `8 passed`.
- `.venv/bin/python -m pytest tests/test_scheduler_paper.py::test_process_signal_writes_prd_named_telegram_jsonl_stream tests/test_scheduler_reports.py::test_paper_exit_publish_record_written tests/test_scheduler_reports.py::test_daily_report_publish_record_written tests/test_storage_restore.py::test_strategy_leaderboard_win_rate_counts_voids_as_closed -q`
  - Result: pass, `4 passed`.
- `PYTHONPYCACHEPREFIX=/tmp/polysignal-lab-todo15-gate-pycache .venv/bin/python -m compileall -q src/polysignal_lab/app/scheduler_processing.py src/polysignal_lab/app/scheduler_reporting.py src/polysignal_lab/app/scheduler_state.py src/polysignal_lab/storage/sqlite_store.py tests/test_scheduler_paper.py tests/test_scheduler_reports.py tests/test_storage_restore.py tests/test_storage_reporting_publish.py`
  - Result: pass, empty output.
- `find data -maxdepth 1 \( -name '*.sqlite' -o -name '*.sqlite3' \) -print`
  - Result: pass, empty output.
- `rg -n "private[_-]?key|PRIVATE_KEY|secret[_-]?key|WALLET|create_order|submit_order|place_order|cancel_order|signed_order|signer|real trading|live trading" ...`
  - Result: pass, no matches in touched Todo 15 repair scope.
- `rg -n 'logs\.append\("(telegram_publish|paper_results)"' src/polysignal_lab/app -g '!*.env' -g '!*.dotenv'`
  - Result: pass, no old runtime append names.
- `rg -n "except Exception|except BaseException" src/polysignal_lab/app/scheduler_state.py src/polysignal_lab/storage/sqlite_store.py -g '!*.env' -g '!*.dotenv'`
  - Result: pass, no broad catches in the required repaired scope.
- `ps -eo pid,ppid,stat,etime,args | awk '/python/ && /pytest|polysignal_lab|uvicorn|fastapi|scheduler/ && !/awk/ {print}'`
  - Result: pass, no long-lived pytest/app/scheduler processes.
- `git diff --check -- src/polysignal_lab/app/scheduler_processing.py src/polysignal_lab/app/scheduler_reporting.py src/polysignal_lab/app/scheduler_state.py src/polysignal_lab/storage/sqlite_store.py tests/test_scheduler_paper.py tests/test_scheduler_reports.py tests/test_storage_restore.py tests/test_storage_reporting_publish.py`
  - Result: pass, empty output.
- Pure LOC check for touched Python files:
  - `scheduler_processing.py` 160, `scheduler_reporting.py` 229, `scheduler_state.py` 76, `sqlite_store.py` 224, `test_scheduler_paper.py` 84, `test_scheduler_reports.py` 210, `test_storage_restore.py` 167, `test_storage_reporting_publish.py` 190.

## directSlopAndProgrammingPass

- Excessive or useless tests: no blocker. The generic JSONL stream test is limited, but the repaired runtime paths are now covered by scheduler calls that create files on disk and assert old files absent.
- Deletion-only/removal-only tests: no blocker. Old stream absence assertions are paired with positive runtime-created PRD stream assertions.
- Tautological/implementation-mirroring tests: no blocker for the repaired behavior. Key tests assert observable files, SQLite rows, restored values, and exception types rather than private call order.
- Unnecessary production extraction/parsing/normalization: no blocker. `sqlite_schema.py` owns DDL and schema metadata, keeps `sqlite_store.py` under the 250 pure LOC ceiling, and is used by migration/validation.
- Broad exceptions: clean in `scheduler_state.py` and `sqlite_store.py`; inherited broad catches remain in `scheduler_processing.py` and are outside this repair blocker.
- Dynamic SQL: `_insert_idempotent()` uses dynamic SQL, but all call sites pass fixed internal literal table/key/column tuples. `query_json(where=...)` remains an internal raw where-fragment surface; table names are allowlisted and params are bound.
- Code review coverage: `.omo/evidence/complete-prd-old-remove-demo-todo-15-code-review.md` explicitly covers slop/overfit repair checks, production-connected stream tests, broad-exception cleanup, and the leaderboard void-denominator case.

## adversarialClasses

- `dirty_worktree`: present. The repo has many unrelated modified/deleted/untracked files from the larger plan. Review was scoped to Todo 15 repair files and required runtime paths.
- `stale_state`: mitigated by rereading current disk state and rerunning all required commands after inspection.
- `misleading_success_output`: mitigated by verifying runtime-created JSONL files, old-file absence, SQLite row contents, and the void-denominator test.
- `schema_drift`: pass. Missing required columns raise `SchemaValidationError`.
- `duplicate_idempotency`: pass. Identical immutable duplicate payloads are no-ops; conflicting duplicate signal ID raises `DuplicateRecordError`.
- `restore_correctness`: pass. Wallet, open positions, reports, and leaderboard restore from persisted SQLite rows; voids count as closed positions.
- `temp_db_hygiene`: pass. Tests use temp paths and `data/` contains no sqlite/sqlite3 artifacts.
- `storage_logging`: pass for repaired runtime scheduler paths and required table/stream names.
- `no_real_trading`: pass in scoped grep.
- `programming_quality`: pass for this repair scope; touched files are below 250 pure LOC and the requested broad-exception scope is clean.
- `remove_ai_slops_overfit`: pass. The prior production-disconnected stream-name proof has been supplemented with runtime-connected scheduler tests.
- `env_secrecy`: pass. No `.env` or dotenv file was read.
- `cleanup`: pass. No long-lived pytest/app/scheduler process remains.

## exactEvidenceGaps

No blocking evidence gaps remain for Todo 15 after repair.

Residual non-blocking risks:
- `scheduler_processing.py` still has inherited broad `except Exception` catches at lines 36, 65, 72, 97, 110, and 124. The prior gate's repair blocker was specific to new `scheduler_state.py` storage/state helpers, which are now clean.
- No production caller for `insert_system_event()` was found. The storage table, insert helper, duplicate semantics, count coverage, and generic JSONL stream coverage exist; PRD-old does not define a concrete runtime system-event emission path for this todo.
- `docs/PRD_OLD_COMPLIANCE.md` still references older JSONL names from PRD-old text; Todo 19 owns docs refresh, and runtime code/tests now use the accepted repaired names.
