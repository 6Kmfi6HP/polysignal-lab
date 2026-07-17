# Diff Notes

## Round 1 (destructive, no verify)

### Product behavior

- **Runtime trading path**: no intentional change. Removed unused domain `OrderBook` model and dead package stub.
- **Telegram formatting tests**: mark price still via `best_bid` attribute; fixture type is now `SideBookView` (same attribute).
- **Test factories `sample_book`**: now returns `SideBookView` (Cache projection shape), not Pydantic OrderBook.

### Explicit non-changes

- `PolySignalNativeStrategy` not thinned yet (still ~1134 LOC).
- SQLiteStore / alpha clone extraction not done.
- Safety forbid-list strings kept (still block reintroduction of deleted dual-path symbols).

## Round 2 — B4 Strategy thin

### Product behavior

- **No intentional trading-behavior change.** Decision path still: Cache books → MarketViewAssembler → alpha core → in-process `DecisionPolicy` → `submit_approved_decision` / `order_factory` + `submit_order`.
- Multi-step evaluation, readiness, market-data observation, and heartbeat scheduling live under `nautilus_runtime/strategy/*`; Strategy only dispatches Nautilus callbacks and holds DI fields.

### Explicit non-changes

- Order submit path still only `native_order.submit_approved_decision`.
- `DecisionPolicy` remains Strategy-owned (no Actor bus).
- SQLiteStore / alpha clones / Gamma parse not touched (B5–B7).
- Protocol-facing methods retained as one-line adapters.

### Metrics

- `native_strategy.py`: 1134 → 461 LOC
- pyscn: 0 dependency cycles; health 74/100 (C); ~10% clone fragments

## Round 3 — B5 NT adapter convergence

### Product behavior

- **Instrument ID**: if Strategy is constructed without an explicit `instrument_id_resolver`, resolution always goes `MarketCatalog.instrument_id_for_token` → official `get_polymarket_instrument_id`. The identity fallback (`token_id` as instrument id) is **gone**. Call sites that omit a resolver now fail loudly on unknown tokens instead of submitting under a fake id.
- **Gamma market parse**: every outcome token's label is produced by NT `parse_polymarket_instrument`. Soft-fail (local name / index-only side without NT) is **gone**. Payloads with hyphenated condition/token ids that violate NT `{condition}-{token}` symbol shape will raise (real CLOB token ids are numeric; condition ids are 0x hex).
- **Order status mapping**: `PolymarketEnumParser.to_nautilus_order_status` removed. Runtime continues to use NT event status enums / existing projections; no production caller existed.

### Explicit non-changes

- Domain Market enrichment (PTB, UMA/resolution status heuristics, Side UP/DOWN product language) remains — NT BinaryOption does not own these.
- `to_nautilus_order_side` / `to_nautilus_time_in_force` kept (domain → NT order construction).
- MarketCatalog injectable resolver kept for unit tests only; production default is official NT helper.
- SQLiteStore / alpha clones not touched (B6/B7).

### Metrics

- `native_strategy.py`: still 461 LOC
- safety-scan: PASS
- B5 gate pytest: PASS

## Round 4 — B6 storage dual-API purge

### Product behavior

- **No trading-path change.** Report read API on `SQLiteStore` is now only `daily_reports` / `strategy_leaderboard` (ReportingReadPort names). Persistence still exposes `query_daily_reports` as a thin facade for Telegram.
- Delete helpers for report_result / daily_report rows share one implementation; public method names unchanged.

### Explicit non-changes

- Publish outbox / claim / authorize / complete daily report flows untouched.
- Legacy paper table migration still present (one-shot upgrade).
- Alpha cores not touched in this round (B7).

### Metrics

- sqlite_store ~2074 → 2079 LOC (helper + removed dual bodies)
- safety-scan: PASS
- storage/dashboard/persistence/boundary tests: PASS

## Round 5 — B7 alpha `_decision` clone purge

### Product behavior

- **No intentional signal-semantics change.** Entry decisions still build the same `OrderDecisionSpec` / `AlphaDecision` via `helpers.build_order_decision`. Removed only per-core passthrough methods that duplicated that call.

### Explicit non-changes

- Hedge/stop logic bodies in dump_hedge and dual_reversion remain (already use `build_hedge_order_decision`).
- Fibonacci / other cores already called `build_order_decision` directly.
- SQLiteStore / NT runtime not touched.

