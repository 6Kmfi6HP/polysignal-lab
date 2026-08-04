# Research: `stale_orderbook`

**Date:** 2026-08-03
**Related:** [`AWAITING_FIRST_BOOK_RESEARCH.md`](AWAITING_FIRST_BOOK_RESEARCH.md), [`MISSING_QUOTE_DEPTH_RESEARCH.md`](MISSING_QUOTE_DEPTH_RESEARCH.md)

## Verdict

`stale_orderbook` is a **local freshness / readiness-miss gate**, not an upstream exception. After a condition is `READY`, if either UP or DOWN book’s `freshness_ms` exceeds the readiness threshold (default **60 000 ms** from `data.polymarket.max_book_staleness_ms`) — or freshness is missing — evaluation is blocked with strategy status `missing_data`. Short-lived hits that recover within tens of seconds match feed gaps / quiet tokens; long-lived hits match known CLOB WS “silent freeze” behavior and warrant reconnect / REST correlation.

## Follow-up evidence and recovery boundary

In the 2026-08-03 40-minute production window, the only readiness miss beyond 60 seconds was one 120-second XRP/15m `stale_orderbook` episode. Both token receipts were about 60.9 seconds old at entry and the next resubscribe cycle recovered it. Historical snapshot requests observed in that window were not live-book recovery evidence and are no longer part of local recovery.

The pinned PyO3 API exposes `Strategy.request_book_snapshot`, backed by the Rust v2 Polymarket REST implementation. Isolated probes on official `20260730` and post-#4604 `20260731` nightlies returned a historical `OrderBook` through `on_book` but did not demonstrate a managed Cache replacement. Local recovery therefore does not request snapshots or pass `resync_live_book`; a released adapter-owned live-book resync operation remains an upstream requirement.

## What it means (three-way comparison)

| | `awaiting_first_book` | `stale_orderbook` | `missing_quote_depth:*` |
| --- | --- | --- | --- |
| When | Before first bilateral book event | After READY; receipts too old / missing | After READY; asks empty |
| Status | `missing_data` | `missing_data` | `untradable` |
| Blocks trading? | Yes (no evaluation) | Yes (evaluation blocked) | Yes (untradable skip) |
| Phase | `AWAITING_FIRST_BOOK` | Usually still `READY` (orthogonal recovery map) | `READY` |
| Recovery | 60 s resubscribe; 240 s abandon if never READY | 60 s resubscribe cadence; **never abandon** | Wait for ask depth / market exit |

Sources: [`readiness.py`](../src/polysignal_lab/nautilus_runtime/strategy/readiness.py), [`condition_evaluation.py`](../src/polysignal_lab/nautilus_runtime/strategy/condition_evaluation.py), [`subscriptions.py`](../src/polysignal_lab/nautilus_runtime/strategy/subscriptions.py).

## Local mechanism

### Detection

```text
evaluate_condition
  → market_book_generation_ready (must be READY)
  → build MarketView
  → stale_orderbook_sides(view, threshold = orderbook_readiness_threshold_ms)
       for each side: freshness_ms is None OR freshness_ms > threshold
         → mark stale
  → store _stale_orderbook_recovery_by_condition[condition]
  → mark_condition_unready(reason="stale_orderbook")  # ready=False → missing_data
```

`stale_orderbook_sides()` treats **missing freshness** the same as over-threshold freshness ([`readiness.py` L399–412](../src/polysignal_lab/nautilus_runtime/strategy/readiness.py)).

`freshness_ms` comes from last book receipt time vs framework now ([`cache_market_data.py`](../src/polysignal_lab/nautilus_runtime/cache_market_data.py) / subscription `last_book_received_at_by_condition`).

### Dual thresholds (important)

| Threshold | Source | Effect |
| --- | --- | --- |
| **Readiness** | `DecisionPolicy.orderbook_readiness_threshold_ms()` ← `polymarket.max_book_staleness_ms` (**60 000** default) | Whole condition → `stale_orderbook` / `missing_data`; no evaluation |
| **Trade / core** | `orderbook_trade_threshold_ms(strategy)` ← strategy `max_orderbook_staleness_ms` (e.g. `late_consensus` **1 500**) | Only skips `evaluate_core` when already past readiness; still may run exits |

