# Manual QA Verdict: PASS

Evidence directory: `.omo/evidence/paper-final-current-qa-final-3/`

## manualQa

### surfaceEvidence

| scenario id | criterion reference | surface | exact invocation | verdict | artifactRefs |
|---|---|---|---|---|---|
| S1 | VERIFY-1 focused smoke observes 62 tests | pytest CLI | `PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_paper_report_boundaries.py tests/test_storage_restore.py tests/test_nautilus_reporting_cache_source.py tests/test_reporting.py tests/test_strategy_stats.py -q` | PASS | A1 |
| S2 | VERIFY-2 direct huge-int/security probe | Python CLI | `PYTHONPATH=tests PYTHONDONTWRITEBYTECODE=1 uv run python - <<'PY' ...` | PASS | A2 |
| S3 | VERIFY-3 required current artifacts non-empty | shell filesystem check | `find .omo -type f -name "$name" -size +0c` for each required artifact | PASS | A3 |
| S4 | VERIFY-4 protected subset git status/diff | git CLI | `git status --short -- refs @refs docs/nautilus_reference`; `git diff --stat -- refs @refs docs/nautilus_reference`; `git diff --exit-code -- refs @refs docs/nautilus_reference` | PASS | A4 |
| S5 | VERIFY-5 cleanup receipt | shell/git CLI | `find . -path '*/__pycache__' -prune -o -name '*.pyc' -print | head -20`; `git status --short -- src tests refs @refs docs/nautilus_reference` | PASS | A5 |

### adversarialCases

| scenario id | criterion reference | adversarial class | expected behavior | verdict | artifactRefs |
|---|---|---|---|---|---|
| ADV1 | VERIFY-2 | huge Python integer passed to report numeric helpers | helpers fail closed as `0.0`, `None`, or `low`; no exception | PASS | A2 |
| ADV2 | VERIFY-2 | persisted `paper_trade_results.payload_json` with a 5000-digit JSON integer | `SQLiteStore.query_json("paper_trade_results")` returns `[]` rather than raising or fabricating a row | PASS | A2 |
| ADV3 | VERIFY-3 | missing/empty required evidence artifact | check would emit `FAIL`; actual run found every required artifact non-empty | PASS | A3 |
| ADV4 | VERIFY-4 | protected reference subset drift | `git diff --exit-code -- refs @refs docs/nautilus_reference` succeeds with no tracked diff | PASS | A4 |

### artifactRefs

| id | kind | description | path |
|---|---|---|---|
| A1 | command transcript | Focused smoke pytest output showing 62 passed tests | `.omo/evidence/paper-final-current-qa-final-3/focused-smoke-pytest.txt` |
| A2 | command transcript | Direct huge-int helper and 5000-digit JSON integer SQLite restore probe | `.omo/evidence/paper-final-current-qa-final-3/security-probe.txt` |
| A3 | command transcript | Required artifact non-empty check for all named current artifacts | `.omo/evidence/paper-final-current-qa-final-3/required-artifacts.txt` |
| A4 | command transcript | Protected subset status and diff check for `refs`, `@refs`, `docs/nautilus_reference` | `.omo/evidence/paper-final-current-qa-final-3/protected-subset.txt` |
| A5 | command transcript | Cleanup receipt and QA-created artifact listing | `.omo/evidence/paper-final-current-qa-final-3/cleanup-receipt.txt` |

## Notes

- The focused smoke transcript shows `62 passed`.
- Required artifacts were found non-empty under `.omo/ulw-loop/evidence/`.
- The checkout has existing dirty `src/` and `tests/` paths recorded in `cleanup-receipt.txt`; this QA run only created evidence files under `.omo/evidence/paper-final-current-qa-final-3/`.
