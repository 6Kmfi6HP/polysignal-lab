# Task 7 report: Passive GTD, expiry, and exits

## Changed files

- `src/polysignal_lab/nautilus_runtime/matching.py`
  - Added `RestingMatchingOrder` and `_resting` storage.
  - Added PASSIVE_GTD resting/expiry processing via `process_resting_orders()`.
  - Added reduce-only `submit_exit(position, bid_price, reason)` through the Nautilus matching boundary.
  - Added reduce-only sell-side boundary handling and wallet updates for full/partial exits.
- `src/polysignal_lab/nautilus_runtime/orchestrator.py`
  - Updated `run_once()` order to market refresh, sync, event drain, resting orders, strategy eval, event drain, position exits, settlement, daily report, health.
  - Added `_phase_event_drain()`, `_phase_resting_orders()`, `_phase_position_exits()`.
  - Kept exit order results out of signal publishing while still recording orders/fills/positions.
- `tests/test_nautilus_matching_execution.py`
  - Added `test_passive_gtd_rests_then_expires`.
  - Added partial-exit wallet regression coverage.
- `tests/test_nautilus_orchestrator.py`
  - Added `test_run_once_drains_resting_orders_and_position_exits`.

## RED evidence

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_execution.py::test_passive_gtd_rests_then_expires tests/test_nautilus_orchestrator.py::test_run_once_drains_resting_orders_and_position_exits -q
```

Result: failed as expected before implementation.

- `test_passive_gtd_rests_then_expires`: `AttributeError: 'NautilusMatchingPaperExecutionClient' object has no attribute 'process_resting_orders'`.
- `test_run_once_drains_resting_orders_and_position_exits`: expected drain/resting/exit phase calls, got only `['strategy']`.

## GREEN focused checks

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_execution.py::test_passive_gtd_rests_then_expires tests/test_nautilus_orchestrator.py -q
```

Result: passed.

```text
.........                                                                [100%]
```

## Review notes

- Requested a focused reviewer pass. The first reviewer agent failed to start due a tool/API 404; fallback reviewer completed.
- Reviewer found important issues around exit result recording, partial exits, and duplicate pending drains.
- Addressed by skipping signal publication for reduce-only order results, applying partial exit fills to wallet/remaining position, and not enqueueing synchronously returned pending results into `_pending`.

## Self-review

- Passive GTD below the ask now returns `RESTING`, stores a single resting record, and expires through `process_resting_orders()` with `GTD_EXPIRED`.
- Resting processing retries only stored records and keeps still-resting orders without calling `submit_spec()` recursively.
- Exit submission builds a reduce-only local `NautilusOrderSpec` and uses the matching boundary; no live Polymarket clients, signing, credentials, local paper executors, or safety-blocked live order API literals were added.
- Orchestrator phases use optional method lookup so clients without resting/exit support remain non-fatal, and health is marked for resting and position-exit phases.

## Concerns

- Superseded by fix pass below: `build_nautilus_runtime()` now passes `components["matching_client"]` into the orchestrator/bundle phase-client slots while strategy wrappers still use `components["paper_client"]`.
- Only the focused commands from the Task 7 brief were run; no project-wide gates, formatters, linters, Docker, or safety scans were run.

## Fix pass: review blockers

### Changed files

- `src/polysignal_lab/nautilus_runtime/node.py`
  - Switched `NautilusOrchestrator.paper_client` and `NautilusRuntimeBundle.paper_client` to `components["matching_client"]` so event drain, resting-order, and exit phases run against the matching client.
  - Left strategy wrappers on `components["paper_client"]` for the Task 8 cutover.
- `src/polysignal_lab/nautilus_runtime/matching.py`
  - Added `submit_exit()` missing/stale order book rejection before matching boundary submission.
- `tests/test_nautilus_node.py`
  - Added runtime wiring assertions for bundle/orchestrator phase client exposure while legacy strategy client remains available.
- `tests/test_nautilus_matching_execution.py`
  - Added exit missing/stale book tests that assert the matching boundary is not called.

