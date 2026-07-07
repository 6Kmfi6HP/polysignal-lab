export const meta = {
  name: 'compliance-refactoring-iter3',
  description: 'Third iteration - deprecate compat wrapper + fix sync HTTP',
  phases: [
    { title: 'Deprecate base.py compat wrapper' },
    { title: 'Fix sync HTTP in market_rotation' },
    { title: 'Verify' },
  ],
}

phase('Deprecate base.py compat wrapper')
log('Deprecating CompatPolySignalNautilusStrategy in favor of PolySignalNativeStrategy')

const f1 = await agent(`
Resolve the remaining CompatPolySignalNautilusStrategy wrapper issue.

FILES:
- src/polysignal_lab/nautilus_runtime/strategies/base.py (582 lines)
- src/polysignal_lab/nautilus_runtime/strategies/__init__.py
- src/polysignal_lab/nautilus_runtime/native_strategy.py (856 lines)
- tests/test_nautilus_strategy_wrappers.py
- tests/test_nautilus_strategy_base.py
- src/polysignal_lab/nautilus_runtime/strategies/cross_market_bot.py (NOT a boilerplate - keep it)

TASK:
Read both CompatPolySignalNautilusStrategy (base.py) and PolySignalNativeStrategy (native_strategy.py) to understand the delta.

Step 1: In strategies/base.py:
- Add a deprecation warning at the top of CompatPolySignalNautilusStrategy.__init__:
  warnings.warn("CompatPolySignalNautilusStrategy is deprecated, use PolySignalNativeStrategy", DeprecationWarning, stacklevel=2)
- Make CompatPolySignalNautilusStrategy inherit from PolySignalNativeStrategy with compat_mode=True
- Remove any code that's now inherited from PolySignalNativeStrategy

Step 2: In strategies/__init__.py:
- Export both PolySignalNativeStrategy and CompatPolySignalNautilusStrategy
- Keep the deprecation path working

Step 3: Update test imports to target PolySignalNativeStrategy where possible

IMPORTANT: DO NOT delete strategies/base.py (needed for backward compat). Just deprecate.
DO NOT modify cross_market_bot.py.
DO NOT modify alpha/*.py

VERIFY: cd /home/debian/polysignal-lab && python -c "from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy; print('OK')"
`, {label: 'deprecate base.py'})

if (!f1) { log('F1 failed') }

// ═══════════════════════════════════════════════
// Fix sync HTTP in market_rotation
// ═══════════════════════════════════════════════
phase('Fix sync HTTP in market_rotation')
log('Replacing sync HTTP with async in _on_refresh_timer')

const f2 = await agent(`
Fix synchronous HTTP call inside Nautilus reactor event loop.

FILE: src/polysignal_lab/nautilus_runtime/market_rotation.py

Current _on_refresh_timer at line ~232:
    def _on_refresh_timer(self, _event: object = None) -> None:
        if self._refresh_in_flight:
            return
        self._refresh_in_flight = True
        try:
            refreshed_markets = tuple(self.market_universe.refresh_once_sync())
            ...
        except ...
            ...
        finally:
            self._refresh_in_flight = False

PROBLEM: This is called from a Nautilus timer callback. refresh_once_sync() makes blocking HTTP calls.

SOLUTION:
The cleanest fix depends on how this timer interacts with the Nautilus actor lifecycle.
Check if this method is called via a Nautilus Timer or if it's wired differently.

Approach A (preferred): Replace with async version if the caller supports it.
Approach B: Wrap in asyncio.to_thread() to avoid blocking the event loop.

Read the full file first, understand the context, then apply the fix.

OPTIONS:
1. If the timer callback supports async, change to async def and use await refresh_once()
2. If it must stay sync, use: loop = asyncio.get_event_loop(); loop.run_in_executor(None, self.market_universe.refresh_once_sync)

Choose the approach that preserves the same thread safety and avoids race conditions.

VERIFY: cd /home/debian/polysignal-lab && python -c "from polysignal_lab.nautilus_runtime.market_rotation import MarketRotationActor; print('OK')"
`, {label: 'fix sync HTTP'})

if (!f2) { log('F2 failed') }

// ═══════════════════════════════════════════════
// Verify
// ═══════════════════════════════════════════════
phase('Verify')
log('Running compliance review...')

const review = await workflow({scriptPath: '/home/debian/polysignal-lab/.claude/workflows/compliance-review.js'})

const verdict = await agent(`
Analyze this compliance review report for remaining P0 issues.

Return structured verdict.

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
