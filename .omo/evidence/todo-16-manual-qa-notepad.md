# Todo 16 manual QA notepad

## Happy scenario

- Scenario: read-only dashboard endpoints return stored SQLite payloads and leaderboard uses stored report rows.
- Invocation: `.venv/bin/python -m pytest tests/test_dashboard.py::test_dashboard_readonly_endpoints_return_stored_data tests/test_dashboard.py::test_leaderboard_uses_sqlite_report_data -q`
- Binary observable: exit code 0, output `2 passed`.
- Captured artifact path: `.omo/evidence/todo-16-manual-qa-notepad.md`
- Values asserted: `/health` signal count `1`; `/api/overview` latest report `dr-1`; `/api/signals` persisted signal id; `/api/rejected-signals` persisted candidate signal id; `/api/positions` `pp-1`; `/api/trades` `pt-1`; `/api/leaderboard` `late_consensus` closed `2`, wins `1`, voids `1`, win_rate `0.5`; `/` contains semantic landmarks and stored data.

## Failure scenario

- Scenario: write methods are not supported by the dashboard surface.
- Invocation: `.venv/bin/python -m pytest tests/test_dashboard.py::test_dashboard_rejects_write_methods -q`
- Binary observable: exit code 0, output `1 passed`.
- Captured artifact path: `.omo/evidence/todo-16-manual-qa-notepad.md`
- Values asserted: POST, PUT, PATCH, and DELETE return 405 for `/`, `/health`, `/api/overview`, `/api/signals`, `/api/rejected-signals`, `/api/positions`, `/api/trades`, and `/api/leaderboard`.

## Full acceptance

- Scenario: focused dashboard acceptance file.
- Invocation: `.venv/bin/python -m pytest tests/test_dashboard.py -q`
- Binary observable: exit code 0, output `3 passed`.
- Captured artifact path: `.omo/evidence/task-16-complete-prd-old-remove-demo.txt`

## Endpoint smoke

- Scenario: endpoint smoke against temp populated SQLite store.
- Invocation: `.venv/bin/python - <<'PY' ... PY; rm -f /tmp/polysignal-dashboard-smoke.sqlite3`
- Binary observable: exit code 0.
- Output: `{'overview_report': 'smoke-report-1', 'daily_reports': 1, 'leaderboard_rows': 1, 'top_win_rate': 0.5}`.
- Captured artifact path: `.omo/evidence/todo-16-manual-qa-notepad.md`

## Visual QA

- Scenario: minimum server-rendered HTML QA through FastAPI TestClient.
- Invocation: `.venv/bin/python -m pytest tests/test_dashboard.py::test_dashboard_readonly_endpoints_return_stored_data -q`
- Binary observable: exit code 0.
- Assertions: `header`, `nav`, `main`, readable stored `ptb_diff` and signal content, no `<form>`, no `<button>`, no lorem text, no order-placement control copy, no `create_order` copy.
- Browser screenshot attempt: `.venv/bin/python - <<'PY' ... import playwright ... PY`
- Binary observable: exit code 1, `ModuleNotFoundError: No module named 'playwright'`.
- Screenshot artifact paths: not created because Playwright is unavailable.

## Hygiene

- Scenario: temp DB hygiene.
- Invocation: `find data -maxdepth 1 \( -name '*.sqlite' -o -name '*.sqlite3' \) -print`
- Binary observable: exit code 0, no output.
- Captured artifact path: `.omo/evidence/todo-16-manual-qa-notepad.md`

- Scenario: no new dashboard write/trading/private-key symbols.
- Invocation: `rg "@app\.(post|put|patch|delete)|private_key|mnemonic|create_order|cancel_order|submit_order|place_order|authenticated" src/polysignal_lab/dashboard/app.py DESIGN.md`
- Binary observable: exit code 1, no matches.
- Captured artifact path: `.omo/evidence/todo-16-manual-qa-notepad.md`
