# Paper Safety Manual QA Rerun 4

<verdict>FAIL</verdict>

Final verdict is FAIL because the storage and dashboard surfaces passed, but the targeted repair safety test did not run to the assertion: importing `scripts/repair_settlement_results.py` failed on missing `nautilus_trader`.

## manualQa

### surfaceEvidence

| scenario id | criterion reference | surface | exact invocation | verdict | artifactRefs |
|---|---|---|---|---|---|
| S1 | storage excludes OPEN rows missing timestamp, invalid opened_at, missing side, and newer malformed latest event blocks stale restore | SQLite restore tests | `set -o pipefail; pytest -q tests/test_storage_restore.py::test_sqlite_store_excludes_open_position_events_without_timestamp tests/test_storage_restore.py::test_sqlite_store_excludes_open_position_event_with_invalid_opened_at tests/test_storage_restore.py::test_sqlite_store_excludes_open_position_event_without_side tests/test_storage_restore.py::test_sqlite_store_newer_invalid_position_event_blocks_stale_restore \| tee /tmp/paper_qa_rerun_4_storage.log` | PASS | A1 |
| S2 | dashboard `/api/positions` excludes invalid opened_at, missing side, incomplete rows; derives side from market token for valid rows | Targeted dashboard pytest cases | `set -o pipefail; pytest -q tests/test_dashboard.py::test_dashboard_excludes_incomplete_open_position_rows tests/test_dashboard.py::test_dashboard_excludes_open_position_with_invalid_opened_at tests/test_dashboard.py::test_dashboard_excludes_open_position_without_resolvable_side tests/test_dashboard.py::test_dashboard_positions_normalize_nautilus_rows_with_market_lookup \| tee /tmp/paper_qa_rerun_4_dashboard.log` | PASS | A2 |
| S3 | dashboard `/api/positions` through ASGI/httpx with mixed invalid and valid persisted rows | ASGI/httpx probe | `set -o pipefail; python - <<'PY' ... PY \| tee /tmp/paper_qa_rerun_4_asgi.log` | PASS | A3 |
| S4 | repair does not fabricate side | Targeted repair pytest case | `set -o pipefail; pytest -q tests/test_repair_settlement_results.py::test_settle_for_repair_rejects_position_without_side \| tee /tmp/paper_qa_rerun_4_repair.log` | FAIL | A4 |
| S5 | temp file cleanup | OS shell cleanup | `wc -c /tmp/paper_qa_rerun_4_*.log; rm -f /tmp/paper_qa_rerun_4_*.log; for f in /tmp/paper_qa_rerun_4_*.log; do test ! -e "$f" && printf 'removed %s\n' "$f"; done` | PASS | A5 |

### adversarialCases

| scenario id | criterion reference | adversarial class | expected behavior | verdict | artifactRefs |
|---|---|---|---|---|---|
| A-S1 | storage excludes malformed OPEN rows | Missing timestamp | OPEN row with money fields but no payload timestamp is excluded from restore | PASS | A1 |
| A-S2 | storage excludes malformed OPEN rows | Invalid primary timestamp with valid fallback timestamps | `opened_at=not-a-date` blocks restore even when `ts` and `created_at` are valid | PASS | A1 |
| A-S3 | storage excludes malformed OPEN rows | Missing side | Otherwise settleable OPEN row with no side is excluded, not defaulted to UP/DOWN | PASS | A1 |
| A-S4 | latest malformed event blocks stale valid restore | Stale valid row shadowed by newer malformed same-position row | Latest malformed state wins selection and is filtered out | PASS | A1 |
| A-D1 | dashboard excludes malformed rows | Incomplete dashboard row | Missing money fields are excluded from `/api/positions` | PASS | A2, A3 |
| A-D2 | dashboard excludes malformed rows | Invalid opened_at | Invalid primary `opened_at` row is excluded from `/api/positions` | PASS | A2, A3 |
| A-D3 | dashboard excludes malformed rows | Missing/unresolvable side | Missing side without market-token resolution is excluded from `/api/positions` | PASS | A2, A3 |
| A-D4 | dashboard derives side for valid rows | Missing explicit side but resolvable market token | Valid row with `instrument_id=down-token.POLYMARKET` returns one OPEN row with `side=DOWN` | PASS | A2, A3 |
| A-R1 | repair does not fabricate side | Repair input missing side | Repair should return `None` instead of fabricating side | FAIL | A4 |

