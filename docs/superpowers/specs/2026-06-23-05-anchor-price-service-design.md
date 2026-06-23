# 05 Anchor Price Service Design

**Status:** Draft for review
**Scope:** One standalone architecture change. Do not execute with specs 01-04 or 06-08 in the same implementation batch.
**Goal:** Replace opportunistic price-to-beat lookup with a durable, boundary-aware anchor price service for short-cycle crypto Up/Down markets.

## Problem

`PriceToBeatProvider` currently derives price-to-beat from Gamma metadata/raw fields, optional Polymarket crypto-price API, or text fallback during snapshot construction. Project memory records that Polymarket's crypto-price endpoint can be Cloudflare-blocked with HTTP 403. For 5m/15m markets, anchor correctness is central to PTB Diff and similar strategies; it should not depend on ad-hoc parsing at snapshot time.

## Non-goals

- No live trading.
- No dependency on blocked/undocumented endpoints as primary source.
- No full historical price database beyond anchors needed by active/recent markets.
- No consensus algorithm for multiple references beyond simple validation in this spec.

## Target behavior

1. A long-running `AnchorPriceService` records anchor prices for configured assets and timeframes at market boundaries.
2. Anchors are persisted by asset, timeframe, market slug/window, boundary timestamp, source, and verification status.
3. Snapshot builder reads cached/persisted anchor first.
4. Gamma metadata/raw PTB remains fallback evidence, not the primary source when a verified anchor exists.
5. PTB-dependent strategies can require verified anchors and reject otherwise.
6. Anchor freshness and source are visible in snapshot metrics and health.

## Data model

```python
@dataclass(frozen=True, slots=True)
class AnchorPrice:
    asset: str
    timeframe: str
    market_slug: str
    window_start: datetime
    window_end: datetime
    price: float
    source: str
    verified: bool
    captured_at: datetime
    lag_ms: int | None
```

SQLite table candidate: `anchor_prices` with unique key `(asset, timeframe, market_slug)` or `(asset, timeframe, window_start)`.

## Source priority

1. Boundary-captured reference stream, initially Binance because it already exists in PolySignal.
2. Optional official Polymarket RTDS crypto/equity stream if later validated.
3. Gamma metadata/raw field if it exactly matches market semantics.
4. Text fallback marked `verified=false`.

## Boundary capture rule

For each configured asset/timeframe:

- compute expected window boundary from market slug or event start/end;
- capture the latest spot price within an allowed lag window around boundary;
- persist `verified=true` only if source lag is within threshold;
- if lag is too high, persist unavailable/degraded evidence rather than inventing an anchor.

## Interface changes

`PriceToBeatProvider.get(market)` becomes a resolver over:

1. `AnchorPriceStore.get_verified(market)`;
2. existing metadata/raw fallback;
3. optional API/text fallback.

Return shape should keep current `value/source/verified` semantics so existing snapshots continue to work.

## Acceptance criteria

- For a market with a persisted verified anchor, snapshot PTB uses that anchor and records source `anchor_service:<source>`.
- For missing anchor, existing Gamma/raw fallback behavior remains available.
- PTB Diff with `require_verified_ptb_source=true` rejects unverified text fallback.
- Anchor records survive scheduler restart.
- Health reports latest anchor lag per asset/timeframe.

## Test strategy

- Unit tests for boundary calculation from market slug/timeframe.
- Store tests for insert/upsert/get verified anchor.
- Snapshot builder test proving anchor precedence over fallback text.
- PTB Diff gate/strategy test for verified vs unverified anchor.
- No live network calls.

## Rollout

1. Add anchor model/store and deterministic tests.
2. Capture anchors from existing `SpotRegistry` at market refresh/evaluation boundaries.
3. Wire `PriceToBeatProvider` to prefer anchor store.
4. Add health metrics for anchor lag.
5. Later evaluate RTDS as a separate source only after read-only smoke proves reliability.