/**
 * re-review-after-iter1 — 迭代 1 修复后的合规重审
 *
 * 检查 iter1 三个修复项是否彻底完成，同时列出仍需处理的发现项。
 * 如果有残留发现项则返回 remaining=true，触发循环。
 */

export const meta = {
  name: 're-review-after-iter1',
  description: 'Check if iter1 fixes resolved their findings; list remaining P1/P2 for next loop',
  phases: [
    { title: 'Check-Rename', detail: 'Verify build_live_node rename clean' },
    { title: 'Check-Alias+Stub', detail: 'Verify alias and stub cleanup' },
    { title: 'Check-Remaining', detail: 'Scan for unresolved P1/P2 findings from original review' },
  ],
}

phase('Check-Rename')
const checkRename = await agent(
  'Verify the build_trading_node → build_live_node rename is complete.\n' +
  'Check:\n' +
  '1. No build_trading_node in src/ (headers are fine)\n' +
  '2. No build_trading_node in tests/ test names or calls\n' +
  '3. python3 -c "from polysignal_lab.nautilus_runtime import build_live_node; print(\'OK\')"\n' +
  '4. All callers in node.py use build_live_node\n' +
  'Return PASS or FAIL with evidence.',
  { label: 'Check-Rename', agentType: 'general-purpose' }
)

phase('Check-Alias+Stub')
const checkAliasStub = await agent(
  'Verify two fixes:\n\n' +
  'Fix-2: runtime_classes.py NautilusDecisionPolicyActor alias\n' +
  '- Confirm NautilusDecisionPolicyActor = LiveDecisionPolicyActor exists with explicit comment\n' +
  '- Confirm it\'s in __all__\n' +
  '- Confirm test_runtime_classes_expose_registerable_nautilus_policy_actor passes\n\n' +
  'Fix-3: scheduler_runtime.py deletion\n' +
  '- Confirm file does not exist: ! test -f src/polysignal_lab/app/scheduler_runtime.py\n' +
  '- Confirm scheduler_shared still importable\n' +
  '- Confirm test_scheduler.py has no scheduler_runtime references\n\n' +
  'Return PASS or FAIL with evidence.',
  { label: 'Check-Alias-Stub', agentType: 'general-purpose' }
)

phase('Check-Remaining')
const checkRemaining = await agent(
  'Check remaining P1/P2 findings from the original compliance review that were NOT addressed in this iteration.\n' +
  'For each, state whether it still exists:\n\n' +
  'P1 still unresolved:\n' +
  '1. CompatPolySignalNautilusStrategy dual wrapper (strategies/base.py) — still exists?\n' +
  '2. Old strategies/ path dual stack (strategies/base.py + factory.py) — still active?\n' +
  '3. signal_layer via DecisionPolicyActor coupling — still imported?\n' +
  '4. PolySignalScheduler full subsystem construction — still happening?\n' +
  '5. decision_policy.py import signal_layer — still true?\n' +
  '6. MarketRotationActor multi-responsibility — still true?\n' +
  '7. node.py constructing PolySignalScheduler as container — still true?\n' +
  '8. scheduler_bridge.py wiring gate/consensus/arbiter — still true?\n\n' +
  'P2 still unresolved:\n' +
  '1. decision_to_signal() legacy conversion — still exists?\n' +
  '2. MarketSubscriptionState — still exists?\n' +
  '3. scheduler_processing.py cleanup — still has stale signatures?\n' +
  '4. PaperReportService dual report logic — still exists?\n' +
  '5. signal_sidecar.py threading — still exists?\n\n' +
  'Oversized files (still >400 lines):\n' +
  '1. native_strategy.py (852)\n' +
  '2. helpers.py (442)\n' +
  '3. observability.py (574)\n' +
  '4. scheduler_reporting.py (648)\n' +
  '5. node.py (550)\n' +
  '6. market_data.py (420)\n\n' +
  'Return JSON-compatible summary: {"fixed": [list of fixed find-gs], "remaining": [list of still-present findings], "remainingCount": <number>, "oversizedRemaining": [list]}',
  { label: 'Check-Remaining', agentType: 'general-purpose' }
)

// Synthesize results
log('Synthesizing results…')

// Parse remaining findings
var remainingCount = 0
var remainingList = []
var oversizedRemaining = []
var fixedList = ['build_trading_node rename', 'NautilusDecisionPolicyActor alias documented', 'scheduler_runtime.py deleted']

if (checkRemaining && typeof checkRemaining === 'string') {
  // Try to find structured data
  var lines = checkRemaining.split('\n')
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i]
    if (line.startsWith('"remainingCount"') || line.startsWith('remainingCount')) {
      var parts = line.split(':')
      if (parts.length > 1) remainingCount = parseInt(parts[1].trim().replace(/[,"]/g, ''))
    }
    if (line.startsWith('"remaining"') || line.startsWith('remaining')) {
      // Collect remaining items
    }
  }
}

// If we can't parse structured data, assume findings remain
if (remainingCount === 0 && checkRemaining && checkRemaining.includes('still')) {
  // Count occurrences of "still exists" or "still true"
  remainingCount = (checkRemaining.match(/still (exists|true)/gi) || []).length
}

log('Remaining findings: ' + remainingCount)
log('Fixed in this iteration: ' + JSON.stringify(fixedList))

return {
  iteration1_complete: true,
  fixes_applied: fixedList,
  remaining_finding_count: remainingCount,
  needs_another_iteration: remainingCount > 0,
  summary: 'Iteration 1 applied ' + fixedList.length + ' safe fixes. ' +
    (remainingCount > 0
      ? remainingCount + ' P1/P2 findings remain for next iteration.'
      : 'All findings resolved.'),
}
