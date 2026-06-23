# Todo 15 Self Review

Scope reviewed: `SQLiteStore`, SQLite schema metadata, scheduler wallet restore, JSONL/state tests, SQLite restore tests, shared test factories.

Schema and migration safety:
- Required PRD audit tables are represented in schema metadata: markets, signals, rejected_signals, paper_orders, paper_fills, paper_positions, paper_trade_results, paper_wallet_snapshots, daily_reports, telegram_publishes, system_events.
- Migration order now creates tables, validates required columns, then creates indexes. This prevents index creation from masking corrupt legacy tables.
- Existing temp DBs with complete schemas remain compatible because DDL is `CREATE TABLE IF NOT EXISTS` and validation is additive-read-only.
- Corrupt/missing required columns are detected by `SchemaValidationError`.

Restore correctness:
- `restore_latest_wallet_snapshot()` uses stored `paper_wallet_snapshots` ordered by `created_at` and row id.
- `restore_open_positions()` reads persisted `paper_positions` rows filtered to `OPEN`.
- `restore_daily_reports()` and `restore_strategy_leaderboard()` use stored `daily_reports` payloads, not fabricated in-memory state.
- Scheduler wallet restore now prefers SQLite wallet/position rows and only falls back to temp JSON state when SQLite does not provide usable data.

Idempotency:
- Immutable audit inserts now check the existing `payload_json` for the primary ID before insert.
- Same ID and same payload is idempotent.
- Same ID and different payload raises `DuplicateRecordError`.
- Paper positions and markets remain true upserts because they model mutable/latest state.
- Wallet snapshots remain append-only because the schema has no stable snapshot ID.

Temp DB hygiene:
- Tests instantiate SQLite under `tmp_path`.
- Final `find data -maxdepth 1 \( -name '*.sqlite' -o -name '*.sqlite3' \) -print` produced empty output.

Storage failure behavior:
- Todo 14 paper result/report rollback tests still pass via `tests/test_scheduler_reports.py`.
- Todo 13 paper order/fill durability tests still pass via `tests/test_scheduler_paper.py`.
- Insert conflicts now raise explicit exceptions for inconsistent duplicates, so storage failures do not become silent successes.

Slop/overfit risks:
- Schema metadata moved to a dedicated module to keep `sqlite_store.py` below 250 pure LOC.
- Tests assert binary observables: row counts, payload fields, exception types, restored wallet/report/leaderboard values.
- The restore test does not mock the store; it writes and reads a real temp SQLite DB.
- No test-only production hooks were added.

Residual concerns:
- `query_json(where=...)` remains an internal raw SQL fragment surface from pre-existing code. Table names are allowlisted, and params are still bound.
- Duplicate wallet snapshots cannot be detected without adding a snapshot identifier or unique constraint; left append-only to preserve wallet history semantics.

Gate repair review for reviewer 019eee11-7dda-7361-a9b4-98017b7b07d1:
- Runtime stream names: PASS. Runtime append calls now write PRD lifecycle stream names: `process_signal()` writes `telegram_publishes`; paper result storage writes `paper_trade_results` and `telegram_publishes`; daily report storage writes `daily_reports` and `telegram_publishes`. Scoped grep `rg -n 'logs\.append\("(telegram_publish|paper_results)"' src/polysignal_lab/app -g '!*.env' -g '!*.dotenv'` returned no matches.
- Production-connected tests: PASS. New/updated assertions exercise actual scheduler runtime paths, not only `JSONLStore.append()` with test-defined names: `test_process_signal_writes_prd_named_telegram_jsonl_stream`, `test_paper_exit_publish_record_written`, and `test_daily_report_publish_record_written`. These tests assert PRD-named JSONL files and assert old `telegram_publish.jsonl` / `paper_results.jsonl` files are absent.
- Leaderboard denominator: PASS. `restore_strategy_leaderboard()` now computes `win_rate` as `wins / closed_positions`, aligning with report math where voids are closed positions. `test_strategy_leaderboard_win_rate_counts_voids_as_closed` persists one WIN plus one VOID and asserts `win_rate == 0.5`.
- Broad exception slop: PASS for the requested scope. `scheduler_state.py` now catches specific `ValidationError`, `json.JSONDecodeError`, `sqlite3.Error`, `OSError`, `TypeError`, and `ValueError` paths. `rg -n "except Exception|except BaseException" src/polysignal_lab/app/scheduler_state.py src/polysignal_lab/storage/sqlite_store.py -g '!*.env' -g '!*.dotenv'` returned no matches.
- Overfit check: PASS. Acceptance includes both broad suites and targeted tests. The targeted stream tests observe runtime-created JSONL files and old-file absence; they do not manually seed stream names. The leaderboard test persists a real `DailyReport` row through `SQLiteStore`.
- Evidence: detailed command/results were appended to `.omo/evidence/task-15-complete-prd-old-remove-demo.txt`; manual QA observables were updated in `.omo/evidence/todo-15-manual-qa-notepad.md`.
