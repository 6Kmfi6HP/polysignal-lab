# Task 11 Report: Backend HTML Route Removal

Base before task: `3dc1661`

## Changes

- Removed the hand-written dashboard HTML `/` route from `src/polysignal_lab/dashboard/app.py`.
- Removed HTML-only `escape`, `HTMLResponse`, and `_text` usage.
- Updated `tests/test_dashboard.py` so:
  - `test_dashboard_readonly_endpoints_return_stored_data` asserts `GET /` returns `404`.
  - `test_dashboard_rejects_write_methods` no longer expects write-method `405` behavior for `/`.
  - the paper execution quality test no longer asserts removed HTML summary text.
- Updated `src/polysignal_lab/app/readonly_smoke_runtime.py` to stop probing `/` in the bounded dashboard read smoke check. This was full-suite fallout from removing the route: the smoke check should now probe the JSON dashboard endpoints only.

## Test-first evidence

- Initial bare command `pytest tests/test_dashboard.py -v` failed before collection because the system `pytest` ran on Python 3.10 while the project requires Python `>=3.11`:
  - `ImportError: cannot import name 'StrEnum' from 'enum' (/usr/lib/python3.10/enum.py)`
- Valid baseline command using the project environment:
  - `.venv/bin/python -m pytest tests/test_dashboard.py -v`
  - Result before changes: `pytest: 8 passed, 1 warning in 1.77s`.
- RED after updating tests first:
  - `.venv/bin/python -m pytest tests/test_dashboard.py -v`
  - Result: `1 failed, 7 passed`; expected failure was `assert root.status_code == 404`, actual `200`.

## Verification evidence

- Focused dashboard suite after production change:
  - Command: `.venv/bin/python -m pytest tests/test_dashboard.py -v`
  - Result: `pytest: 8 passed, 1 warning in 0.75s`.
- Smoke fallout check after removing `/` from dashboard smoke probes:
  - Command: `.venv/bin/python -m pytest tests/test_integration_smoke.py::test_fake_public_api_outage_degrades_without_unhandled_exception -v`
  - Result: `pytest: 1 passed in 3.20s`.
- Full suite:
  - Command: `.venv/bin/python -m pytest`
  - Result: `pytest: 2 failed, 884 passed, 7 skipped, 1 warning in 19.83s`.
  - Remaining failures are unrelated Nautilus tests:
    1. `tests/test_nautilus_native_order.py::test_runtime_native_strategy_type_initializes_nautilus_base` fails with `RuntimeError: PolySignalNativeStrategy requires injected registry, sidecar, and assembler projections`.
    2. `tests/test_nautilus_node.py::test_build_nautilus_runtime_discovers_market_universe_for_trading_node` expects `accuracy_mode == "depth_l2"` but actual is `"fast_l1"`.
  - Pre-existing evidence: the same two Nautilus tests fail at base `3dc1661` when run in a detached base worktree with the same project venv.

## Concerns

- Full `pytest` is not green because of the two pre-existing Nautilus failures above.
- The task brief expected no non-dashboard test references to `/`; full-suite execution proved `readonly_smoke_runtime.py` also probed `/`, so it was updated as a Task 11 fallout fix.
