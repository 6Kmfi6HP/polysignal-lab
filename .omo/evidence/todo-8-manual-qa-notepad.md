# Todo 8 Manual QA Notepad

Date: 2026-06-22

Manual QA matrix:

| Adversarial class | Scenario | Invocation | Binary observable | Captured artifact path | Result |
|---|---|---|---|---|---|
| dirty_worktree | Preserve unrelated work before repair | `git status --short` | Dirty worktree observed with many unrelated tracked/untracked changes; no unrelated files reverted. | `.omo/evidence/task-8-complete-prd-old-remove-demo.txt` | PASS |
| stale_state | Trust no previous evidence without direct rerun | Read gate rejection, inspected current code, reran pytest/py_compile/rg probes | Current scheduler defects reproduced red-first and verified after fix. | `.omo/evidence/task-8-complete-prd-old-remove-demo.txt` | PASS |
| misleading_success_output | Concrete runtime paths, not only unit success | `.venv/bin/python -m pytest tests/test_scheduler_cancelled_markets.py -q` | Red-first: two failures; final: `.. [100%]`. | `.omo/evidence/task-8-complete-prd-old-remove-demo.txt` | PASS |
| malformed_input | Official malformed outcome remains retriable | `.venv/bin/python -m pytest tests/test_market_parsing.py tests/test_settlement.py -q` | `........ [100%]`; malformed outcome test remains covered. | `.omo/evidence/task-8-complete-prd-old-remove-demo.txt` | PASS |
| enum_contract | No PRD-facing `SPLIT` result state | `rg -n "SPLIT" src/polysignal_lab/domain src/polysignal_lab/paper src/polysignal_lab/data/market_snapshot.py` | exit 1 with no matches. | `.omo/evidence/task-8-complete-prd-old-remove-demo.txt` | PASS |
| settlement_safety | Cancelled markets close/refund, unknown resolved markets stay open | `.venv/bin/python -m pytest tests/test_scheduler_cancelled_markets.py tests/test_settlement.py::test_missing_resolved_outcome_stays_unknown_and_retriable -q` | Cancelled scheduler settlement emits VOID and closes position; unknown resolved outcome remains OPEN. | `.omo/evidence/task-8-complete-prd-old-remove-demo.txt` | PASS |
| scheduler_propagation | Cancelled Gamma payload reaches registry/storage | `.venv/bin/python -m pytest tests/test_scheduler_cancelled_markets.py::test_cancelled_gamma_refresh_reaches_registry_and_storage -q` | Registry has `MarketStatus.CANCELLED`; SQLite row has `"CANCELLED"`. | `.omo/evidence/task-8-complete-prd-old-remove-demo.txt` | PASS |
| programming_quality | Compile and strict escape-hatch scan for scoped Todo 8 files | `py_compile` and `rg -n "asyncio|\bAny\b|cast\(|type: ignore|import pandas|except Exception|dict\[str, (Any|object)\]" src/polysignal_lab/app/scheduler_market_data.py src/polysignal_lab/app/scheduler_reporting.py tests/test_scheduler_cancelled_markets.py` | `py_compile` exit 0; strict quality grep exit 1 with no matches, including no `asyncio` substring in `scheduler_market_data.py`. | `.omo/evidence/task-8-complete-prd-old-remove-demo.txt` | PASS |
| remove_ai_slops_overfit | Probes fail for real rejected paths and assert observable state | Red-first and final focused scheduler pytest runs | Red failures matched missing registry/storage propagation and missing VOID settlement; final run passed. | `.omo/evidence/task-8-complete-prd-old-remove-demo.txt` | PASS |
| env_secrecy | Do not read `.env` | No command read `.env`; environment secrets were not inspected. | No `.env` content appears in evidence. | `.omo/evidence/task-8-complete-prd-old-remove-demo.txt` | PASS |
| cleanup | No long-lived process started | No dev server or background task started. | All commands exited. | `.omo/evidence/task-8-complete-prd-old-remove-demo.txt` | PASS |

Manual QA notes:
- Scheduler propagation was tested through `scheduler_market_data.fetch_resolved_markets()` with a real scheduler object, wallet position, registry, SQLite store, and a fake Gamma HTTP client returning `cancelled=true`.
- Settlement safety was tested through `scheduler_reporting.check_settlements()` with a real scheduler object, wallet, settlement engine, registry market, JSONL store, and SQLite store.
- WebSocket task behavior was preserved by routing `scheduler_market_data.py` through the existing `scheduler_runtime` task surface; the returned task objects are still cancellable and awaitable by the scheduler.
- The enum contract remains strict: cancelled/void outcomes map to `TradeResultStatus.VOID`; no source-facing `SPLIT` state exists.
- The malformed input path remains strict: resolved markets with no authoritative winning side stay unknown/retriable rather than inferred from question text.
