# Todo 13 Gate Review

recommendation: REJECT

## originalIntent

Complete paper simulator fills, wallet accounting, exposure tracking, persistence/logging, reporting, and stale-fill rejection for paper-only trading. The user-visible result should be a paper simulator/scheduler path where accepted signals produce paper orders, valid books fill at best ask plus configured slippage, invalid/stale/missing/depth-deficient books reject without wallet/position mutation, reports expose meaningful paper order/fill/rejection/stale-fill counts, and no real trading path is introduced.

## desiredOutcome

- Accepted/published signals create persisted paper orders.
- Filled paper orders use target-token best ask, configured slippage, and depth checks.
- Stale, missing, malformed, and insufficient-depth orderbooks create rejected paper orders without fills, positions, or wallet mutation.
- Filled decisions persist paper order, fill, position, and wallet snapshot; rejected decisions persist/log paper order and wallet snapshot only.
- Daily reports count paper orders from `paper_orders`, fills from `paper_fills`, rejected orders from rejected `paper_orders`, and stale fills as stale `FILLED` rows only.
- No private key, authenticated CLOB client, live submit/cancel/redeem path, or other real trading capability is added.

## userOutcomeReview

NEEDS FIX. The main required tests pass and the ordinary stale/missing/rejection path is implemented, but malformed input handling is incomplete. A non-finite ask price is accepted as a filled paper order when depth checking is disabled by config, producing `fill_price=nan` and debiting wallet cash. That violates the requested behavior that malformed orderbooks reject without fill, position, or wallet mutation.

The executor evidence also overstates review coverage: the submitted code-review artifact is a self-review and does not explicitly cover the same `remove-ai-slops` overfit/slop criteria required by the gate.

## blockers

1. Malformed non-finite ask can fill and mutate wallet.
   - Evidence: `src/polysignal_lab/paper/fill_model.py:31` only rejects levels where `price <= 0` or `size <= 0`; it does not reject `NaN` or non-finite numeric values. Python comparisons with `NaN` at `src/polysignal_lab/paper/fill_model.py:33` and `src/polysignal_lab/paper/fill_model.py:36` are false, so the code can continue to fill.
   - Probe run:
     - `nan_depth_on REJECTED INSUFFICIENT_DEPTH None 1000.0`
     - `inf_depth_on REJECTED ASK_ABOVE_MAX_ENTRY None 1000.0`
     - `nan_depth_off FILLED None nan 990.0`
     - `inf_depth_off REJECTED ASK_ABOVE_MAX_ENTRY None 1000.0`
   - Impact: with `settings.paper_trading.fill_model.require_depth_check = False`, `PaperSimulator.process_signal(...)` returns `FILLED`, creates a fill with `fill_price=nan`, and debits cash from `1000.0` to `990.0`. This fails malformed_input and paper_accounting acceptance.

2. Code-review artifact coverage is insufficient for the required gate.
   - Evidence: `.omo/evidence/complete-prd-old-remove-demo-todo-13-code-review.md` is titled `Todo 13 Self-Review`, reports "pass with one tooling limitation", and contains only broad "Quality/slop risks" bullets.
   - Gap: it does not explicitly show a remove-ai-slops overfit/slop pass over tests and production code, including overfit tests, tautological tests, implementation-mirroring tests, deletion-only tests, needless abstraction, or malformed-input adversarial coverage.
   - Gate rule applied: report coverage cannot replace direct review, and missing/unsupported slop coverage is a rejection condition.

3. Programming-quality slop remains in a claimed changed file.
   - Evidence: `src/polysignal_lab/app/scheduler_processing.py:62-66` catches `Exception` and silently `pass`es while storing rejected signals. `src/polysignal_lab/app/scheduler_processing.py:108-120` also wraps the whole paper-trading path in broad `except Exception`.
   - Impact: this creates false confidence around "all fill decisions are logged/persisted"; a persistence or simulator bug can be swallowed after logging an error and return a result without a paper order. This violates the programming skill's broad/silent-exception criteria for changed Python code.

