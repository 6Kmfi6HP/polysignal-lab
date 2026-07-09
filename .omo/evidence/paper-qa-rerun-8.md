# Paper QA Rerun 8

Verdict: PASS

Scope: zero-money paper QA rerun in `/home/debian/polysignal-lab`.

## manualQa

### surfaceEvidence

| scenario id | criterion reference | surface | exact invocation | verdict | artifactRefs |
|---|---|---|---|---|---|
| S1 | focused pytest selection | CLI pytest | `pytest tests/test_paper_calibration.py tests/test_scheduler_cancelled_markets.py tests/test_nautilus_projections.py tests/test_scheduler_settlement_resolution.py tests/test_settlement.py tests/test_storage_restore.py` | PASS: 48 passed, exit 0 | A1 |
| S2 | system `python -m pytest` same selection | System Python CLI pytest | `python -m pytest tests/test_paper_calibration.py tests/test_scheduler_cancelled_markets.py tests/test_nautilus_projections.py tests/test_scheduler_settlement_resolution.py tests/test_settlement.py tests/test_storage_restore.py` | PASS: `/usr/bin/python` Python 3.11.2 ran 48 passing tests, exit 0 | A2 |
| S3 | direct Python probes | Direct Python CLI probe | `PYTHONPATH=tests:. python - <<'PY'` inline probe for zero-money settlement, missing projected money, malformed restore, and typed malformed idempotent collision | PASS: all probe assertions passed | A3 |
| S4 | protected `refs`/`docs/nautilus_reference` check | Git/filesystem CLI | `test -e refs; git status --short -- refs docs/nautilus_reference; git diff --name-status -- refs docs/nautilus_reference; find refs docs/nautilus_reference -maxdepth 2 -type f \| head -20` | PASS: no git status or diff under protected paths; `refs` directory is absent in this checkout | A4 |
| S5 | evidence non-empty check | Filesystem CLI | `find .omo/evidence/paper-qa-rerun-8 -maxdepth 1 -type f -printf '%p %s\n'` plus `test -s` for report/log artifacts | PASS: every referenced artifact and report is non-empty | A5 |
| S6 | QA scope check | Git CLI | `git status --short -- .omo/evidence/paper-qa-rerun-8 .omo/evidence/paper-qa-rerun-8.md; git status --short -- src tests refs docs/nautilus_reference` | PASS: rerun created QA evidence only; production/test dirtiness is pre-existing baseline | A6 |

### adversarialCases

| scenario id | criterion reference | adversarial class | expected behavior | verdict | artifactRefs |
|---|---|---|---|---|---|
| A-1 | direct Python probes | Zero-money settlement projection | `_paper_trade_result_from_projection(...)` returns `None`, not a zero-stake result | PASS: `settlement_zero_money=None` | A3 |
| A-2 | direct Python probes | Missing Nautilus position money fields | `project_position(...)` preserves unknown monetary fields as `None` | PASS: `quantity`, `avg_entry_price`, and `stake_usdc` are `None` | A3 |
| A-3 | direct Python probes | Malformed `system_events.payload_json` query surface | `query_json("system_events")` skips malformed row and returns `[]` | PASS: `malformed_system_query=[]` | A3 |
| A-4 | direct Python probes | Malformed latest system event restore | `restore_latest_system_event("health")` returns `None` | PASS: `malformed_latest_health=None` | A3 |
| A-5 | direct Python probes | Malformed `daily_reports.payload_json` restore surface | `restore_daily_reports()` skips malformed row and returns `[]` | PASS: `malformed_daily_reports=[]` | A3 |
| A-6 | direct Python probes | Idempotent insert collides with existing malformed payload | Raises typed `MalformedSQLitePayloadError`, not raw JSON error or silent success | PASS: `idempotent_existing_malformed=typed:MalformedSQLitePayloadError` | A3 |
| A-7 | protected refs/docs check | Protected reference/docs drift | No modifications under `refs` or `docs/nautilus_reference` | PASS: no protected path diff/status output | A4 |

### artifactRefs

| id | kind | description | path |
|---|---|---|---|
| A1 | command log | Focused pytest selection, 48 passing tests | `/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-8/pytest-focused.log` |
| A2 | command log | System `python -m pytest` focused selection, 48 passing tests | `/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-8/pytest-system-focused.log` |
| A3 | command log | Direct Python probe outputs for zero-money and malformed restore cases | `/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-8/direct-probes.log` |
| A4 | command log | Protected `refs` and `docs/nautilus_reference` status/diff check | `/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-8/protected-refs-docs.log` |
| A5 | command log | Evidence non-empty check for all referenced artifacts and this report | `/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-8/evidence-nonempty.log` |
| A6 | command log | Final git scope check showing QA evidence paths and baseline production/test dirtiness | `/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-8/final-scope-check.log` |

Notes:
- Baseline working tree already contained many unrelated production/test modifications and deletions. This QA rerun did not edit production or test files.
- The protected `refs` directory does not exist in this checkout; `docs/nautilus_reference` exists and has no status or diff output.
