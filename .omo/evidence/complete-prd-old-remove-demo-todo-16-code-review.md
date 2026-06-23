# Todo 16 self-review

## Read-only guarantee

PASS. The dashboard registers only GET routes for `/health`, `/api/overview`, `/api/signals`, `/api/rejected-signals`, `/api/positions`, `/api/trades`, `/api/leaderboard`, and `/`. The acceptance test `test_dashboard_rejects_write_methods` verifies POST, PUT, PATCH, and DELETE return 405 on every route. No write/admin/trading route decorators were added.

## Real stored data

PASS. The tests populate a `SQLiteStore` under `tmp_path` through public storage methods, then assert API and HTML responses contain exact persisted values: signal id, rejected candidate id, paper position id, paper trade id, daily report id, and stored strategy rows. No fabricated in-memory dashboard data is used.

## Leaderboard correctness

PASS. `/api/leaderboard` delegates to `SQLiteStore.restore_strategy_leaderboard()`. The test inserts a stored daily report with one WIN and one VOID across two closed positions and asserts `win_rate == 0.5`, preserving PRD `wins / closed_positions` semantics.

## UI/design-system compliance

PASS with one tooling limitation. A root `DESIGN.md` was created with the required 7 sections before changing dashboard HTML. Dashboard CSS uses tokenized variables mirrored from DESIGN.md, semantic landmarks, dense tables, and no marketing hero. Playwright screenshots were attempted but unavailable because `playwright` is not installed in `.venv`; TestClient HTML assertions cover structural and content requirements.

## Accessibility

PASS. HTML includes `lang`, title, description, viewport, skip link, `header`, `nav`, `main`, table captions, scope on count row headers, visible link focus states, and no JS-dependent controls.

## Performance/static simplicity

PASS. The dashboard remains server-rendered FastAPI HTML with inline CSS, no JavaScript, no frontend dependencies, and no live browser/server process left running.

## Slop/overfit risk

PASS. Tests exercise public FastAPI endpoints and real storage APIs, not private helpers. The implementation stays within existing FastAPI/SQLiteStore patterns. `app.py` is 216 pure LOC, which is below the 250 limit but in the warning band; split rendering into a template/helper module before any future UI expansion.

## Safety checks

PASS. No private-key/order-submission symbols or write route decorators were found in dashboard/design files. `data/` contains no generated SQLite files after tests. `.env` was not read.
