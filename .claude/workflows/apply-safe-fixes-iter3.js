/**
 * apply-safe-fixes-iter3 — 迭代 3: 清理 paper_portfolio_service.py stub + 双 lazy-import 网关
 *
 * 全部通过 agent 执行，主对话不做任何编辑。
 */

export const meta = {
  name: 'apply-safe-fixes-iter3',
  description: 'Iteration 3: remove paper_portfolio stub, merge lazy-import gateways',
  phases: [
    { title: 'Scout', detail: 'Scope the two fixes' },
    { title: 'Fix', detail: 'Apply changes via agents' },
    { title: 'Verify', detail: 'Run compliance review' },
  ],
}

phase('Scout')
log('Scouting paper_portfolio_service stub and lazy-import gates…')

const scout = await agent(
  'Scout two cleanup opportunities:\n\n' +
  'Fix-1: Remove paper_portfolio_service.py stub\n' +
  '- grep -rn "paper_portfolio_service\|PaperPortfolioService" src/ tests/ --include="*.py"\n' +
  '- Check if PAPER_PORTFOLIO_REMOVED is referenced anywhere\n' +
  '- Check if paper_portfolio_service is imported from any __init__.py\n' +
  '- Determine if file can be safely deleted\n\n' +
  'Fix-2: Merge dual lazy-import gateways\n' +
  '- Read live_node.py and node_builder.py to compare their LiveNode lazy-import logic\n' +
  '- Check which one is the canonical version\n' +
  '- Determine if they can be consolidated\n\n' +
  'Return JSON summary of findings.',
  { label: 'Scout', agentType: 'general-purpose' }
)

phase('Fix')

const fix = await agent(
  'Apply two safe fixes:\n\n' +
  'Fix-1: Delete paper_portfolio_service.py (66-line stub)\n' +
  '- File: src/polysignal_lab/app/services/paper_portfolio_service.py\n' +
  '- First verify: grep -rn "PaperPortfolioService\|paper_portfolio_service" src/ tests/ --include="*.py"\n' +
  '- Check any __init__.py that imports it — update if needed\n' +
  '- Delete the file with: import os; os.remove("src/polysignal_lab/app/services/paper_portfolio_service.py")\n\n' +
  'Fix-2: Merge dual lazy-import gateways\n' +
  '- Read live_node.py (lines 1-45) and node_builder.py (lines 60-140) to find the lazy-import functions\n' +
  '- Check if both have _ensure_* functions and LiveNode stubs\n' +
  '- If they are identical, consolidate one to import from the other (delegate)\n' +
  '- DO NOT delete either file; just make one delegate to the other\n\n' +
  'After changes:\n' +
  '1. Run: python3 -c "from polysignal_lab.nautilus_runtime import build_live_node; print(\'OK\')"\n' +
  '2. Check import of modified modules still works\n' +
  'Report what was done.',
  { label: 'Fix', agentType: 'general-purpose' }
)

phase('Verify')
log('Running compliance review…')

// Note: compliance review will be run by the main loop after this workflow completes
// This workflow only does the fix; the outer loop drives the review + loop decision
log('Fix phase complete. Compliance review will run as next step in the loop.')

return {
  iteration3_complete: true,
  fixStatus: typeof fix === 'string' ? fix.substring(0, 500) : JSON.stringify(fix).substring(0, 500),
}
