# Todo 13 Self-Review

Gate repair update for reviewer 019eedd5-7056-7e60-a617-c5e40328a522:

Verdict: pass for the focused repair. The NaN malformed-orderbook blocker is covered by a red/green regression, rejected-signal persistence errors are no longer silently swallowed, and paper-path exceptions now log signal/token context without returning paper decision fields before persistence completes.

NaN malformed orderbook:
- Regression test: `tests/test_paper_simulation.py::test_nan_ask_rejects_malformed_without_depth_check`.
- Red observable before production fix: targeted pytest failed because the order status was `FILLED` instead of `REJECTED`.
- Green observable after fix: targeted pytest passed and asserts `MALFORMED_ORDERBOOK`, no fill, no position, wallet cash/equity unchanged, open position count `0`, zero market exposure, and metrics reason `MALFORMED_ORDERBOOK` with `require_depth_check=False`.
- Production change: `BestAskTakerFillModel` now requires finite best ask, finite order limit price, finite positive ask price/size for every ask level, and finite computed fill price before fill/depth logic can proceed.

Scheduler exception handling:
- Rejected-signal persistence no longer uses `except Exception: pass`; it now calls `scheduler.logger.exception(...)` with market slug, strategy name, and `reason_code`.
- Paper-trading failures now call `scheduler.logger.exception(...)` with `signal_id` and `token_id`.
- `_store_simulation_result` now assigns `result["paper_order"]`, `result["paper_fill"]`, and `result["paper_position"]` only after the corresponding log/sqlite persistence calls have completed, reducing misleading returned decisions on storage failure.
- Honest residual note: broad scheduler exception boundaries remain around snapshot/strategy/signal/publish/paper processing by existing design to isolate one failing market/strategy/signal from the loop. This repair did not convert all broad catches to specific exception types; it removed the silent swallow called out by the gate and added context to the paper path.

Remove-ai-slops / overfit criteria:
- Obvious comments: no new explanatory comments or section-divider comments were added.
- Over-defensive code: the new finite checks are boundary validation for external orderbook price/size data and prevent a proven wallet-debit bug; no duplicate downstream defensive layer was added.
- Excessive complexity: no new helper stack, branching tree, or long parameter list was introduced; changed Python files remain under 250 pure LOC.
- Needless abstraction: no new abstraction, service, wrapper, or dependency was introduced.
- Boundary violations: changes stay inside the existing fill-model validation boundary and scheduler persistence/logging boundary.
- Dead code: no unused code path was added; compileall and targeted tests passed.
- Duplication/performance: no copy-paste branch or algorithmic rewrite was added; depth computation behavior is unchanged except malformed non-finite ask data is rejected first.
- Missing tests: the NaN malformed-orderbook behavior has a focused regression that failed before the fix and passed after.
- Overfit risk: the test uses the public `PaperSimulator.process_signal` surface and asserts observable wallet/order/position outcomes, not an implementation detail or a mocked call.

Repair validation:
- `.venv/bin/python -m pytest tests/test_paper_simulation.py tests/test_scheduler_paper.py -q` -> 13 passed.
- `.venv/bin/python -m pytest tests/test_paper_simulation.py::test_accepted_signal_fills_at_best_ask_and_updates_wallet -q` -> 1 passed.
- `.venv/bin/python -m pytest tests/test_paper_simulation.py::test_stale_orderbook_rejects_fill_without_position tests/test_scheduler_paper.py::test_stale_paper_fill_count_is_zero -q` -> 2 passed.
- `.venv/bin/python -m pytest tests/test_paper_simulation.py::test_nan_ask_rejects_malformed_without_depth_check -q` -> 1 passed.
- `.venv/bin/python -m compileall -q src/polysignal_lab/paper/fill_model.py src/polysignal_lab/app/scheduler_processing.py tests/test_paper_simulation.py` -> exited 0.
- Scoped no-real-trading grep over `src/polysignal_lab/paper/fill_model.py`, `src/polysignal_lab/app/scheduler_processing.py`, `tests/test_paper_simulation.py`, and `tests/test_scheduler_paper.py` -> no matches, rg exit 1.

