# Todo 11 Code Review

Verdict: PASS with noted residual risk.

Reviewed scope:
- `src/polysignal_lab/strategies/config.py`
- `src/polysignal_lab/strategies/ptb_diff.py`
- `src/polysignal_lab/config.py`
- `config/signal_bot.yaml`
- `tests/test_ptb_diff.py`
- `tests/test_strategies.py`

Findings:
- PASS: PTB row schema now uses PRD trigger fields and rejects old probability-band rows via `PTBTriggerConfig(extra="forbid")`.
- PASS: PTB evaluator uses directional UP/DOWN logic, max token price, probability edge, diff threshold, and min/max seconds-to-close gates before emitting a signal.
- PASS: Accepted signals include concrete PRD reason codes and metrics for trigger, diff, token ask, directional probability, probability edge, time window, spread, freshness, and TP/SL thresholds.
- PASS: Malformed and unsupported inputs reject without candidate emission in `tests/test_ptb_diff.py`.
- PASS: No real trading path was added; touched strategy code only emits `SignalCandidate`.
- WARN: The PRD does not define a formula for `probability_edge`; implementation uses directional payoff probability at current spot state minus token ask and records the inputs in metrics.
- WARN: The multi-agent `review-work` toolchain was unavailable in this session; review was performed locally with tests, py_compile, greps, LOC scan, and manual code inspection.

Verification:
- `.venv/bin/python -m pytest tests/test_ptb_diff.py tests/test_strategies.py -q` -> pass, 12 tests.
- `.venv/bin/python -m pytest tests/test_ptb_diff.py::test_ptb_diff_emits_buy_up_and_down_from_trigger_rows -q` -> pass.
- `.venv/bin/python -m pytest tests/test_ptb_diff.py::test_ptb_diff_rejects_above_max_token_price tests/test_ptb_diff.py::test_ptb_diff_rejects_below_probability_edge -q` -> pass.
- `.venv/bin/python -m py_compile ...` -> pass.
- Targeted quality greps -> no matches for banned escape hatches or old runtime condition usage.

Programming perspective:
- The changed PTB strategy/config/test files stay under the 250 pure-LOC ceiling recorded in task evidence.
- Scoped quality checks found no `Any`, `cast(`, `type: ignore`, `import asyncio`, `import pandas`, broad exceptions, or raw `dict[str, Any]` / `dict[str, object]` in the Todo 11 touched Python files.
- The old `min_prob` / `max_prob` / `time_sec` runtime condition shape is removed from product strategy/config/YAML paths and rejected by the new frozen `PTBTriggerConfig(extra="forbid")`.
- The implementation keeps a typed `SignalCandidate` boundary and does not introduce real order placement, authenticated trading clients, or untyped runtime dispatch.

Remove-ai-slops / overfit coverage:
- Tests exercise public strategy behavior through `PTBDiffStrategy.evaluate()` with real-shaped `MarketSnapshot`, `OrderBook`, and `SpotPrice` objects rather than private helper assertions.
- The red/green path included real rejected classes: old probability-band row shape, token price ceiling, probability edge, diff magnitude, direction, time window, missing PTB/spot/book, unverified PTB, wrong asset/timeframe, stale data, and wide spread.
- No deletion-only, tautological, log-only, or implementation-mirroring tests were used for Todo 11 acceptance.
- No needless abstraction, broad defensive catch, dead code path, duplicated trigger branch cascade, or performance-equivalence churn was added in the scoped Todo 11 changes.
- Oversized-module criterion passed for touched Python files; no Todo 11 touched file exceeds 250 pure LOC.

Conclusion:
- No blocking issue found in the Todo 11 implementation.
