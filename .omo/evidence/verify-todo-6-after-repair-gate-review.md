recommendation: REJECT

originalIntent:
- Verify Todo 6 after repair for `.omo/plans/complete-prd-old-remove-demo.md`: scheduler startup order and subscription lifecycle must match PRD-old.
- Previous blockers to verify fixed:
  - Initial discovery failure must not start streams.
  - Telegram validation must precede strategy loading and paper wallet/simulator/settlement initialization when publishing is enabled.
  - The Todo 6 startup broad `except Exception` wrapper must be gone.
- Todo 6 also requires discovery before WebSocket subscription, non-empty Polymarket token subscriptions, stale subscription stop, token-set resubscribe, and no authenticated/trading client surface.

desiredOutcome:
- A user running the scheduler should get live Telegram validation before startup side effects, successful initial market discovery before any market/Binance stream startup, and no stream startup when initial discovery fails.
- Polymarket market WebSocket subscription should use the discovered non-empty token set, avoid empty subscriptions, and resubscribe when discovered token IDs change.
- Evidence should include current passing tests, manual call-order proof, auth/trading guard proof, py_compile proof, and a current code-review/report artifact covering `programming` and `remove-ai-slops` overfit/slop criteria.

userOutcomeReview:
- The current code satisfies the three prior functional blockers:
  - `src/polysignal_lab/app/scheduler.py:676-686` validates Telegram, initializes trading components, restores state, awaits initial market refresh, awaits resolved-market fetch, then starts websockets.
  - `src/polysignal_lab/app/scheduler.py:52-65` no longer builds strategies or initializes paper wallet/simulator/settlement in `__init__`.
  - Direct diff scan found no newly added `except Exception`/`BaseException` in the Todo 6 startup path.
  - `tests/test_scheduler.py:136-158` covers discovery failure propagation and no stream startup.
  - `tests/test_scheduler.py:161-209` covers validation before strategy/wallet/paper initialization.
- The current test surface passed locally with 9 tests, including the new discovery-failure and validation-before-init tests.
- The authenticated/trading client guard passed with no matches in `src/polysignal_lab/app` or `src/polysignal_lab/data`.
- However, approval is blocked by artifact/quality requirements from the gate role:
  - Existing Todo 6 gate-review artifacts are stale rejected reports from before this repair; no current post-repair code-review report was found that explicitly covers `programming` and `remove-ai-slops` overfit/slop criteria.
  - `.omo/plans/complete-prd-old-remove-demo.md` still shows Todo 6 unchecked at line 147, inconsistent with the completion/repair claim.
  - The direct programming/slop pass still finds `src/polysignal_lab/app/scheduler.py` oversized at 656 non-blank/non-comment lines. This appears inherited, but Todo 6 adds lifecycle responsibility to the same oversized module, so it remains a maintenance-risk finding rather than a clean approval condition.

blockers:
- Missing current post-repair code-review report with explicit `programming` and `remove-ai-slops` overfit/slop criterion coverage. Prior `.omo/evidence/*todo-6*gate-review.md` reports are stale and reject the pre-repair state.
- `.omo/plans/complete-prd-old-remove-demo.md:147` still records Todo 6 as `[ ]`, so the plan artifact does not support the completion claim.
- `src/polysignal_lab/app/scheduler.py` is still oversized under the loaded programming/remove-ai-slops criteria: direct scan measured 656 non-blank/non-comment lines. Classified as a quality/artifact blocker for final approval, not as evidence that the three repaired functional blockers remain broken.

