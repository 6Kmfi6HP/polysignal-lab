# Task 2 Report: Market Data Component Instrumentation

## Status
COMPLETED and committed.

## Files changed
- `src/polysignal_lab/data/polymarket_clob_rest.py`
- `src/polysignal_lab/data/polymarket_clob_ws.py`
- `src/polysignal_lab/data/binance_spot_ws.py`
- `src/polysignal_lab/app/scheduler.py`
- `src/polysignal_lab/app/scheduler_market_data.py`
- `src/polysignal_lab/app/scheduler_health.py`
- `tests/test_market_data.py`
- `tests/test_health_metrics.py`

## Red command/output
Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_data.py::test_clob_ws_exposes_connection_and_invalid_event_metrics tests/test_market_data.py::test_binance_feed_exposes_connection_metrics tests/test_health_metrics.py::test_scheduler_records_market_data_health -q
```

Initial output:

```text
FFF                                                                      [100%]
FAILED tests/test_market_data.py::test_clob_ws_exposes_connection_and_invalid_event_metrics - AttributeError: 'PolymarketMarketWebSocket' object has no attribute 'note_connected'
FAILED tests/test_market_data.py::test_binance_feed_exposes_connection_metrics - AttributeError: 'BinanceSpotFeed' object has no attribute 'note_connected'
FAILED tests/test_health_metrics.py::test_scheduler_records_market_data_health - ModuleNotFoundError: No module named 'polysignal_lab.app.scheduler_health'
```

Additional reviewer-driven red checks in the same targeted command failed before fixes for obsolete stale-token scoping, missing active CLOB token counting, disconnected Binance false-ok health, and completed empty subscription stale counting.

## Green command/output
Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_data.py::test_clob_ws_exposes_connection_and_invalid_event_metrics tests/test_market_data.py::test_binance_feed_exposes_connection_metrics tests/test_health_metrics.py::test_scheduler_records_market_data_health -q
```

Final output after commit:

```text
...                                                                      [100%]
```

## Commit
`a34347b5d5542238c3111c6c0345fb14cb1176d9` (`feat: instrument market data health`)

Note: commit was created with `--no-verify` to honor the task constraint to skip non-target gates/formatters/project-wide checks.

## Self-review
- Added CLOB REST batch success/failure/fallback/latency metrics without live API calls in tests.
- Added CLOB WS and Binance WS connection, reconnect, and error state helpers and loop wiring.
- Added `scheduler_health` helpers for storage, publish, runtime sync, snapshot persistence, CLOB REST/WS, Binance WS, and scoped book staleness.
- Wired `HealthRegistry` into `PolySignalScheduler` and market refresh discovery/storage/REST health updates.
- Addressed reviewer findings for clean WebSocket close reconnect state, obsolete stale token false alarms, missing active CLOB token counting, disconnected Binance false-ok health, and completed empty subscription stale counting.
- Final reviewer check reported the prior blockers resolved with no remaining prior-blocker defect found.

## Concerns
None for Task 2 scope. Only the targeted task tests were run; Docker and project-wide gates were intentionally skipped per brief.

## Fix report: Task 2 review findings

### Status
COMPLETED.

### Files changed
- `src/polysignal_lab/app/scheduler_health.py`
- `tests/test_health_metrics.py`

### Red command/output
Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_data.py::test_clob_ws_exposes_connection_and_invalid_event_metrics tests/test_market_data.py::test_binance_feed_exposes_connection_metrics tests/test_health_metrics.py::test_scheduler_records_market_data_health tests/test_health_metrics.py::test_clob_ws_idle_after_empty_market_refresh_is_ok tests/test_health_metrics.py::test_binance_ws_requires_every_configured_spot -q
```

Initial output:

```text
...FF                                                                    [100%]
FAILED tests/test_health_metrics.py::test_clob_ws_idle_after_empty_market_refresh_is_ok - AssertionError: assert 'degraded' == 'ok'
FAILED tests/test_health_metrics.py::test_binance_ws_requires_every_configured_spot - AssertionError: assert 'ok' == 'degraded'
```

### Green command/output
Commands:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_data.py::test_clob_ws_exposes_connection_and_invalid_event_metrics tests/test_market_data.py::test_binance_feed_exposes_connection_metrics tests/test_health_metrics.py::test_scheduler_records_market_data_health tests/test_health_metrics.py::test_clob_ws_idle_after_empty_market_refresh_is_ok tests/test_health_metrics.py::test_binance_ws_requires_every_configured_spot -q
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_data.py::test_clob_ws_exposes_connection_and_invalid_event_metrics tests/test_market_data.py::test_binance_feed_exposes_connection_metrics tests/test_health_metrics.py::test_scheduler_records_market_data_health -q
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_health_metrics.py -q
```

