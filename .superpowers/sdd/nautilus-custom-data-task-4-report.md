# Task 4 Final Verification Report

Status: PASS

One-line summary: PASS — all corrected Task 4 verification commands completed successfully; basedpyright exited 0 with warnings only.

## Verification commands

### 1. Corrected native strategy pytest command

Command:

```bash
uv run pytest tests/test_nautilus_strategy_base.py::test_native_strategy_on_start_requires_injected_projections tests/test_nautilus_strategy_base.py::test_native_strategy_on_start_requires_injected_assembler tests/test_nautilus_strategy_base.py::test_native_strategy_on_start_subscribes_all_custom_data_with_injected_projections tests/test_nautilus_strategy_base.py::test_native_strategy_metadata_without_registry_fails_clearly tests/test_nautilus_strategy_base.py::test_native_strategy_active_market_without_metadata_stays_pending_until_metadata_arrives tests/test_nautilus_strategy_base.py::test_native_strategy_active_market_without_subscribe_hooks_marks_pending_subscribe tests/test_nautilus_strategy_base.py::test_native_strategy_order_book_callback_updates_shared_books_and_submits tests/test_nautilus_strategy_base.py::test_native_strategy_trade_tick_callback_updates_shared_trade_history -q
```

Output summary:

```text
........                                                                 [100%]
8 passed, with 2 DeprecationWarning warnings from nautilus_trader persistence parquet helpers.
Exit: 0
```

### 2. Runtime wiring pytest command

Command:

```bash
uv run pytest tests/test_nautilus_node.py::test_build_trading_node_injects_shared_projections_and_no_manual_sync_components tests/test_nautilus_node.py::test_build_trading_node_returns_nautilus_runtime_components tests/test_nautilus_node.py::test_build_trading_node_registers_market_rotation_actor tests/test_nautilus_trading_node_runtime.py::test_build_paper_trading_node_config_uses_polymarket_data_and_sandbox_exec tests/test_nautilus_trading_node_runtime.py::test_build_paper_trading_node_config_enables_dynamic_instrument_loading tests/test_nautilus_trading_node_runtime.py::test_register_paper_factories_registers_data_and_sandbox_exec_only -q
```

Output summary:

```text
......                                                                   [100%]
6 passed.
Exit: 0
```

### 3. Legacy compatibility pytest command

Command:

```bash
uv run pytest tests/test_nautilus_data_ingestor.py -q
```

Output summary:

```text
.......                                                                  [100%]
7 passed.
Exit: 0
```

### 4. py_compile command

Command:

```bash
uv run python -m py_compile src/polysignal_lab/nautilus_runtime/native_strategy.py src/polysignal_lab/nautilus_runtime/data_ingestor.py src/polysignal_lab/nautilus_runtime/orchestrator.py
```

Output summary:

```text
(no output)
Exit: 0
```

### 5. basedpyright command

Command:

```bash
uv run basedpyright src/polysignal_lab/nautilus_runtime/native_strategy.py src/polysignal_lab/nautilus_runtime/data_ingestor.py src/polysignal_lab/nautilus_runtime/orchestrator.py tests/test_nautilus_strategy_base.py tests/test_nautilus_node.py tests/test_nautilus_data_ingestor.py
```

Output summary:

```text
0 errors, 1430 warnings, 0 notes
Exit: 0
```

Remaining basedpyright diagnostics are warnings only, not unresolved failures. They include existing warning categories across the checked runtime/test files such as `reportUnannotatedClassAttribute`, `reportAny`, `reportUnusedCallResult`, `reportPrivateUsage`, `reportUnknownParameterType`, `reportMissingParameterType`, and related unknown/Any test-helper warnings.

## Spec coverage self-review

- AC1 Default node wiring is paper-safe: covered by the re-run trading node runtime tests.
- AC2 Strategy bootstraps custom data: covered by the corrected native strategy tests.
- AC3 No default manual sync strategy loop: covered by `test_build_trading_node_injects_shared_projections_and_no_manual_sync_components`.
- AC4 Order book callback evaluates condition: covered by `test_native_strategy_order_book_callback_updates_shared_books_and_submits`.
- AC5 Trade tick callback evaluates condition: covered by `test_native_strategy_trade_tick_callback_updates_shared_trade_history`.
- AC6 Metadata/universe drives dynamic subscription: covered by pending-metadata and metadata-arrival native strategy tests.
- AC7 Missing metadata does not storm subscriptions: covered by the pending metadata native strategy test.
- AC8 Spot/PTB are custom-data driven: spot/custom-data path is covered by native strategy tests; PTB behavior remains on the existing `on_data(PolySignalPriceToBeatData)` path.
- AC9 Changed-only PTB publishing remains intact: not changed by this task; existing market-rotation coverage remains outside these focused commands.
- AC10 Logs remain explainable: not changed by this task; observability log schema coverage remains outside these focused commands.

