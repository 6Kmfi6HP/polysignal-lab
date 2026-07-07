/**
 * apply-safe-fixes-iter6 — 迭代 6
 *
 * 修复 node.py 的 setattr 注入模式。
 * 全部通过 agent 执行。
 */

export const meta = {
  name: 'apply-safe-fixes-iter6',
  description: 'Iteration 6: fix node.py setattr injection pattern',
  phases: [
    { title: 'Fix', detail: 'Fix setattr injection via agent' },
    { title: 'Verify', detail: 'Run tests' },
  ],
}

phase('Fix')
log('Fixing node.py setattr injection…')

const fix = await agent(
  '修复 src/polysignal_lab/nautilus_runtime/node.py 中的 setattr 注入模式。\n\n' +
  '审查指出 node.py 有 7 处 setattr 调用注入属性到外部对象。\n\n' +
  '具体位置：\n' +
  '- line 134-135: setattr(strategy_assembler, ...) and setattr(strategy, ...)\n' +
  '- line 188: setattr(scheduler, ...)\n' +
  '- line 210: setattr(scheduler, ...)\n' +
  '- line 215: setattr(scheduler, ...)\n' +
  '- lines 242-248: setattr(scheduler, ...) and setattr(node.trader, ...)\n\n' +
  '修改方案：\n' +
  '1. Read node.py 完整文件了解每个 setattr 的上下文\n' +
  '2. 对于每个 setattr，判断是否可以替换为：\n' +
  '   a) 目标对象上的显式 setter 方法\n' +
  '   b) 构造参数\n' +
  '   c) 在目标类中添加一个 initialize() 方法\n' +
  '3. 如果目标对象是 PolySignalScheduler，检查 scheduler.py 是否有对应 setter\n' +
  '4. 如果目标对象是策略（native_strategy），检查 PolySignalNativeStrategy 的现有参数\n' +
  '5. 优先使用现有 API，避免创建新方法\n\n' +
  '保守原则：\n' +
  '- 如果替换会引入新的 import 依赖，保持现状\n' +
  '- 如果替换会改变类的公共 API，先检查测试文件是否依赖\n' +
  '- 只做显式的、安全的替换\n\n' +
  '修改后运行：\n' +
  'uv run python -m pytest tests/test_nautilus_node.py -v --tb=short 2>&1 | tail -20',
  { label: 'Fix', agentType: 'general-purpose' }
)

phase('Verify')
log('Running full verification…')

const verify = await agent(
  '运行核心测试验证：\n' +
  'uv run python -m pytest tests/test_nautilus_node.py tests/test_nautilus_decision_policy.py tests/test_nautilus_strategy_base.py tests/test_nautilus_strategy_wrappers.py tests/test_nautilus_full_paper_runtime_smoke.py tests/test_function_size_boundaries.py tests/test_scheduler.py tests/test_scheduler_reports.py -v --tb=short 2>&1 | tail -40\n\n' +
  '报告：通过数、失败数、失败详情。如有新增失败，对比之前的 182 pass 4 fail。',
  { label: 'Verify', agentType: 'general-purpose' }
)

return {
  iteration6_complete: true,
  fixResult: typeof fix === 'string' ? fix.substring(0, 500) : JSON.stringify(fix).substring(0, 500),
  verifyResult: typeof verify === 'string' ? verify.substring(0, 500) : JSON.stringify(verify).substring(0, 500),
}
