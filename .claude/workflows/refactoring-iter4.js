export const meta = {
  name: 'fix-p0-issues-iter4',
  description: 'Fix the 4 specific P0 issues from iter3 review, then verify',
  phases: [
    { title: 'Fix on_order_denied' },
    { title: 'Fix alpha core state persistence' },
    { title: 'Fix async timeout + dual governance' },
    { title: 'Final verification' },
  ],
}

phase('Fix on_order_denied')
const f1 = await agent(`
Fix the custom on_order_denied callback that doesn't exist in Nautilus Strategy API.

File: src/polysignal_lab/nautilus_runtime/native_strategy.py (line ~359)

Current (pre-existing bug):
    def on_order_denied(self, event: object) -> None:
        alpha_event = _order_event(event)
        self._call_core("on_order_denied", alpha_event)

Nautilus Strategy only defines these order callbacks:
- on_order_submitted
- on_order_accepted
- on_order_rejected
- on_order_canceled
- on_order_expired
- on_order_filled
- on_order_pending_update
- on_order_updated
- on_order_partially_filled

If "denied" is a legitimate PolySignal concept (e.g., a signal that was rejected by the gate), it should be handled differently:

Option A: Remove the method and handle "denied" logic inside _on_decision or evaluate_condition instead.
Option B: Route it through on_order_rejected if appropriate.
Option C: If this is a custom signal-layer concept (not Nautilus order denial), rename to make it clear it's not a Nautilus callback: _on_signal_denied or process_order_denied.

Read the full native_strategy.py to understand:
- Where on_order_denied is called from
- Whether it's related to signal rejection or actual order denial
- What test coverage exists

Apply the fix. Update tests if needed.

VERIFY: cd /home/debian/polysignal-lab && python -c "from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy; print('OK')"
`, {label: 'fix on_order_denied'})

phase('Fix alpha core state persistence')
const f2 = await agent(`
Add save_state/load_state to 3 alpha cores that lack them.

Files that need fixing:
- src/polysignal_lab/alpha/dump_hedge_core.py (mutable state: _positions, _entered_markets, _dump_detected)
- src/polysignal_lab/alpha/pre_order_market_core.py (mutable state: _pre_ordered, _entry_prices)
- src/polysignal_lab/alpha/mid_price_sizing_core.py (mutable state: _entry_prices)

Read each file to understand their state structure.

For each, add:
    def save_state(self) -> dict[str, object]:
        return {"key": self._value}

    def load_state(self, state: dict[str, object]) -> None:
        self._value = state.get("key", default)

Use the patterns from other alpha cores that already implement these methods (e.g., vwap_momentum_core.py, binary_momentum_core.py).

Also update PolySignalNativeStrategy.on_save in native_strategy.py:
- At the spot where it checks getattr(core, "save_state", None), add a warning if the core lacks save_state:
    import warnings
    if not hasattr(core, "save_state"):
        warnings.warn(f"{type(core).__name__} has no save_state — state will not persist across restarts")

VERIFY:
cd /home/debian/polysignal-lab && python -c "
from polysignal_lab.alpha.dump_hedge_core import DumpHedgeAlphaCore
from polysignal_lab.alpha.pre_order_market_core import PreOrderMarketAlphaCore
from polysignal_lab.alpha.mid_price_sizing_core import MidPriceSizingAlphaCore
print('all imports OK')
"
`, {label: 'fix state persistence'})

phase('Fix async timeout + dual governance')
const f3 = await agent(`
Fix two issues:

### Issue 1: Fire-and-forget task without timeout
File: src/polysignal_lab/nautilus_runtime/market_rotation.py

Find where asyncio.create_task(self._refresh_async()) is called (probably in _on_refresh_timer).
Add asyncio.wait_for with a timeout of 30 seconds:
    try:
        await asyncio.wait_for(self._refresh_async(), timeout=30)
    except asyncio.TimeoutError:
        logger.warning("market refresh timed out after 30s")
        self._mark_down(TimeoutError("refresh timeout"), phase="refresh")

### Issue 2: Dual governance warning
File: src/polysignal_lab/nautilus_runtime/scheduler_bridge.py

The DecisionPolicyActor and the legacy signal_layer (SignalGate, ConsensusEngine, SignalArbiter) coexist.
Add a runtime warning comment at the point where both are wired:
    # TODO: Dual governance — DecisionPolicyActor subsumes SignalGate/Consensus/SignalArbiter.
    # Legacy signal_layer is still wired for back-compat. Deactivate one pathway.

Also check: does node_builder.py or strategy_builder.py also wire both? If so, add the same warning there.

VERIFY: cd /home/debian/polysignal-lab && python -c "
from polysignal_lab.nautilus_runtime.market_rotation import MarketRotationActor
print('market_rotation OK')
from polysignal_lab.nautilus_runtime.scheduler_bridge import _initialize_nautilus_scheduler_components
print('scheduler_bridge OK')
"
`, {label: 'fix timeout + governance'})

phase('Final verification')
log('Running targeted import + size checks...')

const ok1 = await agent(`
Check if these conditions are met:
1. native_strategy.py does NOT define on_order_denied (check with grep or Read)
2. dump_hedge_core.py, pre_order_market_core.py, mid_price_sizing_core.py have save_state method
3. market_rotation.py _on_refresh_timer has asyncio.wait_for with timeout

Return:
- allFixed: boolean
- details: string
`, {label: 'verify fixes', schema: {
  type: 'object',
  properties: {
    allFixed: {type: 'boolean'},
    details: {type: 'string'},
  },
  required: ['allFixed', 'details'],
}})

return {
  clean: ok1.allFixed,
  details: ok1.details,
  summary: ok1.allFixed
    ? '✅ All targeted P0 issues from iter3 review are fixed'
    : 'Some fixes may need attention: ' + ok1.details,
}
