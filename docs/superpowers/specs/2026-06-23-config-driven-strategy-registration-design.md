# Config-Driven Strategy Registration Design

**Status:** Approved
**Date:** 2026-06-24

## Goal

Replace the hard-coded PRD strategy whitelist with config-driven automatic strategy registration, while keeping production defaults safe: only strategies explicitly present in `config/signal_bot.yaml` and set `enabled: true` are started.

## Current behavior

- `src/polysignal_lab/strategies/factory.py` registers only `vwap_momentum`, `late_consensus`, and `ptb_diff` in `_STRATEGY_REGISTRY`.
- `StrategyConfig.__iter__()` yields only those three strategies.
- `StrategyConfig.reject_restored_strategy_overrides()` rejects other implemented strategies with `Non-PRD strategies are not accepted in production config`.
- `tests/test_config.py` asserts that only the three PRD strategies can be built.

This makes implemented strategies unavailable in production even when their config models and strategy classes exist.

## Decision

Use explicit YAML presence as the production activation boundary.

A strategy is eligible to run only when all are true:

1. It has a `StrategyConfig` field.
2. It has a registered strategy implementation class.
3. Its section is explicitly present in the loaded config source.
4. Its resolved config has `enabled: true`.

Default config model values are still useful for validation and tests, but they do not imply runtime activation unless the strategy appears in YAML.

## Architecture

### Settings/config layer

`StrategyConfig` records which strategy sections were explicitly supplied by the YAML/environment config source.

Implementation:

- During `load_settings(path)`, parse the raw config mapping before `Settings.model_validate`.
- Extract `raw_config.get("strategies", {}).keys()` into a `set[str]`.
- Attach this set to `settings.strategies` via a private Pydantic attribute named `_explicit_strategy_names`.
- Add a public helper on `StrategyConfig`, e.g. `explicit_strategy_names() -> set[str]`, so factory code does not reach into the private attribute.
- Preserve current schema behavior for unknown strategy names through `extra="forbid"`.

### Strategy factory

Replace the PRD-only registry with a complete registry for all implemented strategies:

- `vwap_momentum`
- `late_consensus`
- `ptb_diff`
- `binary_momentum`
- `cross_market_bot`
- `dump_hedge`
- `fibonacci_bot`
- `low_side_dual_reversion`
- `mid_price_sizing`
- `ninety_nine_cent_sniper`
- `one_cent_buy`
- `pre_order_market`
- `skew_mean_reversion`

`build_strategies(config)` iterates over explicit strategy names, validates each has a registered class, and instantiates only configs with `enabled: true`.

`build_strategy(config)` remains as the single-strategy constructor and should support every implemented strategy config type.

### PRD wording

Remove “Non-PRD strategies are not accepted in production config” from code and tests.

Use this wording instead:

- PRD strategies are the recommended default production set.
- Runtime strategy activation is config-driven.
- Experimental/restored strategies may be enabled only by explicitly adding their config section.

## Data flow

1. `docker-compose.yml` starts scheduler with `--config config/signal_bot.yaml`.
2. `load_settings("config/signal_bot.yaml")` reads raw YAML.
3. `Settings.model_validate` validates all known strategy config sections.
4. Loader records explicit strategy section names on `settings.strategies`.
5. `PolySignalScheduler._initialize_trading_components()` calls `build_strategies(settings.strategies)`.
6. Factory builds only explicit enabled strategies.
7. Scheduler logs loaded strategy names as today through `SIGNAL_DIAG`.

## Error handling

- Unknown strategy name in YAML: validation fails through `extra="forbid"`.
- Explicit strategy without implementation registry entry: raise a clear `ValueError("Strategy '<name>' has config but no registered implementation")`.
- Explicit strategy with `enabled: false`: skip silently.
- No explicit enabled strategies: return an empty list; scheduler can run but `SIGNAL_DIAG` reports `0 strategies loaded`.

## Testing

Update `tests/test_config.py`:

1. `test_strategy_factory_builds_default_configured_strategies`: current `config/signal_bot.yaml` builds only `vwap_momentum`, `late_consensus`, `ptb_diff`.
2. `test_explicit_restored_strategy_can_be_built`: construct settings with e.g. `fibonacci_bot: {enabled: true, require_momentum_confirmation: false}` and assert it is built.
3. `test_disabled_explicit_strategy_is_skipped`: explicit strategy with `enabled: false` is not built.
4. `test_unknown_strategy_config_rejected`: unknown strategy key raises `ValidationError`.
5. `test_strategy_config_iteration_matches_explicit_runtime_set`: keep `__iter__()` and make it yield explicit strategy configs in YAML order; it must no longer encode PRD-only behavior.

Run the focused config/strategy tests after implementation.

## Non-goals

- Do not change strategy trading logic.
- Do not tune thresholds or risk limits.
- Do not enable additional strategies in `config/signal_bot.yaml` unless requested separately.
- Do not change paper trading, Telegram, or dashboard behavior.
