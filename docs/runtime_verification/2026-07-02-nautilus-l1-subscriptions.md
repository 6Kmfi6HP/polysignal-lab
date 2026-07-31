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

## Subscription health verification (2026-07-31)

This verification covers the strategy-scoped subscription fix, adapter reconnect
replay, and Telegram URL redaction. The `/health` thresholds and HTTP semantics
were not changed.

### Dependency and subscription scope

- Installed and locked `nautilus_trader[polymarket]==1.231.0a20260730` from the
  official Nautilus package index.
- `vwap_momentum` and `ptb_diff` were limited to their configured BTC 5m/15m
  markets. `late_consensus` retained its configured BTC/ETH/SOL/XRP 5m/15m
  scope.
- The production-equivalent process held 16 active conditions. During the
  final observation, the adapter logged 80 subscriptions each for quotes,
  trades, order-book deltas, and instrument-close data, including startup and
  market rotations. It logged 48 corresponding rotation unsubscriptions for
  quotes, trades, and order-book deltas.
- Readiness details recorded subscribe-intent age, generation age, and first
  bilateral-book latency. The maximum observed bilateral-book generation
  latency was 507 ms.

### Forced reconnect acceptance

The container network was disconnected for 15 seconds and restored without
restarting the process. At `13:34:36Z`, both Polymarket market-data clients
logged `Resubscribing to 16 market assets after reconnect`. Global readiness
recovered by `13:34:41Z`; all reconnect-related condition transitions recovered
within the existing 120-second acceptance window. The container restart count
remained zero.

The final run also recorded 12 automatic reconnect replays, each
restoring the same 16 market assets. This exercises idle/network reconnect
replay in the selected nightly rather than relying only on release notes.

### Continuous rotation observation

Observation window: approximately `14:19Z` through `14:40Z`, sampled every 30
seconds and extended through recovery after the final sample. It covered four
5m rotations and the overlapping 15m rotation.

- All 40 health samples were `healthy`; the process did not restart.
- Initial and rotation bilateral-book generation met the 120-second target; the
  maximum measured first-book latency was 507 ms.
- One XRP 15m readiness miss lasted 175 seconds, from `14:27:05Z` until the
  market exited at `14:30:00Z`. At miss start both book receipts were only 13 ms
  old, so this was not subscription starvation or a stale adapter replay. The
  market view had lost required quote depth and correctly remained fail-closed
  until retirement.
- Recovered conditions had maximum recorded book freshness of 13,450 ms. A
  stale-book transition was detected at 60,984 ms, confirming that the existing
  60-second freshness gate remained fail-closed.
- The extended observation ended with zero readiness misses, but the 175-second
  quote-depth miss means the strict "no persistent readiness_miss" acceptance
  criterion did not pass. Production sign-off remains blocked.

### Resource and log comparison

| Metric | Pre-change snapshot | Final candidate run |
|--------|---------------------|-------------------------|
| CPU | 119.50% | 38.03%-125.18%; final sample 55.99% |
| Memory | 1.017 GiB | 225.3-288.0 MiB |
| Network I/O | 8.46 GB / 369 MB cumulative | 2.03 GB / 69.5 MB over the observation |
| Nautilus runtime log | 343 MB historical set | 7.9 MB final-run file after ~22 min |

The network figures have different accumulation windows and are retained as
snapshots, not presented as a normalized throughput benchmark.

### Secret scanning and operator action

The post-deployment stdout window, application JSONL records, Nautilus JSONL,
and crash log each contained zero Telegram `/bot<token>/` path matches. Unit
tests also cover arbitrary token lengths in text, structured JSON, and exception
formatting. Python `httpx` and `httpcore` loggers run at `WARNING`.

Historical logs still contain the previously exposed token. Per the runtime-data
preservation constraint, this verification did not rewrite or delete them. An
operator with Telegram credential authority must rotate the Bot Token and
restrict access to the historical logs before production sign-off.

### Quality gates

- `uv run pre-commit run --all-files --hook-stage pre-commit`: passed
- `uv run pytest`: 970 passed, 6 skipped
- `uv run basedpyright`: task changes add no errors; the command still exits 1
  with eight pre-existing unrelated errors (detached `HEAD` baseline: nine)
- `uv run polysignal-safety-scan .`: passed
