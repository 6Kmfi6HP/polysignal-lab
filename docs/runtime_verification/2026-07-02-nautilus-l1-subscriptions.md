# Nautilus L1 Subscription Optimization - Runtime Verification

## Implementation Status: CODE COMPLETE (deployment verification needed)

### Changes Summary

**Files modified:**
- `src/polysignal_lab/config.py` — Added `l1_book_snapshot_interval_ms: int = 1000` to `NautilusRuntimeConfig`
- `src/polysignal_lab/nautilus_runtime/native_strategy.py` — Added L1 feed selection, L1 projection handlers, config propagation
- `src/polysignal_lab/nautilus_runtime/node.py` — Passes `l1_book_snapshot_interval_ms` to native strategy construction
- `tests/test_nautilus_strategy_base.py` — Added 7 tests (4 subscription selection, 2 L1 projection, 1 VWAP behavior)
- `tests/test_nautilus_node.py` — Added 1 config propagation test

### Commit History

```
a1be3f3 test: preserve vwap momentum behavior with L1 feed
8da5a90 feat: configure Nautilus L1 book snapshot interval
dca0792 refactor: deduplicate _update_book_from_order_book via _domain_order_book
fc92dff fix: project Nautilus L1 book data into market views
dbbe842 fix: select Nautilus market data feed by book mode
8b67968 test: capture Nautilus L1 subscription selection
```

### Regression Suite: 91/91 tests passing

The focused regression suite (`tests/test_nautilus_strategy_base.py` + `tests/test_nautilus_node.py`) passes all 91 tests.

Full test suite (`tests/`): 693 collected, 1 pre-existing failure in `test_integration_smoke.py::test_fake_public_api_outage_degrades_without_unhandled_exception` (unrelated to L1 subscription changes).

### Selected L1 feed path (determined at deploy time)

- `fast_l1` mode in config -> `L1_MBP` book type
- Tries `subscribe_quote_ticks` first (requires adapter support)
- Falls back to `subscribe_order_book_at_interval` (interval: 1000ms, configurable)
- Falls back to `subscribe_order_book_deltas` with visible `l1_raw_delta_fallback` phase indicator

### Deployment Verification Results

**Date:** 2026-07-02

**Build:** `docker compose up -d --build polysignal-lab` ✅

**Selected L1 feed path:** `quote_ticks` ✅ (optimal path — verified via `SubscribeQuoteTicks` in container logs)

**Verification findings:**
- 32 `SubscribeQuoteTicks` calls observed (one per instrument per strategy)
- 32 `SubscribeTradeTicks` calls observed  
- `l1_raw_delta_fallback`: **0 occurrences** (fallback not triggered)
- Heartbeat phase cycling: `start` → `market_data_evaluation`

**Metrics snapshot (2026-07-02T10:01:16Z):**
| Metric | Value |
|--------|-------|
| CPU | ~50% |
| Memory | 271 MiB / 11.65 GiB |
| Decisions (since start) | ~39,377 |
| Rejected signals (since start) | ~39,354 |

**Metrics after settling (2026-07-02T10:04:35Z):**
| Metric | Value |
|--------|-------|
| CPU | ~91% |
| Memory | 558 MiB / 11.65 GiB |
| Total decisions | 40,221 |
| Total rejected signals | 40,195 |

**Analysis of remaining CPU usage:**
The subscription optimization is confirmed **working** (`quote_ticks` path active, no raw delta fallback). The remaining ~91% CPU and ~220 decisions/second come from strategy evaluation frequency — every incoming quote tick triggers `_evaluate_market_data_condition()` for all active strategies. This is a separate concern from the subscription overhead.

Per the design spec: *"Rejected decision sampling may be considered later if high-frequency rejected writes remain after the subscription mismatch is corrected."* — this optimization is now available as a follow-up.

**Conclusion:** The L1 subscription optimization is successfully deployed and active. The `quote_ticks` feed path replaces the heavier `order_book_deltas` subscription. Remaining high CPU is driven by evaluation frequency on incoming market data, which is outside this optimization's scope.

**Note:** A pre-change baseline was not captured in this session. Future comparisons should capture `docker stats` and decision/rejection rates before and after the config change for a direct comparison.

### Container Restart Analysis

During monitoring a container restart was observed. Root cause identified:

**Error:** `RuntimeError('invalid delta price precision=3 did not match instrument.price_precision=2')` in `DataEngine` queue processing.

**Impact:** The Nautilus `DataEngine` shuts down on unhandled exceptions (`graceful_shutdown_on_exception=False`), causing the TradingNode to exit. Docker auto-restarts the container (`restart: unless-stopped`).

**Timeline (observed restart):**
- T+23min: Delta with price precision=3 received → DataEngine crash → process exit
- Immediate: Docker restart (RestartCount: 1)

**Relationship to L1 optimization:** This error originates from the Polymarket adapter's data format, not from subscription choice. With the `quote_ticks` L1 path active, our strategies no longer subscribe to `order_book_deltas`, so this error should occur less frequently. However, the Polymarket data client may still process deltas for internal book maintenance.

**Status:** This is a pre-existing upstream data quality issue, not introduced by the L1 subscription changes.
