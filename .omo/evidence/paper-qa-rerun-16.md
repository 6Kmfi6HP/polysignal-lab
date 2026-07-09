<verdict>PASS</verdict>
<confidence>HIGH</confidence>
<summary>Final hands-on QA rerun 16 passed the requested command-shaped surfaces for the Nautilus alignment refactor. Parser boundary tests, affected regression tests, git diff check, and refs guard all exited 0; the existing full-suite artifact was inspected and was fresh, non-empty, and showed pytest reaching 100%.</summary>

<scenario_coverage>
- parser-boundary: pytest CLI covering missing exit_mode, invalid exit_mode, missing market_slug, malformed timestamp skipping, and callable cache guard. Artifact: .omo/evidence/paper-qa-rerun-16/parser-boundary-pytest.txt
- focused-regression: pytest CLI covering paper calibration, cancelled markets, reporting cache source, Nautilus projections, scheduler settlement resolution, settlement, and storage restore. Artifact: .omo/evidence/paper-qa-rerun-16/focused-regression-pytest.txt
- full-suite-artifact-inspection: filesystem/CLI inspection of .omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt. Artifact: .omo/evidence/paper-qa-rerun-16/full-suite-artifact-inspection.txt
- git-diff-check: git diff --check. Artifact: .omo/evidence/paper-qa-rerun-16/git-diff-check.txt
- refs-guard: git status/diff against refs, @refs, and docs/nautilus_reference. Artifact: .omo/evidence/paper-qa-rerun-16/refs-guard.txt
- cleanup-confirmation: command-only QA cleanup receipt confirming no server/browser/tmux/container/port was spawned. Artifact: .omo/evidence/paper-qa-rerun-16/cleanup-confirmation.txt
</scenario_coverage>

<test_results>
- PASS parser-boundary: `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_storage_restore.py::test_sqlite_store_rejects_paper_trade_rows_missing_exit_mode tests/test_storage_restore.py::test_sqlite_store_rejects_paper_trade_rows_with_invalid_exit_mode tests/test_storage_restore.py::test_sqlite_store_rejects_paper_trade_rows_missing_market_slug tests/test_storage_restore.py::test_sqlite_store_skips_malformed_timestamp_paper_trade_rows tests/test_nautilus_reporting_cache_source.py` -> 12 passed, EXIT_CODE=0. Transcript: .omo/evidence/paper-qa-rerun-16/parser-boundary-pytest.txt
- PASS focused-regression: `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_paper_calibration.py tests/test_scheduler_cancelled_markets.py tests/test_nautilus_reporting_cache_source.py tests/test_nautilus_projections.py tests/test_scheduler_settlement_resolution.py tests/test_settlement.py tests/test_storage_restore.py` -> 60 passed with 2 upstream NautilusTrader/Pandas deprecation warnings, EXIT_CODE=0. Transcript: .omo/evidence/paper-qa-rerun-16/focused-regression-pytest.txt
- PASS full-suite-artifact-inspection: `.omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt` exists, size 1885 bytes, modified 2026-07-09 10:42:12 +0200, and shows pytest progress through `[100%]`. Transcript: .omo/evidence/paper-qa-rerun-16/full-suite-artifact-inspection.txt
- PASS git-diff-check: `git diff --check` -> EXIT_CODE=0. Transcript: .omo/evidence/paper-qa-rerun-16/git-diff-check.txt
- PASS refs-guard: `git status --short -- refs @refs docs/nautilus_reference` and `git diff --name-only -- refs @refs docs/nautilus_reference` -> no guarded path output, EXIT_CODE=0. Transcript: .omo/evidence/paper-qa-rerun-16/refs-guard.txt
- PASS cleanup-confirmation: no server/browser/tmux/container/port spawned by this QA; teardown required none, EXIT_CODE=0. Transcript: .omo/evidence/paper-qa-rerun-16/cleanup-confirmation.txt
</test_results>

<blocking_issues></blocking_issues>

## manualQa

