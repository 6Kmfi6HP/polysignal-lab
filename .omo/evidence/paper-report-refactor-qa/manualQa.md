# Manual QA Matrix — paper-report refactor evidence

Verdict: PASS

## surfaceEvidence
| scenario id | criterion reference | surface | exact invocation | verdict | artifactRefs |
|---|---|---|---|---|---|
| S1 | artifact integrity | filesystem evidence artifacts | `test -s <each required artifact>; wc -c <artifacts>; ls -l <artifacts>` | PASS | A1 |
| S2 | reporting/storage/settlement coverage | source + evidence text inspection | `sed -n selected line ranges from tests/test_reporting.py tests/test_paper_calibration.py tests/test_scheduler_cancelled_markets.py tests/test_telegram_bot_config.py src/polysignal_lab/app/scheduler_reporting_build.py src/polysignal_lab/app/scheduler_reporting_storage.py; tail requested artifacts` | PASS | A2 |
| S3 | live focused regression | pytest CLI | `.venv/bin/python -m pytest tests/test_reporting.py tests/test_paper_calibration.py tests/test_scheduler_cancelled_markets.py tests/test_telegram_bot_config.py::test_persistence_service_restores_daily_reports_and_latest_event -q` | PASS | A3 |
| S4 | dirty worktree preservation | git CLI | `git status --short` | PASS | A4 |

## adversarialCases
| scenario id | criterion reference | adversarial class | expected behavior | verdict | artifactRefs |
|---|---|---|---|---|---|
| ACSV1 | artifact integrity | missing or empty requested artifact | Any missing/zero-byte required artifact fails QA | PASS | A1 |
| ACSV2 | real-surface coverage | tests are green but unrelated to reporting/storage/settlement | Evidence must show report metrics/message tests, persistence restore/insert tests, and settlement/cancelled-market storage tests | PASS | A2, A3 |
| ACSV3 | failure hidden in logs | artifact contains failed pytest/type/check output | Requested artifacts must show pytest 100%, compileall/diff/refs/no-excuse PASS, and basedpyright 0 errors | PASS | A2, A5 |
| ACSV4 | protected refs/docs contamination | refactor evidence edits protected `refs` or `docs/nautilus_reference` | Protected refs/docs check must pass | PASS | A2 |
| ACSV5 | long command without WORKING marker | live rerun lacks explicit WORKING marker | Focused live pytest artifact must include `WORKING:` before pytest output | PASS | A3 |

## artifactRefs
| id | kind | description | path |
|---|---|---|---|
| A1 | transcript | Required artifact existence, byte counts, and listing | `.omo/evidence/paper-report-refactor-qa/artifact-integrity.txt` |
| A2 | transcript | Source/evidence excerpts proving reporting/storage/settlement coverage and requested artifact pass markers | `.omo/evidence/paper-report-refactor-qa/surface-coverage.txt` |
| A3 | transcript | Live focused pytest rerun with WORKING marker and exit_status=0 | `.omo/evidence/paper-report-refactor-qa/focused-pytest.txt` |
| A4 | transcript | Dirty worktree status captured before QA; production code not edited by QA | `.omo/evidence/paper-report-refactor-qa/git-status.txt` |
| A5 | transcript | Success/failure marker scan over requested artifacts | `.omo/evidence/paper-report-refactor-qa/failure-success-markers.txt` |
| A6 | transcript | Heads/tails of inspected requested artifacts | `.omo/evidence/paper-report-refactor-qa/artifact-heads.txt`, `.omo/evidence/paper-report-refactor-qa/artifact-tails-summary.txt` |

## inspected requested artifacts
- `.omo/ulw-loop/evidence/paper-report-focused-regression.txt`: non-empty, pytest dot output reaches `[100%]`.
- `.omo/ulw-loop/evidence/paper-report-full-pytest.txt`: non-empty, full pytest dot output reaches `[100%]`.
- `.omo/ulw-loop/evidence/paper-report-broad-no-excuse.txt`: non-empty, `no violations in 13 file(s)`.
- `.omo/ulw-loop/evidence/paper-report-broad-basedpyright.txt`: non-empty, `0 errors, 436 warnings, 0 notes`.
- `.omo/ulw-loop/evidence/paper-report-diff-check.txt`: non-empty, `PASS git diff --check`.
- `.omo/ulw-loop/evidence/paper-report-refs-check.txt`: non-empty, `PASS no protected refs/docs/nautilus_reference changes`.
- `.omo/ulw-loop/evidence/paper-report-compileall.txt`: non-empty, `PASS compileall src tests`.
- `.omo/ulw-loop/evidence/paper-report-loc-after.txt`: non-empty, reports `paper/report.py 217` and `paper/report_helpers.py 140`.

## blockers
None.

## notes
- The basedpyright artifact is not clean: it reports 436 warnings, but 0 errors. I did not treat existing warnings as a blocker because the requested evidence gate is about non-empty artifacts plus real CLI/test surface coverage.
- I did not edit production code, commit, or touch protected `refs`/`docs` paths.
