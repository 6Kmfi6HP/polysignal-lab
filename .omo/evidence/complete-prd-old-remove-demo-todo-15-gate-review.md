# Todo 15 Gate Review

recommendation: REJECT

## originalIntent

Task 15 was to make storage, SQLite, and audit logs complete and restorable for the PRD lifecycle. The user-visible outcome should be a storage layer that can be trusted after restart: SQLite validates existing schemas, immutable audit rows cannot silently diverge, JSONL and SQLite use the required audit stream/table names, wallet/open positions/reports/leaderboard are reconstructed from persisted SQLite rows, scheduler wallet restore prefers SQLite and falls back only when SQLite has no usable data, tests use temp DBs, and no real-trading or secret path is introduced.

## desiredOutcome

- JSONL and SQLite cover: `signals`, `rejected_signals`, `paper_orders`, `paper_fills`, `paper_positions`, `paper_trade_results`, `paper_wallet_snapshots`, `daily_reports`, `telegram_publishes`, `system_events`.
- `SQLiteStore.migrate()` rejects corrupt existing schemas missing required columns.
- Immutable duplicate IDs are no-op only for identical payloads and explicit failures for conflicting payloads.
- Restore helpers reconstruct latest wallet snapshot, open positions, daily reports, and strategy leaderboard from persisted SQLite rows.
- Scheduler restore prefers SQLite helpers, with state-file fallback only when SQLite restore yields no usable data.
- Tests are non-tautological, use `tmp_path`, and leave `data/` without sqlite/sqlite3 files.
- Review artifacts explicitly cover programming quality and remove-ai-slops overfit/slop risks.

## userOutcomeReview

NEEDS_FIX. The passing test output is misleading because two user-visible requirements are not actually satisfied on disk:

1. Runtime JSONL audit streams still use non-PRD names for paper results and Telegram publishes.
2. `SQLiteStore.restore_strategy_leaderboard()` restores an incorrect `win_rate` when a strategy has void results.

These are direct Todo 15 storage/restorability failures, not only future dashboard concerns.

## checkedArtifactPaths

- `src/polysignal_lab/storage/sqlite_store.py`
- `src/polysignal_lab/storage/sqlite_schema.py`
- `src/polysignal_lab/app/scheduler_state.py`
- `src/polysignal_lab/app/scheduler_processing.py`
- `src/polysignal_lab/app/scheduler_reporting.py`
- `src/polysignal_lab/paper/report.py`
- `tests/test_storage_reporting_publish.py`
- `tests/test_storage_restore.py`
- `tests/test_reporting.py`
- `tests/factories.py`
- `.omo/evidence/task-15-complete-prd-old-remove-demo.txt`
- `.omo/evidence/complete-prd-old-remove-demo-todo-15-code-review.md`
- `.omo/evidence/todo-15-manual-qa-notepad.md`

## blockers

1. `storage_logging`: JSONL stream names do not match the required PRD lifecycle.
   - Runtime signal publish writes `telegram_publish`, not `telegram_publishes`: `src/polysignal_lab/app/scheduler_processing.py:106`.
   - Runtime paper result writes `paper_results`, not `paper_trade_results`: `src/polysignal_lab/app/scheduler_reporting.py:156`.
   - Runtime paper/daily report publish writes `telegram_publish`, not `telegram_publishes`: `src/polysignal_lab/app/scheduler_reporting.py:158` and `src/polysignal_lab/app/scheduler_reporting.py:246`.
   - The new JSONL test encodes the same wrong names: `tests/test_storage_reporting_publish.py:62` has `paper_results`, and `tests/test_storage_reporting_publish.py:65` has `telegram_publish`.
   - `system_events` has schema/store/test-only coverage, but no production append or `insert_system_event()` call was found outside tests. `rg` only found test calls plus `src/polysignal_lab/storage/sqlite_store.py:162`.

2. `restore_correctness`: restored strategy leaderboard win-rate math conflicts with PRD report math when voids exist.
   - `src/polysignal_lab/storage/sqlite_store.py:228` sets `denominator = wins + losses`, and `src/polysignal_lab/storage/sqlite_store.py:230` uses `wins / denominator`.
   - PRD report math includes voids in closed positions: `src/polysignal_lab/paper/report.py:32` uses `len(closed)` for top-level win rate, and `src/polysignal_lab/paper/report.py:80` plus `src/polysignal_lab/paper/report.py:84` use `closed_positions` for strategy `win_rate`.
   - Existing reporting tests assert this: `tests/test_reporting.py:90-94` expects `1 / 3` with one win, one loss, one void; `tests/test_reporting.py:99-100` expects strategy `win_rate == 0.5` for one win plus one void.
   - Independent adversarial probe wrote a real temp SQLite daily report with one win and one void (`win_rate=0.5`) and `restore_strategy_leaderboard()` returned `win_rate: 1.0`.
   - The new restore test misses this class because its fixture has `void_count=0`: `tests/test_storage_restore.py:95-103` and expected `win_rate: 1.0` at `tests/test_storage_restore.py:125-136`.

3. `remove_ai_slops_overfit`: the JSONL stream coverage test is tautological and production-disconnected.
   - `tests/test_storage_reporting_publish.py:56-69` defines stream names in the test, appends them directly through `JSONLStore`, and then asserts they can be read back. This does not verify that scheduler production paths write the required PRD stream names.
   - The test therefore gives false confidence and missed the runtime stream-name drift above.
   - The code-review artifact has only a narrow slop section at `.omo/evidence/complete-prd-old-remove-demo-todo-15-code-review.md:33-37`; it does not explicitly cover tautological tests, implementation-mirroring tests, deletion-only tests, useless removal checks, or production-disconnected storage logging assertions. It also missed both blockers.

