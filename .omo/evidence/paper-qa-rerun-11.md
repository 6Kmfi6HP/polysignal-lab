# Paper QA Rerun 11

Verdict: PASS

Scope: `/home/debian/polysignal-lab`

Surface: CLI/data evidence review.

Exact invocation:

```bash
for f in .omo/ulw-loop/evidence/paper-r10-protocol-callable-red.txt .omo/ulw-loop/evidence/paper-r10-protocol-callable-green.txt .omo/ulw-loop/evidence/paper-r10-reporting-cache-pytest.txt .omo/ulw-loop/evidence/paper-post-r10-focused-rerun.txt .omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt .omo/ulw-loop/evidence/paper-post-r10-rg-rerun.txt .omo/ulw-loop/evidence/paper-post-r10-diff-check.txt .omo/ulw-loop/evidence/paper-post-r10-refs-check.txt; do test -s "$f" && printf '%s\n' "--- $f ---" && sed -n '1,220p' "$f"; done
```

Binary observable: all required artifacts are non-empty and their contents support every requested criterion.

## manualQa

### surfaceEvidence

| scenario id | criterion reference | surface | exact invocation | verdict | artifactRefs |
|---|---|---|---|---|---|
| SC-01 | callable-boundary red exists | CLI/data evidence | `sed -n '1,220p' .omo/ulw-loop/evidence/paper-r10-protocol-callable-red.txt` | PASS: failing proof exists for `test_report_equity_inputs_requires_reporting_cache_protocol`; failure is `TypeError: 'int' object is not callable` at the protocol boundary before the fix. | A1 |
| SC-02 | callable-boundary green exists | CLI/data evidence | `sed -n '1,220p' .omo/ulw-loop/evidence/paper-r10-protocol-callable-green.txt` | PASS: same callable-boundary test passed after fix, shown as `. [100%]`. | A2 |
| SC-03 | reporting cache tests passed | CLI/data evidence | `sed -n '1,220p' .omo/ulw-loop/evidence/paper-r10-reporting-cache-pytest.txt` | PASS: reporting cache test slice passed, shown as `........ [100%]`. | A3 |
| SC-04 | focused regressions passed | CLI/data evidence | `sed -n '1,220p' .omo/ulw-loop/evidence/paper-post-r10-focused-rerun.txt` | PASS: focused rerun passed, shown as `56 passed` via dots and `[100%]`; warnings only. | A4 |
| SC-05 | full regressions passed | CLI/data evidence | `sed -n '1,220p' .omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt` | PASS: full pytest rerun reached `[100%]`; warnings only. | A5 |
| SC-06 | direct R10 rg evidence remains | CLI/data evidence | `sed -n '1,220p' .omo/ulw-loop/evidence/paper-post-r10-rg-rerun.txt` | PASS: direct callable sites remain at `scheduler_reporting.py:305` and `scheduler_reporting.py:324`. | A6 |
| SC-07 | diff check passed | CLI/data evidence | `sed -n '1,220p' .omo/ulw-loop/evidence/paper-post-r10-diff-check.txt` | PASS: `git diff --check` recorded `RESULT: PASS (no whitespace errors)`. | A7 |
| SC-08 | refs check passed | CLI/data evidence | `sed -n '1,220p' .omo/ulw-loop/evidence/paper-post-r10-refs-check.txt` | PASS: protected `refs` and `@refs` paths are missing as acceptable, and no `docs/nautilus_reference` diff output appears. | A8 |

### adversarialCases

| scenario id | criterion reference | adversarial class | expected behavior | verdict | artifactRefs |
|---|---|---|---|---|---|
| AC-01 | callable-boundary red/green | malformed protocol object: non-callable `account` or `positions` | Pre-fix evidence must fail at callable boundary; post-fix evidence must pass the protocol guard test. | PASS | A1, A2 |
| AC-02 | evidence integrity | missing or empty required artifact | QA must fail if any required evidence file is absent or empty. | PASS: `test -s` inventory succeeded for all eight files. | A9 |
| AC-03 | regression coverage | focused/full tests hide warnings or partial completion | QA must require `[100%]` completion for focused and full reruns; warnings alone do not fail. | PASS | A4, A5 |
| AC-04 | protected reference paths | accidental edits under `refs`, `@refs`, or `docs/nautilus_reference` | QA must fail if protected reference paths show modifications. | PASS | A8 |

### artifactRefs

| id | kind | description | path |
|---|---|---|---|
| A1 | text | Callable protocol-boundary RED pytest output. | `.omo/ulw-loop/evidence/paper-r10-protocol-callable-red.txt` |
| A2 | text | Callable protocol-boundary GREEN pytest output. | `.omo/ulw-loop/evidence/paper-r10-protocol-callable-green.txt` |
| A3 | text | Reporting cache pytest output. | `.omo/ulw-loop/evidence/paper-r10-reporting-cache-pytest.txt` |
| A4 | text | Focused regression rerun output. | `.omo/ulw-loop/evidence/paper-post-r10-focused-rerun.txt` |
| A5 | text | Full pytest rerun output. | `.omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt` |
| A6 | text | Direct R10 `rg` evidence output. | `.omo/ulw-loop/evidence/paper-post-r10-rg-rerun.txt` |
| A7 | text | `git diff --check` output. | `.omo/ulw-loop/evidence/paper-post-r10-diff-check.txt` |
| A8 | text | Protected refs check output. | `.omo/ulw-loop/evidence/paper-post-r10-refs-check.txt` |
| A9 | terminal output | Inventory command observed all eight required evidence files as non-empty: 2182, 80, 80, 1195, 1885, 182, 62, and 196 bytes. | `.omo/evidence/paper-qa-rerun-11.md` |

Cleanup receipt: no runtime processes, tmux sessions, browser contexts, containers, ports, or temp runtime resources were spawned for this verifier-only CLI/data review.
