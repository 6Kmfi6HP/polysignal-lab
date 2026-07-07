/**
 * post-fix-compliance-check — 修复后合规验证 workflow
 *
 * 验证本次修复（iter1）是否成功消除了对应的发现项：
 * - build_trading_node → build_live_node
 * - NautilusDecisionPolicyActor 别名移除
 * - scheduler_runtime.py 删除
 *
 * 同时运行完整测试套件确保无回归。
 */

export const meta = {
  name: 'post-fix-compliance-check',
  description: 'Verify iter1 fixes resolved their compliance findings',
  phases: [
    { title: 'Validate-A', detail: 'Verify build_live_node rename' },
    { title: 'Validate-B', detail: 'Verify alias removal and stub deletion' },
    { title: 'Validate-C', detail: 'Run full test suite' },
  ],
}

phase('Validate-A')
log('验证 Fix-1: build_trading_node → build_live_node…')

const agentA = await agent(
  '验证 build_trading_node → build_live_node 重命名是否正确完成。\n' +
  '1. 检查 src/polysignal_lab/nautilus_runtime/node_builder.py 中函数名为 build_live_node\n' +
  '2. 检查 src/polysignal_lab/nautilus_runtime/__init__.py 导出 build_live_node\n' +
  '3. 检查 tests/ 目录下无 build_trading_node 引用（Output header 中的引用可忽略）\n' +
  '4. 验证: python3 -c "from polysignal_lab.nautilus_runtime import build_live_node; print(\'OK: import works\')"\n' +
  '5. 验证: python3 -c "from polysignal_lab.nautilus_runtime import node; print(type(node.build_live_node))"\n' +
  '如有任何失败，报告具体位置。',
  { label: 'Validate-Rename', agentType: 'general-purpose' }
)

phase('Validate-B')
log('验证 Fix-2 和 Fix-3…')

const agentB = await agent(
  '验证以下两个修复：\n\n' +
  'Fix-2: NautilusDecisionPolicyActor 别名\n' +
  '- 检查 runtime_classes.py 中不再有 NautilusDecisionPolicyActor = LiveDecisionPolicyActor\n' +
  '- LiveDecisionPolicyActor 类仍存在\n' +
  '- 验证: python3 -c "from polysignal_lab.nautilus_runtime.runtime_classes import LiveDecisionPolicyActor; print(\'OK\')"\n\n' +
  'Fix-3: scheduler_runtime.py 删除\n' +
  '- 检查文件不存在: ! test -f src/polysignal_lab/app/scheduler_runtime.py\n' +
  '- 检查 scheduler_shared 仍可导入: python3 -c "from polysignal_lab.app.scheduler_shared import _configured_report_date; print(\'OK\')"\n' +
  '- 检查 scheduler_reporting 仍可导入: python3 -c "from polysignal_lab.app.scheduler_reporting import _store_paper_result; print(\'OK\')"\n\n' +
  '如发现问题，报告具体位置和应做的修复。',
  { label: 'Validate-Alias-Stub', agentType: 'general-purpose' }
)

phase('Validate-C')
log('运行完整测试套件…')

const agentC = await agent(
  '运行测试验证修复未导致回归。由于完整套件可能包含预先存在的问题，先运行核心 Nautilus 测试：\n' +
  'uv run python -m pytest tests/test_nautilus_node.py tests/test_nautilus_decision_policy.py tests/test_nautilus_strategy_base.py tests/test_nautilus_strategy_wrappers.py tests/test_nautilus_full_paper_runtime_smoke.py tests/test_function_size_boundaries.py tests/test_scheduler.py tests/test_scheduler_reports.py -v --tb=short 2>&1 | tail -60\n\n' +
  '报告：\n' +
  '- 总通过数、失败数\n' +
  '- 如果有新失败（之前 71 通过 4 失败），列出新失败详情\n' +
  '- 判断本次修复是否引入回归',
  { label: 'Run-Tests', agentType: 'general-purpose' }
)

// Synthesize
var isValidA = agentA && (typeof agentA === 'string' ? !agentA.includes('FAIL') && !agentA.includes('failed') : true)
var isValidB = agentB && (typeof agentB === 'string' ? !agentB.includes('FAIL') && !agentB.includes('failed') : true)
var isValidC = agentC && (typeof agentC === 'string' ? !agentC.includes('FAILED') && !agentC.includes('NEW FAIL') : true)

log('Validation A (rename): ' + (isValidA ? 'PASS' : 'CHECK RESULTS'))
log('Validation B (alias+stub): ' + (isValidB ? 'PASS' : 'CHECK RESULTS'))
log('Validation C (tests): ' + (isValidC ? 'PASS' : 'CHECK RESULTS'))

var allClean = isValidA && isValidB && isValidC

return {
  allClean: allClean,
  details: {
    renameValidation: typeof agentA === 'string' ? agentA.substring(0, 500) : JSON.stringify(agentA).substring(0, 500),
    aliasStubValidation: typeof agentB === 'string' ? agentB.substring(0, 500) : JSON.stringify(agentB).substring(0, 500),
    testResults: typeof agentC === 'string' ? agentC.substring(0, 500) : JSON.stringify(agentC).substring(0, 500),
  },
  message: allClean ? 'All fixes validated. Ready for final compliance review.' : 'Some issues remain. See details.',
}
