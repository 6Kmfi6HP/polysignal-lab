# Todo 9 Gate Review

recommendation: REJECT

## originalIntent
Implement Todo 9, "Implement VWAP Momentum PRD semantics," so VWAP Momentum follows PRD-old behavior for VWAP/deviation, momentum, z_score, favorite side, target ask, entry window, orderbook freshness/spread, and accepted-signal reason/metric output without demo/fake product data.

## desiredOutcome
Todo 9 can be checked off only if the implementation, tests, manual QA, and review artifacts prove the PRD semantics from `docs/PRD-old.md:203-253` and config sample at `docs/PRD-old.md:884-899`, with no unresolved programming/remove-ai-slops blockers.

## userOutcomeReview
Behavioral tests passed locally and the threshold values in the PRD sample config support fractional ratio interpretation: `min_deviation_pct: 0.015` means 1.5% as a ratio, `min_momentum: 0.01` means 1% as a ratio, and `min_z_score: 1.2` is unitless. The implementation logic uses those ratio units in `src/polysignal_lab/strategies/vwap_momentum.py:202-214` and config values match `docs/PRD-old.md:895-897`.

Todo 9 should not be marked complete yet because the shipped production code still contains stale/misleading strategy docstring text on the exact high-risk semantics under review, and the supplied code-review artifact does not explicitly document the required programming/remove-ai-slops skill-perspective coverage.

## blockers
1. `src/polysignal_lab/strategies/vwap_momentum.py:90-92` contains stale/misleading production documentation:
   - line 90 says deviation is multiplied by 100, while the implemented and PRD-sampled threshold semantics use fractional ratios.
   - line 92 says favorite side is based on higher last-trade price, while the implementation uses `snapshot.favorite_side`, which is based on current UP/DOWN asks in `src/polysignal_lab/domain/snapshot.py:84-87`.
   This is unresolved remove-ai-slops/programming slop because it creates direct threshold-unit and favorite-side ambiguity in the changed strategy.
2. `.omo/evidence/complete-prd-old-remove-demo-todo-9-code-review.md:17-21` lists tests, compile, grep, and LOC checks, but does not explicitly show the required programming skill-perspective pass or remove-ai-slops overfit/slop criterion coverage. The task evidence file mentions `remove_ai_slops_overfit`, but the code review report itself does not provide that coverage.

## checkedArtifactPaths
- `.omo/plans/complete-prd-old-remove-demo.md`
- `.omo/evidence/task-9-complete-prd-old-remove-demo.txt`
- `.omo/evidence/complete-prd-old-remove-demo-todo-9-code-review.md`
- `.omo/evidence/todo-9-manual-qa-notepad.md`
- `docs/PRD-old.md`
- `src/polysignal_lab/strategies/base.py`
- `src/polysignal_lab/strategies/vwap_momentum.py`
- `src/polysignal_lab/strategies/config.py`
- `src/polysignal_lab/config.py`
- `config/signal_bot.yaml`
- `tests/test_vwap_momentum.py`
- `tests/test_strategies.py`

## commandsAndResults
- `git status --short`: dirty worktree with broad unrelated changes; scoped Todo 9 files include modified `config/signal_bot.yaml`, `src/polysignal_lab/config.py`, `src/polysignal_lab/strategies/vwap_momentum.py`, and untracked plan/evidence/docs/tests/config files.
- `.venv/bin/python -m pytest tests/test_vwap_momentum.py tests/test_strategies.py -q`: PASS, `.......... [100%]`.
- `.venv/bin/python -m pytest tests/test_vwap_momentum.py::test_vwap_momentum_emits_buy_up_and_down_with_z_score -q`: PASS, `. [100%]`.
- `.venv/bin/python -m pytest tests/test_vwap_momentum.py::test_vwap_momentum_rejects_below_z_score_threshold tests/test_vwap_momentum.py::test_vwap_momentum_rejects_stale_or_wide_spread_book -q`: PASS, `.. [100%]`.
- `.venv/bin/python -m py_compile src/polysignal_lab/strategies/base.py src/polysignal_lab/strategies/vwap_momentum.py src/polysignal_lab/strategies/config.py src/polysignal_lab/config.py tests/test_vwap_momentum.py tests/test_strategies.py`: PASS.
- Quality grep for `Any`, `cast(`, `type: ignore`, `import asyncio`, `import pandas`, broad exceptions, and raw `dict[str, Any]`/`dict[str, object]` across scoped Python: PASS, no matches.
- Demo/fake data grep across Todo 9 source/test/config surface: PASS, no matches.
- `Settings.from_yaml('config/signal_bot.yaml')` VWAP assertions: PASS, `vwap yaml ok`.
- Pure LOC scan: `vwap_momentum.py 226`, `strategies/config.py 91`, `tests/test_vwap_momentum.py 158`, `tests/test_strategies.py 53`; warning band only, no >250 defect.
- `.env` secrecy: `test -e .env` only checked existence and did not read contents.
- Long-lived process check for pytest/app/uvicorn: PASS, no matches.

## adversarialChecks
- dirty_worktree: Checked. Broad dirty worktree exists; no revert attempted.
- stale_state: Checked. Local reruns support behavioral claims; plan Todo 9 checkbox remains unchecked, which is consistent with gate-review status.
- misleading_success_output: Checked. Passing tests assert concrete signal fields, but stale production docstring remains a misleading artifact.
- malformed_input: Checked. Tests cover stale/wide book, z_score reject, momentum mismatch, and entry-window reject.
- strategy_semantics: Mostly satisfied behaviorally; active, freshness, spread, target ask, entry window, VWAP/deviation, momentum, z_score, and favorite side gates are concrete.
- threshold_units: Logic/config match PRD fractional ratios, but stale docstring contradicts the unit interpretation.
- no_demo_data: Checked. No demo/fake terms in Todo 9 source/test/config surface.
- programming_quality: Compile and grep passed; stale misleading docstring remains a quality blocker.
- remove_ai_slops_overfit: Tests are behavioral, not private-helper mirrors; stale docstring and missing review-report coverage remain blockers.
- env_secrecy: Checked without reading `.env`.

## exactEvidenceGaps
- Code-review report lacks explicit programming/remove-ai-slops criterion coverage required by the gate instructions.
- Production strategy docstring contradicts the fractional threshold-unit and current-orderbook favorite-side semantics that the user explicitly asked to verify.

