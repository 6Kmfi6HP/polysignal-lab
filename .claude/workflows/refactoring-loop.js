export const meta = {
  name: 'compliance-refactoring-loop',
  description: 'Refactor based on compliance review - no worktree isolation, sequential agents',
  phases: [
    { title: 'P0-1: Strategy Wrapper Split' },
    { title: 'P0-2a: node_builder.py' },
    { title: 'P0-2b: strategy_builder + scheduler_bridge' },
    { title: 'P1: Independent Fixes' },
    { title: 'Verify' },
  ],
}

const REVIEW_SCRIPT_PATH = '/home/debian/polysignal-lab/.claude/workflows/compliance-review.js'
const MAX_ITER = 3
let iteration = 0
let clean = false

while (!clean && iteration < MAX_ITER) {
  iteration++
  log(`=== Iteration ${iteration}/${MAX_ITER} ===`)

  if (budget.total && budget.remaining() < 500_000) {
    log('Budget too low for full iteration, stopping'); break
  }

  // ═══════════════════════════════════════════════
  // P0-1+P0-3: Create strategy/ sub-package from native_strategy.py
  // ═══════════════════════════════════════════════
  phase('P0-1: Strategy Wrapper Split')
  log('Splitting native_strategy.py into strategy/ sub-package')

  const p0_1 = await agent(`
Split native_strategy.py (1231 lines) into a strategy/ sub-package.

FILES TO READ FIRST:
- src/polysignal_lab/nautilus_runtime/native_strategy.py (1231 lines)
- src/polysignal_lab/nautilus_runtime/strategies/base.py (559 lines)
- src/polysignal_lab/nautilus_runtime/strategies/__init__.py

TASK:
Create src/polysignal_lab/nautilus_runtime/strategy/ with these modules:

1. strategy/helpers.py — Move all free functions from native_strategy.py:
   - classify_project_owned_data(), DataBoundaryClassification enum
   - _value(), _tags(), _identifier_text(), _nautilus_instrument_id()
   - _subscribe_custom_data(), _instrument_ids(), _asset_conditions()
   - _projection_order_event(), _projection_fill_event(), _fallback_fill_price()
   - All module-level constants: DEFAULT_NATIVE_DATA_NAMES, MISSING_PROJECTIONS_ERROR, EVALUATION_HEARTBEAT_TIMER_NAME, EVALUATION_HEARTBEAT_INTERVAL, DEFAULT_L1_BOOK_SNAPSHOT_INTERVAL_MS, L1_RAW_DELTA_FALLBACK_PHASE
   - Protocols: _Assembler, _Observability (to avoid circular imports)
   - ONLY import needed types (avoid importing from lifecycle or events sub-modules)

2. strategy/subscriptions.py — Move MarketSubscriptionState dataclass and subscription logic
   - DataBoundaryClassification enum (OR import from helpers if moved there)
   - MarketSubscriptionState class
   - classify_project_owned_data() if it uses subscription state
   - Related import statements

3. strategy/__init__.py — Re-export PolySignalNativeStrategy and all public symbols

4. After creating sub-package, EDIT native_strategy.py:
   - Replace all moved code with imports from strategy.{helpers,subscriptions,lifecycle,events,exit}
   - Keep PolySignalNativeStrategy CLASS in native_strategy.py but have its methods imported or delegated
   - KEEP all imports from the sub-package working: native_strategy.py must still export PolySignalNativeStrategy

NOTE: lifecycle.py and events.py and exit.py require more careful class-method extraction.
For this pass, focus on:
- Moving ALL free functions and constants to helpers.py
- Moving MarketSubscriptionState to subscriptions.py
- Keeping PolySignalNativeStrategy class methods IN PLACE but delegating to helpers
- Ensuring native_strategy.py still imports and exports everything it did before

DO NOT touch alpha/*.py files.
DO NOT delete strategies/ files yet.
KEEP all existing public API surface.

VERIFY: cd /home/debian/polysignal-lab && python -c "from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy; print('OK')"
`, {label: `P0-1 iter${iteration}`})

  // ═══════════════════════════════════════════════
  // P0-2a: Create node_builder.py
  // ═══════════════════════════════════════════════
  phase('P0-2a: Create node_builder.py')
  log('Extracting node builder functions to node_builder.py')

  const p0_2a = await agent(`
Create src/polysignal_lab/nautilus_runtime/node_builder.py by extracting functions from node.py.

FILES TO READ:
- src/polysignal_lab/nautilus_runtime/node.py (1081 lines) — source
- src/polysignal_lab/nautilus_runtime/__init__.py — exports

TASK:
Create node_builder.py containing:
1. Module-level globals: LiveNode, PolymarketInstrumentProviderConfig, NautilusActor, NautilusStrategy, NautilusActorConfig, NautilusStrategyConfig
2. All class/type definitions: _TraderLike, _Disposable, _NautilusNodeLike, _NativeStrategyLike, _EmptyBookDataProvider, _StaticMarketUniverse, NautilusRuntimeBundle
3. Functions:
   - _ensure_nautilus_imports()
   - _load_runtime_classes()
   - _runtime_class_triple()
   - _create_configured_live_node(settings, configured_markets)
   - _create_market_projection_components(configured_markets)
   - _register_markets(registry, markets)
   - _instrument_load_ids(markets)
   - _build_runtime_context(settings, condition_ids, markets, market_universe)
   - _configured_condition_ids(condition_ids, markets)
   - build_trading_node(settings, *, condition_ids, markets, ...)
   - build_nautilus_runtime(settings, ...)  [if this function exists — search for "def build_nautilus_runtime"]
   - _runtime_components(...)

After creating node_builder.py, UPDATE node.py:
- IMPORT all these symbols from node_builder instead of defining them locally
- Remove the moved functions from node.py

IMPORTANT: Keep the SAME function signatures. When moving _ensure_nautilus_imports(), keep the lazy-import + sys.modules sync pattern intact.

VERIFY: cd /home/debian/polysignal-lab && python -c "from polysignal_lab.nautilus_runtime.node_builder import build_trading_node; print('node_builder OK')"
`, {label: `P0-2a iter${iteration}`})

  // ═══════════════════════════════════════════════
  // P0-2b: Create strategy_builder.py + scheduler_bridge.py
  // ═══════════════════════════════════════════════
  phase('P0-2b: strategy_builder + scheduler_bridge')
  log('Extracting strategy building and scheduler bridge functions')

  const p0_2b = await agent(`
Create two modules from remaining node.py functions.

FILES TO READ:
- src/polysignal_lab/nautilus_runtime/node.py (currently active)
- src/polysignal_lab/nautilus_runtime/node_builder.py (just created — check if functions already moved)
- src/polysignal_lab/nautilus_runtime/__init__.py
- tests/test_nautilus_node.py
- tests/test_nautilus_trading_node_runtime.py

TASK PART A: Create strategy_builder.py

Move these functions from node.py to strategy_builder.py:
- _build_native_strategies(settings, assembler, policy, condition_ids, registry, observability)
- _create_native_strategy(strategy_type, settings, assembler, policy, ...)
- _attach_strategy_custom_data(strategy, assembler)
- _build_policy(settings, *, policy_type)
- build_control(policy)
- _build_nautilus_config_strategy_schedule(settings)
- _fixed_stake_for(cfg)
- _instrument_id_resolver(registry)
- _native_core_for(name, cfg)

Also add an AlphaCoreRegistry class:
class AlphaCoreRegistry:
    _registry: dict[str, type[AlphaCore]] = {}
    @classmethod def register(cls, name, core_cls): cls._registry[name] = core_cls
    @classmethod def build(cls, name, cfg): ... cls._registry.get(name)(cfg) or None
    @classmethod def names(cls): return tuple(cls._registry.keys())

Replace _native_core_for's if/elif dict with a lookup using AlphaCoreRegistry.

TASK PART B: Create scheduler_bridge.py

Move these functions from node.py to scheduler_bridge.py:
- _initialize_nautilus_scheduler_components(settings, scheduler, configured_markets, discovered_markets, market_universe, store, health, observability)
- _seed_policy_control_from_scheduler(policy, scheduler)
- _disabled_strategy_names_from_scheduler(scheduler)
- _get_or_create_observability(settings, scheduler)
- _register_native_strategy_callback(strategy)

TASK PART C: Update node.py
- Replace all moved functions with imports from strategy_builder and scheduler_bridge
- Keep node.py working as thin orchestration layer + CLI helpers

TASK PART D: Update __init__.py
- Ensure nautilus_runtime/__init__.py still exports public API from correct locations

TASK PART E: Update test files
- Find and update imports in tests/ that reference moved functions

SEARCH for references:
grep -rn "from polysignal_lab.nautilus_runtime.node import\\|from polysignal_lab.nautilus_runtime import" tests/ --include="*.py"
grep -rn "nautilus_runtime\.node\." src/ --include="*.py"

VERIFY: cd /home/debian/polysignal-lab && python -c "from polysignal_lab.nautilus_runtime import build_trading_node, build_nautilus_runtime; print('OK')"
`, {label: `P0-2b iter${iteration}`})

  // ═══════════════════════════════════════════════
  // P1-1: Rename NautilusDecisionPolicyActor
  // ═══════════════════════════════════════════════
  phase('P1: Independent Fixes')
  log('P1-1: Renaming NautilusDecisionPolicyActor')

  const p1_1 = await agent(`
Rename NautilusDecisionPolicyActor → LiveDecisionPolicyActor in runtime_classes.py.

Files:
- src/polysignal_lab/nautilus_runtime/runtime_classes.py
- src/polysignal_lab/nautilus_runtime/node.py (references it)
- src/polysignal_lab/nautilus_runtime/node_builder.py (references it, if it exists)
- src/polysignal_lab/nautilus_runtime/decision_policy_actor.py (defines the seam)

Changes:
1. In runtime_classes.py line 93: class NautilusDecisionPolicyActor → class LiveDecisionPolicyActor
2. Update __all__ tuple (line ~104-106)
3. Search all src/ files for "NautilusDecisionPolicyActor" and update references
4. Keep backward compat: NautilusDecisionPolicyActor = LiveDecisionPolicyActor (alias)

VERIFY: cd /home/debian/polysignal-lab && python -c "from polysignal_lab.nautilus_runtime.runtime_classes import LiveDecisionPolicyActor; print('OK')"
`, {label: `P1-1 iter${iteration}`})

  // ═══════════════════════════════════════════════
  // P1-2: Guard scheduler dead code
  // ═══════════════════════════════════════════════
  log('P1-2: Guarding scheduler dead code')
  const p1_2 = await agent(`
Add runtime guards to legacy scheduler evaluation pipeline.

Files:
- src/polysignal_lab/app/scheduler_processing.py
- src/polysignal_lab/app/scheduler_runtime.py
- src/polysignal_lab/nautilus_runtime/signal_sidecar.py (might import _generate_iteration_report)

Steps:
1. Read both files to understand functions
2. For evaluate_once() in scheduler_processing.py: add at top:
   raise RuntimeError("Legacy scheduler evaluation disabled in Nautilus mode")
3. For run() in scheduler_runtime.py: add at top:
   raise RuntimeError("Legacy scheduler runtime disabled in Nautilus mode")
4. If signal_sidecar.py imports _generate_iteration_report from scheduler_processing, move that function to app/report_helpers.py first, update the import, THEN add the guards.

VERIFY: cd /home/debian/polysignal-lab && python -c "from polysignal_lab.app.scheduler_processing import evaluate_once; print('import OK')"
`, {label: `P1-2 iter${iteration}`})

  // ═══════════════════════════════════════════════
  // P1-3: Consolidate MarketDiscovery async/sync
  // ═══════════════════════════════════════════════
  log('P1-3: Consolidating MarketDiscovery async/sync')
  const p1_3 = await agent(`
Consolidate async/sync method duplication in MarketDiscovery.

File: src/polysignal_lab/data/polymarket_market_discovery.py

Currently has ~7 duplicated async/sync method pairs.
Task: Extract shared HTTP logic into helper, eliminate duplication.

Read the file first. Then consolidate using this approach:
- Create a single _request() helper that handles both async and sync clients
- Each async method stays async but delegates to _request(is_async=True)
- Each sync method stays sync but delegates to _request(is_async=False)
- Keep ALL public method signatures identical

VERIFY: cd /home/debian/polysignal-lab && python -c "from polysignal_lab.data.polymarket_market_discovery import MarketDiscovery; print('OK')"
`, {label: `P1-3 iter${iteration}`})

  // ═══════════════════════════════════════════════
  // P1-4: Consolidate trading_node.py
  // ═══════════════════════════════════════════════
  log('P1-4: Consolidating trading_node.py')
  const p1_4 = await agent(`
Consolidate trading_node.py constants into live_node.py.

Current trading_node.py (15 lines):
PAPER_EXEC_CLIENT_ID = "POLYSIGNAL_PM_PAPER"
POLYMARKET_CLIENT_ID = "POLYMARKET"
def assert_no_live_polymarket_execution(config)

Files:
- src/polysignal_lab/nautilus_runtime/trading_node.py — TO DELETE
- src/polysignal_lab/nautilus_runtime/live_node.py — TO MOVE INTO
- src/polysignal_lab/nautilus_runtime/node.py — references trading_node
- src/polysignal_lab/nautilus_runtime/node_builder.py — might reference trading_node
- tests/test_nautilus_node.py — line 22: imports PAPER_EXEC_CLIENT_ID from trading_node

Steps:
1. Read live_node.py to see if constants already exist there
2. If not, move PAPER_EXEC_CLIENT_ID and POLYMARKET_CLIENT_ID to live_node.py
3. Move assert_no_live_polymarket_execution to live_node.py
4. Update ALL references: grep -rn "trading_node" src/ tests/ --include="*.py"
5. Delete trading_node.py

VERIFY:
cd /home/debian/polysignal-lab && python -c "from polysignal_lab.nautilus_runtime.live_node import PAPER_EXEC_CLIENT_ID; print('OK')"
`, {label: `P1-4 iter${iteration}`})

  // ═══════════════════════════════════════════════
  // P1-10: Fix private member imports
  // ═══════════════════════════════════════════════
  log('P1-10: Fixing private member imports')
  const p1_10 = await agent(`
Fix private member imports. Make _market_metadata and _timestamp_ns public.

Files:
- src/polysignal_lab/nautilus_runtime/sidecar_data.py — define _market_metadata, _timestamp_ns
- src/polysignal_lab/nautilus_runtime/market_rotation.py — import them with private access

Steps:
1. In sidecar_data.py, find _market_metadata and _timestamp_ns
2. Rename to market_metadata and timestamp_ns
3. In market_rotation.py, update import to use public names
4. Remove the "# pyright: ignore[reportPrivateUsage]" comment
5. Check for other references: grep -rn "_market_metadata\\|_timestamp_ns" src/

VERIFY: cd /home/debian/polysignal-lab && python -c "from polysignal_lab.nautilus_runtime.market_rotation import _Health; print('OK')"
`, {label: `P1-10 iter${iteration}`})

  // ═══════════════════════════════════════════════
  // Verify Phase: Run compliance review
  // ═══════════════════════════════════════════════
  phase('Verify')
  log('Running compliance review to verify refactoring results...')

  const review = await workflow({scriptPath: REVIEW_SCRIPT_PATH})

  const verdict = await agent(`
Analyze this compliance review report for remaining P0 issues.

Return:
- hasP0: true/false
- remainingP0Details: what specific P0 issues remain (or "none")
- remainingP1Details: P1 issues still present (or "none")

REPORT:
${review}
`, {label: `verdict iter${iteration}`, schema: {
    type: 'object',
    properties: {
      hasP0: { type: 'boolean' },
      remainingP0Details: { type: 'string' },
      remainingP1Details: { type: 'string' },
    },
    required: ['hasP0', 'remainingP0Details', 'remainingP1Details'],
  }})

  clean = !verdict.hasP0
  log(`Iteration ${iteration}: clean=${clean}`)
  log(`P0 remaining: ${verdict.remainingP0Details || 'none'}`)
  log(`P1 remaining: ${verdict.remainingP1Details || 'none'}`)

  if (!clean && iteration >= MAX_ITER) {
    log('Max iterations reached with remaining P0 issues.')
  }
}

return {
  iterations: iteration,
  clean,
  message: clean
    ? '✓ All P0 compliance issues resolved'
    : `P0 issues remain after ${MAX_ITER} iterations`,
}
