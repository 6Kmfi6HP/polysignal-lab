# Task 4 Report: Delete shared ExternalDataSidecar

## Files changed

- `src/polysignal_lab/nautilus_runtime/custom_data_state.py` (created)
- `src/polysignal_lab/nautilus_bridge/external_data.py` (removed)
- `src/polysignal_lab/nautilus_runtime/sidecar_data.py`
- `src/polysignal_lab/nautilus_runtime/native_strategy.py`
- `src/polysignal_lab/nautilus_runtime/market_rotation.py`
- `src/polysignal_lab/nautilus_runtime/node.py`
- `src/polysignal_lab/nautilus_runtime/runtime_classes.py`
- `src/polysignal_lab/nautilus_bridge/market_view_assembler.py`
- `tests/test_nautilus_sidecar_actor.py`
- `tests/test_nautilus_market_view_assembler.py`
- `tests/test_nautilus_platform_boundary.py`
- `tests/test_nautilus_market_rotation.py`
- `tests/test_nautilus_strategy_base.py`
- `tests/test_nautilus_full_paper_runtime_smoke.py`
- `tests/test_nautilus_native_exit.py`
- `tests/test_nautilus_native_order.py`
- `tests/test_nautilus_external_data.py` (removed)

## TDD / verification

1. RED: `uv run python -m pytest tests/test_nautilus_sidecar_actor.py -q`
   - Observed: collection error, `ImportError: cannot import name 'CustomDataPublisher' from 'polysignal_lab.nautilus_runtime.sidecar_data'`.
2. RED: `uv run python -m pytest tests/test_nautilus_market_view_assembler.py -q`
   - Observed: 3 failures, `TypeError: MarketViewAssembler.__init__() got an unexpected keyword argument 'custom_data'`.
3. GREEN: `uv run python -m pytest tests/test_nautilus_sidecar_actor.py -q`
   - Observed: `... [100%]`.
4. GREEN: `uv run python -m pytest tests/test_nautilus_market_view_assembler.py -q`
   - Observed after implementation: included in combined focused run below, all assembler tests passed.
5. Focused brief tests: `uv run python -m pytest tests/test_nautilus_sidecar_actor.py tests/test_nautilus_market_view_assembler.py -q`
   - Observed: `....... [100%]`.
6. Task 4 boundary test: `uv run python -m pytest tests/test_nautilus_platform_boundary.py::test_default_runtime_has_no_shared_external_sidecar_store -q`
   - Observed: `. [100%]`.
7. Runtime-focused affected files: `uv run python -m pytest tests/test_nautilus_market_rotation.py tests/test_nautilus_strategy_base.py tests/test_nautilus_full_paper_runtime_smoke.py tests/test_nautilus_native_exit.py tests/test_nautilus_native_order.py -q`
   - Observed: `........................................................................ [ 73%]` and `.......................... [100%]`.
8. Source boundary grep: `grep` tool for `ExternalDataSidecar|update_spot\(|update_price_to_beat\(|self\.sidecar` over `src/polysignal_lab/nautilus_runtime` and `src/polysignal_lab/nautilus_bridge`
   - Observed: no matches found.

## Commit

- `2596aa22ac89b47e6d8b952356f8a9a20559aec6` — `refactor: remove shared Nautilus sidecar state`

## Self-review notes

- `CustomDataPublisher` is stateless and only publishes `PolySignal*Data` payloads through the injected publisher.
- `StrategyCustomDataState` owns strategy-local `SpotView` and `PriceToBeatView` snapshots derived from Nautilus custom data messages.
- `MarketViewAssembler` now reads spot/PTB snapshots through the `CustomDataSnapshotProvider` seam while keeping the existing `PolymarketMarketRegistry` condition lookup; no Task 5 market catalog was introduced.
- `MarketRotationActor`, runtime class wrappers, and node wiring no longer construct or pass shared sidecar state.
- Removed only the Task 4 xfail marker from `test_default_runtime_has_no_shared_external_sidecar_store`; other future-task xfails were left unchanged.
- Pre-existing unstaged `.superpowers/sdd/progress.md` and `.superpowers/sdd/task-1-report.md` changes were not modified or committed.
