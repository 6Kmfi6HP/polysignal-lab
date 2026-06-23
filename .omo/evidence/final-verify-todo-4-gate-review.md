# Final Verify Todo 4 Gate Review

recommendation: REJECT

## Original Intent

Todo 4 was intended to remove non-PRD demo/legacy strategy and asset exposure from the current PRD-facing product surface, keep only the PRD strategy set, and ensure result states are PRD-facing as `WIN/LOSS/VOID/UNKNOWN` without `SPLIT`.

## Desired Outcome

- Current config, strategy factory, source, docs, and tests expose only PRD strategies/assets.
- Current PRD-facing docs do not advertise `SPLIT`.
- Focused config/strategy regression tests pass.
- Evidence and code-review artifacts substantiate programming-quality and remove-ai-slops/overfit review.
- No unresolved slop or unsupported review claims remain.

## User Outcome Review

The primary requested reproductions pass:

- `rg -n "SPLIT" README.md docs src tests config` returned exit 1 with empty output.
- `bash -lc '! rg "skew_mean_reversion|DOGE|BNB|HYPE" config src README.md docs/PRD_OLD_COMPLIANCE.md'` returned exit 0 with empty output.
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_config.py tests/test_strategies.py -q` returned exit 0 with `8 passed`.
- `rg -n "\bAny\b|cast\(|type:\s*ignore|import asyncio|import pandas|except (Exception|BaseException)" src/polysignal_lab/config.py` returned exit 1 with empty output.
- Code-review artifact keyword check returned exit 0.
- Manual config/factory load returned `['vwap_momentum', 'late_consensus', 'ptb_diff']` for both bulk and single strategy construction.

Despite that, approval is blocked because the independent programming/remove-ai-slops pass found unresolved slop and unsupported review coverage.

## Blockers

1. Unsupported programming-quality coverage in the standalone code-review artifact.
   - Artifact: `.omo/evidence/complete-prd-old-remove-demo-todo-4-code-review.md`
   - The report claims programming quality pass by checking only `Any`, `cast`, `type: ignore`, `import asyncio`, `import pandas`, and broad `except`.
   - The loaded `omo:programming` criteria also require strict typed containers and reject raw dict-style erasure. The report does not cover that criterion.

2. Unresolved strict-typing slop in Todo 4 production surface.
   - Evidence command: `rg -n "stop_loss_per_coin|dict\[str, dict\]|import os as _os|Side\.UP else" src/polysignal_lab/config.py src/polysignal_lab/strategies/config.py src/polysignal_lab/domain/enums.py`
   - Relevant finding: `src/polysignal_lab/strategies/config.py:43:    stop_loss_per_coin: dict[str, dict] = Field(default_factory=lambda: {`
   - This is a public Pydantic config field with an untyped nested dict. It violates the programming criterion that structured data should use typed containers/models rather than raw dict erasure.

3. Unresolved remove-ai-slops dead/needless abstraction in the diff.
   - Evidence command: `rg -n "load_config\(" . --glob '!*.pyc' --glob '!__pycache__/**' --glob '!.env'`
   - Finding: only `src/polysignal_lab/config.py:265:def load_config(path: str | Path | None = None) -> Settings:`
   - `load_config` is a newly added public helper with no call sites in the inspected workspace. That is dead public API/needless abstraction unless an external compatibility requirement is documented and tested.

## Checked Artifact Paths

- `docs/IMPLEMENTATION_SUMMARY.md`
- `.omo/evidence/complete-prd-old-remove-demo-todo-4-code-review.md`
- `.omo/evidence/task-4-complete-prd-old-remove-demo.txt`
- `config/signal_bot.yaml`
- `src/polysignal_lab/config.py`
- `src/polysignal_lab/strategies/config.py`
- `src/polysignal_lab/strategies/factory.py`
- `src/polysignal_lab/domain/enums.py`
- `tests/test_config.py`
- `tests/test_strategies.py`
- `docs/PRD_OLD_COMPLIANCE.md`

## Commands Inspected

- `git status --short`
- `git diff -- config/signal_bot.yaml src/polysignal_lab/config.py src/polysignal_lab/domain/enums.py src/polysignal_lab/strategies/factory.py`
- `git diff --name-status -- config/signal_bot.yaml src/polysignal_lab/config.py src/polysignal_lab/domain/enums.py src/polysignal_lab/strategies/factory.py src/polysignal_lab/strategies/skew_mean_reversion.py src/polysignal_lab/strategies/binary_momentum.py src/polysignal_lab/strategies/cross_market_bot.py src/polysignal_lab/strategies/dump_hedge.py src/polysignal_lab/strategies/fibonacci_bot.py src/polysignal_lab/strategies/low_side_dual_reversion.py src/polysignal_lab/strategies/mid_price_sizing.py src/polysignal_lab/strategies/ninety_nine_cent_sniper.py src/polysignal_lab/strategies/one_cent_buy.py src/polysignal_lab/strategies/pre_order_market.py`
- `find src/polysignal_lab/strategies -maxdepth 1 -type f -printf '%f\n' | sort`
- `awk '!/^[[:space:]]*$/ && !/^[[:space:]]*(\/\/|#|--)/' src/polysignal_lab/config.py | wc -l`

## Exact Evidence Gaps

- The standalone code-review report does not substantiate the full programming skill criteria; it only proves the narrower requested grep class.
- The report does not acknowledge or justify `dict[str, dict]` in `src/polysignal_lab/strategies/config.py`.
- The report does not acknowledge or justify the newly added unused `load_config` public helper.

