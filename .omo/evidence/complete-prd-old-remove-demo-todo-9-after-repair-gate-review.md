# Todo 9 After-Repair Gate Review

recommendation: APPROVE

## originalIntent
Implement Todo 9, "Implement VWAP Momentum PRD semantics," so VWAP Momentum follows `docs/PRD-old.md` behavior for VWAP/deviation, momentum, z_score, favorite side, target ask, active market, entry window, orderbook freshness/spread, and accepted-signal reason/metric output without product demo/fake market data.

## desiredOutcome
Todo 9 can be checked off after the narrow repair only if the prior stale docstring blocker and missing review-artifact coverage blocker are fixed, and the original Todo 9 behavior remains verified by deterministic local tests and greps.

## userOutcomeReview
The shipped artifact now satisfies the user-visible Todo 9 outcome. The strategy docstring documents fractional ratio threshold semantics and snapshot ask-side favorite semantics. The implementation gates on active market, orderbook freshness, spread, target ask range, entry window, VWAP/deviation, momentum, z_score, and favorite side, then emits concrete reason codes and metrics. The project config loads the shipped VWAP block with `min_deviation_pct == 0.015`, `min_momentum == 0.01`, and `min_z_score == 1.2`.

The prior blockers are resolved:
- `src/polysignal_lab/strategies/vwap_momentum.py:89-95` now says deviation and momentum thresholds are fractional ratios and `0.015` means 1.5%; it no longer says deviation is `* 100` or that favorite side comes from higher last-trade price.
- `.omo/evidence/complete-prd-old-remove-demo-todo-9-code-review.md` now includes explicit `Programming skill coverage` and `Remove-ai-slops / overfit coverage` sections.

## blockers
None.

## checkedArtifactPaths
- `.omo/plans/complete-prd-old-remove-demo.md`
- `.omo/evidence/task-9-complete-prd-old-remove-demo.txt`
- `.omo/evidence/complete-prd-old-remove-demo-todo-9-gate-review.md`
- `.omo/evidence/complete-prd-old-remove-demo-todo-9-code-review.md`
- `.omo/evidence/todo-9-manual-qa-notepad.md`
- `docs/PRD-old.md`
- `src/polysignal_lab/domain/snapshot.py`
- `src/polysignal_lab/strategies/vwap_momentum.py`
- `src/polysignal_lab/strategies/config.py`
- `src/polysignal_lab/config.py`
- `config/signal_bot.yaml`
- `tests/test_vwap_momentum.py`
- `tests/test_strategies.py`

## commandsAndResults
- `git status --short`: dirty worktree with broad unrelated modifications/deletions/untracked files; scoped Todo 9 files remain modified/untracked as expected. No revert attempted.
- `PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-o cache_dir=/tmp/polysignal-lab-pytest-cache-todo9-gate' .venv/bin/python -m pytest tests/test_vwap_momentum.py tests/test_strategies.py -q`: PASS, `.......... [100%]`.
- `PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-o cache_dir=/tmp/polysignal-lab-pytest-cache-todo9-gate' .venv/bin/python -m pytest tests/test_vwap_momentum.py::test_vwap_momentum_emits_buy_up_and_down_with_z_score -q`: PASS, `. [100%]`.
- `PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-o cache_dir=/tmp/polysignal-lab-pytest-cache-todo9-gate' .venv/bin/python -m pytest tests/test_vwap_momentum.py::test_vwap_momentum_rejects_below_z_score_threshold tests/test_vwap_momentum.py::test_vwap_momentum_rejects_stale_or_wide_spread_book -q`: PASS, `.. [100%]`.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/polysignal-lab-pycompile-todo9-gate .venv/bin/python -m py_compile src/polysignal_lab/strategies/vwap_momentum.py src/polysignal_lab/strategies/config.py src/polysignal_lab/config.py tests/test_vwap_momentum.py tests/test_strategies.py`: PASS.
- Quality grep for `Any`, `cast(`, `type: ignore`, `import asyncio`, `import pandas`, `except Exception`, `except BaseException`, and raw `dict[str, Any]`/`dict[str, object]` in scoped Python: PASS, no matches.
- Stale docstring grep for `* 100 (percentage)`, `higher last-trade price`, `higher last trade price`, and `Favorite side = the token`: PASS, no matches.
- Demo/fake data grep for `demo_data|run_demo|fake data|offline demo|fake market|demo market` across the Todo 9 source/test/config surface: PASS, no matches.
- Obsolete threshold grep for `min_momentum_pct`, `deviation_pct: 3.0`, and `max_deviation_pct: 100.0`: PASS, no matches.
- Sanitized project config load: PASS, `vwap yaml ok 0.015 0.01 1.2 0.03 60000`.
- Pure LOC scan: `vwap_momentum.py 228`, `strategies/config.py 91`, `src/polysignal_lab/config.py 212`, `tests/test_vwap_momentum.py 158`, `tests/test_strategies.py 53`; no file exceeds the 250 pure-LOC defect threshold.
- `.env` secrecy: only existence was checked (`./.env`); contents were not read.
- Long-lived process check for pytest/app/uvicorn: PASS, no matches.

## adversarialChecks
- dirty_worktree: Checked. The worktree is broadly dirty from this larger plan; Todo 9 review was scoped and did not revert anything.
- stale_state: Checked. I reran the required tests and greps after the narrow repair rather than relying on prior success prose.
- misleading_success_output: Checked. Tests assert concrete `SignalCandidate` side, reason codes, and metrics; direct source inspection confirms matching production gates.
- malformed_input: Checked. Test coverage includes z_score rejection, stale/wide orderbook rejection, momentum mismatch, and entry-window rejection.
- strategy_semantics: Checked. The source gates on active market, freshness, spread, target ask range, entry window, VWAP/deviation, momentum, z_score, and favorite side.
- threshold_units: Checked. PRD sample, YAML, config model, strategy logic, and docstring use fractional ratio interpretation.
- no_demo_data: Checked. No demo/fake terms in Todo 9 task surface; tests use deterministic real-shaped factories, not product demo data.
- programming_quality: Checked against the loaded programming criteria. Scoped Python greps passed, compile passed, and no file crosses the 250 pure-LOC defect threshold.
- remove_ai_slops_overfit: Checked against the loaded remove-ai-slops criteria. No stale docstring text remains; tests are public behavior tests, not deletion-only, tautological, or private-helper mirrors; no unnecessary new parsing/normalization/extraction blocker found.
- env_secrecy: Checked. `.env` contents were not read, and config loading was run under a sanitized environment.

## exactEvidenceGaps
None blocking. The prior rejection remains as historical evidence, but its two blockers are now resolved by current source and current code-review artifact content.
