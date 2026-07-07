export const meta = {
  name: 'compliance-refactoring-iter2',
  description: 'Second iteration - resolve remaining P0 issues: dual wrappers + dead scheduler code',
  phases: [
    { title: 'F01: Merge Strategy Wrappers' },
    { title: 'F02: Clean Dead Scheduler Code' },
    { title: 'Verify' },
  ],
}

phase('F01: Merge Strategy Wrappers')
log('Merging CompatPolySignalNautilusStrategy into PolySignalNativeStrategy + deleting boilerplate subclasses')

const f01 = await agent(`
Resolve the dual strategy wrapper issue. PolySignalNativeStrategy (native_strategy.py) and CompatPolySignalNautilusStrategy (strategies/base.py) have ~70% overlap.

FILES TO READ FIRST:
- src/polysignal_lab/nautilus_runtime/native_strategy.py (848 lines) — PolySignalNativeStrategy
- src/polysignal_lab/nautilus_runtime/strategy/helpers.py (440 lines) — helpers extracted in P0-1
- src/polysignal_lab/nautilus_runtime/strategy/__init__.py — re-exports
- src/polysignal_lab/nautilus_runtime/strategies/base.py (569 lines) — CompatPolySignalNautilusStrategy
- src/polysignal_lab/nautilus_runtime/strategies/__init__.py — exports
- src/polysignal_lab/nautilus_runtime/strategies/*.py (13 boilerplate stubs: ptb_diff.py, binary_momentum.py etc.)
- src/polysignal_lab/nautilus_runtime/runtime_classes.py — uses PolySignalNativeStrategy
- tests/test_nautilus_strategy_wrappers.py — imports from strategies.*
- tests/test_nautilus_strategy_base.py — imports from strategies.base

TASK:
Step 1: Read both classes and identify the behavioral delta:
- How does each handle on_data?
- How does each handle on_start?
- State serialization differences?
- Any testing-specific hooks?

Step 2: Add a compat_mode parameter to PolySignalNativeStrategy.__init__:
    def __init__(self, ..., compat_mode: bool = False):
When compat_mode=True:
- on_data() should return list[NautilusOrderSpec] instead of dispatching to handlers
- Match CompatPolySignalNautilusStrategy's exact return types

Step 3: Update strategies/base.py:
- Make CompatPolySignalNautilusStrategy a thin subclass of PolySignalNativeStrategy with compat_mode=True
- OR: If the dispatch difference is fundamental, create a new factory function NautilusStrategyWrapper

Step 4: Delete all 13 boilerplate subclass files:
- strategies/ptb_diff.py
- strategies/binary_momentum.py
- strategies/cross_market_bot.py
- strategies/dump_hedge.py
- strategies/fibonacci_bot.py
- strategies/late_consensus.py
- strategies/low_side_dual_reversion.py
- strategies/mid_price_sizing.py
- strategies/ninety_nine_cent_sniper.py
- strategies/one_cent_buy.py
- strategies/pre_order_market.py
- strategies/skew_mean_reversion.py
- strategies/vwap_momentum.py

Step 5: Update strategies/__init__.py:
- Remove all boilerplate subclass imports
- Remove them from __all__
- Update exports to point to PolySignalNativeStrategy

Step 6: Update test imports:
- tests/test_nautilus_strategy_wrappers.py: change imports from strategies.XYZ to native_strategy or strategy
- Any other test files importing from strategies.*

DO NOT modify alpha/*.py files.

VERIFY: cd /home/debian/polysignal-lab && python -c "from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy; print('OK')"
`, {label: 'F01 merge wrappers'})

if (!f01) { log('F01 failed or returned null') }

// ═══════════════════════════════════════════════
// F02: Clean dead scheduler code
// ═══════════════════════════════════════════════
phase('F02: Clean Dead Scheduler Code')
log('Extracting shared function then removing dead scheduler code')

const f02 = await agent(`
Clean up dead scheduler code that is guarded with RuntimeError but still imported.

FILES:
- src/polysignal_lab/app/scheduler_runtime.py (~233 lines)
- src/polysignal_lab/app/scheduler_processing.py (~662 lines)
- src/polysignal_lab/nautilus_runtime/signal_sidecar.py (line 248: imports _generate_iteration_report from scheduler_runtime)

Current state:
- evaluate_once() in scheduler_processing.py has: raise RuntimeError("Legacy scheduler evaluation disabled")
- run() in scheduler_runtime.py has: raise RuntimeError("Legacy scheduler runtime disabled")
- signal_sidecar.py imports _generate_iteration_report from scheduler_runtime for report generation

TASK:
Step 1: Create src/polysignal_lab/app/scheduler_shared.py
- Move async def _generate_iteration_report() from scheduler_runtime.py (lines 232-244) to this file
- Move def _configured_report_date() from scheduler_runtime.py (lines 224-229) to this file
- Add needed imports (ZoneInfo, datetime, date, etc.)

Step 2: Update signal_sidecar.py line 248
- Change import from scheduler_runtime to scheduler_shared

Step 3: Clean scheduler_runtime.py
- Remove: _notify_startup, _notify_shutdown, stop, run, _evaluate_iteration, _process_iteration_signals, _check_iteration_settlements
- Remove the shared functions already moved to scheduler_shared
- Keep: any imports used elsewhere, the module docstring
- Add: from polysignal_lab.app.scheduler_shared import _generate_iteration_report, _configured_report_date as re-exports for backward compat

Step 4: Clean scheduler_processing.py
- Remove ALL functions except the RuntimeError guard in evaluate_once()
- Actually, keep ONLY evaluate_once() with its RuntimeError guard
- Keep imports needed by the module header
- Remove: _LegacyRejectionPersistence, _append_persistence_log, _write_persistence_sqlite, _note_snapshot_success, _note_snapshot_failure, _build_snapshot_for_market, everything

Step 5: Check for other imports:
- grep -rn "scheduler_processing" src/ tests/ --include="*.py"
- grep -rn "scheduler_runtime" src/ tests/ --include="*.py"
- Update any imports that reference removed functions

VERIFY: cd /home/debian/polysignal-lab && python -c "from polysignal_lab.app.scheduler_shared import _generate_iteration_report; print('shared OK')"
`, {label: 'F02 clean scheduler'})

if (!f02) { log('F02 failed or returned null') }

// ═══════════════════════════════════════════════
// Verify
// ═══════════════════════════════════════════════
phase('Verify')
log('Running compliance review to verify...')

const review = await workflow({scriptPath: '/home/debian/polysignal-lab/.claude/workflows/compliance-review.js'})

const verdict = await agent(`
Analyze this compliance review report. Return whether P0 issues remain.

Return:
- hasP0: true/false
- remainingP0Details: what P0 issues remain (or "none")
- remainingP1Details: P1 issues remaining (or "none")

REPORT:
${review}
`, {label: 'verdict', schema: {
  type: 'object',
  properties: {
    hasP0: {type: 'boolean'},
    remainingP0Details: {type: 'string'},
    remainingP1Details: {type: 'string'},
  },
  required: ['hasP0', 'remainingP0Details', 'remainingP1Details'],
}})

return {
  clean: !verdict.hasP0,
  p0Remaining: verdict.remainingP0Details,
  p1Remaining: verdict.remainingP1Details,
}
