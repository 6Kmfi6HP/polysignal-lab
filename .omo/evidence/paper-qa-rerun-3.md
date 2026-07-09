# Paper QA Rerun 3

<verdict>PASS</verdict>

Scope: `/home/debian/polysignal-lab`

Blocking issues: none. I did not edit source/tests, `refs`/`@refs`, `docs/nautilus_reference`, or commit. The system `pytest` used Python 3.11 and lacked `nautilus_trader`; the project `.venv/bin/python` uses Python 3.14 and has the locked dependency, so all executable checks below were rerun through `.venv/bin/python -m pytest` or `.venv/bin/python`.

## Terminal Evidence

### C1/C4: persisted malformed/incomplete `paper_trade_results` excluded; SQLite timestamp guard excludes incomplete OPEN rows

Surface: targeted pytest data/storage surface.

Exact invocation:

```bash
.venv/bin/python -m pytest \
  tests/test_storage_restore.py::test_sqlite_store_rejects_invalid_paper_trade_rows \
  tests/test_storage_restore.py::test_sqlite_store_rejects_incomplete_paper_trade_rows \
  tests/test_storage_restore.py::test_sqlite_store_excludes_open_position_events_without_timestamp \
  tests/test_repair_settlement_results.py::test_settle_for_repair_returns_parseable_trade_result_row \
  tests/test_repair_settlement_results.py::test_settle_for_repair_rejects_incomplete_position_money_fields \
  tests/test_repair_settlement_results.py::test_settle_for_repair_uses_event_timestamp_when_opened_at_missing \
  -q -rA
```

PASS lines:

```text
......                                                                   [100%]
==================================== PASSES ====================================
=========================== short test summary info ============================
PASSED tests/test_storage_restore.py::test_sqlite_store_rejects_invalid_paper_trade_rows
PASSED tests/test_storage_restore.py::test_sqlite_store_rejects_incomplete_paper_trade_rows
PASSED tests/test_storage_restore.py::test_sqlite_store_excludes_open_position_events_without_timestamp
PASSED tests/test_repair_settlement_results.py::test_settle_for_repair_returns_parseable_trade_result_row
PASSED tests/test_repair_settlement_results.py::test_settle_for_repair_rejects_incomplete_position_money_fields
PASSED tests/test_repair_settlement_results.py::test_settle_for_repair_uses_event_timestamp_when_opened_at_missing
```

### C2: manual blocker artifact inspected for repair parseability and fail-closed markers

Surface: CLI artifact inspection.

Exact invocation:

```bash
printf 'existing artifact: .omo/ulw-loop/evidence/paper-blockers-manual-qa.txt\n'
sed -n '1,120p' .omo/ulw-loop/evidence/paper-blockers-manual-qa.txt
```

PASS lines:

```text
existing artifact: .omo/ulw-loop/evidence/paper-blockers-manual-qa.txt
repair_parse=pass pt_20260709020540836794_550ad696 WIN
repair_incomplete_position=pass
cache_guard=pass (1000.0, 1000.0, 0)
split_report=pass 1 2.0
malformed_persisted_rows=pass
dashboard_incomplete_positions=pass
storage_missing_timestamp=pass
```

### C3: dashboard `/api/positions` excludes incomplete OPEN `nautilus_position`

Surface: targeted pytest plus real ASGI/httpx API call.

Exact invocation:

```bash
.venv/bin/python -m pytest tests/test_dashboard.py::test_dashboard_excludes_incomplete_open_position_rows -q -rA
.venv/bin/python - <<'PY'
from __future__ import annotations
import asyncio
import httpx
from polysignal_lab.dashboard.app import create_dashboard_app
from polysignal_lab.domain.enums import PositionStatus
from polysignal_lab.storage.sqlite_store import SQLiteStore

async def main() -> None:
    store = SQLiteStore(':memory:')
    event_time = '2026-06-26T00:00:00+00:00'
    store.insert_system_event({
        'event_id': 'evt-position-incomplete-asgi',
        'event_type': 'nautilus_position',
        'severity': 'info',
        'created_at': event_time,
        'paper_position_id': 'pos-incomplete-asgi',
        'market_id': 'market-incomplete',
        'token_id': 'token-incomplete',
        'status': PositionStatus.OPEN.value,
        'is_closed': False,
        'ts': event_time,
    })
    transport = httpx.ASGITransport(app=create_dashboard_app(store))
    async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
        response = await client.get('/api/positions')
    body = response.json()
    restored = store.restore_open_positions()
    print(f'status_code={response.status_code}')
    print(f'body={body}')
    print(f'restored_open_positions={restored}')
    assert response.status_code == 200
    assert body == []
    assert restored == []
    print('dashboard_asgi_incomplete_open_position=pass')

asyncio.run(main())
PY
```

