# Nautilus L1 Subscription Optimization Design

## Goal

Reduce PolySignal Lab runtime resource usage without changing strategy alpha logic or paper execution semantics. The optimization targets the current mismatch between `fast_l1` execution mode and raw `order_book_deltas` subscriptions.

The strategy core, signal thresholds, gate policy, order mapping, fill callbacks, hedge callbacks, and paper execution behavior must remain unchanged.

## Current Problem

The production config uses `runtime.nautilus.matching_accuracy_mode: fast_l1`, which maps to Nautilus `L1_MBP`. Nautilus documents `L1_MBP` as top-of-book data, which can be maintained from `QuoteTick`, `TradeTick`, or bar-style data. Raw `order_book_deltas` are intended for L2/L3 incremental book maintenance.

Today `PolySignalNativeStrategy` subscribes to `order_book_deltas` and `trade_ticks` for every subscribed instrument. This pushes high-volume book deltas through Python callbacks even when the runtime is configured for L1 behavior. The result is unnecessary callback load, repeated strategy evaluations, and high-frequency rejected decision persistence.

## Recommended Design

Add mode-aware market data subscription behavior in `src/polysignal_lab/nautilus_runtime/native_strategy.py`, using the existing `book_type` already derived from `matching_accuracy_mode`. Before implementation, verify the Polymarket adapter's actual live-data capabilities for the target Nautilus version: `subscribe_quote_ticks` and `subscribe_order_book_at_interval` must be probed or covered by a small runtime test before either path is selected as the primary L1 feed.

For `L1_MBP` / `fast_l1`:

- Subscribe to `trade_ticks` to preserve Nautilus trade-driven execution evidence.
- Prefer `quote_ticks` only after verifying the Polymarket adapter exposes the subscription and emits callbacks for Polymarket instruments.
- Fall back to `order_book_at_interval` only after verifying it works for Polymarket instruments. This fallback is expected to reduce Python strategy callback/evaluation load, but it may still rely on adapter-side book maintenance internally.
- Avoid `order_book_deltas` unless both L1 alternatives are unavailable. If this fallback activates, the runtime remains in the old high-load data mode and must report that clearly.

For `L2_MBP` or deeper modes:

- Keep the existing `order_book_deltas` plus `trade_ticks` behavior.

## Data Flow

The strategy continues to build `MarketView` through the existing assembler path.

- `on_trade_tick()` remains responsible for updating last trade data and triggering evaluation.
- A new L1 handler, either `on_quote_tick()` or `on_order_book()`, updates the book provider with the current top-of-book state.
- L1 projection must preserve the token-level contract expected by `NautilusBookDataProvider` and `MarketViewAssembler`: token ID, bid/ask levels, best ask, last trade price, last trade size, and `received_at`/freshness semantics must remain available to downstream `MarketView` construction.
- Binary market pair handling must remain token-specific. UP and DOWN instruments update their own token books; no parity transform should be introduced in this optimization.
- `VWAPMomentumAlphaCore.evaluate()` receives the same semantic inputs it uses today: best ask, last trade price, last trade size, freshness, and market timing.
- Approved decisions, rejected decisions, order submission, paper fills, and hedge follow-ups continue through the existing code paths.

## Configuration

Use `runtime.nautilus.matching_accuracy_mode` as the primary switch. Add only one narrow setting if interval snapshots are required:

```yaml
runtime:
  nautilus:
    l1_book_snapshot_interval_ms: 1000
```

If quote ticks are available, no new configuration is required.

## Failure Handling

The runtime should degrade safely:

1. In `L1_MBP`, try `subscribe_quote_ticks` first only when capability verification passes.
2. If unavailable, try `subscribe_order_book_at_interval` with the configured interval only when capability verification passes.
3. If unavailable, log a warning and fall back to `subscribe_order_book_deltas` so market data is not silently lost.

Fallback to raw deltas must be visible, not silent. The startup path should emit a warning and expose a health or diagnostic detail indicating that `fast_l1` is running on raw `order_book_deltas`, because that means the resource optimization did not activate.

This preserves functionality even when adapter capabilities differ across Nautilus versions.

## Testing Plan

Add focused tests around `PolySignalNativeStrategy`:

- `L1_MBP` subscribes to `trade_ticks` and an L1 book feed, not raw `order_book_deltas`, when supported.
- `L2_MBP` continues subscribing to `order_book_deltas` and `trade_ticks`.
- L1 book data handlers update the assembler book provider correctly, including token ID, bid/ask levels, best ask, last trade fields, and freshness metadata.
- `on_trade_tick()` behavior remains unchanged.
- Equivalent top-of-book plus trade inputs produce equivalent `vwap_momentum` decisions before and after the L1 feed path change.
- Existing `vwap_momentum` decision and Nautilus runtime tests continue to pass.

Add one runtime verification step after deployment or local compose startup:

- Compare `polysignal-lab` CPU, memory, network input, `nautilus_decisions` rate, and `rejected_signals` rate against the observed baseline.
- Confirm startup diagnostics show the selected L1 feed path. If diagnostics show raw-delta fallback, treat the optimization as not active even if the process remains healthy.

## Out Of Scope

This design does not change:

- `VWAPMomentumAlphaCore` formulas or thresholds.
- Signal gate policy.
- Dedupe semantics for accepted signals.
- Order mapping or submit behavior.
- Fill handling, hedge behavior, or paper execution semantics.
- Broad observability sampling or rejected-log aggregation.

Rejected decision sampling may be considered later if high-frequency rejected writes remain after the subscription mismatch is corrected.
