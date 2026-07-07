/**
 * apply-safe-fixes-iter4 — 迭代 4
 *
 * 通过 agent 重新应用之前主对话直接修改的 runtime_classes.py 变更，
 * 然后尝试修复 P0-3 双继承包装器问题。
 * 全部修改通过 agent 执行，主对话不做任何编辑。
 */

export const meta = {
  name: 'apply-safe-fixes-iter4',
  description: 'Fix P0-3 dual inheritance wrappers + properly re-apply runtime_classes changes via agent',
  phases: [
    { title: 'Fix-RuntimeClasses', detail: 'Re-apply runtime_classes changes properly via agent' },
    { title: 'Fix-P0-3', detail: 'Attempt dual-inheritance refactor (composition pattern)' },
    { title: 'Verify', detail: 'Run tests' },
  ],
}

phase('Fix-RuntimeClasses')
log('Reapplying runtime_classes changes through agent…')

const fixClasses = await agent(
  '修复 runtime_classes.py。当前文件（HEAD 版本）需要以下修改：\n\n' +
  '文件: src/polysignal_lab/nautilus_runtime/runtime_classes.py\n\n' +
  '修改 1: 将 class LiveDecisionPolicyActor 改为 class LiveDecisionPolicyActor（无需改名——已是正确名称）\n' +
  '修改 2: 在第 110 行附近，删除 \"# Backward compatibility alias\" 和 \"NautilusDecisionPolicyActor = LiveDecisionPolicyActor\"\n' +
  '修改 3: 添加带注释的 alias：\n' +
  '  # LiveDecisionPolicyActor is the Nautilus-registerable variant (inherits Actor).\n' +
  '  # Expose under the expected name for discovery via runtime_classes.\n' +
  '  NautilusDecisionPolicyActor = LiveDecisionPolicyActor\n' +
  '修改 4: 在 __all__ 中添加 \"NautilusDecisionPolicyActor\", 和 \"LiveDecisionPolicyActor\",\n' +
  '修改 5: 在文件顶部添加 header docstring：\n' +
  '  """\n' +
  '  Input: __future__, __future__.annotations, collections.abc, collections.abc.Callable, collections.abc.Sequence, nautilus_trader.common.actor, nautilus_trader.common.actor.Actor, nautilus_trader.config, nautilus_trader.config.ActorConfig, nautilus_trader.config.StrategyConfig\n' +
  '  Output: NautilusPolySignalNativeStrategy, NautilusMarketRotationActor, LiveDecisionPolicyActor\n' +
  '  Pos: Application code\n\n' +
  '  🔄 Self-reference: When this file changes, update this header\n' +
  '  """\n\n' +
  '修改后验证：\n' +
  '- python3 -c "from polysignal_lab.nautilus_runtime.runtime_classes import NautilusDecisionPolicyActor; print(\\"OK\\")"\n' +
  '- python3 -c "from polysignal_lab.nautilus_runtime.runtime_classes import LiveDecisionPolicyActor; print(\\"OK\\")"\n' +
  '- uv run python -m pytest tests/test_nautilus_decision_policy.py::test_runtime_classes_expose_registerable_nautilus_policy_actor -v --tb=short 2>&1 | tail -5\n\n' +
  '只修改 runtime_classes.py 文件。',
  { label: 'Fix-RuntimeClasses', agentType: 'general-purpose' }
)

phase('Fix-P0-3')
log('Attempting P0-3 dual-inheritance refactor…')

const fixP03 = await agent(
  '检查 runtime_classes.py 的双继承包装器问题（P0-3）。\n' +
  '审查指出：NautilusPolySignalNativeStrategy 继承 Strategy + PolySignalNativeStrategy，\n' +
  'NautilusMarketRotationActor 继承 Actor + MarketRotationActor，\n' +
  'LiveDecisionPolicyActor 继承 Actor + DecisionPolicyActor。\n\n' +
  '当前文件: src/polysignal_lab/nautilus_runtime/runtime_classes.py\n\n' +
  '阅读该文件后，判断是否可以将多继承改为组合（composition）模式。\n' +
  '如果可以，做修改。如果不行（因 py3.11 兼容性或 Nautilus 可选性），\n' +
  '说明原因并在每个包装类上加注释文档化设计理由。\n\n' +
  '请保守行事——双继承是故意架构选择（支持可选 Nautilus 依赖）。\n' +
  '如果改 composition 风险太高，就加文档注释说明设计理由。',
  { label: 'Fix-P0-3', agentType: 'general-purpose' }
)

phase('Verify')
log('Running tests…')

const verify = await agent(
  '运行核心测试验证：\n' +
  'uv run python -m pytest tests/test_nautilus_node.py tests/test_nautilus_decision_policy.py tests/test_nautilus_strategy_base.py tests/test_nautilus_strategy_wrappers.py tests/test_nautilus_full_paper_runtime_smoke.py tests/test_function_size_boundaries.py tests/test_scheduler.py tests/test_scheduler_reports.py -v --tb=short 2>&1 | tail -40\n\n' +
  '报告：总通过数、失败数、新增失败详情、是否为本次修改引入',
  { label: 'Verify', agentType: 'general-purpose' }
)

return {
  iteration4_complete: true,
  runtimeClassesFix: typeof fixClasses === 'string' ? fixClasses.substring(0, 300) : 'agent returned',
  p03Status: typeof fixP03 === 'string' ? fixP03.substring(0, 500) : 'agent returned',
  verifyResult: typeof verify === 'string' ? verify.substring(0, 500) : 'agent returned',
}