### Metrics

- clone_fragment_pct: ~9.9% → **9.6%** (full tree); storage+alpha mid-measure was 15%
- pyscn: 0 cycles; health 87/100 (B)
- alpha dump/pre_order/cross_market tests: PASS

## Round 6 — B8 boundary harden

### Product behavior

- **No intentional trading-behavior change.** Decision/order path unchanged.
- Safety scanner now blocks additional dual-path residue symbols if reintroduced in project source or guarded packages.
- Strategy host lost only dead private wrappers (no Protocol collaborator depended on them).

### Explicit non-changes

- Keep `on_quote`/`on_book`/`on_trade`/`on_book_deltas` aliases (NT API surface variants).
- Keep Protocol-required adapters (`_record_nautilus_*`, `_subscribe_market_conditions`, etc.).
- SQLiteStore / alpha hedge clones not touched.
- Safety forbid list itself remains (anti-regression, not dual truth).

### Metrics

- `native_strategy.py`: 461 → **431** LOC
- safety-scan: PASS
- B8 gate pytest (safety/platform/dependency/strategy/native_exit/decision_policy/native_order): PASS
- forbidden_symbol_hits_src outside safety: **0**

## Round 7 — B9 full verify + host thin closeout

### Product behavior

- Decision/order path unchanged: Cache → MarketView → alpha → in-process DecisionPolicy → `native_order` (`order_factory` + `submit_order`).
- Strategy construction DI moved to `strategy/host_init.py`; public constructor kwargs and runtime fields unchanged.
- Integration smoke fixtures use NT-legal numeric CLOB token ids (aligns B5 hard parse).
- Authority: installed `nautilus_trader==1.231.0`, `src/`, and `docs/nautilus_reference/developer_guide/*`.

### Explicit non-changes

- SQLiteStore left as REPORT_ONLY residual; no settlement/redeem authority; no live money paths.
- Safety forbid list and accepted domain boundaries retained.

### Verify / metrics

- safety-scan + platform/safety/dependency + full `NAUTILUS_REQUIRED=1 pytest`: PASS
- `native_strategy.py`: 431 → **342** LOC (≤400); forbidden dual-path hits outside safety: **0**
- pyscn: 0 cycles; clone ~9.5–9.6%; registration = Strategy + MarketRotationActor only
- Decision at end of B9: **STOP: CLEAN** (Round 8 later authorized separately)


## Round 8 — B10 destructive audit purge (authorized)

### Product behavior (intentional breaks)

- **Credentials**: Python no longer validates or injects POLYMARKET_* secrets into LiveNode configs. Live path requires only `allow_live_polymarket_execution` + `safety.allow_live_market_actions`. Adapter Rust resolves credentials.
- **Subscriptions**: `wire_condition_ids` removed as confirmed wire truth. Subscribe issues only set `subscribe_intent_condition_ids`; readiness reports `subscribe_requested` / book-generation states, not `"subscribed"` / `wire_subscribed`.
- **CustomData**: Cython CustomData unwrap path removed; only `nautilus_pyo3.CustomData` unwraps.
- **Strategy callbacks**: Alias methods `on_quote` / `on_book` / `on_trade` / `on_book_deltas` deleted.
- **Fills/sides**: Missing positive fill price or unresolved side raises and is quarantined — no Side.UP / scraped ask fabrication.
- **Reporting projection**: SimpleNamespace middle layer deleted. Storage preserves native order statuses (DENIED stays DENIED; ACCEPTED stays ACCEPTED). Unknown statuses become empty and are excluded by dashboard validity.
- **Discovery worker**: `close()` joins (`wait=True`); in-flight refresh no longer continues as a supported post-close contract.
- **Cross-market**: Single-market `evaluate()` approximation deleted (returns []). Multi-leg path is `evaluate_group` only.
- **Gamma parse**: Missing outcome labels or non UP/DOWN text raise. Status no longer ACTIVE-by-default when `active` absent.

### Explicit non-changes (KEEP)

- NautilusCacheMarketDataProvider, native_order order_factory/submit_order, get_polymarket_instrument_id, MarketCatalog UP/DOWN business semantics, LiveNode/Strategy/Cache usage.

### Verify

- Focused pytest (signal/market/nautilus/dashboard/platform/observability/safety): **PASS**
