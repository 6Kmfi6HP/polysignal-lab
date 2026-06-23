recommendation: APPROVE

# Todo 11 Gate Review After Artifact Repair

## blockers
None.

## originalIntent
Verify whether Todo 11, "Implement PTB Diff PRD trigger schema and probability-edge logic," can be marked complete after the prior artifact-only rejection.

## desiredOutcome
Todo 11 is complete only if PTB Diff uses PRD trigger rows with `min_diff_usd`, `max_token_price`, `min_probability_edge`, and min/max seconds-to-close fields; old `min_prob` / `max_prob` / `time_sec` / `conditions` runtime semantics are absent from product strategy/config/YAML paths; BUY_UP and BUY_DOWN accept/reject behavior is covered; no real trading endpoint or live order path was added; deterministic tests, py_compile, greps, and runtime YAML parsing pass; and the code-review artifact explicitly covers the programming perspective and remove-ai-slops/overfit criteria.

## userOutcomeReview
The shipped Todo 11 outcome matches the user-visible request. `config/signal_bot.yaml` contains the PRD trigger-row shape for BTC 5m/15m PTB Diff. `Settings.from_yaml("config/signal_bot.yaml")` parses those rows into `PTBTriggerConfig` instances. `PTBDiffStrategy.evaluate()` emits only `SignalCandidate` objects after direction, diff magnitude, token ask ceiling, probability-edge, seconds-to-close, spread, orderbook freshness, and spot freshness gates.

The prior artifact blocker is resolved. `.omo/evidence/complete-prd-old-remove-demo-todo-11-code-review.md` now includes explicit `Programming perspective` and `Remove-ai-slops / overfit coverage` sections, including the 250 pure-LOC criterion, banned escape-hatch grep, old-runtime-shape removal, behavior-test shape, and overfit/slop checks.

## checkedArtifactPaths
- `.omo/plans/complete-prd-old-remove-demo.md`
- `.omo/evidence/task-11-complete-prd-old-remove-demo.txt`
- `.omo/evidence/complete-prd-old-remove-demo-todo-11-gate-review.md`
- `.omo/evidence/complete-prd-old-remove-demo-todo-11-code-review.md`
- `.omo/evidence/todo-11-manual-qa-notepad.md`
- `docs/PRD-old.md`
- `config/signal_bot.yaml`
- `src/polysignal_lab/config.py`
- `src/polysignal_lab/strategies/config.py`
- `src/polysignal_lab/strategies/ptb_diff.py`
- `tests/test_ptb_diff.py`
- `tests/test_strategies.py`

## directVerification
- `git status --short -- <task paths> .env`: scoped task files are dirty/untracked as expected; `.env` did not appear and was not read. Broader worktree remains dirty outside Todo 11, so unrelated state was treated as stale-state risk rather than approval evidence.
- `.venv/bin/python -m pytest tests/test_ptb_diff.py tests/test_strategies.py -q`: PASS, exit 0, output `............ [100%]`.
- `.venv/bin/python -m pytest tests/test_ptb_diff.py::test_ptb_diff_emits_buy_up_and_down_from_trigger_rows -q`: PASS, exit 0, output `. [100%]`.
- `.venv/bin/python -m pytest tests/test_ptb_diff.py::test_ptb_diff_rejects_above_max_token_price tests/test_ptb_diff.py::test_ptb_diff_rejects_below_probability_edge -q`: PASS, exit 0, output `.. [100%]`.
- `.venv/bin/python -m py_compile src/polysignal_lab/config.py src/polysignal_lab/strategies/config.py src/polysignal_lab/strategies/ptb_diff.py tests/test_ptb_diff.py tests/test_strategies.py`: PASS, exit 0, no output.
- Quality grep for `Any`, `cast(`, `type: ignore`, `import asyncio`, `import pandas`, broad exceptions, raw `dict[str, Any]`, and raw `dict[str, object]` on Todo 11 touched Python/config files: PASS, exit 1, no matches.
- Literal old-semantics grep for `min_prob|max_prob|time_sec|conditions:` on product strategy/config/YAML paths produced substring false positives from `min_probability_edge` and `max_hold_time_sec`. Exact old-key grep `(^|[[:space:]])(min_prob|max_prob|time_sec):|conditions:` on the same product paths: PASS, exit 1, no matches.
- Trading/order grep on touched strategy/config/test files found only safety-deny configuration symbols: `allow_live_market_actions: false` in YAML and the corresponding safety validator in `src/polysignal_lab/config.py`. No real trading endpoint, authenticated order client, create/post/submit/cancel order call, or redemption path was added.
- Runtime YAML parse through `Settings.from_yaml("config/signal_bot.yaml")`: PASS, exit 0. Parsed PTB assets `['BTC']`, timeframes `['5m', '15m']`, and rows `strong_up_late UP 80.0 0.78 0.08 30 180` and `strong_down_late DOWN 80.0 0.78 0.08 30 180`.
- Pure LOC scan: `src/polysignal_lab/config.py` 212, `src/polysignal_lab/strategies/config.py` 114, `src/polysignal_lab/strategies/ptb_diff.py` 182, `tests/test_ptb_diff.py` 195, `tests/test_strategies.py` 54. All are under the 250 pure-LOC defect threshold.