Config: [`config.py`](../src/polysignal_lab/config.py) L169; [`strategy_config.py`](../src/polysignal_lab/domain/strategy_config.py); `config/signal_bot.yaml` `max_book_staleness_ms: 60000`.

Comment on the default: “60s — books refetched every ~30-40s via REST” — historical REST cadence; live path is primarily WS quotes/deltas.

### Recovery (Gap B)

Heartbeat every 10 s ([`lifecycle.py`](../src/polysignal_lab/nautilus_runtime/strategy/lifecycle.py)):

1. `force_resubscribe_if_stale_orderbook` if condition is in `_stale_orderbook_recovery_by_condition` and not currently in first-book awaiting map.
2. Respects 60 s retry window after last rebuild (`_BOOK_GENERATION_STALL_SEC`).
3. Unsubscribe + resubscribe only the stale outcome-side instruments, `begin_market_book_generation` → returns to `awaiting_first_book` for that side subset. A global marker batch starts only when every once-READY active condition awaits both outcomes; all-condition partial-side recovery remains on the normal missing-side retry path. Global suppression ends when any once-READY condition has bilateral receipts strictly later than its batch marker. Before then, a condition with one fresh post-marker side still retries only its missing side at the 60-second cadence; fully silent conditions remain bounded. Markers for still-stalled conditions remain for a renewed batch.
4. **Never abandoned** via the 240 s book-stall clock (W2): once-READY conditions stay active; liveness / data-starvation covers prolonged outages.
5. Clear when `stale_orderbook_recovered`: each previously stale side’s `freshness_ms <=` the stored threshold.

Logs: `condition_stale_orderbook_resubscription`.

### Recovery evaluation at the throttle boundary

The 500 ms market-data throttle previously discarded any recovery event inside the current window. For example, a stale/readiness-miss evaluation at `t0` followed by a fresh book at `t0+100 ms` could remain `missing_data` until another market event or the 10 s heartbeat.

The local fix schedules one non-sliding trailing evaluation for readiness-miss conditions at the original `t0+500 ms` boundary. It reads current Cache state, cancels on an immediate out-of-window evaluation, market exit, or strategy stop, and preserves the same stale thresholds. A still-stale view remains fail-closed and never reaches core or orders.

### Runtime verification (fact)

2026-07-31 production-equivalent run ([`docs/runtime_verification/2026-07-02-nautilus-l1-subscriptions.md`](runtime_verification/2026-07-02-nautilus-l1-subscriptions.md)):

- Real stale transitions at **60 477–60 658 ms** receipt freshness (matches 60 s gate).
- Recoveries completed in **≤41 s**, inside the 120 s / 300 s health windows.
- While stale, strategy status was `missing_data` even with overlapping active / untradable conditions.
- Max book freshness after recovery observed ~13 450 ms in an earlier window.

## Why it appears (ranked)

### H1 — Quiet token / no WS updates past 60 s (strong, expected)

After READY, if neither side (or one side) receives a quote/delta for >60 s, freshness crosses the gate. Polymarket books can be quiet; incremental feeds may not re-emit without a change.

**Fits:** intermittent `stale_orderbook` that clears after a natural update or after 60 s resubscribe.

### H2 — CLOB WS silent freeze (strong for long-lived)

