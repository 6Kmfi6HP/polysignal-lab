recommendation: REJECT

blockers:
- src/polysignal_lab/app/scheduler.py:675: Initial market discovery is wrapped in a newly added broad `except Exception` block at line 678, and the run path proceeds to `start_websockets()` at line 682 after a discovery failure. An inline adversarial probe produced `['discover_raise', 'streams_started']`, so the implementation does not guarantee the PRD/Todo 6 outcome "discover markets, then start streams"; it can start streams after failed discovery.
- src/polysignal_lab/app/scheduler.py:52: `PolySignalScheduler.__init__` builds strategies at line 60 and initializes the wallet/paper components at lines 63-65 before Telegram startup validation runs at line 670. The user-specified startup order requires config load, Telegram validation, then assets/strategies/wallet initialization, then discovery and streams.
- src/polysignal_lab/app/scheduler.py:678: The Todo 6 diff introduces a new broad `except Exception` in the startup path. The requested programming-quality gate requires no new escape hatches. Existing broad exceptions and `import asyncio` are inherited, but this startup catch is new in the inspected diff.

originalIntent:
Todo 6 should repair scheduler startup order and subscription lifecycle for PRD-old: validate Telegram live publishing credentials, discover current Polymarket markets before stream startup, prevent empty Polymarket market websocket subscriptions, stop stale subscriptions, resubscribe when token sets change, start Binance only after the Polymarket market stream step, and avoid authenticated/trading market clients.

desiredOutcome:
Current artifacts should prove the scheduler can only start streaming after successful initial discovery, validates live Telegram credentials before startup side effects required by the PRD order, handles empty and changed token sets correctly, and has focused non-tautological tests plus clean auth/trading and quality gates.

userOutcomeReview:
The focused tests and observed implementation support non-empty subscription after token discovery, empty-refresh no-subscribe, stale subscription stop, and resubscribe on token-set change. The auth/trading grep is clean. However, the user-visible startup guarantee is not satisfied because a failed initial discovery is logged and streams still start. The PRD-order requirement is also only partially met because Telegram validation occurs inside `run()` after scheduler construction has already loaded strategies and initialized wallet/paper components.

checked_artifact_paths:
- .omo/plans/complete-prd-old-remove-demo.md
- docs/PRD-old.md
- src/polysignal_lab/app/scheduler.py
- src/polysignal_lab/app/main.py
- src/polysignal_lab/config.py
- src/polysignal_lab/data/binance_spot_ws.py
- src/polysignal_lab/data/market_snapshot.py
- src/polysignal_lab/data/polymarket_clob_rest.py
- src/polysignal_lab/data/polymarket_clob_ws.py
- src/polysignal_lab/data/polymarket_market_discovery.py
- src/polysignal_lab/data/state.py
- tests/test_scheduler.py
- tests/test_market_data.py
- .omo/evidence/task-6-complete-prd-old-remove-demo.txt
- git status --short --branch

exact_evidence_gaps:
- .omo/plans/complete-prd-old-remove-demo.md still shows Todo 6 unchecked at line 147 despite a task evidence file claiming completion.
- No separate code review report, manual QA matrix, or notepad path was provided in the user input; this review directly inspected the requested artifacts and reran the requested commands.
- Tests cover the successful discovery ordering and subscription lifecycle, but no test covers initial discovery failure. The inline probe demonstrates streams start after that failure.

direct_remove_ai_slops_and_programming_pass:
- No excessive/deletion-only/tautological tests found for the happy subscription, empty refresh, or token-set-change behavior; tests assert observable fake websocket subscriptions and stop counts.
- New production slop found: a broad startup `except Exception` that creates false confidence and permits streams to start after failed discovery.
- Oversized scheduler risk remains: `src/polysignal_lab/app/scheduler.py` measures 653 pure LOC, over the 250 pure LOC programming threshold. This was pre-existing as an oversized module, but Todo 6 added more lifecycle responsibility to it rather than reducing the burden.

repro_summary:
- `.venv/bin/python -m pytest tests/test_scheduler.py tests/test_market_data.py -q`: PASS, 7 passed.
- `.venv/bin/python -m pytest tests/test_scheduler.py::test_refresh_markets_before_starting_streams tests/test_scheduler.py::test_market_ws_subscribes_after_token_discovery -q`: PASS, 2 passed.
- `.venv/bin/python -m pytest tests/test_scheduler.py::test_empty_market_refresh_does_not_subscribe_market_ws -q`: PASS, 1 passed.
- `.venv/bin/python -m pytest tests/test_scheduler.py::test_market_ws_resubscribes_when_token_set_changes -q`: PASS, 1 passed.
- `bash -lc '! rg "Authorization|private_key|create_order|cancel_order|POLY_|api_secret|signer|order submit|submit_order" src/polysignal_lab/app src/polysignal_lab/data'`: PASS, exit 0, no output.
- quality grep: FAIL for confirmation because it shows newly introduced `src/polysignal_lab/app/scheduler.py:678: except Exception as exc` in the Todo 6 startup path.
- `.venv/bin/python -m py_compile src/polysignal_lab/app/scheduler.py tests/test_scheduler.py tests/test_market_data.py`: PASS, exit 0, no output.
