/**
 * apply-safe-fixes-iter10 — 迭代 10
 *
 * 继续清理遗留引用问题。全部通过 agent 执行。
 */

export const meta = {
  name: 'apply-safe-fixes-iter10',
  description: 'Iteration 10: continue minor cleanups',
  phases: [
    { title: 'Fix', detail: 'Clean up via agent' },
    { title: 'Verify', detail: 'Run tests' },
  ],
}

phase('Fix')
log('Applying cleanups…')

const fix = await agent(
  '执行两项清理任务：\n\n' +
  'Task 1: 检查 execution.py 是否可删除\n' +
  '- 文件: src/polysignal_lab/nautilus_runtime/execution.py（16 行，纯 re-export）\n' +
  '- grep -rn "from.*nautilus_runtime.*execution\|nautilus_runtime.execution" src/ tests/ --include="*.py"\n' +
  '- 如果没有任何活跃引用，删除该文件\n' +
  '- 如果有引用，将引用点改为直接从 order_mapping 导入\n' +
  '- 然后删除 execution.py\n\n' +
  'Task 2: 清理 strategies_import_mapping.py（如果存在）中的死代码引用\n' +
  '- find src/polysignal_lab/ -name "*import_mapping*" -o -name "*import_registry*"\n' +
  '- 如果发现任何遗留引用映射文件，检查是否可以删除\n\n' +
  '修改后运行验证。',
  { label: 'Fix', agentType: 'general-purpose' }
)

phase('Verify')
log('Running tests…')

const verify = await agent(
  '运行测试：\n' +
  'uv run python -m pytest tests/test_nautilus_node.py tests/test_nautilus_decision_policy.py tests/test_nautilus_strategy_base.py tests/test_nautilus_strategy_wrappers.py tests/test_nautilus_full_paper_runtime_smoke.py tests/test_function_size_boundaries.py tests/test_scheduler.py tests/test_scheduler_reports.py -v --tb=short 2>&1 | tail -30\n\n' +
  '报告通过数和失败数。',
  { label: 'Verify', agentType: 'general-purpose' }
)

return {
  iteration10_complete: true,
  fixResult: typeof fix === 'string' ? fix.substring(0, 300) : 'agent returned',
  verifyResult: typeof verify === 'string' ? verify.substring(0, 300) : 'agent returned',
}
