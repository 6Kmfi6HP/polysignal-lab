# 02 Strategy Freshness Gates Design

**Status:** Draft for review
**Scope:** One standalone architecture change. Do not execute with specs 01 or 03-08 in the same implementation batch.
**Goal:** Prevent short-window strategies from acting on stale orderbook, spot, or anchor data by enforcing the strictest applicable freshness threshold at the central gate.

## Problem

Global config currently allows 60 seconds of orderbook and spot staleness in `config/signal_bot.yaml`. That may be acceptable for low-frequency diagnostics, but not for 5m/15m crypto Up/Down markets where late-window entries happen inside the final 30-240 seconds. Strategy config models already express stricter intent; for example `LateConsensusConfig` defaults to 1.5s book/spot limits even when the runtime YAML omits those fields, while explicit YAML values should override the model defaults when configured.

The result is architectural drift: strategies assume the pipeline will reject stale data, while the pipeline applies thresholds too wide for their trading horizon unless the gate is taught to resolve strategy-specific model/YAML policy.

## Non-goals

- No rewrite of individual strategies.
- No new market data source.
- No orderbook reconciliation changes; spec 01 owns book correctness.
- No change to paper fill model except consuming the same freshness decision if useful.

## Target behavior

1. Every `SignalCandidate` carries or can resolve its strategy freshness policy.
2. Gate freshness uses the strictest threshold among global config and strategy-specific config.
3. Freshness decisions distinguish missing data from stale data, replacing the current conflation where an absent book or spot source is returned as `STALE_*`:
   - `STALE_ORDERBOOK`
   - `STALE_SPOT_PRICE`
   - `STALE_PRICE_TO_BEAT`
   - `MISSING_ORDERBOOK`
   - `MISSING_SPOT_PRICE`
4. `STALE_PRICE_TO_BEAT`/`max_anchor_staleness_ms` is only enforceable after snapshots carry anchor provenance, timestamp, and measured lag; current snapshots only expose `price_to_beat` plus `price_to_beat_source`/`price_to_beat_verified` metrics.
5. `RejectedSignal.details` includes measured lag and threshold used; this requires the gate check to pass snapshot/freshness measurements into detail construction, not only the candidate and reason code.
6. Strategies no longer need to duplicate freshness checks unless they need strategy-specific semantic checks beyond raw age.
7. Tests prove late-window strategies cannot emit accepted signals with old books or spot data.

## Proposed model

Add a lightweight freshness policy object:

```python
@dataclass(frozen=True, slots=True)
class FreshnessPolicy:
    max_orderbook_staleness_ms: int
    max_spot_staleness_ms: int
    max_anchor_staleness_ms: int | None = None
```

Resolution rule:

```python
orderbook_threshold = min(global_poly.max_book_staleness_ms, strategy.max_orderbook_staleness_ms)
spot_threshold = min(global_binance.max_price_staleness_ms, strategy.max_spot_staleness_ms)
```

If a strategy has no explicit policy, use the existing global threshold.

## Interface options

### Recommended option: strategy exposes policy

`BaseStrategy` can expose:

```python
@property
def freshness_policy(self) -> FreshnessPolicy | None:
    return None
```

Concrete strategies override this from their config. This keeps candidate payloads smaller and avoids duplicating static policy on every candidate.

### Alternative: candidate carries thresholds

`SignalCandidate.metrics` could include thresholds. This avoids base class changes but makes policy implicit and less testable.

Decision: use the strategy property. It is explicit and fits existing factory/config structure.

## Gate behavior

`SignalGate.evaluate()` already receives the candidate and snapshot but not the strategy object. Implementation should either:

- Add `candidate.freshness_policy` at candidate construction, or
- Add a strategy registry lookup in processing before gate evaluation.

Recommended: candidate carries a resolved immutable policy copied from the strategy at emission time. This keeps `SignalGate` pure over candidate + snapshot.

Freshness checks should return structured measurements, not only a reason string, so `_rejection_details()` can persist the actual source lag, threshold, and missing-vs-stale reason without re-reading mutable state.

## Acceptance criteria

- A late-consensus candidate with 2s-old book and a 1.5s policy is rejected even if the 1.5s threshold comes from the current config model default rather than an explicit runtime YAML value, and even though the global config allows 60s.
- Rejection details include actual lag and threshold for book/spot checks, and PTB lag once PTB provenance/timestamp fields exist.
- Existing strategies without explicit freshness policy retain current global behavior.
- Missing required sources produce `MISSING_*` reasons, not stale reasons.
- Dashboard rejected-signals endpoint can show the new reason codes because they are persisted through existing rejected signal storage.

## Test strategy

- Unit test `SignalGate` with constructed snapshots and policies.
- Strategy integration test for late-consensus stale spot/book behavior.
- Regression test ensuring a strategy without policy still uses global thresholds.
- No live API calls.

## Rollout

1. Add `FreshnessPolicy` and candidate/gate plumbing.
2. Wire policies for late-consensus, VWAP momentum, PTB diff.
3. Tighten tests for stale data rejection.
4. Tune config only after observing rejected reason counts in local smoke.