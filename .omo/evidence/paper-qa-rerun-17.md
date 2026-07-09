<verdict>PASS</verdict>
<confidence>HIGH</confidence>
<summary>Final hands-on QA rerun 17 passed for the current Nautilus alignment refactor after zero-money and no-object fixes. Required focused tests, broader paper/storage regression tests, git diff whitespace check, protected refs guard, and a fresh full pytest rerun all exited 0; the prior full-suite artifact was non-empty but lacked an explicit pass summary, so it was not used as sole proof.</summary>
<scenario_coverage>
- C1 focused zero-money/no-object restore + reporting tests: PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_storage_restore.py::test_sqlite_store_rejects_zero_money_paper_trade_rows tests/test_storage_restore.py::test_sqlite_store_excludes_open_position_events_with_zero_money tests/test_storage_restore.py::test_sqlite_store_rejects_paper_trade_rows_with_invalid_exit_mode tests/test_storage_restore.py::test_sqlite_store_rejects_paper_trade_rows_missing_market_slug tests/test_nautilus_reporting_cache_source.py
- C2 broader regression tests: PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_storage_restore.py tests/test_settlement.py tests/test_nautilus_reporting_cache_source.py tests/test_nautilus_projections.py tests/test_scheduler_settlement_resolution.py tests/test_paper_calibration.py tests/test_scheduler_cancelled_markets.py
- C3 whitespace integrity: git diff --check
- C4 protected refs guard: git status --short -- refs @refs docs/nautilus_reference ; git diff --name-only -- refs @refs docs/nautilus_reference
- C5 prior full-suite artifact check: test -s .omo/ulw-loop/evidence/paper-zero-money-full-pytest.txt && tail -n 40 .omo/ulw-loop/evidence/paper-zero-money-full-pytest.txt
- C6 fresh full-suite rerun due ambiguous C5 artifact: PYTHONDONTWRITEBYTECODE=1 uv run pytest -q
</scenario_coverage>
<test_results>
PASS C1 focused tests: .omo/evidence/paper-qa-rerun-17/focused-pytest.txt (12 passed by pytest progress, exit_code: 0, verdict: PASS)
PASS C2 broader regression tests: .omo/evidence/paper-qa-rerun-17/regression-pytest.txt (62 passed by pytest progress, exit_code: 0, verdict: PASS; 2 NautilusTrader dependency deprecation warnings)
PASS C3 git diff --check: .omo/evidence/paper-qa-rerun-17/git-diff-check.txt (exit_code: 0, verdict: PASS)
PASS C4 protected refs guard: .omo/evidence/paper-qa-rerun-17/protected-refs-guard.txt (empty protected status/diff sections, exit_code: 0, verdict: PASS)
INFO C5 existing full-suite artifact check: .omo/evidence/paper-qa-rerun-17/full-suite-artifact-check.txt (artifact non-empty and reached [100%], but no explicit pass/exit/verdict line; not counted as sufficient proof)
PASS C6 fresh full-suite rerun: .omo/evidence/paper-qa-rerun-17/full-suite-rerun.txt (exit_code: 0, verdict: PASS; 2 NautilusTrader dependency deprecation warnings)
</test_results>
<blocking_issues></blocking_issues>

<manualQa>
  <surfaceEvidence>
    <row scenarioId="C1" criterionRef="focused zero-money/no-object restore and reporting tests" surface="CLI pytest" invocation="PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_storage_restore.py::test_sqlite_store_rejects_zero_money_paper_trade_rows tests/test_storage_restore.py::test_sqlite_store_excludes_open_position_events_with_zero_money tests/test_storage_restore.py::test_sqlite_store_rejects_paper_trade_rows_with_invalid_exit_mode tests/test_storage_restore.py::test_sqlite_store_rejects_paper_trade_rows_missing_market_slug tests/test_nautilus_reporting_cache_source.py" verdict="PASS" artifactRefs="A1" />
    <row scenarioId="C2" criterionRef="broader paper/storage regression coverage" surface="CLI pytest" invocation="PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_storage_restore.py tests/test_settlement.py tests/test_nautilus_reporting_cache_source.py tests/test_nautilus_projections.py tests/test_scheduler_settlement_resolution.py tests/test_paper_calibration.py tests/test_scheduler_cancelled_markets.py" verdict="PASS" artifactRefs="A2" />
    <row scenarioId="C3" criterionRef="diff whitespace integrity" surface="CLI git" invocation="git diff --check" verdict="PASS" artifactRefs="A3" />
    <row scenarioId="C4" criterionRef="protected refs/docs guard" surface="CLI git" invocation="git status --short -- refs @refs docs/nautilus_reference ; git diff --name-only -- refs @refs docs/nautilus_reference" verdict="PASS" artifactRefs="A4" />
    <row scenarioId="C6" criterionRef="fresh full-suite proof after ambiguous prior artifact" surface="CLI pytest" invocation="PYTHONDONTWRITEBYTECODE=1 uv run pytest -q" verdict="PASS" artifactRefs="A6" />
  </surfaceEvidence>
  <adversarialCases>
    <row scenarioId="A-C1" criterionRef="zero money paper trade rows" adversarialClass="zero-money persisted trade rows" expectedBehavior="SQLite restore rejects zero-money paper trade rows" verdict="PASS" artifactRefs="A1" />
    <row scenarioId="A-C1b" criterionRef="zero money open position events" adversarialClass="zero-money open-position event rows" expectedBehavior="SQLite restore excludes open-position events with zero money" verdict="PASS" artifactRefs="A1" />
    <row scenarioId="A-C1c" criterionRef="invalid paper trade shape" adversarialClass="invalid exit_mode and missing market_slug" expectedBehavior="SQLite restore rejects malformed paper trade rows" verdict="PASS" artifactRefs="A1" />
    <row scenarioId="A-C4" criterionRef="protected refs/docs guard" adversarialClass="accidental protected reference mutation" expectedBehavior="No status or diff output for refs, @refs, docs/nautilus_reference" verdict="PASS" artifactRefs="A4" />
    <row scenarioId="A-C5" criterionRef="trust-nothing prior artifact handling" adversarialClass="ambiguous previous evidence" expectedBehavior="Do not rely on a non-empty artifact without explicit pass metadata; collect fresh full-suite proof" verdict="PASS" artifactRefs="A5,A6" />
  </adversarialCases>
  <artifactRefs>
    <artifact id="A1" kind="transcript" description="Focused zero-money/no-object pytest run" path="/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-17/focused-pytest.txt" />
    <artifact id="A2" kind="transcript" description="Broader paper/storage regression pytest run" path="/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-17/regression-pytest.txt" />
    <artifact id="A3" kind="transcript" description="git diff --check run" path="/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-17/git-diff-check.txt" />
    <artifact id="A4" kind="transcript" description="Protected refs/docs guard status and diff run" path="/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-17/protected-refs-guard.txt" />
    <artifact id="A5" kind="transcript" description="Prior full-suite artifact verification attempt" path="/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-17/full-suite-artifact-check.txt" />
    <artifact id="A6" kind="transcript" description="Fresh full pytest rerun" path="/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-17/full-suite-rerun.txt" />
    <artifact id="A7" kind="notepad" description="Ultrawork notepad path pointer" path="/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-17/notepad-path.txt" />
  </artifactRefs>
</manualQa>
