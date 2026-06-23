recommendation: APPROVE

originalIntent:
- Final independent verification for Todo 6 after the scheduler refactor.
- Todo 6 requires scheduler startup order and subscription lifecycle to match PRD-old: validate Telegram before strategy/wallet/paper initialization, discover markets before streams, avoid stream startup after discovery failure, subscribe Polymarket WS only with non-empty discovered token ids, stop stale subscriptions on empty discovery, resubscribe on token-set changes, avoid authenticated/trading client surfaces, keep touched Python files under 250 pure LOC, and provide current programming/remove-ai-slops review coverage.

desiredOutcome:
- Todo 6 can be checked off from the user's perspective: running the scheduler validates live Telegram settings before trading component initialization, successful discovery gates stream startup, discovery failure prevents stream startup, and market websocket subscriptions follow discovered non-empty token sets without auth/trading behavior.

userOutcomeReview:
- Confirmed from current disk state, not prior reports. Current `scheduler_runtime.run()` calls Telegram validation, trading-component initialization, wallet restore, market discovery, resolved-market fetch, then `start_websockets()`.
- Discovery failure is not wrapped by a broad startup catch; a focused test and call-order evidence prove streams are not started after initial discovery raises.
- Current `scheduler_market_data.sync_market_ws_subscription()` stops stale Polymarket subscriptions for empty token sets and only calls `poly_ws.subscribe()` with non-empty token ids.
- Token-set changes stop the previous subscription and start a new non-empty subscription.
- Auth/trading guard grep over `src/polysignal_lab/app` and `src/polysignal_lab/data` is clean.
- Touched Python files measure 29-204 pure LOC; source modules measure 77-152 pure LOC.
- Current code-review artifact explicitly covers `programming`, `remove-ai-slops`, overfit, deletion-only, oversized, startup order, broad catch, and auth criteria.

blockers: []

checkedArtifactPaths:
- `src/polysignal_lab/app/scheduler.py`
- `src/polysignal_lab/app/scheduler_market_data.py`
- `src/polysignal_lab/app/scheduler_state.py`
- `src/polysignal_lab/app/scheduler_processing.py`
- `src/polysignal_lab/app/scheduler_reporting.py`
- `src/polysignal_lab/app/scheduler_runtime.py`
- `tests/test_scheduler.py`
- `tests/test_market_data.py`
- `.omo/evidence/task-6-complete-prd-old-remove-demo.txt`
- `.omo/evidence/complete-prd-old-remove-demo-todo-6-code-review.md`
- `.omo/evidence/todo-6-repair-call-order-traces.log`
- `.omo/evidence/todo-6-repair-manual-cli-surface.log`
- `.omo/plans/complete-prd-old-remove-demo.md`
- `.omo/evidence/complete-prd-old-remove-demo-todo-6-gate-review.md`
- `.omo/evidence/task-6-complete-prd-old-remove-demo-gate-review.md`
- `.omo/evidence/verify-todo-6-after-repair-gate-review.md`
- `git status --short`

reproCommands:
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_scheduler.py tests/test_market_data.py -q` -> PASS, `9 passed`.
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_scheduler.py::test_refresh_markets_before_starting_streams tests/test_scheduler.py::test_market_ws_subscribes_after_token_discovery tests/test_scheduler.py::test_empty_market_refresh_does_not_subscribe_market_ws tests/test_scheduler.py::test_market_ws_resubscribes_when_token_set_changes tests/test_scheduler.py::test_initial_discovery_failure_prevents_stream_startup tests/test_scheduler.py::test_live_telegram_validation_runs_before_strategy_and_paper_initialization -q` -> PASS, `6 passed`.
- `bash -lc '! rg "Authorization|private_key|create_order|cancel_order|POLY_|api_secret|signer|order submit|submit_order" src/polysignal_lab/app src/polysignal_lab/data'` -> PASS, exit 0.
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m py_compile src/polysignal_lab/app/scheduler.py src/polysignal_lab/app/scheduler_market_data.py src/polysignal_lab/app/scheduler_state.py src/polysignal_lab/app/scheduler_processing.py src/polysignal_lab/app/scheduler_reporting.py src/polysignal_lab/app/scheduler_runtime.py tests/test_scheduler.py tests/test_market_data.py` -> PASS, exit 0.
- Pure LOC scan over scoped source/tests -> PASS, all scoped Python files <=250 pure LOC.
- Quality grep -> only inherited/moved broad `except Exception` resilience paths and inherited scheduler `import asyncio`; no startup broad catch, no `Any`, no `cast(`, no `type: ignore`, no pandas, no raw public dict signatures.
- Artifact grep over `.omo/evidence/complete-prd-old-remove-demo-todo-6-code-review.md` -> PASS for required coverage terms.

adversarialProbeResults:
- stale_state: Stale rejected Todo 6 gate reports were inspected and treated as superseded by current files, current code-review artifact, and current command results.
- dirty_worktree: Broad dirty worktree inspected only; no unrelated files were reverted.
- misleading_success_output: Done claims were paired with direct code inspection, current pytest reruns, call-order traces, artifact checks, and grep gates.
- malformed_input: Empty discovery, changed token set, and discovery exception are covered by current focused tests and pass.
- authenticated_client_guard: Forbidden auth/order/trading grep is clean in app/data scope.
- programming_quality: Size ceiling fixed by scheduler split; current modules are <=250 pure LOC. Moved broad catches are documented as inherited non-startup resilience paths; no new startup catch remains.
- remove_ai_slops_overfit: Direct pass found the focused tests behavioral rather than deletion-only, tautological, or implementation-only; no unnecessary production abstraction beyond responsibility split.
- env_secrecy: `.env` was not read.

exactEvidenceGaps:
- `.omo/plans/complete-prd-old-remove-demo.md` still shows Todo 6 unchecked, but this is a stale plan-state mismatch rather than a code/evidence blocker. Current disk artifacts support checking it off.
- `ruff` is unavailable in `.venv`; no lint pass was reproduced. Requested pytest, focused tests, py_compile, size, auth guard, quality grep, and artifact coverage all passed.

confidence: high
