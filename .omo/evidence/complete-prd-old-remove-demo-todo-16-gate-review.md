# Todo 16 Gate Review

recommendation: APPROVE

## blockers

None.

## originalIntent

Todo 16 was to complete the read-only dashboard surface from real persisted storage. The user-visible result should be a quiet operational FastAPI dashboard, not a marketing page or trading console, with `/health`, `/api/overview`, `/api/signals`, `/api/rejected-signals`, `/api/positions`, `/api/trades`, `/api/leaderboard`, and `/` backed by `SQLiteStore` rows. The dashboard must preserve the PRD leaderboard semantics from Todo 15: strategy win rate is `win_count / closed_positions`, so voids remain in the denominator.

## desiredOutcome

- All reviewed dashboard routes are GET-only, and POST/PUT/PATCH/DELETE return 405.
- API and HTML responses use stored SQLite payloads, not fabricated in-memory dashboard data.
- `/api/overview` returns current counts and the latest stored daily report.
- `/api/leaderboard` delegates to `SQLiteStore.restore_strategy_leaderboard()`.
- `/` renders counts, latest report, recent signals, recent paper trades, and leaderboard preview from storage.
- Dashboard UI has semantic HTML, no forms/buttons/write controls, no JS bundle, title/meta/viewport, skip link, table captions, focus states, and tokenized CSS tied to `DESIGN.md`.
- Tests and endpoint smoke use temp SQLite stores and leave `data/` free of sqlite/sqlite3 artifacts.
- No `.env` or dotenv file is read.

## userOutcomeReview

CONFIRM. Current disk state satisfies Todo 16 from the user's perspective.

The route definitions in `src/polysignal_lab/dashboard/app.py:41`, `:45`, `:51`, `:55`, `:59`, `:70`, `:74`, and `:78` are GET routes only. A route/method probe returned the eight expected paths with `['GET']` and 405 for POST, PUT, PATCH, and DELETE on each path.

The dashboard reads through `SQLiteStore` at request time. `/api/overview` uses `store.counts()` plus `store.restore_daily_reports(limit=1)` at `src/polysignal_lab/dashboard/app.py:47-49`; `/api/leaderboard` delegates to `store.restore_strategy_leaderboard()` at `src/polysignal_lab/dashboard/app.py:74-76`; HTML preview rows are built from counts, signals, trades, reports, and leaderboard rows at `src/polysignal_lab/dashboard/app.py:80-126`.

Leaderboard math is correct on current disk. `SQLiteStore.restore_strategy_leaderboard()` merges stored daily report `strategy_breakdown` rows and computes `win_rate = wins / closed_positions` at `src/polysignal_lab/storage/sqlite_store.py:207-229`. The existing dashboard test covers one WIN plus one VOID returning `0.5` at `tests/test_dashboard.py:69-115`, and an independent smoke inserted one WIN, one LOSS, one VOID and returned `0.3333333333333333` from `/api/leaderboard`.

The saved HTML artifact `.omo/evidence/todo16-dashboard-actual.html` contains stored values (`2026-06-22`, `sig_06af96d041e2b5cc51af`, `pt-1`, `ptb_diff`, `2.80 USDC`), semantic landmarks, captions, focus CSS, and no form/button/write controls. Browser screenshot QA remains unavailable because `.venv` lacks Playwright and system `chromium-browser` fails under snap confinement; for this static FastAPI HTML surface, saved rendered HTML plus TestClient semantic assertions are sufficient for this gate, with visual screenshot coverage carried as a non-blocking risk.

## checkedArtifactPaths

- `.omo/plans/complete-prd-old-remove-demo.md`
- `.omo/evidence/task-16-complete-prd-old-remove-demo.txt`
- `.omo/evidence/complete-prd-old-remove-demo-todo-16-code-review.md`
- `.omo/evidence/todo-16-manual-qa-notepad.md`
- `.omo/evidence/todo16-dashboard-actual.html`
- `DESIGN.md`
- `src/polysignal_lab/dashboard/app.py`
- `src/polysignal_lab/storage/sqlite_store.py`
- `src/polysignal_lab/paper/report.py`
- `tests/test_dashboard.py`
- `tests/test_storage_restore.py`
- `tests/factories.py`

## commandsRun

- `.venv/bin/python -m pytest tests/test_dashboard.py -q`
  - Result: pass, `3 passed`; inherited Starlette/TestClient httpx2 warning.
- `.venv/bin/python -m pytest tests/test_dashboard.py::test_dashboard_readonly_endpoints_return_stored_data tests/test_dashboard.py::test_leaderboard_uses_sqlite_report_data -q`
  - Result: pass, `2 passed`; inherited warning.
- `.venv/bin/python -m pytest tests/test_dashboard.py::test_dashboard_rejects_write_methods -q`
  - Result: pass, `1 passed`; inherited warning.
- Temp SQLite endpoint smoke with raw stored daily report payload comparison.
  - Result: pass, `{'overview_report': 'gate-report-1', 'daily_reports': 1, 'leaderboard_rows': 1, 'top_strategy': 'gate_strategy', 'top_win_rate': 0.3333333333333333, 'raw_payload_match': True}`.
- `.venv/bin/python -m compileall -q src/polysignal_lab/dashboard/app.py tests/test_dashboard.py`
  - Result: pass, empty output.
