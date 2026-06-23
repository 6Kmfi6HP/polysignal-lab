# Gate Review: complete-prd-old-remove-demo Todo 4 Repair

recommendation: REJECT

## originalIntent
Constrain runtime config, schema, and strategy factory to PRD-old strategies and assets only after the programming-quality repair. The expected user-visible result is only VWAP Momentum, Late Consensus, and PTB Diff over BTC/ETH/SOL/XRP as applicable; non-PRD strategy config is rejected; `skew_mean_reversion`, DOGE, BNB, and HYPE are absent from the requested PRD-facing scope; result states are WIN/LOSS/VOID/UNKNOWN with no PRD-facing SPLIT.

## desiredOutcome
The previous blocker in `src/polysignal_lab/config.py` is gone, the typed YAML boundary is coherent, focused tests and manual config/factory loading pass, and no stale user-visible artifact contradicts the Todo 4 result-state scope.

## userOutcomeReview
The programming-quality repair itself is confirmed: `src/polysignal_lab/config.py` no longer imports `Any`, uses `YAML_CONFIG_ADAPTER: Final = TypeAdapter(dict[str, JsonValue])`, and the requested focused tests/manual config load pass. The Todo 4 outcome is still blocked because `docs/IMPLEMENTATION_SUMMARY.md:15` remains a user-visible documentation claim that settlement states include `SPLIT`, contradicting the requirement that SPLIT is not PRD-facing and final result states are strictly WIN/LOSS/VOID/UNKNOWN.

## blockers
- `docs/IMPLEMENTATION_SUMMARY.md:15` still says `WIN/LOSS/VOID/UNKNOWN/SPLIT`. This is outside the narrow forbidden-strategy grep, but it directly conflicts with the requested `split_result_state` adversarial probe and the original Todo 4 result-state requirement.
- No standalone Todo 4 code-review report artifact with explicit `programming` and `remove-ai-slops` overfit/slop coverage was found under `.omo/evidence/`; only the task evidence and ledger entries exist. Direct slop review did not find an unresolved test/code slop blocker, but the report-coverage artifact is absent.

## checkedArtifactPaths
- `.omo/plans/complete-prd-old-remove-demo.md`
- `.omo/evidence/task-4-complete-prd-old-remove-demo.txt`
- `.omo/start-work/ledger.jsonl`
- `src/polysignal_lab/config.py`
- `src/polysignal_lab/strategies/config.py`
- `src/polysignal_lab/strategies/factory.py`
- `src/polysignal_lab/domain/enums.py`
- `src/polysignal_lab/paper/settlement.py`
- `src/polysignal_lab/paper/report.py`
- `config/signal_bot.yaml`
- `tests/test_config.py`
- `tests/test_strategies.py`
- `tests/test_paper_simulation.py`
- `README.md`
- `docs/PRD_OLD_COMPLIANCE.md`
- `docs/IMPLEMENTATION_SUMMARY.md`

## evidence
- `rg -n "\\bAny\\b|cast\\(|type:\\s*ignore|import asyncio|import pandas|except (Exception|BaseException)" src/polysignal_lab/config.py` exited 1 with empty stdout.
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_config.py tests/test_strategies.py -q` returned 8 passed.
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_config.py::test_strategy_factory_builds_only_prd_strategies -q` returned 1 passed.
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_config.py::test_non_prd_strategy_config_rejected -q` returned 1 passed.
- `bash -lc '! rg "skew_mean_reversion|DOGE|BNB|HYPE" config src README.md docs/PRD_OLD_COMPLIANCE.md'` exited 0 with empty stdout.
- Manual config/factory load printed `['vwap_momentum', 'late_consensus', 'ptb_diff']` twice.
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY' ... Settings.model_validate(...) ... PY` rejected `('strategies', 'skew_mean_reversion')` with `extra_forbidden`.
- `rg -n "SPLIT" README.md docs src tests config` returned `docs/IMPLEMENTATION_SUMMARY.md:15`.
- Touched-file programming grep over `src/polysignal_lab/config.py`, strategy config/factory, enums, paper settlement/report, and focused tests exited 1 with empty stdout.
- Secret marker evidence scan over `.omo/evidence/task-4-complete-prd-old-remove-demo.txt` and `.omo/start-work/ledger.jsonl` exited 1 with empty stdout. `.env` was not read.

## evidenceGaps
- Missing standalone Todo 4 code-review report artifact with explicit programming skill and remove-ai-slops overfit/slop criterion coverage.
- The narrow Todo 4 acceptance grep does not include `docs/IMPLEMENTATION_SUMMARY.md`, so the stale `SPLIT` documentation claim is not caught by the executor's acceptance command.

