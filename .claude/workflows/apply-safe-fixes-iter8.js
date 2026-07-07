/**
 * apply-safe-fixes-iter8 — 迭代 8：清理 compat_mode 死代码
 *
 * CompatPolySignalNautilusStrategy 已被移除，compat_mode 参数不再被
 * 任何活跃代码使用。清理 native_strategy.py 中的相关逻辑。
 * 全部通过 agent 执行。
 */

export const meta = {
  name: 'apply-safe-fixes-iter8',
  description: 'Iteration 8: remove dead compat_mode code from native_strategy.py',
  phases: [
    { title: 'Fix', detail: 'Clean up via agent' },
    { title: 'Verify', detail: 'Run tests' },
    { title: 'Review', detail: '6-agent compliance check' },
  ],
}

phase('Fix')
log('Removing compat_mode dead code…')

const fix = await agent(
  '清理 native_strategy.py 中的 compat_mode 参数和相关死代码。\n\n' +
  'CompatPolySignalNautilusStrategy 已被移除（它是唯一设置 compat_mode=True 的调用者），\n' +
  '现在 compat_mode 参数是死代码。清理后简化 PolySignalNativeStrategy 的初始化逻辑。\n\n' +
  '文件: src/polysignal_lab/nautilus_runtime/native_strategy.py\n\n' +
  '修改：\n' +
  '1. 删除 __init__ 中的 compat_mode 参数（line 107, 109）\n' +
  '2. 删除 self.compat_mode 属性（line 109）\n' +
  '3. 简化 line 110 的条件：当 registry 或 assembler 为 None 时直接 raise\n' +
  '   （因为 compat_mode 不再是合法选项）\n' +
  '4. 简化 line 158 和 164：去掉 and not self.compat_mode 条件\n\n' +
  '注意：保留 registry 和 assembler 参数，只是去掉 compat_mode 分支。\n\n' +
  '修改后验证：\n' +
  '1. grep -rn "compat_mode" src/ tests/ --include="*.py" — 确认无残留\n' +
  '2. uv run python -m pytest tests/test_nautilus_strategy_base.py tests/test_nautilus_strategy_wrappers.py tests/test_nautilus_node.py -v --tb=short 2>&1 | tail -20',
  { label: 'Fix', agentType: 'general-purpose' }
)

phase('Verify')
log('Running verification…')

const verify = await agent(
  '运行完整测试验证：\n' +
  'uv run python -m pytest tests/test_nautilus_node.py tests/test_nautilus_decision_policy.py tests/test_nautilus_strategy_base.py tests/test_nautilus_strategy_wrappers.py tests/test_nautilus_full_paper_runtime_smoke.py tests/test_function_size_boundaries.py tests/test_scheduler.py tests/test_scheduler_reports.py -v --tb=short 2>&1 | tail -40\n\n' +
  '报告通过数、失败数、失败详情。',
  { label: 'Verify', agentType: 'general-purpose' }
)

log('Iteration 8 fix and verify complete. Running compliance review…')

return {
  iteration8_complete: true,
  fixResult: typeof fix === 'string' ? fix.substring(0, 500) : JSON.stringify(fix).substring(0, 500),
  verifyResult: typeof verify === 'string' ? verify.substring(0, 500) : JSON.stringify(verify).substring(0, 500),
}
