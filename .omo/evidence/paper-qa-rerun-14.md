# paper-qa-rerun-14

Verdict: PASS

Scope: `/home/debian/polysignal-lab`

Inputs audited:

- `.omo/ulw-loop/evidence/paper-post-split-loc.txt`
- `.omo/ulw-loop/evidence/paper-post-split-focused-pytest.txt`
- `.omo/ulw-loop/evidence/paper-r10-protocol-callable-red.txt`
- `.omo/ulw-loop/evidence/paper-r10-protocol-callable-green.txt`
- `.omo/ulw-loop/evidence/paper-storage-timestamp-red.txt`
- `.omo/ulw-loop/evidence/paper-storage-timestamp-green.txt`
- `.omo/ulw-loop/evidence/paper-storage-restore-pytest.txt`
- `.omo/ulw-loop/evidence/paper-post-r10-focused-rerun.txt`
- `.omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt`
- `.omo/ulw-loop/evidence/paper-post-r10-rg-rerun.txt`
- `.omo/ulw-loop/evidence/paper-post-r10-diff-check.txt`
- `.omo/ulw-loop/evidence/paper-post-r10-refs-check.txt`

## manualQa.surfaceEvidence

| scenario id | criterion reference | surface | exact invocation | verdict | artifactRefs |
|---|---|---|---|---|---|
| S1 | split LOC under 250 for both files | CLI filesystem evidence audit | `wc -l src/polysignal_lab/domain/paper_result.py src/polysignal_lab/domain/paper_report.py && cat .omo/ulw-loop/evidence/paper-post-split-loc.txt` | PASS: evidence records `paper_result.py` pure LOC 151 and `paper_report.py` pure LOC 144, both under 250 | A1 |
| S2 | focused/full regressions pass | CLI pytest evidence audit | `cat .omo/ulw-loop/evidence/paper-post-split-focused-pytest.txt .omo/ulw-loop/evidence/paper-storage-restore-pytest.txt .omo/ulw-loop/evidence/paper-post-r10-focused-rerun.txt .omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt` plus structural pytest failure scan | PASS: focused, restore, post-r10 focused, and full pytest evidence show `[100%]`; only warnings appear in the larger runs | A2 |
| S3 | RED/GREEN artifacts exist and prove failure then pass | CLI RED/GREEN evidence audit | `test -s` and `cat` for `paper-r10-protocol-callable-{red,green}.txt` and `paper-storage-timestamp-{red,green}.txt` | PASS: RED artifacts are non-empty and contain pytest failure output; GREEN artifacts are non-empty and contain pass markers | A3 |
| S4 | rg/diff/refs checks pass | CLI evidence audit | `cat .omo/ulw-loop/evidence/paper-post-r10-rg-rerun.txt .omo/ulw-loop/evidence/paper-post-r10-diff-check.txt .omo/ulw-loop/evidence/paper-post-r10-refs-check.txt` plus pass-compatible assertions | PASS: rg evidence contains only callable `nautilus_cache.account()` / `positions()` refs, diff check reports no whitespace errors, protected refs diff is empty | A4 |

## manualQa.adversarialCases

| scenario id | criterion reference | adversarial class | expected behavior | verdict | artifactRefs |
|---|---|---|---|---|---|
| A-S1 | split LOC under 250 | stale or inflated split evidence | Audit fails if either recorded pure LOC is missing or `>= 250` | PASS: parser found both required rows and both values are below 250 | A1 |
| A-S2 | focused/full regressions pass | false green from warnings or truncated pytest output | Audit fails on structural pytest failure sections and requires pass/completion markers | PASS: warnings were not treated as failures; no failure sections were present | A2 |
| A-S3 | RED/GREEN artifacts exist | missing RED phase or green artifact still failing | Audit fails if any RED/GREEN file is empty, RED lacks failure markers, or GREEN has failure markers | PASS: both RED phases fail and both GREEN phases pass | A3 |
| A-S4 | refs/diff checks pass | non-callable protocol ref or protected reference mutation | Audit fails on unexpected rg refs, whitespace diff errors, or non-empty protected refs diff | PASS: only callable refs remain; diff/refs checks are clean | A4 |

## manualQa.artifactRefs

| id | kind | description | path |
|---|---|---|---|
| A1 | text | LOC audit transcript and recorded split LOC evidence | `.omo/evidence/paper-qa-rerun-14/loc-check.txt` |
| A2 | text | Focused/full/restore pytest evidence audit transcript | `.omo/evidence/paper-qa-rerun-14/regression-check.txt` |
| A3 | text | RED/GREEN artifact audit transcript | `.omo/evidence/paper-qa-rerun-14/red-green-check.txt` |
| A4 | text | rg/diff/refs audit transcript | `.omo/evidence/paper-qa-rerun-14/diff-refs-check.txt` |

Cleanup: no servers, tmux sessions, browser contexts, containers, or bound ports were spawned. QA-only artifacts are the evidence files listed above.
