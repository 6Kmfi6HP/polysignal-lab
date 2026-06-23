# Todo 9 Manual QA Notepad

Manual QA scope:
- Verify VWAP Momentum PRD behavior from deterministic strategy-level scenarios.
- Avoid `.env` and avoid live/demo/fake market data.

Scenarios executed:
- Red-first: `tests/test_vwap_momentum.py` failed before implementation for missing z_score reason/gate and stale book rejection.
- Happy: `test_vwap_momentum_emits_buy_up_and_down_with_z_score` passed and asserted BUY_UP/BUY_DOWN sides plus reason/metric output.
- Failure: `test_vwap_momentum_rejects_below_z_score_threshold` passed.
- Failure: `test_vwap_momentum_rejects_stale_or_wide_spread_book` passed.
- Failure: `test_vwap_momentum_rejects_momentum_mismatch` passed in the full VWAP suite.
- Failure: `test_vwap_momentum_rejects_outside_entry_window` passed in the full VWAP suite.

Concrete observables:
- Required suite: `.venv/bin/python -m pytest tests/test_vwap_momentum.py tests/test_strategies.py -q` -> `.......... [100%]`.
- Happy QA: `.venv/bin/python -m pytest tests/test_vwap_momentum.py::test_vwap_momentum_emits_buy_up_and_down_with_z_score -q` -> `. [100%]`.
- Failure QA: `.venv/bin/python -m pytest tests/test_vwap_momentum.py::test_vwap_momentum_rejects_below_z_score_threshold tests/test_vwap_momentum.py::test_vwap_momentum_rejects_stale_or_wide_spread_book -q` -> `.. [100%]`.
- YAML compatibility: Settings loaded `config/signal_bot.yaml` and asserted PRD VWAP values.
- Cleanup: process scan showed no long-lived pytest/app/uvicorn process after verification.

Notes:
- Deterministic factories create real-shaped `MarketSnapshot` and `OrderBook` instances. No product demo data was used.
- `.env` existence was checked without reading contents.
