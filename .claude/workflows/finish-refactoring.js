export const meta = {
  name: 'finish-refactoring',
  description: 'Apply P1-10 fix and run compliance verification',
  phases: [
    { title: 'P1-10: Private Imports' },
    { title: 'Verify' },
  ],
}

phase('P1-10: Private Imports')
const p1_10 = await agent(`
Fix private member imports. Make _market_metadata and _timestamp_ns public.

Files:
- src/polysignal_lab/nautilus_runtime/sidecar_data.py — define _market_metadata, _timestamp_ns
- src/polysignal_lab/nautilus_runtime/market_rotation.py — import them with private access

Steps:
1. In sidecar_data.py, find _market_metadata and _timestamp_ns
2. Rename to market_metadata and timestamp_ns
3. In market_rotation.py, update import to use public names
4. Remove the "# pyright: ignore[reportPrivateUsage]" comment
5. Check for other references: grep -rn "_market_metadata\\|_timestamp_ns" src/

VERIFY: cd /home/debian/polysignal-lab && python -c "from polysignal_lab.nautilus_runtime.market_rotation import _Health; print('OK')"
`, {label: 'P1-10 private imports'})

phase('Verify')
log('Running compliance review...')
const review = await workflow({scriptPath: '/home/debian/polysignal-lab/.claude/workflows/compliance-review.js'})

const verdict = await agent(`
Analyze this compliance review report for remaining P0 issues.

Return:
- hasP0: true/false
- remainingP0Details: what P0 issues remain (or "none")
- remainingP1Details: P1 issues remaining (or "none")

REPORT:
${review}
`, {label: 'verdict', schema: {
  type: 'object',
  properties: {
    hasP0: {type: 'boolean'},
    remainingP0Details: {type: 'string'},
    remainingP1Details: {type: 'string'},
  },
  required: ['hasP0', 'remainingP0Details', 'remainingP1Details'],
}})

return {
  clean: !verdict.hasP0,
  p0Remaining: verdict.remainingP0Details,
  p1Remaining: verdict.remainingP1Details,
}
