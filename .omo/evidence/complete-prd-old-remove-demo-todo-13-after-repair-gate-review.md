recommendation: APPROVE
verdict: CONFIRM

## originalIntent

Complete Todo 13 for the old demo-removal PRD by making the paper simulator and scheduler paper path behave like a paper-only trading system: accepted signals create paper orders, valid books fill at best ask with slippage/depth rules, bad books reject without position or wallet mutation, paper decisions are logged/persisted, report metrics expose meaningful paper counts, and no real trading path is introduced.

## desiredOutcome

- Accepted/published signals create paper orders.
- Taker fills use the target token's best ask, configured slippage, and orderbook depth when depth checks are enabled.
- Stale, missing, malformed, insufficient-depth, and non-finite orderbooks reject without fill, position, or wallet mutation.
- Filled decisions persist/log paper order, fill, position, and wallet snapshot; rejected decisions persist/log paper order and wallet snapshot only.
- `stale_paper_fills` is asserted as a meaningful zero from persisted paper-order metrics.
- No private key, authenticated CLOB client, live order placement/cancel, or redemption path is introduced.

## userOutcomeReview

CONFIRM. The focused repair addresses the prior gate blockers from `019eedd5-7056-7e60-a617-c5e40328a522`.

`src/polysignal_lab/paper/fill_model.py` now rejects non-finite best ask, non-finite limit price, non-finite/non-positive ask price, non-finite/non-positive ask size, and non-finite computed fill price before fill or depth logic can proceed. The required targeted regression and an additional direct probe both show that NaN/Inf ask price or size cannot produce a fill with `require_depth_check=False` and cannot mutate wallet state.

`src/polysignal_lab/app/scheduler_processing.py` no longer silently swallows rejected-signal persistence failures. The rejected-signal path logs `logger.exception(...)` with market, strategy, and reason context. The paper path logs failures with signal/token context and only populates returned `paper_order`, `paper_fill`, and `paper_position` fields after the corresponding persistence work has completed.

The repaired code-review artifact includes an explicit remove-ai-slops/overfit section. My direct pass over production and tests found no excessive/useless tests, deletion-only tests, tests that merely verify a removal, tautological mocks, implementation-mirroring assertions, or unnecessary production extraction/parsing/normalization introduced by the repair.

## blockers

None.

## commandsRun

- `find /home/gyue/polysignal-lab -name AGENTS.md -print`
  - No repository-local `AGENTS.md` applies.
- `.venv/bin/python -m pytest tests/test_paper_simulation.py tests/test_scheduler_paper.py -q`
  - Passed: `13 passed`.
- `.venv/bin/python -m pytest tests/test_paper_simulation.py::test_accepted_signal_fills_at_best_ask_and_updates_wallet -q`
  - Passed: `1 passed`.
- `.venv/bin/python -m pytest tests/test_paper_simulation.py::test_stale_orderbook_rejects_fill_without_position tests/test_scheduler_paper.py::test_stale_paper_fill_count_is_zero -q`
  - Passed: `2 passed`.
- `.venv/bin/python -m pytest tests/test_paper_simulation.py::test_nan_ask_rejects_malformed_without_depth_check -q`
  - Passed: `1 passed`.
- Direct non-finite ask probe through `PaperSimulator` with `require_depth_check=False`
  - `price_nan`, `price_pos_inf`, `price_neg_inf`, `size_nan`, `size_pos_inf`, and `mixed_second_level_nan` all returned `REJECTED MALFORMED_ORDERBOOK None 1000.0 0 OK`.
- Direct scheduler accepted-fill probe with valid orderbook
  - Observed `FILLED True True`, persisted counts `1 1 1 1` for paper orders/fills/positions/wallet snapshots, and wallet state `990.0 1 10.0`.