## Final disposition

PASS — all required Task 4 verification commands exited 0. basedpyright produced warnings only and no errors.

## Full-suite regression fix — 2026-06-29

Status: PASS

### Root cause

- Six native strategy tests constructed `PolySignalNativeStrategy` with `registry=` and `assembler=`, but no `sidecar=`, then called `on_start()`. The implementation now correctly fail-fasts when any required native projection dependency is missing, so the tests were stale rather than production behavior being wrong.
- The default runtime integration failure came from `project_portfolio_snapshot()` reading Nautilus `Portfolio.equity()` with no context. Nautilus 1.229 requires either `venue` or `account_id`; the cache reader already had account access, but did not pass it into the projection.

### Changes

- Injected `ExternalDataSidecar()` in the six native strategy tests that intentionally exercise subscribe/unsubscribe/retained-wire behavior.
- Kept the production fail-fast invariant intact: no local projection fallback was restored.
- Wired `NautilusCacheReader.snapshot_portfolio_projection()` to pass `read_account()` into `project_portfolio_snapshot()`.
- Updated `project_portfolio_snapshot()` to use `account.id` when calling callable portfolio equity, with a no-arg fallback only for simple test doubles or portfolio APIs that still support it.

### Commands and output

```text
uv run pytest tests/test_nautilus_strategy_base.py::test_native_strategy_universe_update_recovers_still_active_missing_subscription tests/test_nautilus_strategy_base.py::test_native_strategy_exited_market_unsubscribes_when_hooks_exist tests/test_nautilus_strategy_base.py::test_native_strategy_exited_market_unsubscribes_without_book_type_kwarg tests/test_nautilus_strategy_base.py::test_native_strategy_exited_market_is_noop_when_unsubscribe_disabled tests/test_nautilus_strategy_base.py::test_native_strategy_exited_market_without_unsubscribe_hooks_retains_wire_state tests/test_nautilus_strategy_base.py::test_native_strategy_retained_wire_trade_tick_stays_gated tests/test_nautilus_default_runtime_integration.py::test_default_runtime_routes_fill_position_and_account_through_nautilus
7 passed, 4 warnings in 6.09s
Exit: 0
```

```text
uv run pytest
833 passed, 5 warnings in 25.16s
Exit: 0
```

```text
uv run pytest tests/test_nautilus_strategy_base.py::test_native_strategy_on_start_requires_injected_projections tests/test_nautilus_strategy_base.py::test_native_strategy_on_start_requires_injected_assembler tests/test_nautilus_strategy_base.py::test_native_strategy_on_start_subscribes_all_custom_data_with_injected_projections tests/test_nautilus_strategy_base.py::test_native_strategy_metadata_without_registry_fails_clearly tests/test_nautilus_strategy_base.py::test_native_strategy_active_market_without_metadata_stays_pending_until_metadata_arrives tests/test_nautilus_strategy_base.py::test_native_strategy_active_market_without_subscribe_hooks_marks_pending_subscribe tests/test_nautilus_strategy_base.py::test_native_strategy_order_book_callback_updates_shared_books_and_submits tests/test_nautilus_strategy_base.py::test_native_strategy_trade_tick_callback_updates_shared_trade_history -q
8 passed, 2 warnings
Exit: 0
```

```text
uv run basedpyright src/polysignal_lab/nautilus_runtime/native_strategy.py src/polysignal_lab/nautilus_runtime/data_ingestor.py src/polysignal_lab/nautilus_runtime/orchestrator.py tests/test_nautilus_strategy_base.py tests/test_nautilus_node.py tests/test_nautilus_data_ingestor.py
0 errors, 1430 warnings, 0 notes
Exit: 0
```

```text
uv run basedpyright src/polysignal_lab/nautilus_runtime/cache_reader.py src/polysignal_lab/nautilus_runtime/projections.py
0 errors, 10 warnings, 0 notes
Exit: 0
```
