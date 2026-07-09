# Manual QA Verdict - paper-final-current-qa

Overall verdict: FAIL

Reason: protected `docs` path drift is present in the current working tree:

- `?? docs/architecture-nautilus-alignment.md`
- `?? docs/superpowers/plans/2026-07-09-architecture-boundary-cleanup.md`

## manualQa

### surfaceEvidence

| scenario id | criterion reference | surface | exact invocation | verdict | artifactRefs |
|---|---|---|---|---|---|
| C1 | Required evidence artifacts exist and are non-empty | CLI/data | `python - <<'PY' ... pathlib stat check for required .omo/ulw-loop/evidence files ... PY` | PASS | A1 |
| C2 | Focused paper/storage/reporting smoke | CLI/data | `PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_paper_report_boundaries.py tests/test_storage_restore.py tests/test_nautilus_reporting_cache_source.py tests/test_reporting.py tests/test_strategy_stats.py -q` | PASS | A2 |
| C3 | Protected refs/docs paths unchanged | CLI/data | `git status --short -- refs docs; git diff --stat -- refs docs` | FAIL | A3 |
| C4 | Cleanup receipt | CLI/data | `tmux ls; docker ps --format '{{.ID}} {{.Image}} {{.Names}}'; ss -ltnp` | PASS | A4 |

### adversarialCases

| scenario id | criterion reference | adversarial class | expected behavior | verdict | artifactRefs |
|---|---|---|---|---|---|
| ADV1 | Required evidence artifacts exist and are non-empty | Missing or empty required artifact | Gate fails if any required file is absent or zero bytes | PASS | A1 |
| ADV2 | Focused smoke | Regression in paper/reporting/storage tests | Gate fails on any non-zero pytest exit | PASS | A2 |
| ADV3 | Protected refs/docs paths unchanged | Protected-path drift, including untracked docs/refs files | Gate fails when `git status --short -- refs docs` reports drift | FAIL | A3 |
| ADV4 | Cleanup receipt | Leaked QA runtime resource | Gate fails if this QA spawned server/browser/tmux/container/port without cleanup | PASS | A4 |

### artifactRefs

| id | kind | description | path |
|---|---|---|---|
| A1 | CLI transcript | Required final-gate evidence artifact stat report; all ten required files were non-empty | `.omo/evidence/paper-final-current-qa/required-artifacts.txt` |
| A2 | CLI transcript | Focused pytest smoke transcript; 48 tests passed with exit_code=0 | `.omo/evidence/paper-final-current-qa/focused-smoke-pytest.txt` |
| A3 | CLI transcript | Protected refs/docs status and diff report; untracked docs files caused FAIL | `.omo/evidence/paper-final-current-qa/protected-paths.txt` |
| A4 | CLI transcript | Cleanup receipt; this QA spawned no server/browser/tmux/container/port and required no cleanup | `.omo/evidence/paper-final-current-qa/cleanup-receipt.txt` |
| A5 | Markdown verdict | This manual QA matrix and overall FAIL verdict | `.omo/evidence/paper-final-current-qa/manual-qa-verdict.md` |

## Cleanup Receipt

No server, browser, tmux session, container, or port was spawned by this QA pass. Existing system containers and listeners were observed but not created or modified by this run. Cleanup required: none.
