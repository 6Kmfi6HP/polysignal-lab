# Task 8 Report: Docs and safety boundary

## Files changed

- `src/polysignal_lab/observability/safety.py`
- `docs/NAUTILUS_BRIDGE_BOUNDARY.md`
- `docs/IMPLEMENTATION_SUMMARY.md`
- `docs/PROJECT_ARCHITECTURE_VISUAL.md`
- `docs/PRD.md`
- `tests/test_nautilus_platform_boundary.py`

## Checks/tests run

1. `uv run polysignal-safety-scan .`
   - Observed summary: `Safety scan passed`.

2. `uv run polysignal-safety-scan . && uv run python -m pytest tests/test_nautilus_platform_boundary.py -q`
   - First run observed summary: safety scan passed, then pytest failed in `test_default_source_keeps_forbidden_live_symbols_out_of_runtime` because `src/polysignal_lab/nautilus_runtime/live_node.py` legitimately contains the sandbox config key token `exec_clients` while still needing all live-execution symbols enforced.
   - Follow-up change: narrowed the test allow-list to remove only `exec_clients` for `trading_node.py`/`live_node.py`; all other forbidden tokens remain checked in those files.

3. `uv run polysignal-safety-scan . && uv run python -m pytest tests/test_nautilus_platform_boundary.py -q`
   - Observed summary: `Safety scan passed`; `..................... [100%]`.

4. `uv run python -m pytest tests/test_safety.py::test_safety_scan_project_source -q`
   - Observed summary: `. [100%]`.

## Commit

- `8100468317299fa6749542b3dd85c85b467d602a` — `docs: document final Nautilus runtime boundary`

## Self-review notes

- Public docs now describe the default Nautilus runtime as `LiveNode.builder(...)` + Nautilus sandbox execution, not legacy `TradingNode` or a local paper execution wheel.
- Docs now describe market data/custom-data state as Nautilus cache plus strategy-local `CustomData` derived state, not a shared external sidecar store.
- Task 6 RTDS decision is explicit in boundary/PRD text: checked-in defaults keep `runtime.nautilus.sidecar.spot_source: disabled`; explicit `polymarket_rtds` is documented as fail-fast/unsupported until a Nautilus-managed data-client lifecycle exists.
- Safety scan now blocks the completed Task 2-7 boundary tokens. `asyncio.create_task(` is scoped to the actor fallback files so scheduler/CLI lifecycle tasks are not falsely blocked while stale actor-owned fallback scheduling remains forbidden.
- `tests/test_nautilus_platform_boundary.py` keeps live-execution credential/factory token checks active for `live_node.py`; only the sandbox `exec_clients` config key is exempted.
- Pre-existing uncommitted `.superpowers/sdd/progress.md` and earlier task report edits were not touched or committed.


## Follow-up fix: actor-owned asyncio safety scan scope

### Files changed
- `src/polysignal_lab/observability/safety.py`
- `tests/test_safety.py`

### Checks/tests run
- Safety scan: `uv run polysignal-safety-scan .`
  - Observed: `Safety scan passed`, exit 0.
- Focused safety/platform checks: `uv run polysignal-safety-scan . && uv run python -m pytest tests/test_nautilus_platform_boundary.py tests/test_safety.py::test_safety_scan_blocks_create_task_in_nautilus_actor_fallback_paths tests/test_safety.py::test_safety_scan_project_source -q`
  - Observed: `Safety scan passed`; `.......................                                                  [100%]`, exit 0.

### Commit
- `1142547` — `fix: enforce Nautilus actor scheduling safety boundary`.

### Self-review notes
- The safety scan keeps `asyncio.create_task(` scoped to actor-owned Nautilus fallback paths (`market_rotation.py`, `sidecar_data.py`) so CLI/report lifecycle tasks in `node.py` remain allowed.
- Added a focused safety test proving actor-owned fallback paths are blocked while `node.py` is exempt from that actor-specific rule.


## Follow-up fix: document MarketCatalog boundary and soften legacy TradingNode wording

### Files changed
- `docs/NAUTILUS_BRIDGE_BOUNDARY.md`
- `docs/PROJECT_ARCHITECTURE_VISUAL.md`
- `docs/IMPLEMENTATION_SUMMARY.md`

### Checks/tests run
- Focused safety/platform checks: `uv run polysignal-safety-scan . && uv run python -m pytest tests/test_nautilus_platform_boundary.py tests/test_safety.py::test_safety_scan_blocks_create_task_in_nautilus_actor_fallback_paths tests/test_safety.py::test_safety_scan_project_source -q`
  - Observed: `Safety scan passed`; `.......................                                                  [100%]`, exit 0.
- Stale docs phrase scan: grep pattern `market registry|legacy `TradingNode` is absent from runtime source` over Task 8 docs
  - Observed: no matches.

### Commit
- `2a3044a` — `docs: clarify MarketCatalog runtime boundary`.

### Self-review notes
- Added positive `MarketCatalog` documentation to the bridge boundary, implementation summary, and architecture visual docs.
- Reworded legacy `TradingNode` claims to target the removed import/config construction surface rather than every textual compatibility label.


## Follow-up fix: align PRD spot config snippet

### Files changed
- `docs/PRD.md`

### Checks/tests run
- Focused safety/platform checks: `uv run polysignal-safety-scan . && uv run python -m pytest tests/test_nautilus_platform_boundary.py tests/test_safety.py::test_safety_scan_blocks_create_task_in_nautilus_actor_fallback_paths tests/test_safety.py::test_safety_scan_project_source -q`
  - Observed: `Safety scan passed`; `.......................                                                  [100%]`, exit 0.
- Stale PRD config scan: grep pattern `data:
\s+spot:|runtime_actor_source|explicit_polymarket_rtds` over `docs/PRD.md`
  - Observed: no matches.

### Commit
- `d92a49d` — `docs: align PRD Nautilus spot config path`.

### Self-review notes
- Replaced the invented `data.spot.*` snippet with the real checked-in `runtime.nautilus.sidecar.spot_source` and `price_to_beat_source` path.
- Kept the existing fail-fast note for explicit `runtime.nautilus.sidecar.spot_source: polymarket_rtds` elsewhere in the PRD.