### RED evidence

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_execution.py::test_submit_exit_without_book_rejects_before_boundary tests/test_nautilus_matching_execution.py::test_submit_exit_stale_book_rejects_before_boundary tests/test_nautilus_node.py::test_build_nautilus_runtime_wires_real_book_provider -q
```

Result: failed as expected before implementation.

- Missing exit book raised `KeyError: 'token-up'` from `FakeNautilusBoundary.match_order()`, proving the boundary was called.
- Stale exit book returned `PRICE_ABOVE_LIMIT` instead of `STALE_ORDERBOOK`.
- Runtime bundle exposed `components["paper_client"]` instead of `components["matching_client"]`.

### GREEN focused checks

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_execution.py::test_passive_gtd_rests_then_expires tests/test_nautilus_matching_execution.py::test_submit_exit_without_book_rejects_before_boundary tests/test_nautilus_matching_execution.py::test_submit_exit_stale_book_rejects_before_boundary tests/test_nautilus_orchestrator.py tests/test_nautilus_node.py -q
```

Result: passed.

```text
...................                                                      [100%]
```

### Self-review

- Orchestrator-only Task 7 phase methods now receive the matching client; strategy wrappers still keep the legacy paper client through `build_trading_node()`.
- Exit freshness behavior now matches entry freshness behavior and rejects before any matching boundary call.
- No live trading, signing, authenticated Polymarket clients, Docker, project-wide formatters, linters, or safety gates were run.

### Concerns

- Task 8 still needs the planned strategy-wrapper cutover from legacy paper execution to matching execution.


## Fix pass: persistence and resting freshness blockers

### Changed files

- `src/polysignal_lab/nautilus_runtime/observability.py`
  - Routed Nautilus `orders` event-store writes through `PersistenceService.upsert_paper_order` so terminal RESTING -> REJECTED/FILLED updates can overwrite the same `paper_order_id`.
- `src/polysignal_lab/nautilus_runtime/matching.py`
  - Added stale held-book rejection in `process_resting_orders()` before `_should_rest()` or matching-boundary submission.
- `tests/test_nautilus_observability.py`
  - Updated route-name assertion to `upsert_paper_order`.
  - Added `test_event_store_upserts_terminal_order_update` proving one `paper_order_id` row updates from RESTING to REJECTED through the adapter and SQLite persistence path.
- `tests/test_nautilus_matching_execution.py`
  - Added `test_resting_order_stale_book_rejects_before_boundary` proving stale resting books reject with `STALE_ORDERBOOK`, skip the boundary, and remove the resting order.

### RED evidence

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_execution.py::test_resting_order_stale_book_rejects_before_boundary tests/test_nautilus_observability.py::test_event_store_routes_known_tables_and_rejects_unknown tests/test_nautilus_observability.py::test_event_store_upserts_terminal_order_update -q
```

Result: failed as expected before implementation.

- Resting stale-book test returned `FILLED` instead of `REJECTED`, proving the stale book reached boundary matching.
- Observability route test still called `insert_paper_order`.
- Upsert terminal-update test raised `DuplicateRecordError` via `insert_paper_order` on the second payload for `order-1`.

### GREEN focused checks

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_execution.py::test_resting_order_stale_book_rejects_before_boundary tests/test_nautilus_observability.py::test_event_store_routes_known_tables_and_rejects_unknown tests/test_nautilus_observability.py::test_event_store_upserts_terminal_order_update -q
```

Result: passed.

```text
...                                                                      [100%]
```

Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_matching_execution.py::test_passive_gtd_rests_then_expires tests/test_nautilus_orchestrator.py tests/test_nautilus_observability.py -q
```

Result: passed.

```text
....................                                                     [100%]
```

### Self-review

- Terminal Nautilus order observations now use the existing paper-order upsert path; no new persistence abstraction or duplicate-order shim was added.
- Resting-order freshness now matches entry/exit behavior for stale books and exits before boundary matching; missing held books retain the previous keep-resting behavior.
- No live trading, signing, authenticated Polymarket clients, Docker, project-wide formatters, linters, or safety gates were run.

### Concerns

- None beyond prior Task 7 report concerns.
