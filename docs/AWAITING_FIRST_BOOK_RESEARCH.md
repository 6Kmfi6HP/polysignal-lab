# Research: `awaiting_first_book`

**Date:** 2026-08-03
**Related:** [`MISSING_QUOTE_DEPTH_RESEARCH.md`](MISSING_QUOTE_DEPTH_RESEARCH.md), [`STALE_ORDERBOOK_RESEARCH.md`](STALE_ORDERBOOK_RESEARCH.md)

## Verdict

`awaiting_first_book` is a **subscription lifecycle / feed-readiness** reason, not a quote-depth failure. It means both UP and DOWN have not yet delivered a post-subscribe book event, so the condition never reaches `READY` and evaluation is blocked (`missing_data`). Brief appearances on every market rotation are expected; **prolonged** ones point to quiet books without an initial snapshot, one-sided feed silence, or a failed subscribe — not to empty asks.

## Follow-up evidence and native snapshot status

A 40-minute production observation on 2026-08-03 recorded 79 readiness misses, all closed. The 64 `awaiting_first_book` episodes recovered within 16 seconds; none justified a general REST probe. The only actionable long episode was a separate 120-second `stale_orderbook` case.

The pinned PyO3 strategy does expose `Strategy.request_book_snapshot(instrument_id, depth=None, client_id=None, params=None)`, and the Polymarket implementation is in the Rust v2 adapter. The previous local wrapper called the project-only name without delegating to that native method. Isolated public-data probes against `1.231.0a20260730` and the first post-#4604 nightly (`1.231.0a20260731`) showed that a standard request returned an `OrderBook` through `on_book` but did not refresh the managed Cache book. The pinned response also retained `ts_last=0`; the upstream follow-up parses the REST timestamp so TC-D13 and TC-D14 callbacks can be correlated. Method presence, binary strings, and a successful REST response are therefore insufficient TC-D14 evidence.

Keep these contracts separate:

- **TC-D13:** a requested snapshot is returned as historical request data.
- **TC-D14:** a live managed book is atomically replaced and remains continuous with later WS deltas.

The local 60-second AFB/stale recovery path does not call the historical request or pass `resync_live_book`. An adapter-owned live-book resync remains an upstream capability requirement, not a contract provided by the pinned wheel. No Python side-store is used as a trading data source.

## What it means (vs `missing_quote_depth`)

| | `awaiting_first_book` | `missing_quote_depth:*` |
| --- | --- | --- |
| Phase / gate | `ConditionSubscriptionPhase.AWAITING_FIRST_BOOK` | Already `READY`, then `classify_market_view` |
| Strategy status | `missing_data` | `untradable` |
| Requirement | Bilateral **book events** received after generation start | Both sides have **ask depth** |
| Book may be empty? | Yes — a quote/delta with no asks still clears the side | No — empty asks keep untradable |
| Blocks trading? | Yes (never enters evaluation) | Yes (evaluation skipped as untradable) |

Sources: [`subscriptions.py`](../src/polysignal_lab/nautilus_runtime/strategy/subscriptions.py), [`condition_evaluation.py`](../src/polysignal_lab/nautilus_runtime/strategy/condition_evaluation.py), [`readiness.py`](../src/polysignal_lab/nautilus_runtime/strategy/readiness.py).

## Lifecycle (local)

```text
UNSUBSCRIBED
  → PENDING_METADATA / PENDING_INSTRUMENT
  → SUBSCRIBE_ISSUED
  → AWAITING_FIRST_BOOK   ← begin_market_book_generation (await UP+DOWN)
  → READY                 ← both sides observed after generation start
```

1. Subscribe issues quotes + book_deltas (fire-and-forget; no wire ACK).
2. `begin_market_book_generation` sets `awaiting_book_sides = {UP, DOWN}` and phase `AWAITING_FIRST_BOOK`.
3. Each quote/book/delta event → `observe_market_book_side` discards that side.
4. When both sides clear → `finish_market_book_generation` → `READY`.
5. Only then does `evaluate_condition` build a `MarketView` (where `missing_quote_depth` can appear).

Any instrument-scoped market-data event counts — **depth is not checked** at this gate ([`order_book_observation`](../src/polysignal_lab/nautilus_runtime/strategy/market_data_events.py)).

### Local 500 ms recovery delay and fix

The local market-data evaluator is leading-edge throttled to one evaluation per condition per 500 ms. A first UP event could record `awaiting_first_book`; if DOWN arrived 100 ms later, the old code completed the book generation but discarded the recovery evaluation. Status then waited for another event or the 10 s heartbeat.