Verdict: pass with one tooling limitation. The paper simulator and scheduler now satisfy the requested paper-only fill/rejection/accounting/storage/reporting behavior, and the required pytest scenarios pass.

Paper accounting:
- Accepted fills debit wallet cash by stake, keep equity at cash plus open stake, increment open_position_count, and update market/strategy exposure.
- `test_accepted_signal_fills_at_best_ask_and_updates_wallet` asserts best ask, slippage fill price, cash_balance=990.0, equity=1000.0, open_position_count=1, and exposure=10.0 for market and strategy.
- Scheduler persists a wallet snapshot with each paper decision so cash/equity/open position state can be inspected after processing.

Stale/missing/depth rejection:
- Stale orderbooks reject with `STALE_ORDERBOOK`; no fill or position is created and wallet remains unchanged.
- Missing orderbooks now still create a paper order, rejected with `MISSING_ORDERBOOK`.
- Missing best ask rejects with `MISSING_BEST_ASK`; malformed wrong-token/nonpositive price or size rejects with `MALFORMED_ORDERBOOK`.
- Insufficient depth rejects with `INSUFFICIENT_DEPTH` and records `available_depth_usdc`.

Storage/logging:
- `_store_simulation_result` logs and persists every paper order, whether filled or rejected.
- Fills and positions are logged/persisted only when both accepted fill and position exist.
- Scheduler acceptance tests assert persisted/logged rejection rows and zero persisted fills/positions for rejected paths.
- Daily report generation counts paper orders/rejections from persisted `paper_orders` rows and exposes `stale_paper_fills`.

No real trading:
- The changes stay inside paper simulator, scheduler processing/reporting, domain report model, and tests.
- Scoped grep command over touched paper/scheduler/test files found no `private_key`, `mnemonic`, secure CLOB client, create/submit/cancel order, or redemption symbols.
- No private-key use, authenticated trading endpoint, live order placement, cancellation, or redemption path was added.

Quality/slop risks:
- Files remain below the 250 pure-LOC ceiling: largest changed production file is `scheduler_reporting.py` at 155 pure LOC.
- The implementation uses existing domain models and stores rather than adding a parallel persistence path.
- Tests cover externally visible behavior through simulator and scheduler APIs rather than mocking internals.
- Tool limitation: LSP/basedpyright/ruff are unavailable in this environment; `compileall` and required pytest coverage passed.

Residual risks:
- The repository is a shared dirty worktree with unrelated pre-existing changes in many files, including some files in neighboring scheduler/paper areas. I preserved those and did not attempt to revert them.
- The `review-work` skill was loaded after implementation, but its mandatory five-subagent orchestration cannot run in this session because no `multi_agent_v1` spawn/wait tools are exposed. This artifact records a self-review plus executed QA, not a five-lane independent review pass.

Final-review cancelled resting rejection repair:
- Fix commit: `5d269924067eb58643fd1ab196a72c582e5031ff`.
- Finding repaired: `tick_resting_orders()` now routes cancelled resting results with `GTD_EXPIRED` or `WALLET_INSUFFICIENT_CASH` reasons through the same normalized paper-order upsert and wallet-snapshot path used by rejected resting results, while preserving strategy cancel notification.
- Red evidence: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_scheduler_paper.py::test_cancelled_resting_gtd_expiry_is_persisted_with_normalized_reason -v` failed before the production fix with `AssertionError: assert 'GTD_EXPIRED' == 'PAPER_GTD_EXPIRED'`.
- Green evidence: after the fix, `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_scheduler_paper.py::test_cancelled_resting_gtd_expiry_is_persisted_with_normalized_reason tests/test_scheduler_paper.py::test_cancelled_resting_no_cash_is_persisted_with_normalized_reason -v` passed with `2 passed`.
- Acceptance evidence: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_scheduler_paper.py tests/test_resting_orders.py -v` passed with `23 passed`.
