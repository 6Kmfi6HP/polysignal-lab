# Acceptance Fix Report — Cache Reader + Scheduler Compat Isolation

## Changes Applied

### Gap A: Nautilus Cache/Portfolio Reader

Created `src/polysignal_lab/nautilus_runtime/cache_reader.py`:
- `NautilusCacheReader` — read-only projection adapter over Nautilus cache/portfolio
- `read_orders()` / `read_fills()` / `read_positions()` — project cache callables through existing projections
- `read_account()` — reads `cache.account()` (callable, duck-typed)
- `snapshot_portfolio()` — reads `cache.portfolio` (callable or attribute), returns `None` when absent
- Returns empty lists / `None` for missing cache entries

Created `tests/test_nautilus_cache_reader.py` (7 tests):
- Orders, fills, positions, account, portfolio (callable), portfolio (attribute), empty cache

### Gap B: Scheduler Compat Isolation

Created `src/polysignal_lab/nautilus_runtime/scheduler_compat.py`:
- `COMPATIBILITY_ONLY = True` marker
- `init_scheduler_paper_components(scheduler)` — one-time compat init for PaperWallet/PaperExitEngine/PaperSettlementEngine

Edited `src/polysignal_lab/nautilus_runtime/node.py`:
- `_initialize_nautilus_scheduler_components()`: replaced direct Paper* imports + instantiation with `init_scheduler_paper_components(scheduler)` call

Edited `tests/test_nautilus_platform_boundary.py`:
- Exclusion set: `"node.py"` replaced by `"scheduler_compat.py"` — Paper* truth sources now isolated to the compat module

### Additional (Main IRC request)

Added `read_account()` and `snapshot_portfolio()` methods to `NautilusCacheReader` with corresponding tests. `snapshot_portfolio()` handles both callable and direct-attribute portfolio interfaces per harness advisory.

## Verification

All three test batches pass:

1. `tests/test_nautilus_cache_reader.py` + `test_nautilus_projections.py` + `test_nautilus_observability.py` — 24 passed
2. `tests/test_nautilus_platform_boundary.py` + `test_nautilus_safety_boundary.py` — 11 passed
3. `tests/test_nautilus_native_order.py` + `test_nautilus_strategy_base.py` + `test_nautilus_trading_node_runtime.py` + `test_nautilus_node.py` + `test_nautilus_full_paper_runtime_smoke.py` — 14 passed, 2 skipped (nautilus_trader optional dep)

Total: 49 passed, 2 skipped, 0 failed.
