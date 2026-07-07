/**
 * apply-safe-fixes-iter7 — 迭代 7：DecisionPolicyActor → *Engine 重命名
 *
 * 审查指出 DecisionPolicyActor 后缀 "Actor" 易与 Nautilus Actor 混淆。
 * 重命名为 DecisionPolicyEngine，消除术语冲突。
 * 全部通过 agent 执行。
 */

export const meta = {
  name: 'apply-safe-fixes-iter7',
  description: 'Iteration 7: rename DecisionPolicyActor to DecisionPolicyEngine',
  phases: [
    { title: 'Fix', detail: 'Rename via agent' },
    { title: 'Verify', detail: 'Run tests' },
  ],
}

phase('Fix')
log('Renaming DecisionPolicyEngine…')

const fix = await agent(
  '在 nautilus_runtime/ 目录中，将 DecisionPolicyActor 类重命名为 DecisionPolicyEngine 的方法。\n\n' +
  '审查指出：decision_policy.py 中的 DecisionPolicyActor 带 "Actor" 后缀却非 Nautilus Actor，造成术语混淆。\n\n' +
  '注意：这需要非常小心，因为有多个同名类在不同文件中：\n' +
  '- decision_policy.py:115 — class DecisionPolicyActor（需要重命名）\n' +
  '- decision_policy_actor.py:20 — class NautilusDecisionPolicyActor（不需要改）\n' +
  '- runtime_classes.py — LiveDecisionPolicyActor（不需要改）\n' +
  '- runtime_classes.py — NautilusDecisionPolicyActor alias（不需要改）\n\n' +
  '修改范围：\n' +
  '1. decision_policy.py:115 — class DecisionPolicyActor → class DecisionPolicyEngine\n' +
  '2. 更新 decision_policy.py header Output\n' +
  '3. 查找所有从 decision_policy 导入 DecisionPolicyActor 的文件：\n' +
  '   grep -rn "from.*decision_policy.*import.*DecisionPolicyActor" src/ tests/ --include="*.py"\n' +
  '4. 更新这些 import 和引用\n\n' +
  '注意：\n' +
  '- NautilusDecisionPolicyActor 和 LiveDecisionPolicyActor 是 Nautilus 注册名，不要改\n' +
  '- decision_policy.py 中只改类定义，不改类内部的 self 引用（self 指向实例无所谓叫什么类）\n' +
  '- 确保所有测试文件中的引用也更新\n\n' +
  '风险评估：\n' +
  '如果 rename 涉及太多文件（>15 处引用），这个重命名在当前阶段可能风险过高。\n' +
  '先用 grep 评估引用数量，如果 >20 处则取消并留到下次。\n\n' +
  '修改后运行：\n' +
  'uv run python -m pytest tests/test_nautilus_decision_policy.py tests/test_nautilus_strategy_wrappers.py tests/test_nautilus_node.py -v --tb=short 2>&1 | tail -30',
  { label: 'Fix', agentType: 'general-purpose' }
)

phase('Verify')
log('Running full verification…')

const verify = await agent(
  '运行核心测试验证：\n' +
  'uv run python -m pytest tests/test_nautilus_node.py tests/test_nautilus_decision_policy.py tests/test_nautilus_strategy_base.py tests/test_nautilus_strategy_wrappers.py tests/test_nautilus_full_paper_runtime_smoke.py tests/test_function_size_boundaries.py tests/test_scheduler.py tests/test_scheduler_reports.py -v --tb=short 2>&1 | tail -40\n\n' +
  '报告：通过数、失败数。如有修改引入的新失败，详细列出。',
  { label: 'Verify', agentType: 'general-purpose' }
)

return {
  iteration7_complete: true,
  fixResult: typeof fix === 'string' ? fix.substring(0, 500) : JSON.stringify(fix).substring(0, 500),
  verifyResult: typeof verify === 'string' ? verify.substring(0, 500) : JSON.stringify(verify).substring(0, 500),
}
