status: passed

# Paper QA Rerun 2

Scope: `/home/debian/polysignal-lab`

Verdict: passed. I validated the current required artifacts and added parser evidence under `.omo/evidence/paper-qa-rerun-2/`. No source files were edited.

Blockers: none.

## Command Evidence

| Check | Surface | Exact invocation | Verdict | Artifact |
| --- | --- | --- | --- | --- |
| Required artifacts parseable/non-empty | CLI artifact parser | `python .omo/evidence/paper-qa-rerun-2/validate_artifacts.py \| tee .omo/evidence/paper-qa-rerun-2/artifact-validation.txt` | PASS | `.omo/evidence/paper-qa-rerun-2/artifact-validation.txt` |
| Parseable repair result | CLI artifact validation | `python .omo/evidence/paper-qa-rerun-2/validate_focused_blockers.py \| tee .omo/evidence/paper-qa-rerun-2/focused-blocker-validation.txt` | PASS | `.omo/ulw-loop/evidence/paper-blockers-manual-qa.txt`, `.omo/evidence/paper-qa-rerun-2/focused-blocker-validation.txt` |
| Incomplete position skip | CLI artifact validation | `python .omo/evidence/paper-qa-rerun-2/validate_focused_blockers.py \| tee .omo/evidence/paper-qa-rerun-2/focused-blocker-validation.txt` | PASS | `.omo/ulw-loop/evidence/paper-blockers-manual-qa.txt`, `.omo/evidence/paper-qa-rerun-2/focused-blocker-validation.txt` |
| Incomplete cache guard | CLI artifact validation | `python .omo/evidence/paper-qa-rerun-2/validate_focused_blockers.py \| tee .omo/evidence/paper-qa-rerun-2/focused-blocker-validation.txt` | PASS | `.omo/ulw-loop/evidence/paper-blockers-manual-qa.txt`, `.omo/evidence/paper-qa-rerun-2/focused-blocker-validation.txt` |
| SPLIT daily report counting | CLI artifact validation | `python .omo/evidence/paper-qa-rerun-2/validate_focused_blockers.py \| tee .omo/evidence/paper-qa-rerun-2/focused-blocker-validation.txt` | PASS | `.omo/ulw-loop/evidence/paper-blockers-manual-qa.txt`, `.omo/evidence/paper-qa-rerun-2/focused-blocker-validation.txt` |
| Malformed persisted rows filtered | CLI artifact validation | `python .omo/evidence/paper-qa-rerun-2/validate_focused_blockers.py \| tee .omo/evidence/paper-qa-rerun-2/focused-blocker-validation.txt` | PASS | `.omo/ulw-loop/evidence/paper-blockers-manual-qa.txt`, `.omo/evidence/paper-qa-rerun-2/focused-blocker-validation.txt` |
| Focused tests | Pytest artifact validation | `python .omo/evidence/paper-qa-rerun-2/validate_focused_blockers.py \| tee .omo/evidence/paper-qa-rerun-2/focused-blocker-validation.txt` | PASS: `46 passed` | `.omo/ulw-loop/evidence/paper-blockers-focused-pytest.txt`, `.omo/evidence/paper-qa-rerun-2/focused-blocker-validation.txt` |
| Full test artifact validity | CLI artifact validation | `python .omo/evidence/paper-qa-rerun-2/validate_regression_artifacts.py \| tee .omo/evidence/paper-qa-rerun-2/regression-artifact-validation.txt` | PASS: `661 passed` | `.omo/ulw-loop/evidence/paper-full-pytest.txt`, `.omo/evidence/paper-qa-rerun-2/regression-artifact-validation.txt` |
| Security scope | CLI artifact validation | `python .omo/evidence/paper-qa-rerun-2/validate_regression_artifacts.py \| tee .omo/evidence/paper-qa-rerun-2/regression-artifact-validation.txt` | PASS: `no violations in 4 file(s)` | `.omo/ulw-loop/evidence/paper-no-excuse-security-scope.txt`, `.omo/evidence/paper-qa-rerun-2/regression-artifact-validation.txt` |
| Diff check | CLI artifact validation | `python .omo/evidence/paper-qa-rerun-2/validate_regression_artifacts.py \| tee .omo/evidence/paper-qa-rerun-2/regression-artifact-validation.txt` | PASS: `diff_check=pass` | `.omo/ulw-loop/evidence/paper-diff-check.txt`, `.omo/evidence/paper-qa-rerun-2/regression-artifact-validation.txt` |
| Refs clean | CLI artifact validation | `python .omo/evidence/paper-qa-rerun-2/validate_regression_artifacts.py \| tee .omo/evidence/paper-qa-rerun-2/regression-artifact-validation.txt` | PASS: `refs_check=pass no refs/@refs/docs/nautilus_reference changed` | `.omo/ulw-loop/evidence/paper-refs-check.txt`, `.omo/evidence/paper-qa-rerun-2/regression-artifact-validation.txt` |