Final output:

```text
.....                                                                    [100%]
...                                                                      [100%]
.......                                                                  [100%]
```

### Summary
- CLOB WS health now reports ok/idle after a completed market refresh with zero active token IDs.
- Binance WS health now degrades when any enabled configured symbol has no fresh spot price yet.

### Commit
Committed with message `fix: correct market data health states`; final SHA is reported in the completion result.

### Concerns
None. Only targeted Task 2 checks were run; Docker and project-wide gates were intentionally skipped per constraints.

## Fix report: storage-health attribution

### Status
COMPLETED.

### Files changed
- `src/polysignal_lab/app/scheduler_market_data.py`
- `tests/test_health_metrics.py`

### Red command/output
Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_health_metrics.py::test_refresh_markets_marks_jsonl_failure_without_sqlite_down -q
```

Initial output:

```text
FAILED tests/test_health_metrics.py::test_refresh_markets_marks_jsonl_failure_without_sqlite_down - AssertionError: assert 'down' == 'ok'
```

### Green command/output
Commands:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_health_metrics.py::test_refresh_markets_marks_jsonl_failure_without_sqlite_down -q
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_data.py::test_clob_ws_exposes_connection_and_invalid_event_metrics tests/test_market_data.py::test_binance_feed_exposes_connection_metrics tests/test_health_metrics.py -q
```

Final output:

```text
.                                                                        [100%]
..........                                                               [100%]
```

### Summary
- Split market refresh SQLite and JSONL persistence handling so a JSONL append failure marks `jsonl_storage` down without falsely marking `sqlite_storage` down after a successful SQLite upsert.
- Added a regression test that persists the market to SQLite, forces JSONL append failure, and asserts `sqlite_storage` remains ok while `jsonl_storage` records one write failure.

### Commit
Committed after targeted checks; final SHA is reported in the completion result.

### Concerns
None. Only targeted Task 2 checks were run; Docker and project-wide gates were intentionally skipped per constraints.

## Fix report: CLOB REST outage preservation

### Status
COMPLETED.

### Files changed
- `src/polysignal_lab/app/scheduler_health.py`
- `tests/test_health_metrics.py`

### Red command/output
Command:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_health_metrics.py::test_sync_runtime_health_preserves_clob_rest_down_after_complete_failure -q
```

Initial output:

```text
FAILED tests/test_health_metrics.py::test_sync_runtime_health_preserves_clob_rest_down_after_complete_failure - AssertionError: assert 'degraded' == 'down'
```

### Green command/output
Commands:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_health_metrics.py::test_sync_runtime_health_preserves_clob_rest_down_after_complete_failure -q
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_data.py::test_clob_ws_exposes_connection_and_invalid_event_metrics tests/test_market_data.py::test_binance_feed_exposes_connection_metrics tests/test_health_metrics.py -q
```

Final output:

```text
.                                                                        [100%]
...........                                                              [100%]
```

### Summary
- `sync_runtime_health()` now preserves an existing `clob_rest` down state while merging CLOB REST counter/gauge metrics, so cumulative batch fallback counters cannot downgrade a complete outage to degraded.
- A later successful market refresh can still mark `clob_rest` ok before runtime sync, allowing batch-fallback success to remain degraded rather than down.

### Commit
Committed after targeted checks; final SHA is reported in the completion result.

### Concerns
None. Only targeted Task 2 checks were run; Docker and project-wide gates were intentionally skipped per constraints.
