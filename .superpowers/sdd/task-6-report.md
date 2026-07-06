# Task 6 Report

## Files changed
- `src/polysignal_lab/nautilus_runtime/market_rotation.py`
- `src/polysignal_lab/nautilus_runtime/node.py`
- `src/polysignal_lab/nautilus_runtime/runtime_classes.py`
- `src/polysignal_lab/data/price_to_beat_provider.py`
- `src/polysignal_lab/data/polymarket_market_discovery.py`
- `src/polysignal_lab/app/services/market_universe_service.py`
- `tests/test_nautilus_sidecar_actor.py`
- `tests/test_nautilus_platform_boundary.py`
- `tests/test_nautilus_market_rotation.py`
- `tests/test_nautilus_node.py`
- `tests/test_nautilus_full_paper_runtime_smoke.py`

## Tests run
- `uv run python -m pytest tests/test_nautilus_sidecar_actor.py::test_market_rotation_actor_uses_clock_timer_for_startup -q`
  - RED observed before implementation: failed with `TypeError: MarketRotationActor.__init__() got an unexpected keyword argument 'catalog'`.
- `uv run python -m pytest tests/test_nautilus_sidecar_actor.py::test_market_rotation_actor_uses_clock_timer_for_startup -q`
  - GREEN observed after implementation: `1 passed` (`.` at 100%).
- `uv run python -m pytest tests/test_nautilus_sidecar_actor.py::test_market_rotation_actor_uses_clock_timer_for_startup tests/test_nautilus_platform_boundary.py::test_default_runtime_has_no_asyncio_actor_scheduling_fallbacks -q`
  - Observed summary: `2 passed` (`..` at 100%).
- `uv run python -m py_compile src/polysignal_lab/nautilus_runtime/market_rotation.py src/polysignal_lab/data/price_to_beat_provider.py src/polysignal_lab/app/services/market_universe_service.py src/polysignal_lab/data/polymarket_market_discovery.py tests/test_nautilus_market_rotation.py tests/test_nautilus_sidecar_actor.py tests/test_nautilus_platform_boundary.py`
  - Observed summary: exit 0, no output.
- `uv run python -m pytest tests/test_nautilus_market_rotation.py -q`
  - First focused run exposed stale tests targeting removed async fallback behavior; after updating those tests to the Task 6 synchronous seam, observed summary: `18 passed` (`..................` at 100%).
- `uv run python -m pytest tests/test_nautilus_node.py -q`
  - First focused run exposed one stale `registry` actor-constructor assertion; after updating it to `catalog`, observed summary: `45 passed` (`.............................................` at 100%).
- `uv run python -m pytest tests/test_nautilus_full_paper_runtime_smoke.py::test_runtime_sidecar_actor_and_native_strategy_bridge_to_order_submit tests/test_nautilus_full_paper_runtime_smoke.py::test_market_rotation_actor_rotates_single_native_strategy_without_rebuild -q`
  - First focused run exposed stale async PTB task expectations; after updating to `get_sync`, observed summary: `2 passed` (`..` at 100%).
- `uv run python -m pytest tests/test_nautilus_sidecar_actor.py::test_market_rotation_actor_uses_clock_timer_for_startup tests/test_nautilus_platform_boundary.py::test_default_runtime_has_no_asyncio_actor_scheduling_fallbacks tests/test_nautilus_market_rotation.py tests/test_nautilus_node.py tests/test_nautilus_full_paper_runtime_smoke.py::test_runtime_sidecar_actor_and_native_strategy_bridge_to_order_submit tests/test_nautilus_full_paper_runtime_smoke.py::test_market_rotation_actor_rotates_single_native_strategy_without_rebuild -q`
  - Final observed summary: all selected tests passed (`...................................................................` at 100%).

## Commit
- `bf19c8b14cc99d4afd9d538d46373f91f5caaa02` — `refactor: remove asyncio scheduling from Nautilus actors`

## Self-review notes
- Removed actor-owned `asyncio.create_task`, `asyncio.sleep`, event-loop, `asyncio.run`, and thread-offload fallback patterns from the default market rotation actor path.
- `MarketRotationActor.on_start()` now requires the Nautilus actor clock timer when market rotation is enabled and publishes startup PTB data synchronously.
- `_on_refresh_timer()` now uses `market_universe.refresh_once_sync()` and `_publish_price_to_beat_batch_sync()` without actor-local asyncio scheduling.
- `on_stop()` stops RTDS and cancels the Nautilus timer when a clock exposes `cancel_timer`.
- Added synchronous PTB and market discovery seams (`PriceToBeatProvider.get_sync()`, `MarketDiscovery.discover_sync()`, `MarketUniverseService.refresh_once_sync()`) with the sync discovery client scoped and closed within the refresh call.
- Removed only the Task 6 xfail from the scheduling boundary test; the Task 7 xfail remains unchanged.
- Left pre-existing unstaged SDD/progress files untouched and committed only Task 6 source/test changes.


## Follow-up fix: fail fast for unsupported actor-owned RTDS spot source

### Files changed
- `src/polysignal_lab/nautilus_runtime/market_rotation.py`
- `src/polysignal_lab/config.py`
- `config/signal_bot.yaml`
- `config/signal_bot.lab.yaml`
- `tests/test_nautilus_sidecar_actor.py`
- `tests/test_nautilus_market_rotation.py`
- `tests/test_nautilus_runtime_config.py`

### Tests run
- Focused RTDS fail-fast and timer tests: `uv run python -m pytest tests/test_nautilus_sidecar_actor.py::test_market_rotation_actor_fails_fast_for_unmanaged_rtds_source tests/test_nautilus_sidecar_actor.py::test_market_rotation_actor_uses_clock_timer_for_startup -q`
  - Observed: `..                                                                       [100%]`, exit 0.
- Runtime config tests: `uv run python -m pytest tests/test_nautilus_runtime_config.py -q`
  - Observed: `............                                                             [100%]`, exit 0.
- Task 6 focused runtime tests: `uv run python -m pytest tests/test_nautilus_sidecar_actor.py::test_market_rotation_actor_fails_fast_for_unmanaged_rtds_source tests/test_nautilus_sidecar_actor.py::test_market_rotation_actor_uses_clock_timer_for_startup tests/test_nautilus_platform_boundary.py::test_default_runtime_has_no_asyncio_actor_scheduling_fallbacks tests/test_nautilus_market_rotation.py tests/test_nautilus_node.py tests/test_nautilus_full_paper_runtime_smoke.py::test_runtime_sidecar_actor_and_native_strategy_bridge_to_order_submit tests/test_nautilus_full_paper_runtime_smoke.py::test_market_rotation_actor_rotates_single_native_strategy_without_rebuild -q`
  - Observed: `....................................................................     [100%]`, exit 0.
- Config source scan: grep pattern `spot_source: polymarket_rtds` over `config/`
  - Observed: no matches.

### Commit
- `acdab4b` — `fix: fail fast for unmanaged Nautilus RTDS spot source`.

### Self-review notes
- `MarketRotationActor` no longer leaves an unstarted RTDS feed in the default path: the default and checked-in YAML configs now set `runtime.nautilus.sidecar.spot_source=disabled`.
- If a caller explicitly sets `spot_source=polymarket_rtds`, `on_start()` fails fast with an actionable managed-lifecycle error instead of silently constructing a feed that never runs.
- `on_stop()` stops an RTDS feed only when one was explicitly configured.