## manualQa

### surfaceEvidence

| scenarioId | criterionRef | surface | exactInvocation | verdict | artifactRefs |
| --- | --- | --- | --- | --- | --- |
| S1 | required-current-artifacts | CLI artifact parser | `python .omo/evidence/paper-qa-rerun-2/validate_artifacts.py \| tee .omo/evidence/paper-qa-rerun-2/artifact-validation.txt` | PASS | A1, A10 |
| S2 | focused-blocker-coverage | CLI artifact parser | `python .omo/evidence/paper-qa-rerun-2/validate_focused_blockers.py \| tee .omo/evidence/paper-qa-rerun-2/focused-blocker-validation.txt` | PASS | A2, A4, A5, A11 |
| S3 | regression-artifact-validity | CLI artifact parser | `python .omo/evidence/paper-qa-rerun-2/validate_regression_artifacts.py \| tee .omo/evidence/paper-qa-rerun-2/regression-artifact-validation.txt` | PASS | A3, A6, A7, A8, A9, A12 |

### adversarialCases

| scenarioId | criterionRef | adversarialClass | expectedBehavior | verdict | artifactRefs |
| --- | --- | --- | --- | --- | --- |
| A-S1 | parseable-repair-result | persisted repair output parsing | Repair result remains parseable and resolves to a concrete `WIN` result id. | PASS | A4 |
| A-S2 | incomplete-position-skip | incomplete money fields | Incomplete position rows are skipped/rejected instead of settled. | PASS | A4 |
| A-S3 | incomplete-cache-guard | incomplete cache source | Cache guard keeps invalid cache data from changing balances/counts. | PASS | A4 |
| A-S4 | split-daily-report-counting | SPLIT result classification | Daily report counts SPLIT as settled and preserves pnl/counting. | PASS | A4 |
| A-S5 | malformed-persisted-rows | malformed storage rows | Malformed persisted rows are filtered instead of silently restored as valid rows. | PASS | A4 |
| A-S6 | refs-protection | protected reference trees | `refs/`, `@refs`, and `docs/nautilus_reference` remain unmodified. | PASS | A9 |

### artifactRefs

| id | kind | description | path |
| --- | --- | --- | --- |
| A1 | command-output | Required artifact parser; proves all six required artifacts exist, are non-empty, and contain expected markers. | `.omo/evidence/paper-qa-rerun-2/artifact-validation.txt` |
| A2 | command-output | Focused blocker marker parser; proves five blocker markers plus `46 passed`. | `.omo/evidence/paper-qa-rerun-2/focused-blocker-validation.txt` |
| A3 | command-output | Regression artifact parser; proves full pytest, security, diff, and refs markers. | `.omo/evidence/paper-qa-rerun-2/regression-artifact-validation.txt` |
| A4 | existing-artifact | Manual QA blocker proof: repair parse, incomplete position, cache guard, SPLIT report, malformed persisted rows. | `.omo/ulw-loop/evidence/paper-blockers-manual-qa.txt` |
| A5 | existing-artifact | Focused pytest proof: `46 passed, 2 warnings`. | `.omo/ulw-loop/evidence/paper-blockers-focused-pytest.txt` |
| A6 | existing-artifact | Full pytest proof: `661 passed, 2 warnings`. | `.omo/ulw-loop/evidence/paper-full-pytest.txt` |
| A7 | existing-artifact | Security scope proof: `no violations in 4 file(s)`. | `.omo/ulw-loop/evidence/paper-no-excuse-security-scope.txt` |
| A8 | existing-artifact | Diff check proof: `diff_check=pass`. | `.omo/ulw-loop/evidence/paper-diff-check.txt` |
| A9 | existing-artifact | Refs protection proof: `refs_check=pass no refs/@refs/docs/nautilus_reference changed`. | `.omo/ulw-loop/evidence/paper-refs-check.txt` |
| A10 | validation-script | Exact parser script for required current artifacts. | `.omo/evidence/paper-qa-rerun-2/validate_artifacts.py` |
| A11 | validation-script | Exact parser script for focused blocker markers. | `.omo/evidence/paper-qa-rerun-2/validate_focused_blockers.py` |
| A12 | validation-script | Exact parser script for full/security/diff/refs markers. | `.omo/evidence/paper-qa-rerun-2/validate_regression_artifacts.py` |