## checkedArtifactPaths

- `.omo/evidence/task-13-complete-prd-old-remove-demo.txt`
- `.omo/evidence/complete-prd-old-remove-demo-todo-13-code-review.md`
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
- `src/polysignal_lab/storage/sqlite_store.py`
- `tests/test_paper_simulation.py`
- `tests/test_scheduler_paper.py`
- `tests/conftest.py`
- `tests/factories.py`

## commandsRun

- `find /home/gyue/polysignal-lab -name AGENTS.md -print`
  - No governing workspace `AGENTS.md` found.
- `git status --short && git diff --stat && git diff -- <claimed task files>`
  - Worktree is dirty; several claimed task files are untracked, so current disk state was inspected directly.
- `.venv/bin/python -m pytest tests/test_paper_simulation.py tests/test_scheduler_paper.py -q`
  - Passed: `12 passed`.
- `.venv/bin/python -m pytest tests/test_paper_simulation.py::test_accepted_signal_fills_at_best_ask_and_updates_wallet -q`
  - Passed: `1 passed`.
- `.venv/bin/python -m pytest tests/test_paper_simulation.py::test_stale_orderbook_rejects_fill_without_position tests/test_scheduler_paper.py::test_stale_paper_fill_count_is_zero -q`
  - Passed: `2 passed`.
- `.venv/bin/python -m compileall -q <claimed task files>`
  - Passed with exit code 0.
- Non-finite orderbook probe using `PaperSimulator` and current `Settings`
  - Demonstrated `NaN` ask fills when `require_depth_check=False`.
- `rg -n "private_key|mnemonic|SecureClient|ClobClient\\(|create_order|post_order|submit_order|cancel_order|redeem_positions" <reviewed scope>`
  - No matches.
- `find . -maxdepth 3 -type f \( -name '*.sqlite' -o -name '*.sqlite3' -o -name '*.db' \) -not -path './.venv/*' -print`
  - No repo sqlite/db artifacts found.
- `pgrep -af '[p]olysignal_lab.app.main|[p]ytest' || true`
  - No long-lived app/pytest process found.
- Per-file pure LOC `awk` over claimed files
  - `fill_model.py` 52, `simulator.py` 104, `scheduler_processing.py` 151, `scheduler_reporting.py` 155, `paper_result.py` 68, `report.py` 90, `test_paper_simulation.py` 132, `test_scheduler_paper.py` 63.

## adversarialClasses

- dirty_worktree: Reviewed current disk state and noted untracked claimed files; dirty worktree prevents trusting diff-only evidence.
- stale_state: Reran required tests and direct probes against current files.
- misleading_success_output: Required pytest scenarios pass, but direct malformed probe contradicts the DoneClaim's malformed-input guarantee.
- malformed_input: Fails for non-finite ask with depth checking disabled.
- paper_accounting: Fails in that malformed scenario because wallet cash is debited to `990.0` and fill price is `nan`.
- no_real_trading: Scoped grep found no private key, CLOB secure client, submit/cancel/redeem symbol in reviewed task scope.
- storage_logging: Normal filled/rejected paths persist/log expected rows; broad exception handling still weakens the "all decisions" claim.
- programming_quality: Broad/silent `except Exception` remains in a claimed changed Python file.
- remove_ai_slops_overfit: Direct pass found a missing malformed numeric test and insufficient code-review artifact coverage.
- env_secrecy: No `.env` or dotenv file content was read.
- cleanup: No repo sqlite/db artifacts and no long-lived app/pytest processes observed after verification.

## exactEvidenceGaps

- No test covers `BookLevel(price=nan, size=...)` or other non-finite malformed levels.
- No test toggles `settings.paper_trading.fill_model.require_depth_check = False` to prove malformed books reject independently of depth checking.
- The code-review artifact does not document a category-by-category slop/overfit pass and does not catch the non-finite malformed-input hole.
- Static tooling remains unavailable per executor report; basedpyright/ruff claims are not independently green.