PASS lines:

```text
.                                                                        [100%]
==================================== PASSES ====================================
=========================== short test summary info ============================
PASSED tests/test_dashboard.py::test_dashboard_excludes_incomplete_open_position_rows
status_code=200
body=[]
restored_open_positions=[]
dashboard_asgi_incomplete_open_position=pass
```

## Scenario Coverage

| Criterion | Verdict | Evidence |
| --- | --- | --- |
| Persisted malformed `paper_trade_results` are excluded. | PASS | `test_sqlite_store_rejects_invalid_paper_trade_rows`; manual marker `malformed_persisted_rows=pass`. |
| Persisted incomplete `paper_trade_results` are excluded. | PASS | `test_sqlite_store_rejects_incomplete_paper_trade_rows`. |
| Repair settlement rows are parseable. | PASS | `test_settle_for_repair_returns_parseable_trade_result_row`; manual marker `repair_parse=pass ... WIN`. |
| Repair incomplete positions fail closed. | PASS | `test_settle_for_repair_rejects_incomplete_position_money_fields`; manual marker `repair_incomplete_position=pass`. |
| Dashboard `/api/positions` excludes incomplete OPEN `nautilus_position` rows. | PASS | `test_dashboard_excludes_incomplete_open_position_rows`; ASGI/httpx `status_code=200`, `body=[]`. |
| SQLite `restore_open_positions` excludes OPEN row with money fields but missing `opened_at`/`ts`/`created_at` in payload. | PASS | `test_sqlite_store_excludes_open_position_events_without_timestamp`; manual marker `storage_missing_timestamp=pass`. |

## manualQa

### surfaceEvidence

| scenarioId | criterionRef | surface | exactInvocation | verdict | artifactRefs |
| --- | --- | --- | --- | --- | --- |
| S1 | C1,C2,C4 | CLI pytest/data surface | `.venv/bin/python -m pytest tests/test_storage_restore.py::test_sqlite_store_rejects_invalid_paper_trade_rows tests/test_storage_restore.py::test_sqlite_store_rejects_incomplete_paper_trade_rows tests/test_storage_restore.py::test_sqlite_store_excludes_open_position_events_without_timestamp tests/test_repair_settlement_results.py::test_settle_for_repair_returns_parseable_trade_result_row tests/test_repair_settlement_results.py::test_settle_for_repair_rejects_incomplete_position_money_fields tests/test_repair_settlement_results.py::test_settle_for_repair_uses_event_timestamp_when_opened_at_missing -q -rA` | PASS | A1 |
| S2 | C2 | CLI artifact inspection | `sed -n '1,120p' .omo/ulw-loop/evidence/paper-blockers-manual-qa.txt` | PASS | A1,A2 |
| S3 | C3 | ASGI/httpx API call | `.venv/bin/python - <<'PY' ... response = await client.get('/api/positions') ... PY` | PASS | A1 |

### adversarialCases

| scenarioId | criterionRef | adversarialClass | expectedBehavior | verdict | artifactRefs |
| --- | --- | --- | --- | --- | --- |
| A-S1 | C1 | Hostile malformed persisted trade-result row | Query/restore excludes malformed persisted `paper_trade_results`. | PASS | A1 |
| A-S2 | C1 | Incomplete persisted trade-result row | Query/restore excludes missing required trade-result fields. | PASS | A1 |
| A-S3 | C2 | Repair settlement output parseability | Repair result parses via `parse_paper_trade_result_row` and yields a concrete trade id/result. | PASS | A1,A2 |
| A-S4 | C2 | Repair position missing money fields | Repair settlement returns no result for un-settleable incomplete position. | PASS | A1,A2 |
| A-S5 | C3 | Incomplete OPEN dashboard position | `/api/positions` returns HTTP 200 with `[]`, excluding the incomplete row. | PASS | A1 |
| A-S6 | C4 | OPEN row has money fields but no timestamp in payload | `restore_open_positions()` and `restore_closed_positions()` both return `[]`. | PASS | A1,A2 |

### artifactRefs

| id | kind | description | path |
| --- | --- | --- | --- |
| A1 | report | This report embeds the exact terminal invocations and PASS output lines from the rerun. | `.omo/evidence/paper-qa-rerun-3.md` |
| A2 | existing-artifact | Existing manual blocker artifact inspected during this rerun; non-empty and contains required pass markers. | `.omo/ulw-loop/evidence/paper-blockers-manual-qa.txt` |

Cleanup receipt: no persistent temp evidence files were created; the only allowed workspace write is this report. The ultrawork notepad temp file `/tmp/ulw-20260709-041215.mmvb1s.md` was used during execution and is removed after report verification.