## originalCriterionReview
- PRD trigger schema: PASS. `PTBTriggerConfig` has `min_diff_usd`, `max_token_price`, `min_probability_edge`, `min_seconds_to_close`, and `max_seconds_to_close`.
- Old semantics removed from runtime paths: PASS. Product strategy/config/YAML paths have no exact stale `min_prob`, `max_prob`, `time_sec`, or `conditions:` keys. The old keys remain only inside `tests/test_ptb_diff.py` as a rejection fixture.
- BUY_UP / BUY_DOWN behavior: PASS. Tests assert both sides emit with PRD reason codes and metrics.
- Token price, probability edge, diff, and time-window rejects: PASS. Required focused tests pass.
- No real trading endpoints: PASS. Strategy still only emits `SignalCandidate`; touched config contains safety flags only.
- Probability-edge semantics: PASS. The PRD names `probability_edge` but does not define a numeric formula in the inspected PTB sections. With the current snapshot input surface, `directional_probability - token_ask` is an acceptable inferred edge and is audited in emitted metrics.

## removeAiSlopsOverfitPass
Direct slop/overfit pass found no unresolved blocker. Tests are not deletion-only, tautological, log-only, or private-helper-only. They drive public `PTBDiffStrategy.evaluate()` behavior with real-shaped snapshots and assert observable candidates or no candidates. The old-row schema test verifies a required boundary rejection, not a standalone removal claim. Production changes did not introduce broad defensive catches, dead trigger branches, duplicate variant cascades, needless parsing layers, real trading adapters, or performance churn.

## programmingQualityPass
Direct programming pass found no Todo 11 blocker. The touched files compile, stay under the 250 pure-LOC ceiling, avoid the requested escape hatches, use typed config rows, and use exhaustive `match` handling for `Side` variants in the changed PTB logic/tests. No `.env` content was read.

## adversarialChecks
- dirty_worktree: PASS. Dirty scoped and broader worktree state was inspected and preserved.
- stale_state: PASS. Current plan, prior rejection, repaired code review, manual QA notepad, PRD, YAML, code, and tests were read directly.
- misleading_success_output: PASS. Executor evidence was not trusted; required tests, compile, greps, and YAML parse were rerun locally.
- malformed_input: PASS. Tests cover missing PTB, missing spot, missing side book, unverified PTB, wrong asset, unsupported timeframe, missing seconds, stale data, and wide spread.
- strategy_semantics: PASS. Direction, diff, token price, probability edge, and time-window behavior match Todo 11 scope.
- probability_edge_semantics: PASS. No new contradiction found beyond the already accepted inferred formula.
- no_real_trading: PASS. No real trading addition found in touched files.
- programming_quality: PASS. py_compile, LOC, and banned-pattern grep are clean for Todo 11 scope.
- remove_ai_slops_overfit: PASS. Direct slop pass and repaired code-review artifact coverage are both present.
- env_secrecy: PASS. `.env` was not read.

## exactEvidenceGaps
None. The prior gap in `.omo/evidence/complete-prd-old-remove-demo-todo-11-code-review.md` is repaired and supported by direct verification.
