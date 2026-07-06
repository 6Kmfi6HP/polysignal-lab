# Task 5 Report: Market catalog cutover

## Commit

- `77fa9eb67604737f038f09d304df3f4029e3ac13` — `refactor: replace instrument registry with market catalog`

## Files changed

- Added `src/polysignal_lab/nautilus_bridge/market_catalog.py`
- Deleted `src/polysignal_lab/nautilus_bridge/market_registry.py`
- Modified `src/polysignal_lab/nautilus_bridge/market_view_assembler.py`
- Modified `src/polysignal_lab/nautilus_runtime/cache_market_data.py`
- Modified `src/polysignal_lab/nautilus_runtime/market_rotation.py`
- Modified `src/polysignal_lab/nautilus_runtime/native_strategy.py`
- Modified `src/polysignal_lab/nautilus_runtime/node.py`
- Modified `src/polysignal_lab/nautilus_runtime/runtime_classes.py`
- Modified `tests/test_nautilus_cache_market_data.py`
- Modified `tests/test_nautilus_full_paper_runtime_smoke.py`
- Added `tests/test_nautilus_market_catalog.py`
- Deleted `tests/test_nautilus_market_registry.py`
- Modified `tests/test_nautilus_market_rotation.py`
- Modified `tests/test_nautilus_market_view_assembler.py`
- Modified `tests/test_nautilus_native_exit.py`
- Modified `tests/test_nautilus_platform_boundary.py`
- Modified `tests/test_nautilus_strategy_base.py`

## Tests run

1. Red checkpoint:
   - Command: `uv run python -m pytest tests/test_nautilus_market_catalog.py -q`
   - Observed summary: collection failed with `ModuleNotFoundError: No module named 'polysignal_lab.nautilus_bridge.market_catalog'` before `market_catalog.py` existed.

2. Catalog green checkpoint:
   - Command: `uv run python -m pytest tests/test_nautilus_market_catalog.py -q`
   - Observed summary: `.... [100%]`.

3. Focused catalog/cache/assembler suite:
   - Command: `uv run python -m pytest tests/test_nautilus_market_catalog.py tests/test_nautilus_cache_market_data.py tests/test_nautilus_market_view_assembler.py -q`
   - Observed summary: `............ [100%]`.

4. Reverse registry boundary test:
   - Command: `uv run python -m pytest tests/test_nautilus_platform_boundary.py::test_market_catalog_has_no_reverse_instrument_truth_source -q`
   - Observed summary: `. [100%]`.

5. Native exit seam check:
   - Command: `uv run python -m pytest tests/test_nautilus_native_exit.py -q`
   - Observed summary: `.... [100%]`.

6. Targeted market-data mapping seam check:
   - Command: `uv run python -m pytest tests/test_nautilus_strategy_base.py::test_native_strategy_partial_market_data_mappings_are_dropped_without_evaluation -q`
   - Observed summary: `. [100%]`.

## Self-review notes

- Replaced the reverse instrument registry with `MarketCatalog`, keyed by condition and token only.
- Kept `polymarket_instrument_id` as a monkeypatchable function in `market_catalog.py`, but made it a local wrapper to avoid a catalog/runtime package circular import during test collection.
- Updated market view assembly and cache market data access to resolve instrument IDs through `MarketCatalog.instrument_id_for_token` instead of storing instrument IDs in token metadata.
- Updated native strategy market-data, order-event, subscription, and exit lookup paths to derive instrument IDs through the catalog or compare against the current `MarketView`, with no calls to `condition_id_for_instrument`, `token_id_for_instrument`, or `by_instrument`.
- Removed only the Task 5 xfail marker from `test_market_catalog_has_no_reverse_instrument_truth_source`; Task 6/7 xfails were left unchanged.
- Updated compatibility imports/types in runtime wrappers, market rotation, and affected tests so deleted `market_registry.py` is not imported.
- Pre-existing unstaged files `.superpowers/sdd/progress.md`, `.superpowers/sdd/task-1-report.md`, and `.superpowers/sdd/task-4-report.md` were not staged or committed.

## Follow-up fix: native order/fill attribution fallback

### Commit

- `6844cdf3e78ee7ca929e962c0402cc52394a784a` — `fix: bind strategy assemblers to custom data`
- `10a1d1d2c7acf6e5a2140b73377dc755dbd77edd` — `fix: preserve catalog order attribution fallback`

### Fix details

- Added `MarketCatalog.condition_ids()` so runtime code can derive a catalog condition universe from registered business pairs without reintroducing `market_registry.py`, `by_instrument`, `_by_instrument`, `condition_id_for_instrument`, or `token_id_for_instrument`.
- Changed native order/fill fallback attribution to scan the registered catalog condition universe instead of only `self._active_condition_ids`, preserving attribution for exited or inactive but still registered instruments.
- Restored DOWN-side attribution for known instruments by resolving the token from the catalog path before falling back to `Side.UP`.
- Updated node/smoke tests to match the Task 5 no-sidecar runtime shape and catalog-derived Polymarket instrument IDs.
- Bound each constructed native strategy to its own `StrategyCustomDataState` and a per-strategy assembler view so the shared runtime assembler does not leak custom data across strategies.

### Tests run

1. Per-strategy custom-data RED/GREEN checkpoint:
   - Command: `uv run python -m pytest tests/test_nautilus_node.py::test_build_trading_node_gives_each_strategy_own_custom_data_state -q`
   - Observed summary before the fix: failed with `AssertionError: assert False` because the fake runtime strategy had no `StrategyCustomDataState`.
   - Observed summary after the fix: `. [100%]`.