[Polymarket/py-clob-client#292](https://github.com/Polymarket/py-clob-client/issues/292) (**open**): WSS accepts connect + subscribe; PING/PONG works; **zero** `book` / `price_change` for extended periods (hours observed). REST midpoint/price still work. Distinct from RTDS-only freezes.

**Fits:** sustained `stale_orderbook` / readiness_miss despite “subscribed”; resubscribe alone may not help until the connection is truly recycled.

### H3 — Tick-size book epoch / adapter book clear (moderate)

Nautilus Polymarket docs: on `tick_size_change`, local book is dropped and waits for a fresh snapshot while deltas are ignored ([NT polymarket.md](https://raw.githubusercontent.com/nautechsystems/nautilus_trader/develop/docs/integrations/polymarket.md)). During that gap, freshness can age out → `stale_orderbook` (or empty asks → `missing_quote_depth` once a thin book returns).

### H4 — One-sided update starvation (moderate)

Only one outcome keeps updating; the other side’s `freshness_ms` exceeds 60 s → whole condition marked stale (bilateral rule). Different from `missing_quote_depth:DOWN` (asks empty but receipts may be fresh).

### H5 — Batch / reconnect data loss (moderate, mostly mitigated upstream)

- [NT #4604](https://github.com/nautechsystems/nautilus_trader/issues/4604): closed/fixed v2 batch-dispatch bug; not evidence for this pinned v1 runtime.
- [NT #4343](https://github.com/nautechsystems/nautilus_trader/issues/4343): RTDS reconnect dark (spot, not CLOB books).
- The former local wrapper was a **no-op** despite a native request surface. A standard request is historical TC-D13 behavior; local recovery does not use it. Managed-book TC-D14 recovery needs a released adapter-owned live-resync path.

### H6 — Threshold too tight relative to feed cadence (weak–moderate)

Default 60 s is intentional fail-closed. Strategy trade thresholds (e.g. late_consensus 1.5 s) are **stricter for core alpha** but do not create the `stale_orderbook` readiness reason — that always uses the 60 s readiness threshold.

## Upstream findings

| Source | Relevance |
| --- | --- |
| [py-clob-client #292](https://github.com/Polymarket/py-clob-client/issues/292) | Silent CLOB market WS: subscribed, no book updates |
| [NT polymarket.md](https://raw.githubusercontent.com/nautechsystems/nautilus_trader/develop/docs/integrations/polymarket.md) | Tick-size epoch clears book pending snapshot |
| [NT #3963](https://github.com/nautechsystems/nautilus_trader/issues/3963) | Quiet market / initial dump class (closed) |
| [NT #4604](https://github.com/nautechsystems/nautilus_trader/issues/4604) | Historical v2 batch drop, fixed; excluded as current v1 incident evidence |
| [Polymarket AsyncAPI](https://docs.polymarket.com/asyncapi.json) | Snapshot/delta/tick-size event contract; `initial_dump` defaults to true |
| Local runtime verification | Confirmed ~60 s trip + ≤41 s recovery |

No upstream issue defines the string `stale_orderbook` (project-local).

## Recommended triage

When status shows `stale_orderbook` / `missing_data`:

1. Readiness detail: `freshness_ms_by_side`, `max_freshness_ms`, `last_book_received_at_by_side`, `generation_age_ms` / `total_stall_age_ms`.
2. **Just over 60 s, both sides** → quiet book or brief gap; wait for heartbeat resubscribe / next update.
3. **One side ≫ 60 s, other fresh** → one-sided starvation; check that token’s REST `/book` and WS activity.
4. **Persists across multiple `condition_stale_orderbook_resubscription` logs** → suspect #292-class silent freeze; force full WS reconnect / process bounce; compare REST book timestamps.
5. **REST asks updating but Cache freshness stuck** → adapter/cache path, not venue liquidity.

## Mitigations

### Operational

- Treat brief `stale_orderbook` as expected fail-closed at 60 s.
- Alert on **duration** (e.g. readiness miss age → 120 s / 300 s liveness), not every transition.
- For #292: do not trust PING/PONG; require application-level book activity watchdog.

### Code / config (only if lost tradable time is dominated by false stalls)

1. Keep the readiness gate for safety; do not raise `max_book_staleness_ms` blindly without measuring quiet-market false positives.
2. Do not invoke historical snapshots from stale repair, inject directly into Nautilus Cache, or maintain a Python trading side-store. A future live resync must be adapter-owned and explicitly supported by the installed wheel.
3. Richer logs: per-side freshness + last event type when entering/leaving `stale_orderbook`.
4. Optional: inactivity reconnect when **no** market-data events for any subscribed token for N seconds (venue #292 pattern).

## Open gaps

- No live capture in this note of how often `stale_orderbook` is quiet-market vs silent-freeze in current production.
- Whether NT adapter already implements an inactivity reconnect for CLOB market WS in pin `1.231.0a20260730` was not byte-audited here.

## Sources

- Local: `readiness.py`, `condition_evaluation.py`, `subscriptions.py` (`force_resubscribe_if_stale_orderbook`), `lifecycle.py`, `decision_policy.py`, `config.py`
- Local: `docs/runtime_verification/2026-07-02-nautilus-l1-subscriptions.md`
- Local tests: `tests/test_nautilus_book_stall_resubscription.py`
- https://github.com/Polymarket/py-clob-client/issues/292
- https://raw.githubusercontent.com/nautechsystems/nautilus_trader/develop/docs/integrations/polymarket.md
