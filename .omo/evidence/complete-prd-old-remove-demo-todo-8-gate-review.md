recommendation: REJECT

blockers:
- scheduler_propagation / settlement_safety: cancelled/void markets do not reach runtime settlement. `src/polysignal_lab/app/scheduler_market_data.py:80-81` only rebuilds/upserts closed markets when `resolved` or `resolved_outcome` is truthy, so a closed Gamma payload with `cancelled=true` and no winning side is skipped before `Market.from_gamma()` can mark it `CANCELLED`. Read-only probe output: `0 0` for context and SQLite upserts.
- scheduler_propagation / VOID semantics: `src/polysignal_lab/app/scheduler_reporting.py:35-43` only calls settlement for `MarketStatus.RESOLVED` and explicitly skips resolved markets with `resolved_outcome is None`. `MarketStatus.CANCELLED` never reaches `PaperSettlementEngine.settle()`, so the PRD VOID refund path is not executed by the scheduler. Read-only probe output: `0 OPEN 1 990.0`.
- programming_quality: the scoped scheduler refresh/update files fail the requested quality grep. Command matched `src/polysignal_lab/app/scheduler.py:3` for `import asyncio`; broad `except Exception` in `src/polysignal_lab/app/scheduler_market_data.py:31`, `:43`, `:91`, `:96`; and broad `except Exception` in `src/polysignal_lab/app/scheduler_reporting.py:31`, `:68`, `:74`, `:119`, `:126`, `:135`.
- artifact coverage: no Todo 8 standalone code-review report was found with explicit `programming` and `remove-ai-slops` overfit/slop criterion coverage, and no Todo 8 manual QA matrix/notepad path was found. The task evidence transcript is not a substitute for the required report coverage.

originalIntent:
Todo 8 asks to parse PTB/resolution metadata and normalized snapshots correctly. The plan requires `Market.from_gamma()` and scheduler updates to populate `price_to_beat`, active/resolved/closed status, market time window, token mapping, and `resolved_outcome` for WIN/LOSS/VOID/UNKNOWN; keep PRD final result states strict; remove or isolate PRD-facing `SPLIT`; and avoid non-authoritative outcome inference.

desiredOutcome:
Current Gamma metadata should flow from discovery and closed-market refresh into the market registry/storage, snapshots should include PTB/resolution/token/window metadata, settlement should map WIN/LOSS/VOID/UNKNOWN strictly, malformed/missing official outcomes should remain retriable/open, and cancelled/void markets should close paper positions as VOID/refund rather than staying open.

userOutcomeReview:
The domain-level parser and snapshot builder satisfy important parts of the request: PTB, start/end timestamps, token mapping, resolved outcome, status, resolution source, and snapshot metrics are present; malformed official outcome data remains unresolved; and `TradeResultStatus.SPLIT` is removed from the enum. The shipped artifact does not yet satisfy the user-visible Todo 8 outcome because scheduler closed-market refresh skips cancelled payloads and scheduler settlement skips `CANCELLED` markets, leaving PRD VOID/cancellation results open in runtime. The passing unit tests are too narrow to catch that scheduler path.

checked artifact paths:
- `.omo/plans/complete-prd-old-remove-demo.md`
- `.omo/evidence/task-8-complete-prd-old-remove-demo.txt`
- `docs/PRD-old.md`
- `src/polysignal_lab/domain/market.py`
- `src/polysignal_lab/data/market_snapshot.py`
- `src/polysignal_lab/paper/settlement.py`
- `src/polysignal_lab/app/scheduler.py`
- `src/polysignal_lab/app/scheduler_market_data.py`
- `src/polysignal_lab/app/scheduler_reporting.py`
- `src/polysignal_lab/app/scheduler_runtime.py`
- `src/polysignal_lab/data/polymarket_market_discovery.py`
- `src/polysignal_lab/domain/enums.py`
- `tests/test_market_parsing.py`
- `tests/test_settlement.py`

commands/results:
- `git status --short` -> dirty worktree with many tracked modifications/deletions and untracked `.omo/`, `docs/`, `tests/`, scheduler split files, etc.; inspected only.
- `.venv/bin/python -m pytest tests/test_market_parsing.py tests/test_settlement.py -q` -> `........ [100%]`.
- `.venv/bin/python -m pytest tests/test_market_parsing.py::test_gamma_resolved_payload_sets_resolved_outcome tests/test_settlement.py::test_resolved_up_and_down_positions_settle_win_loss -q` -> `.. [100%]`.
- `.venv/bin/python -m pytest tests/test_settlement.py::test_missing_resolved_outcome_stays_unknown_and_retriable -q` -> `. [100%]`.
- `.venv/bin/python -m py_compile src/polysignal_lab/domain/market.py src/polysignal_lab/data/market_snapshot.py src/polysignal_lab/paper/settlement.py src/polysignal_lab/app/scheduler.py src/polysignal_lab/app/scheduler_market_data.py src/polysignal_lab/app/scheduler_reporting.py` -> exit 0.
- `rg -n "SPLIT" src/polysignal_lab/domain src/polysignal_lab/paper src/polysignal_lab/data/market_snapshot.py tests` -> only `tests/test_settlement.py:70` assertion that enum excludes `SPLIT`.
- Todo 8 claimed-file quality grep over `market.py`, `market_snapshot.py`, `settlement.py`, and focused tests -> no matches.
- Scheduler-scope quality grep -> matched the broad exception/import asyncio lines listed above.
- Pure LOC check -> `market.py 201`, `market_snapshot.py 62`, `settlement.py 63`, `scheduler.py 152`, `scheduler_market_data.py 140`, `scheduler_reporting.py 125`, `tests/test_market_parsing.py 78`, `tests/test_settlement.py 69`; all under 250, with `market.py` in the 200-250 warning band.
- Read-only probe for cancelled closed-market fetch -> `0 0`, confirming no market upsert when `cancelled=true` is present without `resolved/resolved_outcome`.
- Read-only probe for cancelled scheduler settlement -> `0 OPEN 1 990.0`, confirming no VOID settlement and position remains open through `check_settlements()`.

remove-ai-slops / programming direct pass:
- Direct pass found no deletion-only or tautological focused unit tests in `tests/test_market_parsing.py` or `tests/test_settlement.py`; they assert concrete parsed values and wallet/position effects.
- Direct pass found missing behavior coverage for the scheduler cancellation propagation path. This is not just a missing test: manual execution shows the runtime path is currently wrong.
- Direct pass found unresolved production quality issues in the scheduler files that are explicitly in the review scope, especially broad exception swallowing in market refresh/settlement helper paths.

exact evidence gaps:
- No `.omo/evidence/*todo-8*code-review*.md` or equivalent standalone code-review artifact was present.
- No Todo 8 manual QA matrix or notepad path was present.
- Existing `.omo/evidence/task-8-complete-prd-old-remove-demo.txt` records only the narrower unit tests and task-file quality scan; it does not substantiate scheduler cancellation propagation or required report coverage.

env_secrecy:
No `.env` content was read.
