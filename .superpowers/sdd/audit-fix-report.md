# Audit Fix Report

## Changes

### Fix 1: Projection store routes (`src/polysignal_lab/nautilus_runtime/observability.py`)
Added three missing table routes to `NautilusEventStoreAdapter.__init__`:
- `_routes`: `nautilus_order`, `nautilus_fill`, `nautilus_position` → `persistence.insert_system_event`
- `_streams`: `nautilus_order` → `nautilus_orders`, `nautilus_fill` → `nautilus_fills`, `nautilus_position` → `nautilus_positions`

These routes are needed by `ObservabilityActor.record_nautilus_order_event()` which calls `record_event("nautilus_order", ...)` and its siblings.

### Fix 2: Smoke test isolation regression (`tests/test_nautilus_full_paper_runtime_smoke.py`)
Reverted to committed pattern: deferred `import polysignal_lab.nautilus_runtime.node as node_mod` inside the test function, and used `monkeypatch.setattr(node_mod, ...)` instead of top-level `from ... import build_trading_node` with string-path monkeypatches. This survives platform-level reimport in test suites.

## Test Results

Batch 1:
```
uv run pytest tests/test_nautilus_native_order.py tests/test_nautilus_strategy_base.py \
  tests/test_nautilus_trading_node_runtime.py tests/test_nautilus_node.py \
  tests/test_nautilus_projections.py tests/test_nautilus_platform_boundary.py \
  tests/test_nautilus_safety_boundary.py tests/test_nautilus_full_paper_runtime_smoke.py -q
```
**36 passed, 2 skipped**

Batch 2:
```
uv run pytest tests/test_nautilus_projections.py tests/test_nautilus_observability.py -q
```
**17 passed**

## Status: DONE