checkedArtifactPaths:
- `.omo/plans/complete-prd-old-remove-demo.md`
- `docs/PRD-old.md`
- `src/polysignal_lab/app/scheduler.py`
- `tests/test_scheduler.py`
- `tests/test_market_data.py`
- `.omo/evidence/task-6-complete-prd-old-remove-demo.txt`
- `.omo/evidence/todo-6-repair-call-order-traces.log`
- `.omo/evidence/todo-6-repair-manual-cli-surface.log`
- `.omo/evidence/todo-6-repair-startup-lines.log`
- `.omo/evidence/todo-6-repair-quality-scan.log`
- `.omo/evidence/todo-6-repair-focused-discovery-failure.log`
- `.omo/evidence/todo-6-repair-focused-validation-before-init.log`
- `.omo/evidence/todo-6-repair-authenticated-client-guard.log`
- `.omo/evidence/todo-6-repair-full-pytest.log`
- `.omo/evidence/todo-6-repair-py-compile.log`
- `.omo/evidence/complete-prd-old-remove-demo-todo-6-gate-review.md`
- `.omo/evidence/task-6-complete-prd-old-remove-demo-gate-review.md`
- `git status --short`

reproCommands:
- `.venv/bin/python -m pytest tests/test_scheduler.py tests/test_market_data.py -q` -> PASS, `9 passed`
- `.venv/bin/python -m pytest tests/test_scheduler.py::test_refresh_markets_before_starting_streams tests/test_scheduler.py::test_market_ws_subscribes_after_token_discovery -q` -> PASS, `2 passed`
- `.venv/bin/python -m pytest tests/test_scheduler.py::test_empty_market_refresh_does_not_subscribe_market_ws -q` -> PASS, `1 passed`
- `.venv/bin/python -m pytest tests/test_scheduler.py::test_market_ws_resubscribes_when_token_set_changes -q` -> PASS, `1 passed`
- `.venv/bin/python -m pytest tests/test_scheduler.py::test_initial_discovery_failure_prevents_stream_startup tests/test_scheduler.py::test_live_telegram_validation_runs_before_strategy_and_paper_initialization -q` -> PASS, `2 passed`
- `bash -lc '! rg "Authorization|private_key|create_order|cancel_order|POLY_|api_secret|signer|order submit|submit_order" src/polysignal_lab/app src/polysignal_lab/data'` -> PASS, exit 0
- `.venv/bin/python -m py_compile src/polysignal_lab/app/scheduler.py tests/test_scheduler.py tests/test_market_data.py` -> PASS, exit 0
- `git diff -U0 -- src/polysignal_lab/app/scheduler.py | rg -n "^@@|^\\+.*except (Exception|BaseException)|^\\+.*except .*Exception"` -> PASS for startup catch removal; only hunk headers, no added broad exceptions
- `rg -n "except (BaseException|Exception)|except .*Exception" src/polysignal_lab/app/scheduler.py` -> existing broad exceptions remain, but none are the removed startup wrapper

adversarialProbeResults:
- stale_state: Inspected current files and evidence directly from disk; current `scheduler.py` differs from stale rejected gate reports.
- misleading_success_output: Reran tests rather than trusting evidence. Current tests prove discovery failure no-stream behavior and validation-before-init behavior.
- malformed_input: Empty discovery, token-set change, and discovery exception are covered by focused tests and all pass.
- authenticated_client_guard: Clean forbidden-pattern grep over app/data scope; no `Authorization`, private key, signing, or order submit/create/cancel surface found.
- programming_quality: No new startup broad catch found. Existing broad exceptions remain outside the repaired startup block. Oversized scheduler remains unresolved at 656 pure-ish LOC.
- dirty_worktree: `git status --short` shows a broadly dirty worktree with many unrelated modified/deleted/untracked files; inspected only, no revert attempted.
- env_secrecy: `.env` was not read.
- slop_overfit_direct_pass: Focused tests are behavioral, not deletion-only or tautological for the repaired blockers. Artifact/report coverage remains missing/stale.

exactEvidenceGaps:
- No current post-repair code-review report artifact explicitly covering the `programming` and `remove-ai-slops` overfit/slop criteria.
- No current report artifact demonstrating the stale rejected Todo 6 gate-review findings were superseded.
- Todo 6 remains unchecked in the plan artifact despite completion/repair evidence.
- Lint evidence is incomplete in the inspected task evidence because `.venv/bin/python -m ruff` was unavailable.

confidence: high