- `find data -maxdepth 1 \( -name '*.sqlite' -o -name '*.sqlite3' \) -print`
  - Result: pass, empty output.
- `rg -n "@app\.(post|put|patch|delete)|private_key|mnemonic|create_order|cancel_order|submit_order|place_order|authenticated|api_secret|wallet_secret" src/polysignal_lab/dashboard/app.py DESIGN.md`
  - Result: pass, no matches.
- Route/method TestClient probe for `/`, `/health`, `/api/overview`, `/api/signals`, `/api/rejected-signals`, `/api/positions`, `/api/trades`, `/api/leaderboard`.
  - Result: pass, routes are GET-only and write methods return 405.
- `pgrep`/`ps` process check for `uvicorn`, dashboard app, Playwright, Chromium, and headless shell.
  - Result: no Todo 16 dashboard server or uvicorn process. Long-lived Playwright/MCP and deleted-path headless-shell processes predate this review by multiple days and are environment residue.
- `chromium-browser --headless ... --screenshot=/tmp/todo16-dashboard-1280.png file://...todo16-dashboard-actual.html`
  - Result: failed with snap-confine permission error; no PNG produced.
- `.venv/bin/python` Playwright import probe.
  - Result: `ModuleNotFoundError: No module named 'playwright'`.
- `git diff --check -- DESIGN.md src/polysignal_lab/dashboard/app.py tests/test_dashboard.py ...`
  - Result: pass, empty output.
- Pure LOC checks:
  - `src/polysignal_lab/dashboard/app.py` 216, `tests/test_dashboard.py` 113, `DESIGN.md` 74.

## directSlopAndProgrammingPass

- Overfit/slop: pass. Tests drive public FastAPI endpoints and public storage insert/query APIs, and assert concrete persisted IDs, report IDs, counts, strategy rows, and write-method rejection. They are not deletion-only, tautological, or private-helper mirroring tests.
- Leaderboard implementation: pass. Dashboard does not reimplement stale `wins / (wins + losses)` math; it calls the storage restore helper.
- Production extraction/abstraction: pass for this scope. `app.py` is in the 200-250 pure-LOC warning band, but still below the hard ceiling. The large `home()` route is mostly a static template for one FastAPI-rendered page; splitting templates should happen before future UI expansion, but it is not a blocker here.
- Python quality: pass for touched dashboard/test files. No broad `except Exception`, no `Any`/`object` annotations in `app.py`, no casts/type ignores, and status filtering uses bound SQL params through `query_json()`.
- Design system: pass. `DESIGN.md` has the seven required sections, and every raw hex in dashboard CSS is declared in `DESIGN.md`; undeclared hex set is empty. The warm neutral palette is restrained but should be watched if the UI grows, to avoid a one-note tan/amber theme.
- Accessibility/performance: pass for a static HTML gate. No JS bundle, no form controls, semantic landmarks, skip link, title/meta/viewport, table captions, and link focus states are present.
- Code review coverage: present and supported. `.omo/evidence/complete-prd-old-remove-demo-todo-16-code-review.md` covers read-only routes, real stored data, leaderboard correctness, design/accessibility/performance, slop/overfit risk, pure LOC warning band, safety checks, and env secrecy. My direct pass above supplies the independent verification.

## adversarialClasses

- `dirty_worktree`: pass with scope caveat. Repo has many unrelated dirty files from the larger plan; Todo 16 changed `DESIGN.md`, `src/polysignal_lab/dashboard/app.py`, `tests/test_dashboard.py`, and evidence artifacts. No unrelated changes were reverted.
- `stale_state`: pass. Current disk files, plan, evidence, rendered HTML, and storage helper code were reread before verification.
- `misleading_success_output`: pass. Executor claims were independently rerun; smoke compared API output to raw persisted SQLite payload JSON.
- `readonly_surface`: pass. Reviewed dashboard routes are GET-only; write methods return 405.
- `real_storage_data`: pass. Tests and smoke populate temp SQLite stores and assert stored payload values.
- `leaderboard_math`: pass. Uses `restore_strategy_leaderboard()` and verifies void-inclusive denominator.
- `design_system`: pass. `DESIGN.md` exists with seven sections and CSS colors trace to tokens.
- `accessibility_performance`: pass for static HTML; browser screenshot unavailable due tooling.
- `temp_db_hygiene`: pass. `data/` has no sqlite/sqlite3 files.
- `no_real_trading`: pass. No write route decorators or private-key/order-submission symbols in dashboard/design scope.
- `programming_quality`: pass with warning-band note for `app.py` size.
- `remove_ai_slops_overfit`: pass. No unresolved overfit/slop blocker found in tests or production code.
- `env_secrecy`: pass. No `.env` or dotenv files were read.
- `cleanup`: pass. No Todo 16 server/process remains; existing browser processes are environment residue.

## exactEvidenceGaps

No blocking evidence gaps remain for Todo 16.

Residual non-blocking risks:
- No PNG/browser screenshot exists. Playwright is absent from `.venv`, direct headless-shell path shown by old processes is gone, and system Chromium fails with snap-confine permissions. Saved HTML and TestClient assertions cover this static FastAPI dashboard for this gate.
- `src/polysignal_lab/dashboard/app.py` is 216 pure LOC and should be split into a template/rendering module before additional dashboard growth.
- Existing Starlette/TestClient warning recommends `httpx2`; this is inherited from FastAPI/TestClient usage and does not affect Todo 16 behavior.
