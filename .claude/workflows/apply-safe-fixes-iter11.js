/**
 * apply-safe-fixes-iter11 — 迭代 11
 *
 * 减少 SignalGate/ConsensusEngine/SignalArbiter 的多重实例化。
 * 全部通过 agent 执行。
 */

export const meta = {
  name: 'apply-safe-fixes-iter11',
  description: 'Iteration 11: reduce redundant signal_layer instantiations',
  phases: [
    { title: 'Fix', detail: 'Audit and reduce via agent' },
    { title: 'Verify', detail: 'Run tests' },
  ],
}

phase('Fix')
log('Auditing signal_layer instance count…')

const fix = await agent(
  '审查 SignalGate、ConsensusEngine、SignalArbiter 的实例化次数，减少冗余。\n\n' +
  '审查指出这三个类各有 2-3 个实例：\n' +
  '- SignalGate: scheduler.__init__, strategy_builder._build_policy, DecisionPolicyActor.__init__\n' +
  '- ConsensusEngine: scheduler.__init__, strategy_builder._build_policy, DecisionPolicyActor.__init__\n' +
  '- SignalArbiter: scheduler_bridge.py, strategy_builder._build_policy, DecisionPolicyActor.__init__\n\n' +
  '第一步：确认这确实发生\n' +
  'grep -n "SignalGate\|ConsensusEngine\|SignalArbiter" src/polysignal_lab/nautilus_runtime/scheduler_bridge.py src/polysignal_lab/nautilus_runtime/strategy_builder.py src/polysignal_lab/nautilus_runtime/decision_policy.py src/polysignal_lab/app/scheduler.py --include="*.py"\n\n' +
  '第二步：在 decision_policy.py 的 DecisionPolicyActor.__init__ 中，\n' +
  '如果 gate/consensus/arbiter 已经通过参数传入，就不用默认创建。\n' +
  '但这是一个设计决定，需要谨慎处理。\n\n' +
  '如果无法安全减少实例化次数，则在 decision_policy.py 中添加注释\n' +
  '说明每个构造路径的目的，并在 strategy_builder.py 的 TODO 处更新状态。\n\n' +
  '保守行事——不要改变决策策略的运行逻辑。',
  { label: 'Fix', agentType: 'general-purpose' }
)

phase('Verify')
log('Running tests…')

const verify = await agent(
  '运行测试确认无回归：\n' +
  'uv run python -m pytest tests/test_nautilus_node.py tests/test_nautilus_decision_policy.py tests/test_nautilus_strategy_base.py tests/test_nautilus_strategy_wrappers.py -v --tb=short 2>&1 | tail -20',
  { label: 'Verify', agentType: 'general-purpose' }
)

return {
  iteration11_complete: true,
  fixResult: typeof fix === 'string' ? fix.substring(0, 400) : 'agent returned',
  verifyResult: typeof verify === 'string' ? verify.substring(0, 300) : 'agent returned',
}
