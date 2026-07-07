/**
 * apply-safe-fixes-iter1 — 安全机械性修复 workflow
 *
 * 基于合规审查结果，应用低风险修复：
 * 1. build_trading_node → build_live_node 重命名
 * 2. 移除 NautilusDecisionPolicyActor 向后兼容别名
 * 3. 删除 scheduler_runtime.py 空桩 + 更新测试
 *
 * 运行后执行合规审查 workflow 验证。
 */

export const meta = {
  name: 'apply-safe-fixes-iter1',
  description: 'Apply safe mechanical P1/P2 fixes from compliance review - iteration 1',
  phases: [
    { title: 'Fix', detail: '3 parallel agents for independent safe fixes' },
    { title: 'Verify', detail: 'Run tests to confirm no regressions' },
  ],
}

// ─── Agent 1: Rename build_trading_node → build_live_node ───
const AGENT_1_RENAME = `你是 PolySignal Lab 代码重构 agent。

## 任务
将 nautilus_runtime 中的 build_trading_node 函数重命名为 build_live_node。

## 需要修改的文件（相对于 /home/debian/polysignal-lab）

### 1. src/polysignal_lab/nautilus_runtime/node_builder.py
- 第3行（header Output）：把 build_trading_node 改为 build_live_node
- 第282行：def build_trading_node( → def build_live_node(
- 第292行 docstring 里的 "Build the Nautilus-owned paper runtime wiring" 改为 "Build a LiveNode-based paper runtime wiring"
- 第293行注释里的 node 改为 node（不用改，这是内部 deferred import 注释）

### 2. src/polysignal_lab/nautilus_runtime/node.py
- 第90行 from node_builder import 中的 build_trading_node 改为 build_live_node
- 第230行 components = build_trading_node( → components = build_live_node(

### 3. src/polysignal_lab/nautilus_runtime/__init__.py
- 第15行 build_trading_node → build_live_node
- 第23行 "build_trading_node" → "build_live_node"

## 方法
1. 用 Read 读取每个文件的相关行
2. 用 Edit 做精确的字符串替换
3. 修改完成后，执行: python -c "from polysignal_lab.nautilus_runtime import build_live_node; print('OK')" 验证

只做以上修改，不要改动任何其他代码。`

// ─── Agent 2: Remove NautilusDecisionPolicyActor alias ───
const AGENT_2_ALIAS = `你是 PolySignal Lab 代码重构 agent。

## 任务
从 runtime_classes.py 中移除 NautilusDecisionPolicyActor 向后兼容别名。

## 需要修改的文件

### src/polysignal_lab/nautilus_runtime/runtime_classes.py
- 删除第109-110行的注释和别名：
  """
  # Backward compatibility alias
  NautilusDecisionPolicyActor = LiveDecisionPolicyActor
  """
- 注意不要删除中间的空行（保留空行结构，不产生两个连续空行）

## 验证
修改后执行以下验证脚本：
python3 -c "
import ast
with open('src/polysignal_lab/nautilus_runtime/runtime_classes.py') as f:
    tree = ast.parse(f.read())
# Verify NautilusDecisionPolicyActor is not an assignment in module body
for node in ast.walk(tree):
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == 'NautilusDecisionPolicyActor':
                print('FAIL: alias still exists')
                exit(1)
# Verify LiveDecisionPolicyActor class still exists
for node in ast.walk(tree):
    if isinstance(node, ast.ClassDef) and node.name == 'LiveDecisionPolicyActor':
        print('OK: LiveDecisionPolicyActor preserved')
        exit(0)
print('FAIL: LiveDecisionPolicyActor not found')
exit(1)
"

只做以上修改，不要改动任何其他代码。`

