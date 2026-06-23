recommendation: APPROVE

blockers:
- none

originalIntent:
Todo 8 asks to parse PTB/resolution metadata and normalized snapshots correctly. The plan requires `Market.from_gamma()` and scheduler updates to populate `price_to_beat`, active/resolved/closed/cancelled status, market windows, token mapping, and `resolved_outcome` for WIN/LOSS/VOID/UNKNOWN; keep PRD result states strict; remove or isolate `SPLIT`; and avoid non-authoritative outcome inference.

desiredOutcome:
Current Gamma metadata flows through discovery and closed-market refresh into the market registry and SQLite storage. Normalized snapshots expose PTB, resolution, token, status, and window metadata. Settlement produces only WIN/LOSS/VOID/UNKNOWN, malformed or missing official outcomes stay retriable, and cancelled/void markets close paper positions as VOID/refund.

userOutcomeReview:
CONFIRM. The shipped artifact now satisfies the Todo 8 user outcome. Domain parsing sets PTB, status, resolved outcome, resolution source, market window, and token mapping from official Gamma fields in `src/polysignal_lab/domain/market.py`. Snapshot metadata includes the normalized PTB/resolution/window/token fields in `src/polysignal_lab/data/market_snapshot.py`. Settlement maps cancelled markets to VOID/refund and leaves resolved markets without authoritative outcomes UNKNOWN/retriable in `src/polysignal_lab/paper/settlement.py`.

The prior scheduler blockers are fixed. `src/polysignal_lab/app/scheduler_market_data.py` now parses matching closed Gamma payloads before deciding whether to persist them and upserts both `RESOLVED` and `CANCELLED` markets to the runtime registry and SQLite. `src/polysignal_lab/app/scheduler_reporting.py` now settlement-checks `CANCELLED` markets and routes them through the existing `PaperSettlementEngine` VOID/refund behavior.

The prior artifact blockers are fixed. Standalone code-review and manual-QA artifacts now exist and include programming-quality, scheduler-propagation, settlement-safety, malformed-input, enum-contract, and remove-ai-slops/overfit coverage. The current code-review report is supported by direct inspection and fresh commands.

The narrow asyncio-import blocker is fixed. The strict scoped grep over `scheduler_market_data.py`, `scheduler_reporting.py`, and `tests/test_scheduler_cancelled_markets.py` returned no matches for `asyncio` or other listed escape hatches. `scheduler_runtime.py` still contains asyncio primitives, but it is the scheduler lifecycle/runtime compatibility module identified by the brief. Direct inspection found it centralizes `CancelledError`, `Task`, `create_task`, and `sleep` for scheduler lifecycle/task compatibility; the required scheduler regression tests passed, and no Todo 8 behavior regression or new broad escape hatch beyond that runtime role was found.

checked artifact paths:
- `.omo/plans/complete-prd-old-remove-demo.md`
- `.omo/evidence/task-8-complete-prd-old-remove-demo.txt`
- `.omo/evidence/complete-prd-old-remove-demo-todo-8-gate-review.md`
- `.omo/evidence/complete-prd-old-remove-demo-todo-8-after-repair-gate-review.md`
- `.omo/evidence/complete-prd-old-remove-demo-todo-8-code-review.md`
- `.omo/evidence/todo-8-manual-qa-notepad.md`
- `src/polysignal_lab/domain/market.py`
- `src/polysignal_lab/data/market_snapshot.py`
- `src/polysignal_lab/paper/settlement.py`
- `src/polysignal_lab/app/scheduler_market_data.py`
- `src/polysignal_lab/app/scheduler_reporting.py`
- `src/polysignal_lab/app/scheduler_runtime.py`
- `src/polysignal_lab/domain/enums.py`
- `tests/test_market_parsing.py`
- `tests/test_settlement.py`
- `tests/test_scheduler_cancelled_markets.py`

