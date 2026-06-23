# Todo 4 Gate Review

date: 2026-06-22
recommendation: APPROVE

## originalIntent

Todo 4 was intended to constrain runtime config, schema, docs, and factory behavior to PRD-old strategy/assets only: VWAP Momentum, Late Consensus, PTB Diff; BTC/ETH/SOL/XRP only where applicable; no `skew_mean_reversion`, DOGE, BNB, HYPE, or PRD-facing `SPLIT`.

The latest repair specifically claimed removal of the unused `ValidationError` import from `src/polysignal_lab/config.py`, updated code-review evidence for dead-import coverage, and continued passing config/strategy acceptance tests.

## desiredOutcome

The user should receive a current, independently verified Todo 4 state where:

- `src/polysignal_lab/config.py` has no unused `ValidationError` import and no forbidden Python escape hatches in the touched config surfaces.
- `LateConsensusConfig.stop_loss_per_coin` is a typed Pydantic boundary value, not `dict[str, dict]`.
- malformed stop-loss and non-PRD strategy config inputs are rejected by behavior tests.
- `load_settings(...)` is the only config loader API in current source/tests/config; the dead `load_config(...)` helper is gone.
- current PRD-facing source/docs/config contain no forbidden non-PRD strategy/assets or `SPLIT`.
- the code-review artifact covers programming quality, dead imports, raw public fields, helper/dead abstractions, overfit/deletion-only tests, SPLIT, result states, and `dict[str, dict]`.

## userOutcomeReview

Current source, tests, docs/config scans, and evidence artifacts support checking off Todo 4. The prior blocker in this gate file is resolved: `src/polysignal_lab/config.py` no longer imports `ValidationError`, and the requested forbidden-token scan over `src/polysignal_lab/config.py` plus `src/polysignal_lab/strategies/config.py` returns no matches.

The current factory/config manual load prints only `['vwap_momentum', 'late_consensus', 'ptb_diff']` twice. Focused pytest passes with all 9 tests. The PRD-facing grep probes for non-PRD strategy/assets, `SPLIT`, and `load_config(` are clean.

The direct remove-ai-slops/programming pass found no remaining blocker in the scoped files. `src/polysignal_lab/config.py` remains in the programming warning band at 212 pure LOC, but it is below the 250 LOC defect threshold and this latest repair removed code instead of adding responsibility.

## checkedArtifactPaths

- `src/polysignal_lab/config.py`
- `src/polysignal_lab/strategies/config.py`
- `src/polysignal_lab/strategies/factory.py`
- `tests/test_config.py`
- `tests/test_strategies.py`
- `config/signal_bot.yaml`
- `.omo/evidence/complete-prd-old-remove-demo-todo-4-code-review.md`
- `.omo/evidence/complete-prd-old-remove-demo-todo-4-gate-review.md`

## commandsInspected

- `sed -n '1,260p' /home/gyue/.codex/plugins/cache/sisyphuslabs/omo/4.12.1/skills/programming/SKILL.md`
- `sed -n '1,260p' /home/gyue/.codex/plugins/cache/sisyphuslabs/omo/4.12.1/skills/remove-ai-slops/SKILL.md`
- `sed -n '1,260p' /home/gyue/.codex/plugins/cache/sisyphuslabs/omo/4.12.1/skills/programming/references/python/README.md`
- `git status --short` -> dirty worktree inspected only
- `rg -n "ValidationError|\bAny\b|cast\(|type:\s*ignore|import asyncio|import pandas|except (Exception|BaseException)|dict\[str, dict\]" src/polysignal_lab/config.py src/polysignal_lab/strategies/config.py` -> exit 1, empty stdout
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_config.py tests/test_strategies.py -q` -> exit 0, `9 passed`
- `bash -lc '! rg "skew_mean_reversion|DOGE|BNB|HYPE" config src README.md docs/PRD_OLD_COMPLIANCE.md'` -> exit 0, empty stdout
- `rg -n "SPLIT" README.md docs src tests config` -> exit 1, empty stdout
- `rg -n "load_config\(" src tests config` -> exit 1, empty stdout
- `test -f .omo/evidence/complete-prd-old-remove-demo-todo-4-code-review.md && rg "dead-import|ValidationError|programming|raw public field|helper|overfit|deletion-only|SPLIT|WIN/LOSS/VOID/UNKNOWN|dict\[str, dict\]" .omo/evidence/complete-prd-old-remove-demo-todo-4-code-review.md` -> exit 0 with required coverage terms present
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "from polysignal_lab.config import load_settings; from polysignal_lab.strategies.factory import build_strategies; settings = load_settings('config/signal_bot.yaml'); print([strategy.name for strategy in build_strategies(settings.strategies)]); print([strategy.name for strategy in build_strategies(load_settings('config/signal_bot.yaml').strategies)])"` -> exit 0, printed `['vwap_momentum', 'late_consensus', 'ptb_diff']` twice
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_config.py::test_late_consensus_stop_loss_config_rejects_malformed_entry tests/test_config.py::test_non_prd_strategy_config_rejected tests/test_config.py::test_strategy_factory_builds_only_prd_strategies -q` -> exit 0, 3 passed
- `awk '!/^[[:space:]]*$/ && !/^[[:space:]]*(#|\/\/)/' src/polysignal_lab/config.py | wc -l` -> 212
- `awk '!/^[[:space:]]*$/ && !/^[[:space:]]*(#|\/\/)/' src/polysignal_lab/strategies/config.py | wc -l` -> 88
- `awk '!/^[[:space:]]*$/ && !/^[[:space:]]*(#|\/\/)/' tests/test_config.py | wc -l` -> 43

## blockers

None.

## exactEvidenceGaps

- Ruff was not used as independent lint evidence because this verification followed the user-requested repro list and direct source inspection. The focused pytest, grep probes, manual factory load, and direct slop/programming pass were sufficient for the latest Todo 4 dead-import repair.
- The worktree remains dirty with broad Todo 4 changes and untracked project files; this was inspected as current state and is not a blocker for checking off Todo 4.
- `.env` was not read.

## final

APPROVE
