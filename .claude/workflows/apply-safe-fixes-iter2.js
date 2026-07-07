/**
 * apply-safe-fixes-iter2 — 迭代 2 修复 workflow
 *
 * 专注于移除 CompatPolySignalNautilusStrategy 双份 wrapper
 * 全部修改通过 agent 执行，主对话不做任何编辑。
 */

export const meta = {
  name: 'apply-safe-fixes-iter2',
  description: 'Iteration 2: remove CompatPolySignalNautilusStrategy dual wrapper',
  phases: [
    { title: 'Scout', detail: 'Read files, plan all changes needed' },
    { title: 'Fix', detail: 'Remove CompatPolySignalNautilusStrategy via agents, update tests' },
    { title: 'Verify', detail: 'Run tests' },
  ],
}

phase('Scout')
log('Scouting CompatPolySignalNautilusStrategy references…')

const scout = await agent(
  '找出 CompatPolySignalNautilusStrategy 的所有引用点。\n' +
  '搜索整个仓库（包括 tests/）：\n' +
  '1. grep -rn "CompatPolySignalNautilusStrategy" src/ tests/ --include="*.py"\n' +
  '2. 列出每个引用位置的文件、行号、上下文\n' +
  '3. 判断哪些引用可以安全删除，哪些需要改写为 PolySignalNativeStrategy\n' +
  '4. grep -rn "strategies/base" tests/ --include="*.py"\n' +
  '返回 JSON: {"files": [{"path": <path>, "lines": [<line numbers>], "action": "remove_import|rewrite_test|keep"}], "total_refs": <count>}',
  { label: 'Scout', agentType: 'general-purpose' }
)

phase('Fix')
log('Removing CompatPolySignalNautilusStrategy…')

// Step 1: Update source code (src files only)
const fixSource = await agent(
  '移除 CompatPolySignalNautilusStrategy 双份 wrapper。\n' +
  '这是过时的兼容类，PolySignalNativeStrategy 是它的替代品。\n\n' +
  '修改 1: src/polysignal_lab/nautilus_runtime/strategies/base.py\n' +
  '- 删除整个 CompatPolySignalNautilusStrategy 类（第56-590行）\n' +
  '- 保留 COMPAT_DATA_NAMES、DEFAULT_DATA_NAMES、COMPATIBILITY_ONLY(可保留但标记)\n' +
  '- 删除本文件中不再需要的 import（AlphaDecision, AlphaFillEvent, AlphaOrderEvent, NautilusOrderSpec, ApprovedDecision, RejectedDecision, order_spec_from_decision, classify_project_owned_data, DataBoundaryClassification, utc_now, warnings, cast）\n' +
  '- 更新文件 header Output 为: Output: DEFAULT_DATA_NAMES, COMPAT_DATA_NAMES, COMPATIBILITY_ONLY\n' +
  '- 删除文件末尾的辅助函数（_callable_attr, _object_dict, _float_or_zero, _first_attr, _event_strategy, _spec_lookup_ids, _optional_str, _side, _timestamp, _is_hedge_or_gtd_fill），这些是 CompatPolySignalNautilusStrategy 专用的\n\n' +
  '修改 2: src/polysignal_lab/nautilus_runtime/strategies/__init__.py\n' +
  '- 删除 CompatPolySignalNautilusStrategy 的导入和导出\n' +
  '- 只保留 DEFAULT_DATA_NAMES 的导入和导出\n\n' +
  '修改 3: src/polysignal_lab/nautilus_runtime/strategy_builder.py\n' +
  '- 检查是否引用 CompatPolySignalNautilusStrategy\n\n' +
  '修改后运行: python3 -c "from polysignal_lab.nautilus_runtime.strategies import DEFAULT_DATA_NAMES; print(\'OK\')"\n' +
  '以及: python3 -c "from polysignal_lab.nautilus_runtime.strategies import CompatPolySignalNautilusStrategy"（应失败）\n\n' +
  '只做以上修改，通过 Edit 工具进行。',
  { label: 'Fix-Source', agentType: 'general-purpose' }
)

// Step 2: Update test files
const fixTests = await agent(
  '更新测试文件以移除 CompatPolySignalNautilusStrategy 引用。\n\n' +
  '修改 1: tests/test_nautilus_strategy_base.py\n' +
  '- 第316-318行从 strategies.base 导入 CompatPolySignalNautilusStrategy 作为 RuntimeStrategy。改为从 native_strategy 导入 PolySignalNativeStrategy\n' +
  '- 所有使用 RuntimeStrategy 的地方改为 PolySignalNativeStrategy\n' +
  '- 由于 PolySignalNativeStrategy 初始化参数不同（需要 assembler 为 _Assembler 类型，没有 submitter 参数），可能需要调整 mock\n' +
  '- 检查 PolySignalNativeStrategy.__init__ 的签名来确定正确的 mock 参数\n' +
  '- 运行修改后的测试看是否通过\n\n' +
  '修改 2: tests/test_nautilus_strategy_wrappers.py\n' +
  '- 第34行从 strategies.base 导入 CompatPolySignalNautilusStrategy 作为 PolySignalNautilusStrategy\n' +
  '- 改为从 nautilus_runtime.native_strategy 导入 PolySignalNativeStrategy\n' +
  '- 查看所有使用 PolySignalNautilusStrategy 的地方（在 WRAPPERS 列表和各个测试函数中）\n' +
  '- PolySignalNativeStrategy 的 __init__ 参数与 CompatPolySignalNautilusStrategy 不同，需要调整 mock 和调用\n\n' +
  '方法：\n' +
  '1. 先 Read PolySignalNativeStrategy 的 __init__ 签名\n' +
  '2. Read 测试文件，理解每个测试的 mock 模式\n' +
  '3. 逐步修改\n' +
  '4. 每次修改后运行单独的测试函数验证\n\n' +
  '修改后运行完整测试验证：\n' +
  'uv run python -m pytest tests/test_nautilus_strategy_base.py tests/test_nautilus_strategy_wrappers.py -v --tb=long 2>&1 | tail -40',
  { label: 'Fix-Tests', agentType: 'general-purpose' }
)

// Step 3: Verify all tests pass
phase('Verify')
log('Running full verification…')

const verify = await agent(
  '验证 CompatPolySignalNautilusStrategy 移除后所有测试通过。\n\n' +
  '1. 确认源文件不再有引用：grep -rn "CompatPolySignalNautilusStrategy" src/ --include="*.py"\n' +
  '2. 运行核心测试：\n' +
  '   uv run python -m pytest tests/test_nautilus_strategy_base.py tests/test_nautilus_strategy_wrappers.py tests/test_nautilus_node.py tests/test_nautilus_decision_policy.py tests/test_nautilus_full_paper_runtime_smoke.py tests/test_function_size_boundaries.py tests/test_scheduler.py tests/test_scheduler_reports.py -v --tb=short 2>&1 | tail -30\n' +
  '3. 报告通过/失败数，失败详情\n' +
  '4. 判断是否有本次修改引入的新失败',
  { label: 'Verify', agentType: 'general-purpose' }
)

var verifiedClean = verify && (typeof verify === 'string' ? !verify.includes('FAILED') && !verify.includes('failed') : false)

return {
  iteration2_complete: true,
  fixSourceStatus: typeof fixSource === 'string' ? fixSource.substring(0, 300) : 'non-string result',
  fixTestsStatus: typeof fixTests === 'string' ? fixTests.substring(0, 300) : 'non-string result',
  verificationStatus: typeof verify === 'string' ? verify.substring(0, 500) : 'non-string result',
  verifiedClean: verifiedClean,
}
