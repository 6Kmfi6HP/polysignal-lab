# Paper QA Rerun 9

VERDICT: FAIL

Reason: one required artifact is empty: `.omo/ulw-loop/evidence/paper-post-r10-diff-check.txt`. The assignment says missing or failed artifacts fail the verdict.

## manualQa

### surfaceEvidence

| scenario id | criterion reference | surface | exact invocation | verdict | artifactRefs |
|---|---|---|---|---|---|
| S1 | Required artifacts exist | CLI filesystem evidence | `test -s <required-artifact>` for each required artifact | FAIL | A1, A7, A8 |
| S2 | Focused tests 55 passed | CLI pytest evidence artifact | `sed -n '1,120p' .omo/ulw-loop/evidence/paper-post-r10-focused-rerun.txt` | PASS | A1, A8 |
| S3 | Full pytest passed | CLI pytest evidence artifact | `sed -n '1,140p' .omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt` | PASS | A2, A8 |
| S4 | R10 rg proves direct account/positions and no incomplete-cache test | CLI ripgrep evidence artifact | `rg -n "account|positions|incomplete|cache|test" .omo/ulw-loop/evidence/paper-post-r10-rg-rerun.txt` | PASS | A3, A8 |
| S5 | Manual QA covers zero-money/projection/storage surfaces | CLI manual QA evidence artifact | `rg -n "zero|money|projection|storage|PASS|FAIL|surface|manual" .omo/ulw-loop/evidence/paper-post-zero-money-manual-qa.txt` | PASS | A5, A8 |
| S6 | Refs check artifact is present and clean | CLI git refs evidence artifact | `sed -n '1,80p' .omo/ulw-loop/evidence/paper-post-r10-refs-check.txt` | PASS | A6, A8 |
| S7 | Diff check artifact is present and usable | CLI filesystem evidence | `test -s .omo/ulw-loop/evidence/paper-post-r10-diff-check.txt` | FAIL | A7, A8 |

### adversarialCases

| scenario id | criterion reference | adversarial class | expected behavior | verdict | artifactRefs |
|---|---|---|---|---|---|
| ADV1 | Required artifacts exist | Empty required artifact | Empty evidence must fail instead of being inferred from surrounding artifacts | FAIL | A7, A8 |
| ADV2 | R10 rg evidence | Stale/incomplete cache test escape | Artifact must show direct `nautilus_cache.account()` and `nautilus_cache.positions()` lines and no incomplete-cache test hit | PASS | A3, A8 |
| ADV3 | Manual QA coverage | Narrow manual smoke missing storage/projection surface | Artifact must include zero-money, projection, storage query, malformed payload, and cleanup lines | PASS | A5, A8 |

### artifactRefs

| id | kind | description | path |
|---|---|---|---|
| A1 | pytest artifact | Focused rerun output; 55 progress dots at `[100%]`, no failure line in inspected artifact | `.omo/ulw-loop/evidence/paper-post-r10-focused-rerun.txt` |
| A2 | pytest artifact | Full pytest rerun output reaches `[100%]`, no failure line in inspected artifact | `.omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt` |
| A3 | rg artifact | Shows direct `nautilus_cache.account()` and `nautilus_cache.positions()` | `.omo/ulw-loop/evidence/paper-post-r10-rg-rerun.txt` |
| A4 | typecheck artifact | Basedpyright rerun output reports `0 errors, 135 warnings, 0 notes` | `.omo/ulw-loop/evidence/paper-post-r10-basedpyright-rerun.txt` |
| A5 | manual QA artifact | Zero-money/projection/storage manual QA output and cleanup receipt | `.omo/ulw-loop/evidence/paper-post-zero-money-manual-qa.txt` |
| A6 | refs artifact | Refs/docs check output with no diff names shown | `.omo/ulw-loop/evidence/paper-post-r10-refs-check.txt` |
| A7 | diff-check artifact | Required diff-check artifact is zero bytes | `.omo/ulw-loop/evidence/paper-post-r10-diff-check.txt` |
| A8 | executor transcript | This QA executor's artifact validation transcript | `.omo/evidence/paper-qa-rerun-9/verify-artifacts.txt` |

## Notes

- I did not rerun tests; the failure is from current artifact state.
- The focused/full pytest artifacts do not include explicit final summary text such as `55 passed`; they show complete progress to `[100%]` with no failure lines in the captured evidence.
