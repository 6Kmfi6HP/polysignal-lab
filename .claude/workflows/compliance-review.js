export const meta = {
  name: 'compliance-review',
  description: '6-agent parallel compliance review of Polysignal Lab Nautilus design boundaries',
  phases: [
    { title: 'Read Reference Docs' },
    { title: 'Parallel Review' },
    { title: 'Synthesize' },
  ],
}

phase('Read Reference Docs')
const principles = await agent('Read docs/nautilus_reference/developer_guide/design_principles.md and output the 3-5 most important constraints for this review (ownership, data-client, lifecycle, etc). Keep under 10 lines.', {label: 'doc:principles'})
const adapters = await agent('Read docs/nautilus_reference/developer_guide/adapters.md and output: (1) how data/execution engine works (2) cache + portfolio expectations (3) strategy lifecycle callbacks. Keep under 15 lines.', {label: 'doc:adapters'})

const docContext = [
  '=== DESIGN PRINCIPLES ===', principles,
  '=== ADAPTERS GUIDE ===', adapters,
].join('\n\n')

phase('Parallel Review')

const results = await parallel([
  () => agent(`[AGENT A - Nautilus Runtime Assembly]
Tool: CodeGraph only. No grep, no find, no blind file reading.
Reference docs: ${docContext}

Scope: src/polysignal_lab/nautilus_runtime/ node.py, live_node.py, trading_node.py, runtime_classes.py

Checks:
1. Does node.py properly use Nautilus TradingNode/DockerizedTradingNode? Or does it build its own runtime from scratch?
2. Any monkey-patching of Nautilus internals?
3. Any dynamic factory pattern that duplicates Nautilus's built-in component registration?
4. Is node.py >400 lines and multi-responsibility? (god-module)
5. runtime_classes.py - does it define classes that Nautilus already provides?

Output EXACTLY in the required format with:
## [Agent A] Nautilus Runtime Assembly
### 取证
### Nautilus 对齐
### 重复造轮子
### Oversized
### 合理保留
### 未决`, {label: 'Agent A', agentType: 'code-reviewer'}),

  () => agent(`[AGENT B - Execution & Orders]
Tool: Fast Context only (mcp__fast_context_search).
Reference docs: ${docContext}

Scope (search src/polysignal_lab/): native_order.py, native_exit.py, execution.py, order_plan.py, order_mapping.py, exit_policy.py, decision_policy.py

Checks:
1. Is there a custom execution/fill simulator that duplicates Nautilus's built-in execution engine?
2. Do order spec mappings duplicate Nautilus order types (MarketOrder, LimitOrder, etc.)?
3. DecisionPolicy - could/should this be a Nautilus Actor?
4. Is exit_policy duplicating Nautilus's native exit/stop handling?
5. Any oversized functions >80 lines?

Output format:
## [Agent B] Execution & Orders
### 取证
### Nautilus 对齐
### 重复造轮子
### Oversized
### 合理保留
### 未决`, {label: 'Agent B', agentType: 'code-reviewer'}),

  () => agent(`[AGENT C - Cache / Portfolio / Projections]
Tool: CodeGraph only. No grep, no find, no blind file reading.
Reference docs: ${docContext}

Scope: src/polysignal_lab/ app/services/paper_portfolio_service.py, cache_reader.py, projections.py, cache_market_data.py, group_views.py, observability.py

Checks:
1. paper_portfolio_service - second paper ledger that STILL drives runtime decisions? Or read projection?
2. projections.py - read-only derived state, or dual-write?
3. cache_reader.py - thin bridge to Nautilus cache, or duplicate cache implementation?
4. Is SQLite used as source-of-truth alongside Nautilus cache? (state split risk)
5. Any oversized >80 line functions?

Output format:
## [Agent C] Cache / Portfolio / Projections
### 取证
### Nautilus 对齐
### 重复造轮子
### Oversized
### 合理保留
### 未决`, {label: 'Agent C', agentType: 'code-reviewer'}),

  () => agent(`[AGENT D - Market Data / Bridge / CustomData]
Tool: Fast Context only (mcp__fast_context_search).
Reference docs: ${docContext}

Scope (search src/polysignal_lab/): nautilus_bridge/*, market_data.py, market_rotation.py, sidecar_data.py, custom_data_state.py, instrument_mapping.py, data/polymarket_market_discovery.py, data/price_to_beat_provider.py

Checks:
1. nautilus_bridge/ - re-implement instrument hydration that Polymarket adapter already handles?
2. Book deltas re-derived instead of using adapter's built-in book management?
3. sidecar_data - publish data outside Nautilus data-client ownership model?
4. Async sidecar running outside a Nautilus Actor? (violates data-client ownership)
5. instrument_mapping - thin business-key bridge, or full instrument registry?

Output format:
## [Agent D] Market Data / Bridge / CustomData
### 取证
### Nautilus 对齐
### 重复造轮子
### Oversized
### 合理保留
### 未决`, {label: 'Agent D', agentType: 'code-reviewer'}),

  () => agent(`[AGENT E - Strategy Wrapper & Alpha Boundary]
Tool: CodeGraph only. No grep, find, or blind file reading.
Reference docs: ${docContext}

Scope: native_strategy.py, nautilus_runtime/strategies/ (base.py), alpha/types.py, sample 2-3 alpha/*_core.py files, compare with strategies/ legacy

Checks:
1. native_strategy.py - duplicate Nautilus Strategy event dispatch? (on_start, on_stop, on_save, on_load, on_data)
2. State serialization - use on_save/on_load or custom codec?
3. Duplicate adapters (one in strategies/ legacy, one in nautilus_runtime)?
4. alpha/types.py+*_core.py - pure strategy logic (Accept) or contain trading infrastructure?
5. Any oversized symbols >80 lines or files >400 lines with multiple responsibilities?

Output format:
## [Agent E] Strategy Wrapper & Alpha Boundary
### 取证
### Nautilus 对齐
### 重复造轮子
### Oversized
### 合理保留
### 未决`, {label: 'Agent E', agentType: 'code-reviewer'}),

  () => agent(`[AGENT F - Legacy Scheduler Parallel Runtime]
Tool: Fast Context only (mcp__fast_context_search).
Reference docs: ${docContext}

Scope (search src/polysignal_lab/): app/scheduler*.py, strategies/ (non-alpha), paper/, signal_layer/

Checks:
1. app/scheduler*.py - second trading runtime? Conflict with spec 15 decision?
2. paper/ - paper trading duplicating Nautilus sandbox?
3. signal_layer/ - event distribution duplicating Nautilus strategy lifecycle?
4. Still referenced by nautilus_runtime/node.py? (dead code or parallel operation?)
5. Largest files/functions in these paths.

Output format:
## [Agent F] Legacy Scheduler Parallel Runtime
### 取证
### Nautilus 对齐
### 重复造轮子
### Oversized
### 合理保留
### 未决`, {label: 'Agent F', agentType: 'code-reviewer'}),
])

phase('Synthesize')
const synthesis = await agent(`Synthesize these 6 compliance review reports into one consolidated report.

Start with an Executive Summary that gives the overall health assessment and top 3-5 findings across all agents.

Then organize findings by severity (P0, P1, P2, Accept) with specific file:line evidence.

Include an Oversized section covering all oversized symbols found across all agents.

End with a Recommended Action Plan - ordered by impact, listing what to fix and how, with specific files and suggested approaches.

Reports:
${results.filter(Boolean).join('\n\n=== NEXT REPORT ===\n\n')}

For each finding, preserve the original file:line references. Be specific - no generic advice. Use markdown tables where appropriate.`, {label: 'Synthesis', agentType: 'code-reviewer'})

return synthesis