4. `programming_quality`: new scheduler restore/persist code catches broad `Exception` in non-top-level helpers without a specific typed boundary justification.
   - `src/polysignal_lab/app/scheduler_state.py:20`, `src/polysignal_lab/app/scheduler_state.py:24`, `src/polysignal_lab/app/scheduler_state.py:35`, `src/polysignal_lab/app/scheduler_state.py:44`, and `src/polysignal_lab/app/scheduler_state.py:87`.
   - This violates the loaded programming criteria's broad-except rule and can hide restore/persist bugs as warnings.

## positiveEvidence

- `schema_drift`: `validate_sqlite_schema()` checks missing columns, not just missing tables, via `PRAGMA table_info` and `required - present` at `src/polysignal_lab/storage/sqlite_schema.py:188-194`. The corrupt-table test passes.
- `duplicate_idempotency`: `_insert_idempotent()` compares stored `payload_json` to the incoming payload and raises `DuplicateRecordError` on conflict at `src/polysignal_lab/storage/sqlite_store.py:241-249`. Call sites use internal literal table/key/column tuples.
- `restore_helpers`: wallet, open positions, daily reports, and leaderboard read persisted SQLite payloads rather than in-memory fixtures for the tested happy path.
- `scheduler_restore`: `restore_wallet_state()` calls SQLite position and wallet restore helpers before state fallback at `src/polysignal_lab/app/scheduler_state.py:15` and `src/polysignal_lab/app/scheduler_state.py:43`, with state fallback at `src/polysignal_lab/app/scheduler_state.py:27` and `src/polysignal_lab/app/scheduler_state.py:47`.
- `JSONLStore.read_all()`: malformed JSON is not swallowed; `json.loads(line)` is called directly and the test expects `ValueError`.

## commandsRun

- `.venv/bin/python -m pytest tests/test_storage_reporting_publish.py tests/test_storage_restore.py -q`
  - Result: passed, `11 passed`, one StarletteDeprecationWarning.
- `.venv/bin/python -m pytest tests/test_storage_restore.py::test_sqlite_store_restores_wallet_reports_and_leaderboard -q`
  - Result: passed, `1 passed`.
- `.venv/bin/python -m pytest tests/test_storage_reporting_publish.py::test_schema_rejects_missing_required_columns tests/test_storage_reporting_publish.py::test_duplicate_ids_are_idempotent_or_reported -q`
  - Result: passed, `2 passed`, one StarletteDeprecationWarning.
- `.venv/bin/python -m pytest tests/test_scheduler_paper.py tests/test_scheduler_reports.py -q`
  - Result: passed, `7 passed`.
- `PYTHONPYCACHEPREFIX="$tmp_cache" .venv/bin/python -m compileall -q src/polysignal_lab/storage/sqlite_store.py src/polysignal_lab/storage/sqlite_schema.py src/polysignal_lab/app/scheduler_state.py tests/test_storage_reporting_publish.py tests/test_storage_restore.py tests/factories.py`
  - Result: passed on rerun. First attempt failed due zsh `status` being a read-only variable in the wrapper, not due compile errors.
- `find data -maxdepth 1 \( -name '*.sqlite' -o -name '*.sqlite3' \) -print`
  - Result: empty output.
- Scoped no-real-trading/private-key grep over touched storage/state/test files:
  - `rg -n -i "private[ _-]?key|POLYMARKET_PRIVATE_KEY|secret[ _-]?key|real[ _-]?trading|enable[ _-]?real|place[ _-]?real|execute[ _-]?trade|live[ _-]?order" ...`
  - Result: no matches.
- Long-lived process check:
  - `ps -eo pid,ppid,stat,etime,command | rg -i "pytest|polysignal|uvicorn|fastapi|python.*scheduler" ...`
  - Result: no pytest/app/scheduler processes remained. The codegraph MCP server was excluded as expected.
- Adversarial restore probe:
  - Wrote a real temp SQLite `DailyReport` with one win and one void, persisted `win_rate=0.5`, then printed `restore_strategy_leaderboard()`.
  - Result: returned `win_rate: 1.0`, confirming blocker 2.

## adversarialClasses

- `dirty_worktree`: present. The repo has many unrelated modified/deleted/untracked files from the larger plan. Review was scoped to Todo 15 paths and referenced runtime paths needed for storage logging.
- `stale_state`: mitigated by reading current disk state after tests and artifacts.
- `misleading_success_output`: present. Required tests pass but miss production JSONL stream names and void-rate restore math.
- `schema_drift`: acceptable for required-column detection.
- `duplicate_idempotency`: acceptable for immutable rows; mutable market/position upserts are justified as latest-state rows.
- `restore_correctness`: failed for strategy leaderboard void-rate semantics.
- `temp_db_hygiene`: passed; `data/` has no sqlite/sqlite3 artifacts.
- `storage_logging`: failed for JSONL stream names and system event runtime coverage.
- `no_real_trading`: passed in scoped touched-file grep.
- `programming_quality`: failed broad-except criterion in new scheduler state helper.
- `remove_ai_slops_overfit`: failed due tautological JSONL stream test and incomplete code-review slop coverage.
- `env_secrecy`: passed; no `.env` or dotenv file was read.
- `cleanup`: passed; no long-lived pytest/app processes found.

## exactEvidenceGaps

- No test exercises scheduler production JSONL writes and asserts the required PRD names `paper_trade_results` and `telegram_publishes`.
- No test exercises `restore_strategy_leaderboard()` with voids even though report tests already require voids in the denominator.
- No production path was found that writes `system_events` to JSONL/SQLite.
- The code-review artifact did not explicitly cover the requested remove-ai-slops overfit criteria and did not catch the production-disconnected JSONL test.