### surfaceEvidence
| scenario id | criterion reference | surface | exact invocation | verdict | artifactRefs |
|---|---|---|---|---|---|
| parser-boundary | VERIFY 1 | pytest CLI | `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_storage_restore.py::test_sqlite_store_rejects_paper_trade_rows_missing_exit_mode tests/test_storage_restore.py::test_sqlite_store_rejects_paper_trade_rows_with_invalid_exit_mode tests/test_storage_restore.py::test_sqlite_store_rejects_paper_trade_rows_missing_market_slug tests/test_storage_restore.py::test_sqlite_store_skips_malformed_timestamp_paper_trade_rows tests/test_nautilus_reporting_cache_source.py` | PASS | A1 |
| focused-regression | VERIFY 2 | pytest CLI | `PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_paper_calibration.py tests/test_scheduler_cancelled_markets.py tests/test_nautilus_reporting_cache_source.py tests/test_nautilus_projections.py tests/test_scheduler_settlement_resolution.py tests/test_settlement.py tests/test_storage_restore.py` | PASS | A2 |
| full-suite-artifact-inspection | VERIFY 3 | filesystem/CLI | `ls -l .omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt && tail -n 80 .omo/ulw-loop/evidence/paper-post-r10-full-pytest-rerun.txt` plus bounded stat/head/grep metadata check | PASS | A3 |
| git-diff-check | VERIFY 4 | git CLI | `git diff --check` | PASS | A4 |
| refs-guard | VERIFY 4 | git CLI | `git status --short -- refs @refs docs/nautilus_reference` and `git diff --name-only -- refs @refs docs/nautilus_reference` | PASS | A5 |
| cleanup-confirmation | VERIFY 5 | CLI transcript | record no server/browser/tmux/container/port was spawned by this QA | PASS | A6 |

### adversarialCases
| scenario id | criterion reference | adversarial class | expected behavior | verdict | artifactRefs |
|---|---|---|---|---|---|
| missing-exit-mode | VERIFY 1 | parser boundary: missing required field | paper trade row is rejected fail-closed | PASS | A1 |
| invalid-exit-mode | VERIFY 1 | parser boundary: invalid enum/value | paper trade row is rejected fail-closed | PASS | A1 |
| missing-market-slug | VERIFY 1 | parser boundary: missing market identity | paper trade row is rejected fail-closed | PASS | A1 |
| malformed-timestamp | VERIFY 1 | parser boundary: malformed timestamp | malformed paper trade row is skipped without corrupt restore | PASS | A1 |
| callable-cache-guard | VERIFY 1, VERIFY 2 | cache source misuse: direct/non-callable guard | reporting cache path remains guarded by focused tests | PASS | A1, A2 |
| guarded-reference-paths | VERIFY 4 | forbidden reference/doc mutation | refs, @refs, and docs/nautilus_reference show no status or diff names | PASS | A5 |
| spawned-resource-leak | VERIFY 5 | QA environment contamination | no server/browser/tmux/container/port was spawned, so no teardown is required | PASS | A6 |

### artifactRefs
| id | kind | description | path |
|---|---|---|---|
| A1 | command transcript | Parser boundary focused pytest run; 12 passed, EXIT_CODE=0 | .omo/evidence/paper-qa-rerun-16/parser-boundary-pytest.txt |
| A2 | command transcript | Focused affected regression pytest run; 60 passed, EXIT_CODE=0 | .omo/evidence/paper-qa-rerun-16/focused-regression-pytest.txt |
| A3 | command transcript | Existing full-suite artifact inspection and metadata check | .omo/evidence/paper-qa-rerun-16/full-suite-artifact-inspection.txt |
| A4 | command transcript | git diff --check transcript; EXIT_CODE=0 | .omo/evidence/paper-qa-rerun-16/git-diff-check.txt |
| A5 | command transcript | refs/@refs/docs/nautilus_reference status and diff guard transcript | .omo/evidence/paper-qa-rerun-16/refs-guard.txt |
| A6 | command transcript | cleanup receipt confirming command-only QA and no spawned resources | .omo/evidence/paper-qa-rerun-16/cleanup-confirmation.txt |
</manualQa>

Report path: /home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-16.md
