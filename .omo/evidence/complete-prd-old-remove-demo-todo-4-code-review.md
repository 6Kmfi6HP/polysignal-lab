# Todo 4 Code Review: Code-Quality Repair

date: 2026-06-22
scope: remaining Todo 4 code-quality blockers
artifact: `.omo/evidence/complete-prd-old-remove-demo-todo-4-code-review.md`

## Reviewed Surface

- `src/polysignal_lab/config.py`
- `src/polysignal_lab/strategies/config.py`
- `tests/test_config.py`
- `.omo/evidence/task-4-complete-prd-old-remove-demo.txt`

## Findings

programming coverage: PASS. The touched Python surface was reviewed under the Python programming rules for no unused `ValidationError` dead import, no `Any`, no `cast`, no `type: ignore`, no `import asyncio`, no `import pandas`, no broad `except Exception` / `except BaseException`, no `dict[str, dict]`, typed boundary parsing, no new one-off helper, behavior-oriented tests, and code-size review.

raw dict / public field audit: PASS. `LateConsensusConfig.stop_loss_per_coin` is no longer the public raw nested field `dict[str, dict]`. It is now a typed `StopLossPerCoinConfig` Pydantic boundary value containing `FixedStopLossConfig` entries with `type: Literal["fixed"]` and `value: float`.

helper / dead abstraction audit: PASS. The dead public alias `load_config(...)` was removed. Source/test/config search for `load_config\(` returned no matches after the repair, so no stale imports or call sites remain. The dead-import check was rerun after removing `ValidationError` from `src/polysignal_lab/config.py`; it is clean with no `ValidationError` matches in the touched config surfaces. No replacement helper was added solely for manual QA.

overfit / deletion-only test audit: PASS. `tests/test_config.py::test_late_consensus_stop_loss_config_rejects_malformed_entry` is behavior-oriented. Red proof: before the model change it failed because malformed stop-loss input did not raise `ValidationError`; after the model change it passes. Existing PRD behavior tests still prove factory construction and non-PRD strategy rejection.

split-state audit: PASS. `rg -n "SPLIT" README.md docs src tests config` returned no matches. The PRD-facing result state set remains `WIN/LOSS/VOID/UNKNOWN`.

code-size review: PASS_WITH_WARNING. Pure LOC after dead-import repair: `src/polysignal_lab/config.py` = 212, `src/polysignal_lab/strategies/config.py` = 88, `tests/test_config.py` = 43. `config.py` remains in the 200-250 warning band and should be split before future additive edits, but this repair removed the dead `ValidationError` import and did not broaden its responsibility.

## Evidence Commands And Results

scenario: malformed stop-loss red proof
invocation: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_config.py::test_late_consensus_stop_loss_config_rejects_malformed_entry -q`
result before fix: FAIL, exit=1, `Failed: DID NOT RAISE ValidationError`
result after fix: PASS, exit=0, `. [100%]`

scenario: programming-quality forbidden token and dead-import scan
invocation: `rg -n "ValidationError|\bAny\b|cast\(|type:\s*ignore|import asyncio|import pandas|except (Exception|BaseException)|dict\[str, dict\]" src/polysignal_lab/config.py src/polysignal_lab/strategies/config.py`
result: PASS, exit=1 with empty stdout.

scenario: focused config and strategy regression suite
invocation: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_config.py tests/test_strategies.py -q`
result: PASS, exit=0, `9 passed`.

scenario: standalone PRD factory behavior
invocation: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_config.py::test_strategy_factory_builds_only_prd_strategies -q`
result: PASS, exit=0, `. [100%]`.

scenario: malformed non-PRD strategy rejection
invocation: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_config.py::test_non_prd_strategy_config_rejected -q`
result: PASS, exit=0, `. [100%]`.

scenario: forbidden non-PRD strategy/assets scan
invocation: `bash -lc '! rg "skew_mean_reversion|DOGE|BNB|HYPE" config src README.md docs/PRD_OLD_COMPLIANCE.md'`
result: PASS, exit=0 with empty stdout.

scenario: PRD-facing split-state scan
invocation: `rg -n "SPLIT" README.md docs src tests config`
result: PASS, exit=1 with empty stdout.

scenario: removed dead public config API search
invocation: `rg -n "load_config\(" /home/gyue/polysignal-lab --glob '!*.pyc' --glob '!__pycache__/**' --glob '!.git/**'`
result before evidence update: PASS, exit=1 with empty stdout.

scenario: removed dead public config API code-surface search after evidence update
invocation: `rg -n "load_config\(" src tests config`
result: PASS, exit=1 with empty stdout.

scenario: manual canonical config/factory load
invocation: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "from polysignal_lab.config import load_settings; from polysignal_lab.strategies.factory import build_strategies; settings = load_settings('config/signal_bot.yaml'); print([strategy.name for strategy in build_strategies(settings.strategies)]); print([strategy.name for strategy in build_strategies(load_settings('config/signal_bot.yaml').strategies)])"`
result: PASS, exit=0.
observable:
`['vwap_momentum', 'late_consensus', 'ptb_diff']`
`['vwap_momentum', 'late_consensus', 'ptb_diff']`

scenario: artifact keyword coverage
invocation: `test -f .omo/evidence/complete-prd-old-remove-demo-todo-4-code-review.md && rg "programming|raw dict|public field|helper|dead|overfit|deletion-only|SPLIT|WIN/LOSS/VOID/UNKNOWN|dict\[str, dict\]" .omo/evidence/complete-prd-old-remove-demo-todo-4-code-review.md`
result: PASS, exit=0 with matches for the required programming, raw dict, public field, helper, dead, overfit, deletion-only, SPLIT, WIN/LOSS/VOID/UNKNOWN, and dict[str, dict] review terms.

## Cleanup Receipt

runtime_processes: none started.
temporary_files: none created.
plan_checkbox: not marked.
env_secrecy: `.env` was not read.

## Risks

- The worktree was already dirty before this repair and remains dirty with unrelated Todo 4 changes outside the scoped files.
- `src/polysignal_lab/config.py` remains in the Python programming warning band at 212 pure LOC; no broad refactor was performed because the task asked for the smallest scoped code-quality repair.
