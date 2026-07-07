/**
 * apply-safe-fixes-iter5 — 迭代 5 循环继续
 *
 * 继续修复审查发现的零散项目。
 * 全部通过 agent 执行，主对话不做任何修改。
 */

export const meta = {
  name: 'apply-safe-fixes-iter5',
  description: 'Iteration 5: continue fixing remaining P1/P2 items',
  phases: [
    { title: 'Fix', detail: 'Apply fix via agent' },
    { title: 'Verify', detail: 'Run tests' },
  ],
}

phase('Fix')
log('Cleaning up remaining legacy markers…')

const fix = await agent(
  '清理 nautilus_runtime/strategies/base.py 中的遗留兼容标记。\n\n' +
  '这个文件现在只有 23 行，包含 COMPAT_DATA_NAMES、DEFAULT_DATA_NAMES（别名）和 COMPATIBILITY_ONLY = True。\n' +
  '这些是在 CompatPolySignalNautilusStrategy 移除后留下的惰性常量。\n\n' +
  '检查以下内容：\n' +
  '1. 哪些文件 import COMPAT_DATA_NAMES？哪些 import DEFAULT_DATA_NAMES？\n' +
  '2. 哪些文件 import COMPATIBILITY_ONLY？\n' +
  '3. 这些常量是否还在使用？\n\n' +
  '修改：\n' +
  '- 在 nautilus_runtime/strategies/__init__.py 中：保持 DEFAULT_DATA_NAMES 的导出，但让它直接从 base.py 导入\n' +
  '- 如果 COMPAT_DATA_NAMES 和 DEFAULT_DATA_NAMES 指向相同的值，合并它们\n' +
  '- 如果 COMPATIBILITY_ONLY = True 没有被任何活跃代码读取，删除它\n' +
  '- 删除 strategies/base.py 中不再需要的 import\n\n' +
  '修改后运行：\n' +
  'uv run python -m pytest tests/test_nautilus_strategy_base.py tests/test_nautilus_strategy_wrappers.py -v --tb=short 2>&1 | tail -20',
  { label: 'Fix', agentType: 'general-purpose' }
)

phase('Verify')
log('Running full verification…')

const verify = await agent(
  '运行核心测试验证：\n' +
  'uv run python -m pytest tests/test_nautilus_node.py tests/test_nautilus_decision_policy.py tests/test_nautilus_strategy_base.py tests/test_nautilus_strategy_wrappers.py tests/test_nautilus_full_paper_runtime_smoke.py tests/test_function_size_boundaries.py tests/test_scheduler.py tests/test_scheduler_reports.py -v --tb=short 2>&1 | tail -40\n\n' +
  '报告：通过数、失败数、失败详情',
  { label: 'Verify', agentType: 'general-purpose' }
)

return {
  iteration5_complete: true,
  fixResult: typeof fix === 'string' ? fix.substring(0, 500) : JSON.stringify(fix).substring(0, 500),
  verifyResult: typeof verify === 'string' ? verify.substring(0, 500) : JSON.stringify(verify).substring(0, 500),
}
