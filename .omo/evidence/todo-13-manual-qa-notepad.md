# Todo 13 Manual QA Notepad

Happy scenario:
- Invocation: `.venv/bin/python -m pytest tests/test_paper_simulation.py::test_accepted_signal_fills_at_best_ask_and_updates_wallet -q`
- Result: passed, output summary `1 passed`.
- Binary observables asserted by the test: paper order status `FILLED`; `raw_best_ask` equals target-side book best ask; fill price equals best ask plus configured slippage; wallet cash balance `990.0`; wallet equity `1000.0`; open position count `1`; market exposure `10.0`; strategy exposure `10.0`; fill decision reason `FILLED`; available depth is at least stake.
- What this proves: accepted paper signals fill from target-side best ask/depth and update wallet/exposure without real trading.
- Captured artifact path: `.omo/evidence/todo-13-manual-qa-notepad.md`

Failure scenario:
- Invocation: `.venv/bin/python -m pytest tests/test_paper_simulation.py::test_stale_orderbook_rejects_fill_without_position tests/test_scheduler_paper.py::test_stale_paper_fill_count_is_zero -q`
- Result: passed, output summary `2 passed`.
- Binary observables asserted by the tests: stale order status `REJECTED`; reject reason `STALE_ORDERBOOK`; no fill; no position; wallet cash/equity unchanged; open position count `0`; persisted order metrics reason `STALE_ORDERBOOK`; report paper orders `1`; report fills `0`; rejected paper orders `1`; stale paper fills `0`; persisted fills and positions counts `0`.
- What this proves: stale books are rejected without creating positions, rejection decisions are persisted, and the explicit stale-fill metric remains zero.
- Captured artifact path: `.omo/evidence/todo-13-manual-qa-notepad.md`

Additional failure coverage:
- Invocation: `.venv/bin/python -m pytest tests/test_paper_simulation.py::test_missing_and_malformed_orderbooks_reject_without_position tests/test_scheduler_paper.py::test_missing_orderbook_persists_rejected_paper_order_without_fill -q`
- Result: covered during the acceptance suite.
- Binary observables asserted by tests: missing book reject reason `MISSING_ORDERBOOK`; malformed book reject reason `MALFORMED_ORDERBOOK`; scheduler persists/logs missing-book paper order; fills and positions remain zero.

NaN malformed-orderbook repair scenario:
- Red invocation before production fix: `.venv/bin/python -m pytest tests/test_paper_simulation.py::test_nan_ask_rejects_malformed_without_depth_check -q`
- Red result: failed, output summary `1 failed`; binary observable was order status `FILLED` when the test expected `REJECTED`.
- Green invocation after production fix: `.venv/bin/python -m pytest tests/test_paper_simulation.py::test_nan_ask_rejects_malformed_without_depth_check -q`
- Green result: passed, output summary `1 passed`.
- Binary observables asserted by the test: `require_depth_check=False`; NaN ask rejects with `MALFORMED_ORDERBOOK`; no fill; no position; wallet cash balance `1000.0`; wallet equity `1000.0`; open position count `0`; market exposure `0.0`; fill decision reason `MALFORMED_ORDERBOOK`.
- What this proves: non-finite ask prices cannot bypass depth checking to fill or debit wallet cash.
- Captured artifact path: `.omo/evidence/todo-13-manual-qa-notepad.md`

Repair acceptance scenario:
- Invocation: `.venv/bin/python -m pytest tests/test_paper_simulation.py tests/test_scheduler_paper.py -q`
- Result: passed, output summary `13 passed`.
- Binary observables covered by the suite: accepted fill accounting still works; stale/missing/malformed/depth rejections do not create positions; scheduler paper rejection persistence/report counts still work; NaN malformed orderbook rejects without wallet mutation.
- Captured artifact path: `.omo/evidence/task-13-complete-prd-old-remove-demo.txt`