The recovery scheduler keeps the leading edge and adds one fixed-deadline trailing evaluation only for a condition already in readiness miss or `untradable`. Bursts coalesce without moving the deadline; the callback reads the latest Cache-built `MarketView`, not the old event. Exit and stop cancel it. The deterministic regression in `tests/test_nautilus_strategy_base.py` covers bilateral arrival at +100 ms and evaluation at +500 ms.

## Why it shows up often

### 1. Normal rotation / subscribe warm-up (expected, short)

Every new or rotated condition starts in `AWAITING_FIRST_BOOK` until the first bilateral books arrive. Runtime verification measured first bilateral latency typically **well under 1 s** (max ~507 ms; overlapping 15m rotation ~141 ms) within a 120 s acceptance window.
Source: [`docs/runtime_verification/2026-07-02-nautilus-l1-subscriptions.md`](runtime_verification/2026-07-02-nautilus-l1-subscriptions.md).

**Inference:** Frequent short-lived UI/status samples of `awaiting_first_book` during 5m rotations are largely this warm-up, not a permanent block.

### 2. Quiet market / no initial snapshot (designed stall)

Local comments state Polymarket WS can leave a subscribed condition without a first book until the book changes; incremental `book_delta` has no snapshot fallback ([`subscriptions.py` L56–60](../src/polysignal_lab/nautilus_runtime/strategy/subscriptions.py)).

