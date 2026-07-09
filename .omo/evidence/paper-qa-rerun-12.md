# Paper QA Rerun 12

Verdict: PASS

Scope: `/home/debian/polysignal-lab`

## manualQa

### surfaceEvidence

| scenario id | criterion reference | surface | exact invocation | verdict | artifactRefs |
|---|---|---|---|---|---|
| S1 | required artifacts are non-empty | CLI/data evidence audit | `test -s` loop over the 10 requested `.omo/ulw-loop/evidence/*.txt` files, recording bytes and lines | PASS | A1 |
| S2 | callable-cache blocker RED exists | CLI/pytest transcript inspection | `sed -n '1,220p' .omo/ulw-loop/evidence/paper-r10-protocol-callable-red.txt` and `rg -q "TypeError: 'int' object is not callable"` | PASS | A2, A12 |
| S3 | callable-cache blocker GREEN exists | CLI/pytest transcript inspection | `sed -n '1,80p' .omo/ulw-loop/evidence/paper-r10-protocol-callable-green.txt` and `rg -q "\\[100%\\]"` with no `FAILED|ERROR|Traceback` | PASS | A3, A12 |
| S4 | malformed-timestamp blocker RED exists | CLI/pytest transcript inspection | `sed -n '1,220p' .omo/ulw-loop/evidence/paper-storage-timestamp-red.txt` and `rg -q "ValueError: Invalid isoformat string: 'not-a-date'"` | PASS | A4, A12 |
| S5 | malformed-timestamp blocker GREEN exists | CLI/pytest transcript inspection | `sed -n '1,80p' .omo/ulw-loop/evidence/paper-storage-timestamp-green.txt` and `rg -q "\\[100%\\]"` with no `FAILED|ERROR|Traceback` | PASS | A5, A12 |
| S6 | storage restore regression passes | CLI/pytest transcript inspection | `sed -n '1,120p' .omo/ulw-loop/evidence/paper-storage-restore-pytest.txt` and `rg -q "\\[100%\\]"` with no `FAILED|ERROR|Traceback` | PASS | A6, A12 |
| S7 | focused regression rerun passes | CLI/pytest transcript inspection | `sed -n '1,180p' .omo/ulw-loop/evidence/paper-post-r10-focused-rerun.txt` and `rg -q "\\[100%\\]"` with no `FAILED|ERROR|Traceback` | PASS | A7, A12 |
| S8 | full pytest rerun passes | CLI/pytest transcript inspection | `sed -n '1,220p' .omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt` and `rg -q "\\[100%\\]"` with no `FAILED|ERROR|Traceback` | PASS | A8, A12 |
| S9 | callable rg rerun is bounded | CLI/rg transcript inspection | `sed -n '1,120p' .omo/ulw-loop/evidence/paper-post-r10-rg-rerun.txt` and `rg -q` for the two expected `nautilus_cache.account()` / `positions()` call sites | PASS | A9, A12 |
| S10 | diff check passes | CLI/git transcript inspection | `sed -n '1,120p' .omo/ulw-loop/evidence/paper-post-r10-diff-check.txt` and `rg -q "RESULT: PASS"` | PASS | A10, A12 |
| S11 | refs check passes | CLI/git transcript inspection | `sed -n '1,160p' .omo/ulw-loop/evidence/paper-post-r10-refs-check.txt` and no modified/add/delete/untracked status lines for `refs`, `@refs`, or `docs/nautilus_reference` | PASS | A11, A12 |

### adversarialCases

| scenario id | criterion reference | adversarial class | expected behavior | verdict | artifactRefs |
|---|---|---|---|---|---|
| A-S1 | artifact integrity | missing or empty evidence artifact | Any missing/empty required evidence file fails the rerun | PASS | A1 |
| A-S2 | callable-cache blocker | non-callable cache protocol member | RED transcript fails with `TypeError`; GREEN transcript passes at 100% with no failure markers | PASS | A2, A3, A12 |
| A-S3 | malformed timestamp blocker | invalid ISO timestamp payload | RED transcript fails with `ValueError`; GREEN and restore pytest transcripts pass at 100% with no failure markers | PASS | A4, A5, A6, A12 |
| A-S4 | regression coverage | focused/full suite regression | Focused and full pytest rerun transcripts reach `[100%]` with no `FAILED`, `ERROR`, or `Traceback` markers | PASS | A7, A8, A12 |
| A-S5 | protected reference drift | accidental refs/reference-doc edit | Refs check transcript shows missing `refs`/`@refs` are only informational and no diff/status output under protected reference paths | PASS | A11, A12 |

### artifactRefs

| id | kind | description | path |
|---|---|---|---|
| A1 | CLI transcript | Non-empty check for all requested evidence files | `.omo/evidence/paper-qa-rerun-12/file-check.txt` |
| A2 | pytest RED transcript | Callable-cache protocol blocker fails before fix | `.omo/ulw-loop/evidence/paper-r10-protocol-callable-red.txt` |
| A3 | pytest GREEN transcript | Callable-cache protocol blocker passes after fix | `.omo/ulw-loop/evidence/paper-r10-protocol-callable-green.txt` |
| A4 | pytest RED transcript | Malformed timestamp blocker fails before fix | `.omo/ulw-loop/evidence/paper-storage-timestamp-red.txt` |
| A5 | pytest GREEN transcript | Malformed timestamp blocker passes after fix | `.omo/ulw-loop/evidence/paper-storage-timestamp-green.txt` |
| A6 | pytest transcript | Storage restore regression passes | `.omo/ulw-loop/evidence/paper-storage-restore-pytest.txt` |
| A7 | pytest transcript | Focused post-r10 rerun passes | `.omo/ulw-loop/evidence/paper-post-r10-focused-rerun.txt` |
| A8 | pytest transcript | Full post-r10 pytest rerun passes | `.omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt` |
| A9 | rg transcript | Callable rg rerun output | `.omo/ulw-loop/evidence/paper-post-r10-rg-rerun.txt` |
| A10 | git transcript | `git diff --check` pass receipt | `.omo/ulw-loop/evidence/paper-post-r10-diff-check.txt` |
| A11 | git transcript | Protected refs/reference-doc check receipt | `.omo/ulw-loop/evidence/paper-post-r10-refs-check.txt` |
| A12 | CLI transcript | Pattern-based inspection receipt for all criteria | `.omo/evidence/paper-qa-rerun-12/inspection.txt` |

## Notes

The first local file-check attempt failed before validation because zsh reserves `$status`; the check was rerun with `rc` and passed. No product files were edited.