1. Attribution RED checkpoint:
   - Command: `uv run python -m pytest tests/test_nautilus_strategy_base.py::test_native_strategy_attributes_inactive_registered_down_order_and_fill_from_catalog -q`
   - Observed summary before the fix: failed with `AssertionError: assert '' == 'btc-exited-5m'`, proving registered-but-inactive DOWN instrument events were not attributed from the catalog.

2. Focused attribution/order-event rerun:
   - Command: `uv run python -m pytest tests/test_nautilus_strategy_base.py::test_native_strategy_attributes_inactive_registered_down_order_and_fill_from_catalog tests/test_nautilus_strategy_base.py::test_native_strategy_on_order_accepted_preserves_approved_signal_metrics tests/test_nautilus_strategy_base.py::test_native_strategy_on_order_denied_records_event_and_forgets_metrics tests/test_nautilus_strategy_base.py::test_order_submitted_observability_failure_does_not_block_core_event tests/test_nautilus_strategy_base.py::test_native_strategy_fill_and_position_callbacks_bridge_to_observability tests/test_nautilus_strategy_base.py::test_native_strategy_notifies_core_before_fill_handler -q`
   - Observed summary: `...... [100%]`.

3. Native order tests:
   - Command: `uv run python -m pytest tests/test_nautilus_native_order.py -q`
   - Observed summary: `........ [100%]`.

4. Native exit tests:
   - Command: `uv run python -m pytest tests/test_nautilus_native_exit.py -q`
   - Observed summary: `.... [100%]`.

5. Node and full paper runtime smoke checks:
   - Command: `uv run python -m pytest tests/test_nautilus_node.py tests/test_nautilus_full_paper_runtime_smoke.py -q`
   - Observed summary: `................................................. [100%]`.

6. Task 5 focused catalog/cache/assembler checks:
   - Command: `uv run python -m pytest tests/test_nautilus_market_catalog.py tests/test_nautilus_cache_market_data.py tests/test_nautilus_market_view_assembler.py -q`
   - Observed summary: `............ [100%]`.

7. Reverse-registry boundary check:
   - Command: `uv run python -m pytest tests/test_nautilus_platform_boundary.py::test_market_catalog_has_no_reverse_instrument_truth_source -q`
   - Observed summary: `. [100%]`.

### Non-final diagnostic runs

- Command: `uv run python -m pytest tests/test_nautilus_strategy_base.py tests/test_nautilus_native_order.py tests/test_nautilus_native_exit.py -q`
  - Observed summary: failed in 17 `tests/test_nautilus_strategy_base.py` subscription/market-data tests with `RuntimeError: Nautilus Polymarket adapter is required to resolve instrument IDs`; the final focused attribution/order-event checks plus `tests/test_nautilus_native_order.py` and `tests/test_nautilus_native_exit.py` passed after narrowing to the affected order/fill paths.
- Command: `uv run python -m pytest tests/test_nautilus_node.py tests/test_nautilus_full_paper_runtime_smoke.py -q`
  - Observed summary before test wiring updates: failed in `test_build_trading_node_injects_shared_projections_and_no_manual_sync_components` on the stale `sidecar` runtime assertion and in `test_runtime_sidecar_actor_and_native_strategy_bridge_to_order_submit` on missing fake Polymarket adapter / stale token-only instrument IDs; the final exact command passed.

## Follow-up fix: no-Nautilus catalog test resolver seam

### Commit

- `15dfa20e51ab0324bd3de392fed4d0585b5322d0` — `fix: keep catalog tests independent of Nautilus adapter`

### Fix details

- Added an optional `instrument_id_resolver` seam to `MarketCatalog`; the default path still lazily delegates to `polymarket_instrument_id`, so production keeps requiring the Nautilus Polymarket adapter for real instrument IDs.
- Added a catalog resolver injection test and wired native strategy/exit tests through shared test catalog builders instead of installing or relying on `nautilus_trader.adapters.polymarket`.
- Kept the Task 5 reverse-registry deletion intact; the focused platform boundary check below still passes.

### Tests run

1. Catalog resolver RED checkpoint:
   - Command: `uv run python -m pytest tests/test_nautilus_market_catalog.py::test_market_catalog_uses_injected_instrument_id_resolver -q`
   - Observed summary before the fix: failed with `TypeError: MarketCatalog.__init__() got an unexpected keyword argument 'instrument_id_resolver'`.

2. Affected strategy/native suite:
   - Command: `uv run python -m pytest tests/test_nautilus_strategy_base.py tests/test_nautilus_native_order.py tests/test_nautilus_native_exit.py -q`
   - Observed summary before the fix: failed in strategy-base subscription/market-data tests with `RuntimeError: Nautilus Polymarket adapter is required to resolve instrument IDs`.
   - Observed summary after the fix: `........................................................................ [ 96%]` / `... [100%]`.

3. Node and full paper runtime smoke checks:
   - Command: `uv run python -m pytest tests/test_nautilus_node.py tests/test_nautilus_full_paper_runtime_smoke.py -q`
   - Observed summary: `................................................. [100%]`.

4. Task 5 focused catalog/cache/assembler checks:
   - Command: `uv run python -m pytest tests/test_nautilus_market_catalog.py tests/test_nautilus_cache_market_data.py tests/test_nautilus_market_view_assembler.py -q`
   - Observed summary: `............. [100%]`.

5. Reverse-registry boundary check:
   - Command: `uv run python -m pytest tests/test_nautilus_platform_boundary.py::test_market_catalog_has_no_reverse_instrument_truth_source -q`
   - Observed summary: `. [100%]`.