Upstream: [NT #3963](https://github.com/nautechsystems/nautilus_trader/issues/3963) — without `initial_dump: true`, quiet markets may never emit a book frame until a natural update. Closed after reporter noted defaults already set `initial_dump`; residual quiet-token behavior can still delay first events.

### 3. Historical snapshot boundary

The historical wrapper was a logged no-op even though the PyO3 base exposes `request_book_snapshot`. A standard native request is a historical TC-D13 operation; it is not live recovery evidence and the recovery cycle does not request it. TC-D14 managed Cache refresh needs a released adapter-owned live-resync contract.

### 4. One side never updates

If UP events arrive but DOWN never does (or vice versa), phase stays `AWAITING_FIRST_BOOK` with `awaiting_book_sides: ["DOWN"]`. Distinct from `missing_quote_depth:DOWN` (which requires READY + empty asks).

Possible causes (ranked):

1. Quiet DOWN token / no WS frames after subscribe (venue).
2. Historical auto-load skip subscribe ([NT #4574](https://github.com/nautechsystems/nautilus_trader/issues/4574), fixed 2026-07-26; pin `1.231.0a20260730` should include fix).
3. Instrument pending / wrong token mapping (would often show `awaiting_instrument` first).

### 5. Stale-book repair re-enters the phase

Once-READY conditions that go stale are rebuilt via `force_resubscribe_if_stale_orderbook` → `begin_market_book_generation` again, so `awaiting_first_book` reappears during repair. Those are **not** abandoned by the 240 s clock (W2: only never-ready conditions abandon).

Ordinary partial stale repair and global-silent recovery have different evidence:

- Ordinary partial repair seeds `awaiting_book_sides` with only the stale outcome sides, so those sides can return the condition to `READY` without resetting a healthy side.
- At the start of a heartbeat, when every once-READY active condition needs either first-book or stale-book recovery, one global recovery epoch is opened and one initial batch targets only each condition's missing outcome sides. Until one once-READY condition receives both UP and DOWN strictly after that epoch, both recovery paths keep readiness/evaluation/liveness work active but suppress every later wire retry. A one-sided receipt updates only that side and does not release suppression.
- Bilateral recovery of any once-READY condition closes the epoch. Conditions still awaiting a side then resume the ordinary 60-second missing-side-only retry. Market rotation does not close an epoch; newly discovered never-READY conditions retain their independent 240-second abandon clock. An orphan epoch is reclaimed only after no active once-READY conditions remain.

## Built-in recovery timers

| Timer | Value | Behavior |
| --- | --- | --- |
| Stall / resubscribe | 60 s | Heartbeat: if still awaiting first book → resubscribe only the still-awaited instruments and retain the generation's side receipts; during a detected feed-wide outage, the first recovery batch is bounded across once-READY and never-READY conditions |
| Abandon | 240 s | If first book **never** arrived → drop condition from active set (`condition_abandoned_no_book`) |
| Liveness readiness miss | 300 s | Node unhealthy if readiness miss persists; abandon is set below this (240+heartbeat &lt; 300) |

Heartbeat every 10 s runs `force_resubscribe_if_book_stalled` ([`lifecycle.py`](../src/polysignal_lab/nautilus_runtime/strategy/lifecycle.py)).

## Upstream findings

| Source | Relevance |
| --- | --- |
| [NT Polymarket docs](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/integrations/polymarket.md) | Live L2 deltas, quotes, trades — no dual-side first-book SLA |
| [NT #3963](https://github.com/nautechsystems/nautilus_trader/issues/3963) | Missing initial dump → no book until natural change; closed |
| [NT #4574](https://github.com/nautechsystems/nautilus_trader/issues/4574) | Auto-load race: subscribe logged but WS never joined for rotating Up/Down markets; fixed before our nightly |
| [NT #4604](https://github.com/nautechsystems/nautilus_trader/issues/4604) | Closed/fixed v2 batch-dispatch bug. It shows a historical silent-loss class but is not evidence for this pinned v1 incident. |
| [py-clob-client #292](https://github.com/Polymarket/py-clob-client/issues/292) (open) | CLOB WSS: subscribe + PING OK, but no `book`/`price_change` for long periods while REST still works — strongest venue-side match for prolonged `awaiting_first_book` |
| [Polymarket AsyncAPI](https://docs.polymarket.com/asyncapi.json) | Subscription is per token ID and `initial_dump` defaults to true; bilateral readiness remains an application concern. |

No upstream issue defines the string `awaiting_first_book` (project-local). More depth on ask emptiness after READY: [`MISSING_QUOTE_DEPTH_RESEARCH.md`](MISSING_QUOTE_DEPTH_RESEARCH.md).

## Recommended triage

When status shows `awaiting_first_book` / `missing_data`:

1. Read readiness detail: `awaiting_book_sides`, `generation_age_ms`, `subscribe_intent_age_ms`, `last_book_received_at_by_side`.
2. **generation_age_ms ≪ 60 s** after rotation → warm-up; wait.
3. **One side in `awaiting_book_sides`, other has receipts** → one-sided feed silence; check REST `/book` for that token; watch for `condition_book_resubscription` at ~60 s.
4. **Both sides empty past 60 s** → stall recovery path; during a feed-wide outage, later wire retries are suppressed but a never-READY condition still abandons past ~240 s.
5. **REST has updates but Cache never observes** → subscribe/adapter path (#4574 family); confirm NT version and subscribe logs.

Do **not** “fix” by relaxing ask-depth policy — that only affects `missing_quote_depth` after READY.

## Mitigations

### Operational

- Alert on **persistent** readiness miss / high `generation_age_ms`, not on every sample during 5m rotations.
- Correlate with logs: `condition_book_resubscription` and `condition_abandoned_no_book`. Recovery does not emit snapshot-backstop events.

### Code (only if prolonged stalls dominate lost tradable time)

1. **Adapter boundary:** do not treat a historical snapshot request as live recovery. A future released adapter-owned live-resync operation must own any snapshot replacement and WS delta replay.
2. Keep NT nightlies past the [#4574](https://github.com/nautechsystems/nautilus_trader/issues/4574) fix (already true for `20260730`).
3. Optional: shorten `_BOOK_GENERATION_STALL_SEC` if telemetry shows most recoveries need only a quick resubscribe — tradeoff: more WS churn.

## Open gaps

- The 40-minute follow-up measured current production (64 AFB episodes, all recovered within 16 seconds); a longer observation is still needed for rare venue-wide freezes.
- The official AsyncAPI says `initial_dump` defaults to true. This audit did not capture a live wire subscription payload from the pinned wheel.

## Sources

- Local: `src/polysignal_lab/nautilus_runtime/strategy/subscriptions.py`, `market_data_events.py`, `condition_evaluation.py`, `readiness.py`, `lifecycle.py`, `native_strategy.py`
- Local: `docs/runtime_verification/2026-07-02-nautilus-l1-subscriptions.md`
- Local tests: `tests/test_nautilus_book_stall_resubscription.py`, `tests/test_nautilus_subscription_health.py`
- [NT #3963](https://github.com/nautechsystems/nautilus_trader/issues/3963), [NT #4574](https://github.com/nautechsystems/nautilus_trader/issues/4574)
- [Polymarket Real-Time Data](https://docs.polymarket.com/market-data/realtime-data)
