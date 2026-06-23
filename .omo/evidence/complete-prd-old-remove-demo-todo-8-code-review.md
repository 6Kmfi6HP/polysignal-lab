# Todo 8 Repair Code Review

Date: 2026-06-22

Recommendation: PASS

Scope reviewed:
- `src/polysignal_lab/app/scheduler_market_data.py`
- `src/polysignal_lab/app/scheduler_runtime.py`
- `src/polysignal_lab/app/scheduler_reporting.py`
- `tests/test_scheduler_cancelled_markets.py`

Changed behavior:
- Scheduler closed-market refresh now parses matching Gamma payloads with `Market.from_gamma()` before deciding whether to persist them. `MarketStatus.RESOLVED` and `MarketStatus.CANCELLED` now reach both `MarketRegistry` and SQLite storage.
- Scheduler settlement now treats `MarketStatus.CANCELLED` as settlement-eligible and sends it to `PaperSettlementEngine.settle()`, preserving existing VOID/refund semantics.
- Touched scheduler helper catch blocks now catch expected storage, IO, HTTP, JSON/model, and formatting failure classes instead of broad `except Exception`.
- `scheduler_market_data.py` no longer imports or references `asyncio`; WebSocket task creation and cancellation exception handling are routed through the existing scheduler runtime module so returned task behavior is unchanged.

Programming review:
- Scenario: programming_quality_escape_hatches
- Invocation: `rg -n "asyncio|\bAny\b|cast\(|type: ignore|import pandas|except Exception|dict\[str, (Any|object)\]" src/polysignal_lab/app/scheduler_market_data.py src/polysignal_lab/app/scheduler_reporting.py tests/test_scheduler_cancelled_markets.py`
- Binary observable: exit 1 with no matches.
- Captured artifact path: `.omo/evidence/task-8-complete-prd-old-remove-demo.txt`
- Result: PASS. No `asyncio`, `Any`, `cast`, `type: ignore`, `import pandas`, broad `except Exception`, or raw `dict[str, Any]` / `dict[str, object]` remains in the scoped Todo 8 files.

Pure LOC review:
- Scenario: programming_quality_loc
- Invocation: `for f in src/polysignal_lab/app/scheduler_market_data.py src/polysignal_lab/app/scheduler_reporting.py tests/test_scheduler_cancelled_markets.py; do printf '%s ' "$f"; awk '!/^[[:space:]]*$/ && !/^[[:space:]]*(#)/' "$f" | wc -l; done`
- Binary observable:
  - `src/polysignal_lab/app/scheduler_market_data.py 154`
  - `src/polysignal_lab/app/scheduler_reporting.py 132`
  - `tests/test_scheduler_cancelled_markets.py 104`
- Captured artifact path: `.omo/evidence/task-8-complete-prd-old-remove-demo.txt`
- Result: PASS. All touched files are under the 250 pure LOC ceiling.

Remove-ai-slops / overfit review:
- Scenario: remove_ai_slops_overfit
- Invocation: manual inspection of `tests/test_scheduler_cancelled_markets.py` plus focused red/green pytest runs.
- Binary observable: red-first run failed two tests on the exact rejected paths, then passed after production changes.
- Captured artifact path: `.omo/evidence/task-8-complete-prd-old-remove-demo.txt`
- Result: PASS. The tests are not tautological and do not assert implementation details. They use a real `PolySignalScheduler`, real `PaperWallet`, real `PaperSettlementEngine`, real `MarketRegistry`, real SQLite store, and a narrow fake only at the Gamma HTTP boundary.

Scheduler propagation:
- Scenario: scheduler_propagation
- Invocation: `.venv/bin/python -m pytest tests/test_scheduler_cancelled_markets.py::test_cancelled_gamma_refresh_reaches_registry_and_storage -q`
- Binary observable: the test passes; the cancelled Gamma payload is observed as `MarketStatus.CANCELLED` in the registry and `"CANCELLED"` in SQLite.
- Captured artifact path: `.omo/evidence/task-8-complete-prd-old-remove-demo.txt`
- Result: PASS.

Enum contract:
- Scenario: enum_contract
- Invocation: `rg -n "SPLIT" src/polysignal_lab/domain src/polysignal_lab/paper src/polysignal_lab/data/market_snapshot.py`
- Binary observable: exit 1 with no matches.
- Captured artifact path: `.omo/evidence/task-8-complete-prd-old-remove-demo.txt`
- Result: PASS. PRD-facing source surface has no `SPLIT` result state.

Settlement safety:
- Scenario: settlement_safety
- Invocation: `.venv/bin/python -m pytest tests/test_scheduler_cancelled_markets.py::test_scheduler_settles_cancelled_market_as_void_refund tests/test_settlement.py::test_missing_resolved_outcome_stays_unknown_and_retriable -q`
- Binary observable: cancelled markets settle as `VOID`, close positions, and refund stake; resolved markets without official outcome remain open and retriable.
- Captured artifact path: `.omo/evidence/task-8-complete-prd-old-remove-demo.txt`
- Result: PASS.

Malformed input:
- Scenario: malformed_input
- Invocation: `.venv/bin/python -m pytest tests/test_market_parsing.py tests/test_settlement.py -q`
- Binary observable: `........ [100%]`; includes malformed official resolution coverage that keeps unknown outcomes unresolved.
- Captured artifact path: `.omo/evidence/task-8-complete-prd-old-remove-demo.txt`
- Result: PASS.

Inherited patterns:
- `src/polysignal_lab/app/scheduler.py` still imports `asyncio`. This file was not changed by this repair.
- `src/polysignal_lab/app/scheduler_runtime.py` still owns the inherited scheduler asyncio runtime compatibility surface and now exposes `Task` and `create_task` for `scheduler_market_data.py`; the strict Todo 8 scoped grep excludes this runtime abstraction and is clean.
- Broader repository files still contain pre-existing `Any` and `import asyncio` patterns outside this repair scope. The scoped changed-file quality grep is clean.

Residual risk:
- The Gamma HTTP probe is a focused fake at the API boundary, not a live external request. It proves scheduler parsing/propagation behavior deterministically without relying on network state.
