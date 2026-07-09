# Paper QA Rerun 10

VERDICT: PASS

## Scope

- Workspace: `/home/debian/polysignal-lab`
- Source edits: none
- Diff-check artifact refreshed: `.omo/ulw-loop/evidence/paper-post-r10-diff-check.txt`

## manualQa

### surfaceEvidence

| scenario id | criterion reference | surface | exact invocation | verdict | artifactRefs |
|---|---|---|---|---|---|
| S1 | focused tests passed | CLI artifact inspection | `wc -c .omo/ulw-loop/evidence/paper-post-r10-focused-rerun.txt && sed -n '1,220p' .omo/ulw-loop/evidence/paper-post-r10-focused-rerun.txt` | PASS: non-empty transcript shows pytest progress through `[100%]` with warnings only and no failures/errors | A1 |
| S2 | full pytest passed | CLI artifact inspection | `wc -c .omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt && sed -n '1,220p' .omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt` | PASS: non-empty transcript shows full pytest progress through `[100%]` with warnings only and no failures/errors | A2 |
| S3 | R10 rg evidence proves direct account/positions | CLI artifact inspection | `wc -c .omo/ulw-loop/evidence/paper-post-r10-rg-rerun.txt && sed -n '1,220p' .omo/ulw-loop/evidence/paper-post-r10-rg-rerun.txt` | PASS: transcript shows direct `nautilus_cache.account()` and `nautilus_cache.positions()` calls in `src/polysignal_lab/app/scheduler_reporting.py` | A3 |
| S4 | basedpyright has no errors | CLI artifact inspection | `wc -c .omo/ulw-loop/evidence/paper-post-r10-basedpyright-rerun.txt && sed -n '1,220p' .omo/ulw-loop/evidence/paper-post-r10-basedpyright-rerun.txt` | PASS: transcript ends with `0 errors, 135 warnings, 0 notes` | A4 |
| S5 | manual QA covers zero-money/projection/storage surfaces | CLI artifact inspection | `wc -c .omo/ulw-loop/evidence/paper-post-zero-money-manual-qa.txt && sed -n '1,220p' .omo/ulw-loop/evidence/paper-post-zero-money-manual-qa.txt` | PASS: transcript covers `settlement_zero_money`, `project_position_missing_money`, storage queries, malformed idempotency handling, and cleanup | A5 |
| S6 | refreshed diff-check artifact is non-empty and PASS | CLI git whitespace check | `git diff --check` captured to `.omo/ulw-loop/evidence/paper-post-r10-diff-check.txt`, then `wc -c` and `sed -n '1,20p'` | PASS: refreshed artifact is 62 bytes and records `RESULT: PASS (no whitespace errors)` | A6 |
| S7 | refs check protects refs/@refs/docs/nautilus_reference | CLI artifact inspection | `wc -c .omo/ulw-loop/evidence/paper-post-r10-refs-check.txt && sed -n '1,220p' .omo/ulw-loop/evidence/paper-post-r10-refs-check.txt` | PASS: transcript checks `git status --short -- refs @refs docs/nautilus_reference` and `git diff --name-only -- refs @refs docs/nautilus_reference`; only missing `refs` and `@refs` are reported as OK | A7 |

### adversarialCases

| scenario id | criterion reference | adversarial class | expected behavior | verdict | artifactRefs |
|---|---|---|---|---|---|
| ADV1 | R10 rg evidence has no incomplete-cache test | stale/incomplete cache regression evidence | No `incomplete.*cache` or `cache.*incomplete` matches under `tests`, `src`, or the R10 rg transcript | PASS: `rg` returned exit code 1 and the supplemental artifact records this as no matches | A8 |
| ADV2 | diff-check artifact is not empty placeholder | empty or stale evidence artifact | Artifact must be non-empty and contain a PASS result from refreshed `git diff --check` | PASS: refreshed artifact is non-empty and records PASS | A6 |
| ADV3 | protected reference paths are not modified | accidental edits to protected reference material | `refs`, `@refs`, and `docs/nautilus_reference` should have no status/diff output except allowed missing path notes | PASS: refs check artifact records no changed files for those paths | A7 |

### artifactRefs

| id | kind | description | path |
|---|---|---|---|
| A1 | pytest transcript | Focused R10 pytest rerun output, non-empty, `[100%]`, warnings only | `.omo/ulw-loop/evidence/paper-post-r10-focused-rerun.txt` |
| A2 | pytest transcript | Full pytest rerun output, non-empty, `[100%]`, warnings only | `.omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt` |
| A3 | rg transcript | R10 rg proof of direct Nautilus cache account and positions calls | `.omo/ulw-loop/evidence/paper-post-r10-rg-rerun.txt` |
| A4 | type-check transcript | basedpyright rerun output ending in zero errors | `.omo/ulw-loop/evidence/paper-post-r10-basedpyright-rerun.txt` |
| A5 | manual QA transcript | Zero-money, projection, storage, malformed idempotency, and cleanup evidence | `.omo/ulw-loop/evidence/paper-post-zero-money-manual-qa.txt` |
| A6 | git diff-check transcript | Refreshed non-empty `git diff --check` PASS artifact | `.omo/ulw-loop/evidence/paper-post-r10-diff-check.txt` |
| A7 | refs protection transcript | Protected refs/@refs/docs/nautilus_reference status and diff check | `.omo/ulw-loop/evidence/paper-post-r10-refs-check.txt` |
| A8 | supplemental rg transcript | Negative no-incomplete-cache search evidence captured for this rerun | `.omo/evidence/paper-qa-rerun-10/rg-no-incomplete-cache.txt` |
