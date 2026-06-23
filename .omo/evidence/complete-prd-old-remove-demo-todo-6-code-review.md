# Todo 6 Scheduler Refactor Code Review

Date: 2026-06-22

## Current Refactor Summary

Todo 6 scheduler behavior was preserved while the oversized scheduler module was split by responsibility:

- `src/polysignal_lab/app/scheduler.py`: dependency construction, Telegram startup gate, trading-component lazy init, and public compatibility wrappers.
- `src/polysignal_lab/app/scheduler_market_data.py`: discovery, resolved-market fetch, token extraction, Polymarket subscription lifecycle, Binance stream startup.
- `src/polysignal_lab/app/scheduler_state.py`: wallet/state restore and persistence.
- `src/polysignal_lab/app/scheduler_processing.py`: strategy evaluation, gate/consensus handling, signal storage, Telegram signal publish, paper simulation.
- `src/polysignal_lab/app/scheduler_reporting.py`: settlement checks and daily report publish/store.
- `src/polysignal_lab/app/scheduler_runtime.py`: run loop and shutdown lifecycle.

## File-Size Table

Measured with `awk '!/^[[:space:]]*$/ && !/^[[:space:]]*(#)/' <file> | wc -l`.

| File | Pure LOC | Status |
| --- | ---: | --- |
| `src/polysignal_lab/app/scheduler.py` | 152 | PASS, no longer oversized |
| `src/polysignal_lab/app/scheduler_market_data.py` | 140 | PASS |
| `src/polysignal_lab/app/scheduler_state.py` | 77 | PASS |
| `src/polysignal_lab/app/scheduler_processing.py` | 135 | PASS |
| `src/polysignal_lab/app/scheduler_reporting.py` | 125 | PASS |
| `src/polysignal_lab/app/scheduler_runtime.py` | 139 | PASS |

## Programming Coverage

- No touched Python file exceeds the 250 pure LOC `programming` ceiling.
- No `Any`, `cast(`, `type: ignore`, `import pandas`, or `dict[str, dict]` was introduced in the touched scheduler files.
- `scheduler.py` still has the inherited `import asyncio` because tests and runtime public annotations use `scheduler_module.asyncio.Task` and existing asyncio task objects. New helper modules use direct imports for the moved task primitives rather than adding `import asyncio`.
- The broad catch grep lists inherited scheduler resilience paths moved into smaller modules. They remain around existing storage, network, strategy, Telegram publish, settlement, and shutdown boundaries; no startup broad `except Exception` wrapper was added back.
- Public dict-shaped process summaries are now `TypedDict` contracts (`ProcessSignalResult`, `AcceptedSignalSummary`) instead of untyped raw dict public signatures.

## remove-ai-slops / Overfit Coverage

- The refactor is behavior-preserving extraction, not a deletion-only cleanup.
- Existing Todo 6 tests are behavioral: startup order, discovery failure no-stream, non-empty subscription, empty no-subscribe, resubscribe, and validation-before-init. They are not deletion-only tests.
- No dead helper module was created: each new module owns one runtime responsibility and is called through existing `PolySignalScheduler` wrappers.
- No redundant post-action verification was added. Verification lives in command artifacts and tests, not production code.
- No one-off helper without purpose was added; helpers either preserve public scheduler methods or split repeated runtime phases (`_evaluate_iteration`, `_process_iteration_signals`, settlement/report generation).

## Todo 6 Behavior Review

- Startup order: `scheduler_runtime.run()` calls `_validate_telegram_startup()`, `_initialize_trading_components()`, `_restore_wallet_state()`, `refresh_markets_once()`, `_fetch_resolved_markets()`, then `start_websockets()`.
- Discovery failure no-stream: initial `refresh_markets_once()` is not wrapped in a broad startup catch, so a discovery exception propagates before streams can start.
- Non-empty Polymarket subscription: `start_websockets()` subscribes from `_latest_market_token_ids`, populated by discovery via `token_ids_for_markets()`.
- Empty discovery no-subscribe: empty token ids call `stop_market_ws_subscription()` and return before subscribe.
- Resubscribe: changed token ids stop the old market subscription and create a new non-empty subscription.
- No auth/trading clients: forbidden auth/order-surface grep over `src/polysignal_lab/app` and `src/polysignal_lab/data` returned no matches.
- Result-state scope note: this Todo 6 refactor did not alter paper settlement result semantics; no unrelated WIN/LOSS/VOID/UNKNOWN result-state behavior was changed.

## Exact Verification Results

- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_scheduler.py tests/test_market_data.py -q` -> PASS, `9 passed`.
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_scheduler.py::test_refresh_markets_before_starting_streams tests/test_scheduler.py::test_market_ws_subscribes_after_token_discovery tests/test_scheduler.py::test_empty_market_refresh_does_not_subscribe_market_ws tests/test_scheduler.py::test_market_ws_resubscribes_when_token_set_changes tests/test_scheduler.py::test_initial_discovery_failure_prevents_stream_startup tests/test_scheduler.py::test_live_telegram_validation_runs_before_strategy_and_paper_initialization -q` -> PASS, `6 passed`.
- `bash -lc '! rg "Authorization|private_key|create_order|cancel_order|POLY_|api_secret|signer|order submit|submit_order" src/polysignal_lab/app src/polysignal_lab/data'` -> PASS, exit 0, empty stdout.
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m py_compile src/polysignal_lab/app/scheduler.py src/polysignal_lab/app/scheduler_market_data.py src/polysignal_lab/app/scheduler_state.py src/polysignal_lab/app/scheduler_processing.py src/polysignal_lab/app/scheduler_reporting.py src/polysignal_lab/app/scheduler_runtime.py` -> PASS, exit 0.
- Size check -> PASS: all touched Python files are 77-152 pure LOC.
- Quality grep -> documented inherited broad catch and inherited scheduler `import asyncio` matches; no `Any`, `cast(`, `type: ignore`, `import pandas`, or `dict[str, dict]` matches.
- Manual QA call-order trace -> PASS: `manual.discovery_failure_no_stream events=['discover_raise'] result=PASS`; `manual.validation_before_init events=['telegram_validate'] result=PASS`.

## Risks

- Existing broad `except Exception` resilience behavior remains in moved code paths. This refactor did not narrow those catches because Todo 6 scope requires behavior-preserving extraction and the catches are existing I/O/runtime isolation behavior, not the removed startup-order broad catch.
- `ruff` is not installed in `.venv`, so the optional linter check could not run locally; requested pytest, py_compile, size, auth guard, quality grep, and manual QA evidence are current and recorded.
