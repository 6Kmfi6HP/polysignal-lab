# Paper QA Rerun 7

Verdict: PASS

Scope: current Nautilus paper/domain/storage refactor in `/home/debian/polysignal-lab`.

## manualQa

### surfaceEvidence

| scenario id | criterion reference | surface | exact invocation | verdict | artifactRefs |
|---|---|---|---|---|---|
| S1 | focused pytest selection | CLI pytest | `python -m pytest tests/test_paper_calibration.py tests/test_scheduler_cancelled_markets.py tests/test_nautilus_projections.py tests/test_scheduler_settlement_resolution.py tests/test_settlement.py tests/test_storage_restore.py` | PASS: 44 passed, exit 0 | A1 |
| S2 | system `python -m pytest` focused selection | System Python CLI pytest | `/usr/bin/python3 -m pytest tests/test_paper_calibration.py tests/test_scheduler_cancelled_markets.py tests/test_nautilus_projections.py tests/test_scheduler_settlement_resolution.py tests/test_settlement.py tests/test_storage_restore.py` | PASS: 44 passed, exit 0 | A2 |
| S3 | direct Python probes | Direct Python CLI probe | `python - <<'PY'` inline probe for settlement missing stake, malformed system/daily restore, latest health, idempotent existing malformed payload | PASS: all probe values matched expected output | A3 |
| S4 | protected refs/docs check | Git/filesystem CLI | `test -e refs; git status --short -- refs docs/nautilus_reference; git diff --name-status -- refs docs/nautilus_reference; find refs docs/nautilus_reference -maxdepth 2 -type f \| head -20` | PASS: no git status or diff under protected paths | A4 |
| S5 | evidence non-empty check | Filesystem CLI | `find .omo/evidence/paper-qa-rerun-7 -maxdepth 1 -type f -printf '%p %s\n'` plus `test -s` for report/log artifacts | PASS: every referenced artifact is non-empty | A5 |
| S6 | QA scope check | Git CLI | `git status --short -- .omo/evidence/paper-qa-rerun-7 .omo/evidence/paper-qa-rerun-7.md; git status --short -- src tests refs docs/nautilus_reference` | PASS: this rerun added only QA evidence; production/test dirtiness is baseline from A0 | A7 |

### adversarialCases

| scenario id | criterion reference | adversarial class | expected behavior | verdict | artifactRefs |
|---|---|---|---|---|---|
| A-1 | direct Python probes | Missing monetary stake in settlement projection | `_paper_trade_result_from_projection(...)` returns `None`; no inflated settlement result | PASS: `settlement_missing_stake=None` | A3 |
| A-2 | direct Python probes | Malformed `system_events.payload_json` in restore/query surface | `query_json("system_events")` skips malformed row and returns `[]` | PASS: `system_events_query=[]` | A3 |
| A-3 | direct Python probes | Malformed latest health event payload | `restore_latest_system_event("health")` returns `None` | PASS: `latest_health=None` | A3 |
| A-4 | direct Python probes | Malformed `daily_reports.payload_json` in restore surface | `restore_daily_reports()` skips malformed row and returns `[]` | PASS: `daily_reports=[]` | A3 |
| A-5 | direct Python probes | Idempotent insert collides with existing malformed payload | Raises typed `MalformedSQLitePayloadError`, not raw JSON error or silent success | PASS: `idempotent_existing_malformed=typed:MalformedSQLitePayloadError` | A3 |
| A-6 | protected refs/docs check | Protected reference/docs drift | No modifications under `refs` or `docs/nautilus_reference` | PASS: no protected path diff/status output | A4 |

### artifactRefs

| id | kind | description | path |
|---|---|---|---|
| A0 | command log | Repository baseline and comparison artifact listing for `.omo/ulw-loop/evidence/paper-post-security-fix-*.txt` | `/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-7/repo-state.log` |
| A1 | command log | Focused pytest rerun, 44 passing tests | `/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-7/pytest-focused.log` |
| A2 | command log | System Python focused pytest rerun, 44 passing tests | `/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-7/pytest-system-focused.log` |
| A3 | command log | Direct Python probe outputs for required storage/domain edge cases | `/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-7/direct-probes.log` |
| A4 | command log | Protected `refs` and `docs/nautilus_reference` status/diff check | `/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-7/protected-refs-docs.log` |
| A5 | command log | Evidence non-empty check for all referenced artifacts and this report | `/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-7/evidence-nonempty.log` |
| A6 | command log | Context search for probe locations and prior manual QA outputs | `/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-7/context-rg.log` |
| A7 | command log | Final git scope check showing QA evidence paths and baseline production/test dirtiness | `/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-7/final-scope-check.log` |

Notes:
- Existing comparison artifacts were present and non-empty under `.omo/ulw-loop/evidence/paper-post-security-fix-*.txt`.
- Baseline working tree already contained many unrelated modified/deleted/untracked files; this rerun only created QA evidence artifacts under `.omo/evidence/paper-qa-rerun-7/` and this report.
