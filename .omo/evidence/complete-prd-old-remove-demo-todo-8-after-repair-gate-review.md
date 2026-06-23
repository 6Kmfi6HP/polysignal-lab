recommendation: REJECT

blockers:
- programming_quality: `src/polysignal_lab/app/scheduler_market_data.py:4` still imports asyncio runtime symbols with `from asyncio import CancelledError, Task, create_task`. The exact requested grep for `import asyncio` is clean, but the required programming skill bans asyncio imports for Python async code, and this is inside the scoped Todo 8 repair file set. The standalone code-review artifact's "no import asyncio" claim is therefore unsupported by the stricter programming pass.

originalIntent:
Todo 8 asks to parse PTB/resolution metadata and normalized snapshots correctly. The plan requires `Market.from_gamma()` and scheduler updates to populate `price_to_beat`, active/resolved/closed/cancelled status, market windows, token mapping, and `resolved_outcome` for WIN/LOSS/VOID/UNKNOWN; keep PRD result states strict; remove or isolate `SPLIT`; and avoid non-authoritative outcome inference.

desiredOutcome:
Current Gamma metadata should flow through discovery and closed-market refresh into market registry/storage, normalized snapshots should expose PTB/resolution/token/window metadata, settlement should produce only WIN/LOSS/VOID/UNKNOWN, malformed or missing official outcomes should stay retriable, and cancelled/void markets should close paper positions as VOID/refund.

userOutcomeReview:
The prior functional blockers are resolved. `fetch_resolved_markets()` now parses matching cancelled Gamma payloads and upserts `MarketStatus.CANCELLED` to the runtime registry and SQLite. `check_settlements()` now processes `MarketStatus.CANCELLED` through `PaperSettlementEngine`, producing VOID/refund behavior. The prior artifact blocker is also resolved: standalone Todo 8 code-review and manual-QA/notepad artifacts now exist and cover programming, remove-ai-slops/overfit, scheduler propagation, and settlement safety. However, Todo 8 should not be checked off under the strict final gate because a scoped changed file still violates the programming async-runtime criterion.

checked artifact paths:
- `.omo/plans/complete-prd-old-remove-demo.md`
- `.omo/evidence/task-8-complete-prd-old-remove-demo.txt`
- `.omo/evidence/complete-prd-old-remove-demo-todo-8-gate-review.md`
- `.omo/evidence/complete-prd-old-remove-demo-todo-8-code-review.md`
- `.omo/evidence/todo-8-manual-qa-notepad.md`
- `docs/PRD-old.md`
- `src/polysignal_lab/domain/market.py`
- `src/polysignal_lab/data/market_snapshot.py`
- `src/polysignal_lab/paper/settlement.py`
- `src/polysignal_lab/app/scheduler_market_data.py`
- `src/polysignal_lab/app/scheduler_reporting.py`
- `src/polysignal_lab/domain/enums.py`
- `tests/test_market_parsing.py`
- `tests/test_settlement.py`
- `tests/test_scheduler_cancelled_markets.py`

commands/results:
- `git status --short -- . ':!.env' && test -e .env || true` -> dirty worktree with broad tracked/untracked changes; no `.env` content read.
- `.venv/bin/python -m pytest tests/test_market_parsing.py tests/test_settlement.py -q` -> `........ [100%]`.
- `.venv/bin/python -m pytest tests/test_scheduler_cancelled_markets.py -q` -> `.. [100%]`.
- `.venv/bin/python -m pytest tests/test_scheduler.py tests/test_scheduler_cancelled_markets.py -q` -> `......... [100%]`.
- `.venv/bin/python -m pytest tests/test_market_parsing.py::test_gamma_resolved_payload_sets_resolved_outcome tests/test_settlement.py::test_resolved_up_and_down_positions_settle_win_loss -q` -> `.. [100%]`.
- `.venv/bin/python -m pytest tests/test_settlement.py::test_missing_resolved_outcome_stays_unknown_and_retriable -q` -> `. [100%]`.
- `.venv/bin/python -m py_compile src/polysignal_lab/domain/market.py src/polysignal_lab/data/market_snapshot.py src/polysignal_lab/paper/settlement.py src/polysignal_lab/app/scheduler_market_data.py src/polysignal_lab/app/scheduler_reporting.py src/polysignal_lab/domain/enums.py tests/test_market_parsing.py tests/test_settlement.py tests/test_scheduler_cancelled_markets.py` -> exit 0.
- `rg -n "\bAny\b|cast\(|type: ignore|import asyncio|import pandas|except Exception|dict\[str, (Any|object)\]" <scoped Todo 8 files>` -> exit 1, no exact-pattern matches.
- `rg -n "asyncio|\bAny\b|cast\(|type: ignore|import pandas|except Exception|dict\[str, (Any|object)\]" <scoped Todo 8 files>` -> matched `src/polysignal_lab/app/scheduler_market_data.py:4:from asyncio import CancelledError, Task, create_task`.
- `rg -n "SPLIT" src/polysignal_lab/domain src/polysignal_lab/paper src/polysignal_lab/data/market_snapshot.py` -> exit 1, no matches.
- pure LOC check -> `market.py 201`, `market_snapshot.py 62`, `settlement.py 63`, `scheduler_market_data.py 154`, `scheduler_reporting.py 132`, `enums.py 34`, `test_market_parsing.py 78`, `test_settlement.py 69`, `test_scheduler_cancelled_markets.py 104`.

adversarial checks:
- dirty_worktree: PASS with caveat; worktree is dirty, but review was scoped and no unrelated files were reverted.
- stale_state: PASS; current files were inspected and fresh tests/greps were run.
- misleading_success_output: PASS; reports were not trusted without rerunning tests and inspecting code.
- malformed_input: PASS; focused tests cover malformed official outcome staying unresolved/retriable.
- enum_contract: PASS; `SPLIT` is absent from scoped PRD-facing source.
- settlement_safety: PASS; cancelled markets settle VOID/refund and unknown resolved outcomes remain open.
- scheduler_propagation: PASS; cancelled Gamma payload reaches registry and SQLite in the focused scheduler test.
- programming_quality: FAIL; scoped file still imports asyncio runtime symbols.
- remove_ai_slops_overfit: PASS; tests exercise real scheduler/registry/wallet/SQLite boundaries with a fake only at Gamma HTTP.
- env_secrecy: PASS; no `.env` content was read.

exact evidence gaps:
- The new code-review artifact exists and covers the required categories, but its programming grep only proves the exact substring `import asyncio` is absent. It does not support the stricter programming criterion because `from asyncio import ...` remains in a scoped changed file.