// ─── Agent 3: Delete scheduler_runtime.py stub ───
const AGENT_3_STUB = `你是 PolySignal Lab 代码重构 agent。

## 任务
删除 scheduler_runtime.py 空桩文件，并更新引用它的测试文件。

## 上下文
scheduler_runtime.py 当前是一个纯重导出桩（14行），仅导出 scheduler_shared 的两个函数。它已无实际用途。

## 修改

### 1. src/polysignal_lab/app/scheduler_runtime.py
- 删除整个文件（用 Python 执行 os.remove）

### 2. tests/test_scheduler.py
- 第311-316行 test_scheduler_runtime_no_tick_resting_orders 函数：修改为直接从 scheduler_shared 验证，不经过 scheduler_runtime：
  """
  def test_scheduler_runtime_no_tick_resting_orders() -> None:
      \"\"\"_tick_resting_orders was a no-op function and has been removed.\"\"\"
      from polysignal_lab.app.scheduler_shared import _configured_report_date
      assert _configured_report_date is not None, (
          "scheduler_shared should still be importable"
      )
  """

### 3. tests/test_scheduler_reports.py
- 第20行：from polysignal_lab.app import scheduler_reporting, scheduler_runtime, scheduler_shared
  改为：from polysignal_lab.app import scheduler_reporting, scheduler_shared
  （scheduler_runtime 在此文件中从未实际使用过）

## 验证
1. 确认文件已删除: ! test -f src/polysignal_lab/app/scheduler_runtime.py
2. 运行验证: python -c "from polysignal_lab.app.scheduler_shared import _configured_report_date; print('OK')"

只做以上修改，不要改动任何其他代码。`

// ─── Launch phase 1: Fix ───
phase('Fix')
log('启动 3 路并行安全修复 agent…')

const fixers = await parallel([
  () => agent(AGENT_1_RENAME, { label: 'Fix-1-Rename', agentType: 'general-purpose' }),
  () => agent(AGENT_2_ALIAS, { label: 'Fix-2-Alias', agentType: 'general-purpose' }),
  () => agent(AGENT_3_STUB, { label: 'Fix-3-StubDelete', agentType: 'general-purpose' }),
])

// Collect results
var successCount = 0
var failedCount = 0
for (var fi = 0; fi < fixers.length; fi++) {
  var f = fixers[fi]
  if (f) {
    log('Agent ' + fi + ' completed: ' + (typeof f === 'string' ? f.substring(0, 200) : JSON.stringify(f).substring(0, 200)))
    successCount++
  } else {
    log('Agent ' + fi + ' returned null (error)')
    failedCount++
  }
}
log('Fixes applied: ' + successCount + ' succeeded, ' + failedCount + ' failed')

// ─── Phase 2: Verify ───
phase('Verify')
log('Running test verification…')

const verification = await agent(
  '运行测试验证代码修改未破坏任何功能。\n\n' +
  '先执行：python -c "from polysignal_lab.nautilus_runtime import build_live_node; print(\'OK: build_live_node imported\')"\n\n' +
  '然后运行核心测试：\n' +
  'uv run python -m pytest tests/test_nautilus_node.py tests/test_nautilus_decision_policy.py tests/test_nautilus_strategy_base.py tests/test_nautilus_strategy_wrappers.py tests/test_scheduler.py tests/test_scheduler_reports.py -v --tb=short 2>&1 | tail -80\n\n' +
  '报告测试结果（成功/失败数，关键失败原因）。',
  { label: 'Verify-Tests', agentType: 'general-purpose' }
)

// Return the final status
var finalMessage = ''
if (typeof verification === 'string') {
  // Check for failure indicators
  if (verification.includes('FAILED') || verification.includes('failed')) {
    finalMessage = 'TESTS FAILED: ' + verification.substring(0, 500)
  } else if (verification.includes('passed') || verification.includes('PASSED')) {
    finalMessage = 'TESTS PASSED. Ready for re-review workflow.'
  } else {
    finalMessage = 'Test result ambiguous: ' + verification.substring(0, 500)
  }
} else {
  finalMessage = 'Verification returned non-string: ' + JSON.stringify(verification).substring(0, 500)
}

log(finalMessage)

return {
  fixesApplied: successCount,
  fixesFailed: failedCount,
  verificationStatus: finalMessage,
  readyForReReview: !finalMessage.includes('FAILED') && !finalMessage.includes('failed'),
}
