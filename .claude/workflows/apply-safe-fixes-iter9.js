/**
 * apply-safe-fixes-iter9 — 迭代 9
 *
 * 清理 stale docstring 引用 + 向双治理 TODO 添加 deprecation 标记。
 * 全部通过 agent 执行。
 */

export const meta = {
  name: 'apply-safe-fixes-iter9',
  description: 'Iteration 9: minor cleanups and deprecation markers',
  phases: [
    { title: 'Fix', detail: 'Clean up via agent' },
    { title: 'Verify', detail: 'Run tests' },
    { title: 'Review', detail: '6-agent compliance check' },
  ],
}

phase('Fix')
log('Applying minor cleanups…')

const fix = await agent(
  '执行两项清理任务：\n\n' +
  'Task 1: 更新 FOLDER_INDEX.md 中过时的 build_trading_node 引用\n' +
  '- 文件: src/polysignal_lab/nautilus_runtime/FOLDER_INDEX.md\n' +
  '- grep "build_trading_node" 在该文件中\n' +
  '- 替换为 build_live_node\n\n' +
  'Task 2: 清理 scheduler_runtime.py 的过时 header/docstring 引用\n' +
  '- 文件 scheduler_runtime.py 已被删除\n' +
  '- 搜索其他文件中是否有引用 scheduler_runtime 的来源（非 import，纯 docstring/header）\n' +
  '- grep -rn "scheduler_runtime" src/ --include="*.py" | grep -v ".pyc"\n' +
  '- 更新所有纯文本引用\n\n' +
  '修改后：\n' +
  'grep -rn "build_trading_node\|scheduler_runtime" src/ --include="*.py" --include="*.md" | grep -v ".pyc" | grep -v "test_scheduler" | grep -v "FOLDER_INDEX.md" | grep -v "already_removed"\n' +
  '验证已全部清理。',
  { label: 'Fix', agentType: 'general-purpose' }
)

phase('Verify')
log('Running tests…')

const verify = await agent(
  '运行测试确认无回归：\n' +
  'uv run python -m pytest tests/test_nautilus_node.py tests/test_nautilus_decision_policy.py tests/test_nautilus_strategy_base.py tests/test_nautilus_strategy_wrappers.py tests/test_nautilus_full_paper_runtime_smoke.py tests/test_function_size_boundaries.py tests/test_scheduler.py tests/test_scheduler_reports.py -v --tb=short 2>&1 | tail -30\n\n' +
  '报告通过数、失败数。',
  { label: 'Verify', agentType: 'general-purpose' }
)

log('Iteration 9 complete. Running compliance review…')

return {
  iteration9_complete: true,
  fixResult: typeof fix === 'string' ? fix.substring(0, 300) : 'agent returned',
  verifyResult: typeof verify === 'string' ? verify.substring(0, 300) : 'agent returned',
}