- `.venv/bin/python -m compileall -q src/polysignal_lab/paper/fill_model.py src/polysignal_lab/paper/simulator.py src/polysignal_lab/app/scheduler_processing.py src/polysignal_lab/app/scheduler_reporting.py src/polysignal_lab/domain/paper_result.py src/polysignal_lab/paper/report.py tests/test_paper_simulation.py tests/test_scheduler_paper.py`
  - Passed with exit code 0.
- `rg -n "private_key|mnemonic|SecureClient|ClobClient\\(|create_order|post_order|submit_order|cancel_order|redeem_positions|real[-_ ]?trading|live[-_ ]?order|authenticated" ...`
  - No matches in touched paper/scheduler/test scope.
- `find . -path ./.venv -prune -o -path ./.git -prune -o -type f \( -name '*.sqlite' -o -name '*.sqlite3' -o -name '*.db' -o -name '*.db-wal' -o -name '*.db-shm' \) -print`
  - No repo runtime sqlite/db artifacts found.
- `pgrep -af '[p]olysignal_lab.app.main|[p]ytest'`
  - No long-lived app or pytest process found.
- `.venv/bin/python -m ruff check <touched files>`
  - Not available: `No module named ruff`.
- `.venv/bin/python -m basedpyright <touched files>`
  - Not available: `No module named basedpyright`.

## checkedArtifactPaths

- `.omo/evidence/task-13-complete-prd-old-remove-demo.txt`
- `.omo/evidence/complete-prd-old-remove-demo-todo-13-code-review.md`
- `.omo/evidence/complete-prd-old-remove-demo-todo-13-gate-review.md`
- `.omo/evidence/todo-13-manual-qa-notepad.md`
- `src/polysignal_lab/paper/fill_model.py`
- `src/polysignal_lab/paper/simulator.py`
- `src/polysignal_lab/app/scheduler_processing.py`
- `src/polysignal_lab/app/scheduler_reporting.py`
- `src/polysignal_lab/domain/paper_result.py`
- `src/polysignal_lab/paper/report.py`
- `src/polysignal_lab/domain/orderbook.py`
- `src/polysignal_lab/domain/paper_order.py`
- `src/polysignal_lab/paper/wallet.py`
- `tests/test_paper_simulation.py`
- `tests/test_scheduler_paper.py`
- `tests/factories.py`

## adversarialClasses

- dirty_worktree: Worktree is broadly dirty; reviewed current disk state and scoped verification to Todo 13 repair/task files without reverting unrelated changes.
- stale_state: Reran required tests and direct probes after reading current files.
- misleading_success_output: Verified concrete statuses, reasons, fill/position presence, wallet balances, exposure, persisted counts, and report counts, not only pytest pass lines.
- malformed_input: NaN/Inf ask price and ask size reject as `MALFORMED_ORDERBOOK` with depth check disabled.
- paper_accounting: Accepted fill updates cash, equity/open-position state, market exposure, and strategy exposure; malformed/stale paths leave wallet unchanged.
- no_real_trading: Scoped grep found no private-key, secure CLOB client, live order submit/cancel, or redemption symbols.
- storage_logging: Rejected-signal persistence errors are logged with context; paper returned fields are assigned only after persistence; scheduler probes/tests verify persisted/logged paper decisions in normal paths.
- programming_quality: Touched files are under 250 pure LOC; compileall and behavioral tests pass. Broad scheduler exception boundaries remain as existing loop isolation but are no longer silent for the repaired paths.
- remove_ai_slops_overfit: No needless abstraction, no deletion-only/tautological tests, no implementation-mirroring mocks, no removal-only tests, and no unnecessary extraction/parsing/normalization were introduced.
- env_secrecy: Did not read `.env` or dotenv file contents.
- cleanup: No repo sqlite/db runtime artifacts and no long-lived app/pytest processes after verification.

## exactEvidenceGaps

- `ruff` and `basedpyright` are not installed in `.venv`, so lint/typecheck could not be independently run.
- The shared worktree contains many unrelated pre-existing modifications and untracked files; this gate confirms only the Todo 13 paper repair scope named above.
