# Paper QA Rerun 6

QA execution date: 2026-07-09

Scope: `/home/debian/polysignal-lab`

Verdict: PASS

## Criteria

- C1: Focused settlement/cancelled/telegram/storage/repair tests pass under `uv run pytest`.
- C2: Same focused selection passes under system `python -m pytest`, proving imports work without relying on an installed system `nautilus_trader`.
- C3: Manual probes confirm settlement skips invalid projections without storing results and malformed `paper_trade_results.payload_json` returns `[]`.
- C4: Protected `refs` and `docs/nautilus_reference` were not modified by this QA run.

## manualQa

### surfaceEvidence

| scenario id | criterion reference | surface | exact invocation | verdict | artifactRefs |
|---|---|---|---|---|---|
| S1 | C1 | Python test suite via uv-managed environment | `uv run pytest -q tests/test_scheduler_settlement_resolution.py tests/test_scheduler_cancelled_markets.py tests/test_settlement.py tests/test_telegram_bot_service.py tests/test_repair_settlement_results.py tests/test_storage_restore.py -k 'settlement or cancelled or telegram_bot_positions_skips_rows_without_side or paper_trade_rows or malformed_payload or invalid_position or incomplete_open_position or open_position_event or newer_invalid'` | PASS: 29 passed | A1 |
| S2 | C2 | Python test suite via system Python | `python -m pytest -q tests/test_scheduler_settlement_resolution.py tests/test_scheduler_cancelled_markets.py tests/test_settlement.py tests/test_telegram_bot_service.py tests/test_repair_settlement_results.py tests/test_storage_restore.py -k 'settlement or cancelled or telegram_bot_positions_skips_rows_without_side or paper_trade_rows or malformed_payload or invalid_position or incomplete_open_position or open_position_event or newer_invalid'` | PASS: 29 passed | A2 |
| S3 | C3 | Direct Python manual probes | `python - <<'PY' ... PY` from `/home/debian/polysignal-lab`, captured in `manual-probes.log` | PASS: all helper, live settlement, store-call-count, and malformed payload probes passed | A3 |
| S4 | C4 | Protected refs/docs inspection | `git status --short -- refs docs/nautilus_reference`; `test ! -e refs && find docs/nautilus_reference -type f -printf '%p %s bytes\n' | sort | head -20` | PASS: no git status output for protected paths; `refs` absent; docs reference files listed read-only | A4 |
| S5 | C1-C4 | Evidence non-empty check | `wc -c .omo/evidence/paper-qa-rerun-6/{git-scope-check,manual-probes,protected-refs-check,pytest-system-python,pytest-uv}.log && sha256sum same files` | PASS: all PASS-supporting artifacts are non-empty | A5 |

### adversarialCases

| scenario id | criterion reference | adversarial class | expected behavior | verdict | artifactRefs |
|---|---|---|---|---|---|
| ACASE1 | C3 | Projection has missing/unresolvable side | `_paper_trade_result_from_projection` returns `None`; live settlement returns `[]`; `insert_paper_trade_result.call_count == 0` | PASS | A3 |
| ACASE2 | C3 | Projection has no opened timestamp | `_paper_trade_result_from_projection` returns `None`; live settlement returns `[]`; `insert_paper_trade_result.call_count == 0` | PASS | A3 |
| ACASE3 | C3 | Projection has invalid `opened_at` | `_paper_trade_result_from_projection` returns `None`; live settlement returns `[]`; `insert_paper_trade_result.call_count == 0` | PASS | A3 |
| ACASE4 | C3 | SQLite `paper_trade_results.payload_json` is malformed JSON | `SQLiteStore.query_json("paper_trade_results")` returns `[]` and does not raise | PASS | A3 |
| ACASE5 | C1 | Telegram position row lacks side | Focused pytest includes `telegram_bot_positions_skips_rows_without_side`; expected skipped row behavior remains green | PASS | A1, A2 |
| ACASE6 | C1, C2 | Invalid/incomplete paper trade result rows and newer invalid rows | Focused pytest selection keeps invalid rows skipped and repair/storage behavior green | PASS | A1, A2 |

### artifactRefs

| id | kind | description | path |
|---|---|---|---|
| A1 | command transcript | `uv run pytest` focused QA rerun; 29 passed with two deprecation warnings from vendored Nautilus parquet code | `.omo/evidence/paper-qa-rerun-6/pytest-uv.log` |
| A2 | command transcript | `python -m pytest` focused QA rerun; 29 passed | `.omo/evidence/paper-qa-rerun-6/pytest-system-python.log` |
| A3 | command transcript | Manual probes for helper skips, live settlement store call counts, and malformed storage payload | `.omo/evidence/paper-qa-rerun-6/manual-probes.log` |
| A4 | command transcript | Protected refs/docs status and reference-doc listing | `.omo/evidence/paper-qa-rerun-6/protected-refs-check.log` |
| A5 | command transcript | Artifact size and SHA-256 receipt for non-empty evidence files | `.omo/evidence/paper-qa-rerun-6/artifact-sizes.log` |
| A6 | command transcript | QA evidence scope check showing only rerun-6 evidence directory in current QA scope before report creation | `.omo/evidence/paper-qa-rerun-6/git-scope-check.log` |

<verdict>PASS</verdict>
