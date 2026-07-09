# Manual QA Verdict

Verdict: PASS

Scope: final manual QA for current paper/reporting/storage refactor gate after huge-integer overflow fix. QA only; no production source or test files edited. Corrected protected subset used: `refs`, `@refs`, `docs/nautilus_reference`.

## manualQa

### surfaceEvidence

| scenario id | criterion reference | surface | exact invocation | verdict | artifactRefs |
|---|---|---|---|---|---|
| S1 | focused smoke pytest includes 61 tests | CLI pytest | `PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_paper_report_boundaries.py tests/test_storage_restore.py tests/test_nautilus_reporting_cache_source.py tests/test_reporting.py tests/test_strategy_stats.py -q` | PASS | A1 |
| S2 | required artifacts are non-empty | CLI file integrity | `for each required .omo/ulw-loop/evidence artifact, test -s and print byte count` | PASS | A3 |
| S3 | corrected protected subset unchanged | CLI git | `git status --short -- refs @refs docs/nautilus_reference`; `git diff --name-only -- refs @refs docs/nautilus_reference` | PASS | A4 |
| S4 | cleanup receipt | CLI cleanup receipt | `record QA-spawned runtime resources and teardown state` | PASS | A5 |

### adversarialCases

| scenario id | criterion reference | adversarial class | expected behavior | verdict | artifactRefs |
|---|---|---|---|---|---|
| A2.1 | huge-int helper fail-closed probe | hostile `10**4000` numeric payload | `wallet_float`, `report_float`, `trade_result_float`, `optional_float`, and `confidence_bucket` fail closed without overflow | PASS | A2 |
| A2.2 | daily report huge-int survival | huge int in trade result, confidence, execution depth, staleness | `PaperReportService.build_daily_report` returns a report with invalid huge values ignored and valid depth preserved | PASS | A2 |
| A2.3 | SQLite hostile persisted row | huge int in persisted `paper_trade_results.payload_json` | `SQLiteStore.query_json("paper_trade_results")` returns `[]` and does not leak overflow | PASS | A2 |

### artifactRefs

| id | kind | description | path |
|---|---|---|---|
| A1 | text | Focused pytest smoke; exit 0; observed 61 tests | `.omo/evidence/paper-final-current-qa-final-2/focused-smoke-pytest.txt` |
| A2 | text | Direct huge-int security probe; fail-closed helpers, report survival, hostile SQLite row returns `[]` | `.omo/evidence/paper-final-current-qa-final-2/security-probe.txt` |
| A3 | text | Required prior artifact integrity; all named artifacts non-empty | `.omo/evidence/paper-final-current-qa-final-2/required-artifacts.txt` |
| A4 | text | Protected subset git status and diff for `refs @refs docs/nautilus_reference` | `.omo/evidence/paper-final-current-qa-final-2/protected-subset.txt` |
| A5 | text | Cleanup receipt; no persistent server/browser/tmux/container/port spawned | `.omo/evidence/paper-final-current-qa-final-2/cleanup-receipt.txt` |
| A6 | markdown | This final manual QA verdict and matrix | `.omo/evidence/paper-final-current-qa-final-2/manual-qa-verdict.md` |

## Notes

- Focused smoke artifact records `observed_test_count: 61`, `required_test_count: 61`, and `exit_status: 0`.
- Security probe artifact records `SECURITY_PROBE_PASS` and `exit_status: 0`.
- Protected subset artifact records empty command output for both status and diff sections, with exit status 0.
