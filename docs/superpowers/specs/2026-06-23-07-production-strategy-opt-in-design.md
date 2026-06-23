# 07 Production Strategy Opt-In and Calibration Design

**Status:** Draft for review
**Scope:** One standalone architecture change. Do not execute with specs 01-06 or 08 in the same implementation batch.
**Goal:** Prevent untuned or unsupported strategies from polluting production signals by making production strategy activation explicit and calibration-aware.

## Problem

The current YAML config enables many strategies beyond the core documented set. Market discovery is limited to BTC/ETH/SOL/XRP and 5m/15m markets, while some restored/default strategy configs support wider or different universes. The scheduler runs every loaded strategy against every active snapshot. This can create hidden no-ops, noisy rejected signals, misleading paper reports, and unclear production behavior.

## Non-goals

- No deletion of experimental strategies.
- No strategy performance optimization in this spec.
- No machine-learning consensus engine.
- No live trading risk budget.

## Target behavior

1. Production config uses explicit opt-in strategy activation.
2. Each strategy declares supported assets/timeframes and required data fields.
3. Scheduler skips incompatible strategy/market pairs before evaluation and records the reason separately from gate rejection.
4. Strategy status is visible: active, disabled, unsupported market, missing data, uncalibrated.
5. Paper outcomes are aggregated per strategy/asset/timeframe to support calibration.
6. Consensus weights remain fixed initially but have a clear path to using calibration metrics later.

## Strategy metadata

Add metadata to `BaseStrategy` or strategy config:

```python
@dataclass(frozen=True, slots=True)
class StrategyReadiness:
    name: str
    production_enabled: bool
    supported_assets: tuple[str, ...]
    supported_timeframes: tuple[str, ...]
    required_fields: tuple[str, ...]
    calibration_required: bool
    calibration_status: Literal["unknown", "insufficient_data", "calibrated"]
```

Required fields examples:

- `up_book`, `down_book`
- `spot`
- `price_to_beat`
- `spot_history`
- `market_end_ts`

## Config policy

Introduce two profiles by convention:

- `production`: only explicitly reviewed strategies enabled.
- `lab`: experimental strategies may be enabled for research.

The default Docker/runtime config should be production-safe. Experimental breadth belongs in a separate config file, not the default formal runtime path.

## Calibration metrics

Persist/report per strategy/asset/timeframe:

- signals emitted;
- gate accepted/rejected;
- paper attempted/filled/rejected;
- resolved wins/losses;
- average entry price;
- average return;
- precision by confidence bucket;
- Brier-like score when model probability exists.

## Acceptance criteria

- A strategy unsupported for a market is skipped before `evaluate()` and does not create a rejected signal row as if it failed a trade gate.
- Default production config contains only intentionally enabled strategies.
- Dashboard/report can show inactive/no-op strategies separately.
- Paper leaderboard distinguishes insufficient sample size from poor performance.
- Existing lab experimentation remains possible through separate config.

## Test strategy

- Unit tests for strategy readiness compatibility matching.
- Scheduler processing test proving unsupported strategy is skipped without calling `evaluate()`.
- Config load test for production vs lab profile behavior.
- Reporting test for calibration status and sample size.

## Rollout

1. Add metadata/readiness model and compatibility filter.
2. Annotate core strategies first.
3. Split production and lab config profiles.
4. Add report/dashboard fields.
5. Only after calibration data exists, consider learned consensus weighting in a separate spec.