commands/results:
- `git status --short -- . ':!.env'` -> dirty worktree with broad tracked/untracked changes; review stayed scoped and no unrelated files were reverted.
- `test -e .env; rc=$?; printf 'test -e .env exit=%s\n' "$rc"` -> `test -e .env exit=0`; `.env` exists, but no content was read.
- `.venv/bin/python -m pytest tests/test_market_parsing.py tests/test_settlement.py -q` -> `........ [100%]`.
- `.venv/bin/python -m pytest tests/test_scheduler_cancelled_markets.py -q` -> `.. [100%]`.
- `.venv/bin/python -m pytest tests/test_scheduler.py tests/test_scheduler_cancelled_markets.py -q` -> `......... [100%]`.
- `.venv/bin/python -m pytest tests/test_market_parsing.py::test_gamma_resolved_payload_sets_resolved_outcome tests/test_settlement.py::test_resolved_up_and_down_positions_settle_win_loss -q` -> `.. [100%]`.
- `.venv/bin/python -m pytest tests/test_settlement.py::test_missing_resolved_outcome_stays_unknown_and_retriable -q` -> `. [100%]`.
- `.venv/bin/python -m py_compile src/polysignal_lab/domain/market.py src/polysignal_lab/data/market_snapshot.py src/polysignal_lab/paper/settlement.py src/polysignal_lab/app/scheduler_market_data.py src/polysignal_lab/app/scheduler_reporting.py src/polysignal_lab/app/scheduler_runtime.py tests/test_market_parsing.py tests/test_settlement.py tests/test_scheduler_cancelled_markets.py` -> exit 0.
- `rg -n "asyncio|\bAny\b|cast\(|type: ignore|import pandas|except Exception|dict\[str, (Any|object)\]" src/polysignal_lab/app/scheduler_market_data.py src/polysignal_lab/app/scheduler_reporting.py tests/test_scheduler_cancelled_markets.py` -> exit 1, no matches.
- `rg -n "SPLIT" src/polysignal_lab/domain src/polysignal_lab/paper src/polysignal_lab/data/market_snapshot.py` -> exit 1, no matches.
- `rg -n "TELEGRAM_BOT_TOKEN|TELEGRAM_CHANNEL_ID|PRIVATE_KEY|MNEMONIC|API_SECRET|SECRET=|TOKEN="` over the referenced Todo 8 evidence artifacts -> exit 1, no matches.
- Pure LOC check -> `market.py 201`, `market_snapshot.py 62`, `settlement.py 63`, `scheduler_market_data.py 158`, `scheduler_reporting.py 132`, `scheduler_runtime.py 139`, `test_market_parsing.py 78`, `test_settlement.py 69`, `test_scheduler_cancelled_markets.py 104`. All are under the 250 pure LOC ceiling; `market.py` remains in the 200-250 warning band.

adversarial checks:
- dirty_worktree: PASS. The worktree is dirty, but the review stayed scoped and did not revert unrelated files.
- stale_state: PASS. Current files and artifacts were inspected, and fresh deterministic tests/greps were run.
- misleading_success_output: PASS. Previous success prose was treated as untrusted; current code and commands support completion.
- malformed_input: PASS. `tests/test_market_parsing.py::test_gamma_malformed_official_resolution_stays_unknown` remains covered by the green market/settlement suite.
- enum_contract: PASS. `SPLIT` is absent from PRD-facing domain/paper/snapshot source.
- settlement_safety: PASS. Cancelled markets settle VOID/refund; missing authoritative resolved outcome stays UNKNOWN and leaves the position open/retriable.
- scheduler_propagation: PASS. The focused scheduler test proves cancelled Gamma payloads reach the registry and SQLite.
- programming_quality: PASS. Strict scoped grep is clean; py_compile is green. `scheduler_runtime.py` was inspected under the prompt nuance and remains confined to scheduler lifecycle/runtime compatibility.
- remove_ai_slops_overfit: PASS. Tests are not deletion-only, tautological, or implementation-mirroring; they assert observable parser/snapshot/wallet/position/SQLite behavior. The fake in the scheduler test is limited to the Gamma HTTP boundary.
- env_secrecy: PASS. `.env` content was not read; evidence artifacts searched for common secret markers had no matches.

remove-ai-slops / programming direct pass:
- No excessive or useless Todo 8 tests were found. The scheduler cancellation tests fail on the previously rejected runtime paths and assert concrete registry, SQLite, wallet, position, and result state.
- No deletion-only test, test that merely verifies a requested removal, tautological mock, or implementation-mirroring assertion was found.
- No unnecessary production extraction, parsing, or normalization was found in the Todo 8 diff. The added parsing helpers replace unsafe broad JSON parsing and are tied to official Gamma field variants required by the task.
- No unresolved scoped escape hatch was found in `scheduler_market_data.py`, `scheduler_reporting.py`, or `tests/test_scheduler_cancelled_markets.py`.

exact evidence gaps:
- none

final status:
- Todo 8 can be checked off. All prior Todo 8 blockers are resolved.