### artifactRefs

| id | kind | description | path |
|---|---|---|---|
| A1 | embedded command transcript | Storage pytest passed: `.... [100%]` for four targeted restore cases. | `/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-4.md` |
| A2 | embedded command transcript | Dashboard pytest passed: `.... [100%]` for incomplete row, invalid opened_at, missing side, and market-token side derivation cases. | `/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-4.md` |
| A3 | embedded ASGI/httpx transcript | `GET /api/positions status 200`, `row_count 1`, `paper_position_ids ['pos-valid-derived-side']`, surviving row had `side: DOWN`; probe printed `ASGI probe PASS`. | `/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-4.md` |
| A4 | embedded command transcript | Repair pytest failed before assertion with `ModuleNotFoundError: No module named 'nautilus_trader'` while importing `src/polysignal_lab/nautilus_runtime/custom_data_types.py:16`. | `/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-4.md` |
| A5 | cleanup receipt | Temp logs had non-zero sizes before cleanup: `4076`, `80`, `555`, `3601`, `751` bytes; shell printed removed lines for all five `/tmp/paper_qa_rerun_4_*.log` files. | `/home/debian/polysignal-lab/.omo/evidence/paper-qa-rerun-4.md` |

## command evidence

Storage:

```text
....                                                                     [100%]
```

Dashboard pytest:

```text
....                                                                     [100%]
=============================== warnings summary ===============================
../.local/lib/python3.11/site-packages/fastapi/testclient.py:1
  /home/debian/.local/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa
```

ASGI/httpx probe:

```text
GET /api/positions status 200
row_count 1
paper_position_ids ['pos-valid-derived-side']
surviving_row {'avg_entry_price': 0.6, 'created_at': '2026-06-26T00:00:00+00:00', 'event_id': 'evt-valid-derived-side', 'event_type': 'nautilus_position', 'instrument_id': 'down-token.POLYMARKET', 'is_closed': False, 'position_id': 'pos-valid-derived-side', 'quantity': 12.0, 'severity': 'info', 'status': 'OPEN', 'ts': '2026-06-26T00:00:00+00:00', 'paper_position_id': 'pos-valid-derived-side', 'asset': 'BTC', 'timeframe': '15m', 'market_id': 'market-valid', 'market_slug': 'btc-updown-15m', 'token_id': 'down-token', 'side': 'DOWN', 'entry_price': 0.6, 'shares': 12.0, 'stake_usdc': 7.199999999999999, 'opened_at': '2026-06-26T00:00:00+00:00'}
ASGI probe PASS
```

Repair:

```text
F                                                                        [100%]
E   ModuleNotFoundError: No module named 'nautilus_trader'
src/polysignal_lab/nautilus_runtime/custom_data_types.py:16: ModuleNotFoundError
=========================== short test summary info ============================
FAILED tests/test_repair_settlement_results.py::test_settle_for_repair_rejects_position_without_side
```

Cleanup:

```text
4076 /tmp/paper_qa_rerun_4_pytest.log
  80 /tmp/paper_qa_rerun_4_storage.log
 555 /tmp/paper_qa_rerun_4_dashboard.log
3601 /tmp/paper_qa_rerun_4_repair.log
 751 /tmp/paper_qa_rerun_4_asgi.log
9063 total
removed /tmp/paper_qa_rerun_4_pytest.log
removed /tmp/paper_qa_rerun_4_storage.log
removed /tmp/paper_qa_rerun_4_dashboard.log
removed /tmp/paper_qa_rerun_4_repair.log
removed /tmp/paper_qa_rerun_4_asgi.log
```

## blocking issues

- `tests/test_repair_settlement_results.py::test_settle_for_repair_rejects_position_without_side` cannot verify repair behavior in this environment because `scripts/repair_settlement_results.py` imports Nautilus runtime modules and fails on missing `nautilus_trader`.
- No product source, tests, refs, or Nautilus reference docs were edited.
