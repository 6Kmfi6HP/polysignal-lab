# PolySignal Lab — NautilusTrader 设计合规审查报告

> **历史审查快照（已过时）**：本文包含已删除的 `LiveNode.builder`、旧 scheduler 运行时和旧行号，不能作为当前架构指导。当前实现以 `docs/NAUTILUS_BRIDGE_BOUNDARY.md` 与 `docs/architecture-review-2026-07-09.md` 为准。
>
> **当前边界补充（2026-07-11）**：当前 generic TP/SL/max-hold bridge 位于 `native_strategy_exit.py`，仅生成 reduce-only native order decision；由于锁定的 NautilusTrader 1.229.0 没有公开的 prediction-market payout authority，settlement 仍明确为 report-only，不伪造 `PositionClosed`、Account 或 Portfolio mutation。

生成日期: 2026-07-06

---

Below is a condensed summary (under 500 words) of the Nautilus boundary rules most relevant to a compliance audit, extracted from `docs/nautilus_reference/developer_guide/adapters.md`:

---

**Order Command Outcome Policy** -- The most critical compliance boundary. Adapters may emit rejection events (`OrderRejected`, `OrderModifyRejected`, `OrderCancelRejected`) only from definitive evidence: structured venue responses, per-order batch results, or local prepare failures that can be unambiguously attributed to a single command. When the outcome is unknown (transport errors, timeouts, WebSocket send failures, disconnects, HTTP 5xx, rate limits, retry exhaustion, parse failures after the request may have reached the venue), the adapter must NOT emit a rejection event -- it must leave the order in-flight and let reconciliation resolve the state. For batch commands, a whole-request failure must not produce one rejection per order; only per-order venue results that unambiguously reject a command are acceptable evidence.

**Credential Security** -- Config structs are pure DTOs and must never contain credential resolution logic; all resolution belongs in a dedicated `common/credential.rs` module. Environment variable names are centralized in a single `credential_env_vars()` function and never duplicated as string literals. Secrets are stored as `Box<[u8]>` with `#[zeroize]`. Invalid credentials must fail fast with an error, never silently degrade to unauthenticated mode.

**Fill and Event Deduplication** -- Two mechanisms prevent double-reporting of fills: (1) `WsDispatchState` tracks `emitted_accepted`, `filled_orders`, and `triggered_orders` via bounded `DashSet` (capacity 10,000) to prevent duplicate lifecycle events across reconnections and fast-fill races. (2) Cross-source deduplication uses `BoundedDedup<T>` with trade IDs (symbol + trade ID tuples) to prevent the same fill from being emitted from both WebSocket user data and HTTP reconciliation.

**Connection Lifecycle** -- Both data and execution clients must complete ALL initialization inside `connect()` before signaling connected. Execution clients follow a strict sequence: ensure instruments initialized, connect WebSocket, subscribe channels, fetch account state, await account registration, then signal connected. This prevents strategies from running against incomplete state.

**Timestamp Integrity** -- All venue timestamps are converted at the parser boundary using `nautilus_core::datetime::millis_to_nanos`. `ts_event` is the converted venue timestamp; `ts_init` is `clock.get_time_ns()`. Instruments with no venue timestamp use `clock.get_time_ns()` for both fields.

**Enum Hardening** -- Reference/descriptive fields (instrument type, market status) must include an `Unknown` fallback so new venue values degrade gracefully with a warning. Order/fill/position state fields must stay strict: an unmodeled value must fail deserialization loudly to prevent the engine from running out of sync with the venue.

**Instrument Status Diffing** -- When polling instrument status via REST, the diff function (`diff_and_emit_statuses`) emits `InstrumentStatus` events only for changed instruments. Instruments absent from a new snapshot are treated as removed and emit `NotAvailableForTrading`.

**Reconnection Guarantees** -- On reconnect, adapters must re-authenticate and restore all tracked subscriptions. Failed subscriptions remain pending and are retried automatically. The handler uses a `SetClient` handshake with strict ordering to prevent races where commands arrive before the handler is wired.

**Data Integrity** -- Order book delta flags (`F_LAST`, `F_SNAPSHOT`) must be set correctly on every delta; missing `F_LAST` is a silent bug where subscribers never receive data when buffering is enabled. Test data must be sourced from official API docs or live API calls -- never fabricated, to avoid missing edge cases in real venue responses.

---

## Agent A - Nautilus Runtime Assembly

### Evidence
- Primary tool: `codegraph_explore` on `node.py`, `live_node.py`, `trading_node.py`, `runtime_classes.py`, `native_strategy.py`, `market_rotation.py`, `decision_policy_actor.py`
- Direct reads: `node.py` (1020 lines), `native_strategy.py` (1342 lines), `runtime_classes.py`, `trading_node.py`, `market_rotation.py`, `decision_policy_actor.py`, `node_cli.py`
- Grep confirm: `TradingNode` (zero results in runtime), `asyncio.create_task` (zero in market_rotation/sidecar_data), `PaperWallet`/`PaperSimulator`/`PaperExitEngine` (zero in runtime)

### Degradation notes
None. The index served source without fallback.

### Nautilus Alignment

| Project Pattern | Nautilus Expected | Verdict | Evidence(file:line) |
|---|---|---|---|
| LiveNode builder chain | `LiveNode.builder(...).add_data_client(...).add_exec_client(...).build()` | **Accept** | `live_node.py:44-70` - Uses `LiveNode.builder(trader_id_text, trader_id, Environment.SANDBOX)` with downstream `add_data_client`/`add_exec_client`/`build()` |
| Strategy registration | `node.trader.add_strategy(...)` | **Accept** | `node.py:282-283` - iterates strategies, calls `node.trader.add_strategy(strategy)` |
| Actor registration | `node.trader.add_actor(...)` | **Accept** | `node.py:279-281` - calls `node.trader.add_actor()` for market rotation and policy actors |
| Runtime config construction | Nautilus config classes, not dicts | **Accept** | `live_node.py:74-92`, `runtime_classes.py:52` - uses `CacheConfig`, `LiveDataEngineConfig`, `LiveExecEngineConfig`, `StrategyConfig()`, `ActorConfig()` |
| Paper execution | `SandboxLiveExecClientFactory` | **Accept** | `live_node.py:64-68` - adds `PAPER_EXEC_CLIENT_ID` with `SandboxLiveExecClientFactory` |
| Live Polymarket data | `PolymarketLiveDataClientFactory` | **Accept** | `live_node.py:59-63` - adds `POLYMARKET_CLIENT_ID` with `PolymarketLiveDataClientFactory` |
| Live execution guard | `assert_no_live_polymarket_execution` | **Accept** | `live_node.py:54` - asserts no `POLYMARKET_CLIENT_ID` in `exec_clients` before `build()` |
| `on_save`/`on_load` | `dict[str, bytes]`, key format `polysignal.<name>.state.v<N>` | **Accept** | `native_strategy.py:283-286`, `decision_policy_actor.py:15-21` - key format via `nautilus_bridge.state` confirms `polysignal.{name}.state.v{version}` |
| No `TradingNode` class | Zero references in runtime source | **Accept** | `grep -rn "TradingNode" src/polysignal_lab/nautilus_runtime/ --include="*.py"` (no output) |
| `TradingNodeConfig` blocked | Safety-scan blocked symbol | **Accept** | `observability/safety.py:49` - in `LOCAL_PAPER_ISOLATION_SYMBOLS` |
| No monkeypatches | No `monkeypatch.setattr` on Nautilus internals | **Accept** | Runtime uses lazy imports with module-level placeholders (`node.py:146-187`); test-targeted, not production monkeypatches |
| No `new_class(...)` | No dynamic runtime class factory | **Accept** | `node.py` and `runtime_classes.py` use standard class instantiation; no calls to `type()` or `new_class()` |
| Single lifecycle entry | One `LiveNode.run()` call | **Accept** | `node.py:838` (`_run_async_node_with_report_loop`), `node.py:928-932` (`_run_sync_cli_main`) both delegate to `node.run()` |
| No `asyncio.create_task` in sidecar/rotation | Path-banned in safety scan | **Accept** | `grep -n "asyncio.create_task" market_rotation.py sidecar_data.py` (no output) |
| State persistence contract | JSON bytes, no pickle, unknown version fails closed | **Accept** | `nautilus_bridge/state.py:16-27` - `encode_state`/`decode_state` use `f"polysignal.{name}.state.v{version}"` with `StateSchemaError` on unknown schema |

### Repeated Wheels

| Severity | Project Module | Nautilus Equivalent | Evidence | Suggestion |
|---|---|---|---|---|
| P2 | `native_strategy.py` (1342 lines) | Nautilus `Strategy` callbacks + on_save/on_load | The file aggregates ALL Nautilus callback-shaped logic: order events, fill events, position tracking, book subscriptions, custom data subscriptions, exit policy, state persistence — every Nautilus-facing callback | Split into focused files: `native_lifecycle.py` (on_start/stop/save/load), `native_orders.py` (order/fill events), `native_subscriptions.py` (subscribe/unsubscribe), `native_exit.py` (exit position handling, partially done in separate file) |
| P2 | `node.py` (1020 lines) | Nautilus `LiveNode` | God-module with 5+ responsibilities: runtime assembly, CLI sync wrapper, CLI async wrapper, OS signal handling, crash logging, thread stack dumps, thread-based telegram/report sidecars | Split: `node_runtime.py` (build_*, _create_*, _attach_*, _register_*), `node_cli.py` (sync/async entry points — already partially extracted but still imported from node.py), `node_crash.py` (crash logging, atexit), `node_signals.py` (already exists) |
| Accept | `market_rotation.py` (374 lines) | Nautilus Actor + clock timer | Market rotation replicates a market refresh/publish timer that overlaps with Nautilus data client's `update_instruments_interval_mins` capability | Accept — the rotation layer also manages spot/price-to-beat data not covered by Polymarket adapter; reasonable bridge |
| Accept | `decision_policy.py` + `decision_policy_actor.py` | Nautilus Actor's on_save/on_load | `NautilusDecisionPolicyActor` wraps `DecisionPolicyActor` with Nautilus lifecycle hooks | Accept — thin seam (22 lines) that adapts pure logic to Nautilus lifecycle per bridge pattern |

### Oversized

| Symbol | file:line | Lines | Issue |
|---|---|---|---|
| `node.py` | (entire file) | 1020 | Exceeds 400-line threshold; 5+ responsibilities in one module |
| `native_strategy.py` | (entire file) | 1342 | Exceeds 400-line threshold; aggregates all Nautilus-facing callbacks, order/fill logic, subscription management, custom data handling |
| `market_rotation.py` | (entire file) | 374 | Near threshold (374/400); market rotation logic, spot/PTB publishing, epoch tracking |

### Acceptable
- `live_node.py` (163 lines) — clean single-purpose module for building a LiveNode via canonical Nautilus builder path.
- `runtime_classes.py` (110 lines) — thin seam classes combining PolySignal logic with Nautilus `Strategy`/`Actor`.
- `decision_policy_actor.py` (22 lines) — minimal Nautilus lifecycle wrapper around pure decision policy.
- `trading_node.py` (15 lines) — constants only (`PAPER_EXEC_CLIENT_ID`, `POLYMARKET_CLIENT_ID`) and a one-shot safety assertion.
- `node_cli.py` (81 lines) — async CLI orchestrator cleanly separated from node assembly.
- Node uses `Environment.SANDBOX` correctly, never constructs live execution clients.
- All Nautilus config objects are constructed via the canonical class, not dicts.
- No `TradingNode` class anywhere in runtime source.
- No monkeypatch/dynamic factory patterns applied to Nautilus internals.
- No `asyncio.create_task` in safety-banned paths.
- No forbidden internal classes (`NautilusMatchingPaperExecutionClient`, `PaperWallet`, etc.) appear.

### Open Questions
1. **`node.py:198` — `_create_configured_live_node` returns `tuple[_NautilusNodeLike, object]` but is listed with "no covering tests found".** Should this path have integration test coverage? The function is critical because it bridges the settings/instrument config to the Nautilus LiveNode.
2. **`node.py:189` — `_load_runtime_classes` is also untested.** It imports the runtime class seam and is an obvious failure point if `runtime_classes.py`'s MRO ordering changes.
3. **`node.py:215-228` — `_create_configured_live_node` loads `build_paper_live_node` via deferred import inside the function body.** This is fine for lazy loading, but any import failure would not surface until runtime execution. Consider whether an import guard at module level is warranted.
4. **`_ensure_nautilus_imports` (`node.py:146-187`)** has a complex `sys.modules` sync dance to support test monkeypatching. The comment documents this, but the pattern is fragile — if code paths exercise this while `sys.modules` state is inconsistent, the cast/assign logic could silently fall through. The test suite should verify this path explicitly.

---

## [Agent B] Execution & Orders

### Evidence

- **Primary tool**: `mcp__fast_context_search` with queries on execution, orders, decision policy, exit policy, fill simulation
- **Full file reads**: `native_order.py`, `native_exit.py`, `order_plan.py`, `order_mapping.py`, `exit_policy.py`, `decision_policy.py`, `nautilus_runtime/execution.py`, `strategies/execution.py`, `native_strategy.py`, `strategies/base.py`, `decision_policy_actor.py`
- **Cross-references**: verified usage of `bracket_attachments_for`, `ExitPolicyConfig`, `CompatPolySignalNautilusStrategy` across production source
- **Degradation notes**: None; all files were accessible and directly readable.

### Nautilus Alignment

| Project Pattern | Nautilus Expected | Verdict | Evidence(file:line) |
|---|---|---|---|
| Order submission via `strategy.order_factory.limit()` + `strategy.submit_order()` | Use Nautilus `order_factory` and `submit_order` via strategy | ALIGNED | native_order.py:63-73, native_exit.py:25-38 |
| Order spec mapping (`OrderIntent` -> `TimeInForce`) | Bridge may map domain enums to Nautilus enums | ALIGNED | native_order.py:85-90, order_plan.py:37-43 |
| Decision policy as standalone class (`DecisionPolicyActor`) | Domain gating logic kept outside Actor; Nautilus owns actor lifecycle | ALIGNED | decision_policy.py:111-241 |
| `NautilusDecisionPolicyActor` with `on_save`/`on_load` | Bridge state persistence for domain-only data | ALIGNED | decision_policy_actor.py:10-21 |
| Exit policy reading position projections (read-only `Mapping[str, object]`) | Strategy may read portfolio/cache projections for exit logic | ALIGNED | exit_policy.py:49-73, native_strategy.py:518-535 |
| `strategies/execution.py` build_strategy_schedule() | Legacy scheduler path (default runtime) | ALIGNED (legacy) | strategies/execution.py:103-120 |
| Lazy Nautilus type loading via `import_module` | No hard Nautilus dependency in bridge; graceful fallback | ALIGNED | native_order.py:145-150 |

### Repeated Wheels

| Severity | Project Module | Nautilus Equivalent | Evidence | Suggestion |
|---|---|---|---|---|
| P2 | `order_plan.py` order spec construction | Nautilus `order_factory.limit()` parameter preparation | order_plan.py:11-34: maps domain `OrderIntent` to Nautilus `TimeInForce`, resolves price/quantity/tags | Acceptable thin bridge - no self-built order type |
| P2 | `decision_policy.py` DecisionPolicyActor | Nautilus `Actor` with strategy callbacks | decision_policy.py:111-241: gate/arbiter/consensus logic bundled as standalone | Acceptable - domain gating logic, not Nautilus Actor lifecycle |
| P2 | `exit_policy.py` evaluate_exit_decision | Nautilus bracket orders / TP/SL on `OrderFilled` | exit_policy.py:49-73: reads position projections, produces exit decisions | Acceptable - strategy-level exit gating; orders submitted through Nautilus factory |
| P2 | `decision_policy_actor.py` NautilusDecisionPolicyActor.on_save/on_load | Nautilus Strategy.on_save/on_load | decision_policy_actor.py:15-21: bridges domain state to Nautilus lifecycle | Acceptable thin bridge - domain-only state keyed as "decision_policy" |
| P1 | `strategies/base.py` CompatPolySignalNautilusStrategy (v1 path) | Nautilus Strategy lifecycle callbacks | base.py:38-560: implements on_data, on_order_* callbacks; produces NautilusOrderSpec | Shadow from v1->v2 migration. 11 strategies inherit from it. Consolidate with `PolySignalNativeStrategy` when deprecating the v1 path. |

### Oversized

| Symbol | File | Lines | Issue |
|---|---|---|---|
| `PolySignalNativeStrategy` | native_strategy.py:172-1310 | ~1160 (class body) | Single class handles 12 distinct responsibilities: data classification, subscription management, market data routing, decision handling, exit evaluation, order event extraction, fill event extraction, position tracking, telemetry projection, state persistence, instrument resolution, assembly management. File is 1342 lines total. |
| `PolySignalNativeStrategy._order_event` | native_strategy.py:779-818 | 40 | OK (within 80) |
| `PolySignalNativeStrategy._fill_event` | native_strategy.py:820-858 | 39 | OK (within 80) |
| `evaluate_exit_decision` | exit_policy.py:49-73 | 25 | OK |
| `bracket_attachments_for` | exit_policy.py:76-117 | 42 | OK |

### Acceptable

- **`order_mapping.py`** (27 lines): Thin dispatch to `build_order_spec`; no logic duplication.
- **`native_exit.py`** (40 lines): Trivial exit-order submission through `strategy.order_factory.limit()`; no self-built exit engine.
- **`nautilus_runtime/execution.py`** (5 lines): Pure re-export of `order_spec_from_decision` for downstream stability; no executor logic.
- **`strategies/execution.py`** (121 lines): Legacy DAG-based strategy scheduler for default runtime, not Nautilus; no trading execution logic. No recent feature additions -- stable legacy glue.
- **`NautilusOrderFactory` protocol** (native_order.py:17-29): Protocol typing only, no implementation.
- **`OrderSubmittingStrategy` protocol** (native_order.py:32-36): Protocol typing only, no implementation.
- **Lazy Nautilus type resolution** (`_optional_nautilus_attr`, `_enum_member`): Correct pattern for Nautilus-free default import.
- **No fill simulation found anywhere** in the Execution & Orders domain. Fills arrive exclusively through Nautilus `on_order_filled` callback.
- **No partial fill logic, position reconciliation, or wallet ledger** found in this scope.
- **No self-built `MarketOrder`, `StopMarket`, `StopLimit`** -- bridge only produces limit orders via Nautilus `order_factory.limit()`.

### Open Questions

1. **`bracket_attachments_for` is dead production code**. Defined in `exit_policy.py:76-117` with tests but never called from any production path. `PolySignalNativeStrategy._submit_exit_position` calls only `evaluate_exit_decision` (the single-exit variant). Is `bracket_attachments_for` planned for future use, or should it be removed to reduce maintenance surface?

2. **Dual strategy base class migration status**. `CompatPolySignalNautilusStrategy` (strategies/base.py, 560 lines, 11 inheriting strategies) shadows `PolySignalNativeStrategy` (native_strategy.py, 1342 lines). Both evaluate decisions, apply policy, and produce orders. The doc states "long-term dual-runtime evolution is prohibited." Is there a planned deprecation/migration of the 11 Compat-based strategy implementations to PolySignalNativeStrategy, or is the Compat path still the active default?

3. **Exit position book resolution timing**. In `native_strategy.py:518-535`, `evaluate_exit_positions` iterates all open positions on every evaluation cycle. Each position reads from Nautilus cache via `cache_reader.read_positions()` -- this returns a full snapshot. For an active strategy with many open positions, this could be O(n) per data event. Is there a mechanism (e.g., position-change-only evaluation) to avoid repeated full scans?

4. **`DecisionPolicyActor` freshness policy not persisted**. `strategy_freshness_policies` (decision_policy.py:133) is set at init from `decision_policy.py:120` parameter but is NOT included in `save_state()` (line 141). On restart, freshness policies are silently lost and must be re-injected externally. Should this be persisted alongside `disabled_strategies`?

---

Now I have complete insight into all 6 files. Let me compile the structured audit report.

---

## Agent C Cache / Portfolio / Projections

### Evidence

- Primary tool: `codegraph_explore` across all 6 target files plus `node.py`, `native_strategy.py`, `scheduler_state.py`, `scheduler.py`, `scheduler_reporting.py`, `live_node.py`
- Full `Read` of all 6 scope files and supporting callers
- Line count verification via `wc -l` and function-size check via `awk`

### Nautilus Alignment

| Project Pattern | Nautilus Expected | Verdict | Evidence(file:line) |
|---|---|---|---|
| `project_order_event(projections.py:9)` projects Nautilus order events to dicts | Nautilus owns order lifecycle; bridge may transform for external consumers | Accept | One-way read-only transform; 0 writes |
| `project_fill_event(projections.py:38)` projects Nautilus fill events to dicts | Nautilus owns fill lifecycle; bridge may project for audit trail | Accept | Pure projection, no dual-write |
| `project_position(projections.py:62)` projects Nautilus position objects to dicts | Nautilus owns position/portfolio state; bridge may read for projections | Accept | Reads from Nautilus Position native object; returns `signed_qty`, `avg_px_open`, `realized_pnl` as dict |
| `NautilusCacheReader` reads orders/fills/positions from Nautilus Cache via duck-typing | Bridge boundary: read from Nautilus cache, write to projection store | Accept | 122-line adapter; 12 callers in `node.py`; used in `evaluate_exit_positions` decision path (but reads Nautilus truth) |
| `NautilusCacheMarketDataProvider` reads books/trades from Nautilus Cache | Nautilus owns data ingestion; bridge may read for strategy consumption | Accept | Read-only via `cache.order_book()` and `cache.trade_ticks()` |
| `MarketGroupViewAssembler` assembles views with freshness skew check | Nautilus does not have this abstraction -- it is PolySignal signal-layer logic | Accept | Pure signal assembly; 55 lines, no portfolio overlap |
| `ObservabilityActor` records events to SQLite+JSONL via `NautilusEventStoreAdapter` | Audit trail/adapter boundary; projection store acceptable | Accept | Single direction (Nautilus runtime -> SQLite); telemetry writer thread for best-effort tables |
| `PaperPortfolioService` stub with `name="paper_portfolio_removed"` | No local paper ledger or wallet may exist | Accept | Neutered stub: `process_signal()` raises `RuntimeError`; `health()` reports "removed" |

### Repeated Wheels

No repeated wheels (P0/P1 conflicts) found in the Cache/Portfolio/Projections domain.

| Severity | Project Module | Nautilus Equivalent | Evidence | Suggestion |
|---|---|---|---|---|
| Accept | `projections.py:9-217` | Nautilus native objects remain authoritative | Pure projection functions, 0 writes, 0 state | Keep as-is |
| Accept | `cache_reader.py:7-122` | `NautilusCache` native methods | Thin duck-typed adapter for optional Nautilus dependency boundary | Keep as-is |
| Accept | `paper_portfolio_service.py:7-56` | Nautilus Sandbox execution | Removed stub; no execution capability remains | Keep as neutralized compatibility shim |
| Accept | `persist_state()` at `scheduler_state.py:12-24` writes `market_cache` and `signal_dedupe` | Nautilus owns strategy state via `on_save/on_load` | Writes market metadata (not runtime state) and signal dedupe snapshots (not position/order state) | Accept; these do not overlap Nautilus position/order/portfolio state |

### Oversized

| Symbol | file:line | Lines | Issue |
|---|---|---|---|
| `observability.py` | (entire file) | 564 | Exceeds 400-line threshold; mixed responsibilities: `NautilusEventStoreAdapter` (66 lines), `NautilusNotifierAdapter` (8 lines), `ObservabilityActor` (~270 lines), `DecisionPolicyControl` (13 lines), plus protocols, enums, free functions, and repeat-suppression logic |
| — No single function >80 lines across any scope file — | | | All functions under threshold |

### Acceptable

- **`projections.py`** -- Pure-read projection functions. No writes, no state. Essential bridge layer converting Nautilus native objects to plain dicts for downstream consumers that cannot import Nautilus types. The `_portfolio_equity` helper (18 lines) handles duck-typed Nautilus portfolio equity access with proper callable sensitivity.

- **`cache_reader.py`** -- Thin adapter reading from Nautilus Cache via duck-typing. Used in `native_strategy.py:evaluate_exit_positions()` (lines 518-536) to read positions from Nautilus for exit decisions, which is the correct source of truth. Also used in `scheduler_reporting.py` for daily report equity inputs. No dual-write or redundant storage.

- **`cache_market_data.py`** -- Reads order books and trade ticks from Nautilus Cache via `MarketCatalog`-resolved instrument IDs. Pure read-only. No state ownership.

- **`group_views.py`** -- Temporal consistency validation for signal-domain market views. Does not overlap with portfolio aggregation or Nautilus Portfolio. 55 lines, single clear responsibility.

- **`paper_portfolio_service.py`** -- Previously identified as a P0 repeated wheel, now explicitly neutralized. Name is `"paper_portfolio_removed"`, all execution methods are no-ops or raise `RuntimeError`, `health()` confirms `"status": "removed"` and `"equity_source": "nautilus_cache_portfolio"`. Not wired into `scheduler.py` services list. Serves only as a compatibility shim delegating `check_settlements` and `generate_daily_report` to `scheduler_reporting.py`.

- **`NautilusEventStoreAdapter`** (observability.py:114-181) -- Writes Nautilus events to SQLite+JSONL as an audit trail. Tables are `nautilus_decision`, `nautilus_order`, `nautilus_fill`, `nautilus_position`, `health_snapshot` (best-effort), plus `signals`, `rejected_signals` (durable). Classification via `PersistenceClass` enum ensures appropriate durability semantics per table. Stream names aligned to projection store conventions.

- **SQLite vs Nautilus source-of-truth split** -- Confirmed: Nautilus Cache/Portfolio is the authoritative source of truth. SQLite is populated exclusively through read-one projections from Nautilus native objects. `persist_state()` writes market metadata and signal-dedupe snapshots (not order/position/portfolio state). No dual-write path exists where PolySignal could compute position or equity independently.

### Open Questions

- **observability.py (564 lines)** -- Should it be split? The file contains 4 distinct logical units (event store adapter, notifier adapter, observability actor, decision policy control) plus protocols and free functions. While no single function exceeds 80 lines, the file as a whole exceeds the 400-line threshold and mixes concerns. A split into `event_store.py`, `observability_actor.py`, and `telemetry.py` could improve maintainability. However, this is a naming/concern-separation issue, not a compliance or Nautilus boundary problem.

- **cache_reader projection freshness** -- When `cache_reader.read_positions()` is called inside `evaluate_exit_positions()` (native_strategy.py:518-536), it projects the Nautilus native position to a dict via `project_position()`. If the Nautilus position object's `signed_qty` or `avg_px_open` is stale relative to the latest sandbox execution, the exit decision may be based on stale data. Is there a guarantee that the Nautilus cache is flushed before `evaluate_exit_positions` runs? The pattern appears to rely on Nautilus's own callback ordering (on_fill -> on_position -> re-evaluate), which should be correct, but should be explicitly verified before declaring bridge compliance in this path.

---

## [Agent D] Market Data / Bridge / CustomData

### Evidence
- Primary tool: Fast Context for initial broad file discovery, followed by targeted file reads for code-level analysis.
- Key queries: `nautilus_bridge directory structure and key classes`, `market_data.py market_rotation.py sidecar_data.py custom_data_state.py instrument_mapping.py`, `data/polymarket_market_discovery.py data/price_to_beat_provider.py`
- Degradation notes: Fast Context hit resource exhaustion on 3rd query; fell back to direct reads via Bash + Read.

### Nautilus Alignment

| Project Pattern | Nautilus Expected | Verdict | Evidence(file:line) |
|---|---|---|---|
| `polymarket_instrument_id()` in `instrument_mapping.py` | Delegates to `nautilus_trader.adapters.polymarket.get_polymarket_instrument_id` | Accept | `src/polysignal_lab/nautilus_runtime/instrument_mapping.py:18-24` |
| `MarketCatalog` registry | Read-optimized condition-to-market-metadata map, not a reverse instrument registry | Accept | `src/polysignal_lab/nautilus_bridge/market_catalog.py:76-118` |
| `MarketViewAssembler` | Combines catalog, book data provider, custom data into MarketView projection | Accept | `src/polysignal_lab/nautilus_bridge/market_view_assembler.py:24-74` |
| `CustomDataPublisher` | Wraps `Actor.publish_data` with `DataType` for Nautilus CustomData bus | Accept | `src/polysignal_lab/nautilus_runtime/sidecar_data.py:38-94` |
| `MarketRotationActor` | Uses Nautilus actor lifecycle (`on_start`, `on_stop`, clock timers, `publish_data`) | Accept | `src/polysignal_lab/nautilus_runtime/market_rotation.py:46-338` |
| `StrategyCustomDataState` | Strategy-local derived state from CustomData messages | Accept | `src/polysignal_lab/nautilus_runtime/custom_data_state.py:35-71` |
| State encode/decode | Conforms to `dict[str, bytes]` / `on_save`/`on_load` contract with versioned keys `polysignal.<name>.state.v1` | Accept | `src/polysignal_lab/nautilus_bridge/state.py:19-44` |
| `PolySignal*Data` classes | Extend Nautilus `Data` base class, immutable once constructed (`_sealed` pattern) | Accept | `src/polysignal_lab/nautilus_runtime/market_data.py:91-378` |
| `MarketDiscovery` (Gamma REST) | Raw market metadata fetcher from Polymarket Gamma API; no adapter logic duplication | Accept | `src/polysignal_lab/data/polymarket_market_discovery.py:21-366` |
| `PriceToBeatProvider` | PTB resolution domain-specific to PolySignal; no Nautilus adapter overlap | Accept | `src/polysignal_lab/data/price_to_beat_provider.py:39-259` |

### Repeated Wheels

| Severity | Project Module | Nautilus Equivalent | Evidence | Suggestion |
|---|---|---|---|---|
| P2 | `nautilus_runtime/market_data.py:368-378` `PolySignalMarketUniverseData.to_dict()` | Serialization override converting `MappingProxyType` to `dict` and tuple to list | `market_data.py` is 416 lines and handles both definition and serialization for 4 data types. The `to_dict` override on `PolySignalMarketUniverseData` exists because `MappingProxyType` and tuples are not JSON-serializable by default. | Move each data class into its own file under `market_data/` namespace package, or extract serialization into a separate module. The 416-line file is just over the 400-line oversized threshold. |
| P2 | `nautilus_bridge/market_catalog.py:12-17` | None (re-export bridge) | `market_catalog.py` lazily imports `polymarket_instrument_id` from `nautilus_runtime.instrument_mapping`, creating a cross-package dependency path. The same ID resolver is referenced from `nautilus_bridge` and `nautilus_runtime`. | Push the resolver entirely into `nautilus_runtime` and pass it as a constructor arg to `MarketCatalog`, removing the lazy import from the bridge layer. Minor; the current pattern is a local function default that typically resolves at test time. |
| P2 | `nautilus_runtime/sidecar_data.py:114-119` `_timestamp_ns()` | `nautilus_core::datetime::millis_to_nanos` | `_timestamp_ns` is a 6-line manual datetime-to-nanosecond converter. While tiny, the Nautilus Polysignal adapter or `nautilus_core` provides a canonical conversion. | Replace with `nautilus_core_python.datetime.millis_to_nanos` or the Polysignal adapter's clock utility when Nautilus is available; use the manual fallback only when Nautilus is absent. Very minor. |

### Oversized

| Symbol | file:line | Lines | Issue |
|---|---|---|---|
| `nautilus_runtime/market_data.py` | whole file | 416 | Exceeds 400-line threshold by 16 lines. Contains 4 data class definitions + `register_polysignal_data_types()` + helper conversion functions. Could be split into `market_data/_types.py` + `market_data/_register.py`. |
| `nautilus_runtime/native_strategy.py` | whole file | 1341 | Outside strict scope, but heavily referenced by the bridge. Single file contains `PolySignalNativeStrategy` (~1000 loc), 11+ helper functions, subscription management, exit policy, order event reconstruction, and fill fallback pricing. Should be decomposed into a strategy module (`strategy/`) with separate files for execution, subscriptions, events, and helpers. |

### Acceptable

- `nautilus_bridge/market_catalog.py` -- Read-optimized metadata registry keyed by condition ID. Uses `@dataclass(frozen=True, slots=True)` for `MarketPairMeta` and `InstrumentTokenMeta`. Constructs from `Market` domain objects or from `PolySignalMarketMetaData` custom data. Accept.
- `nautilus_bridge/market_view_assembler.py` -- Assembles `MarketView` projections by combining catalog lookup, book data, and custom data. The `with_custom_data()` method correctly rebinds the `StrategyCustomDataState` provider. Accept.
- `nautilus_bridge/state.py` -- State encode/decode conforms to Nautilus `on_save`/`on_load` contract. Key format `polysignal.<name>.state.v1`. Unknown version fails closed. Missing optional state cold-starts with migration reason. Accept.
- `nautilus_bridge/strategy_base.py` -- Legacy `LegacyPolySignalNautilusStrategy` base class for strategies not yet migrated to `PolySignalNativeStrategy`. Uses `_load_strategy_base()` lazy import pattern. The `on_save`/`on_load` conform to the state contract. Accept as compatible legacy.
- `nautilus_runtime/instrument_mapping.py` -- 29-line thin bridge delegating to the Nautilus Polymarket adapter's `get_polymarket_instrument_id`. Validates inputs, raises `RuntimeError` if adapter is missing. Accept.
- `nautilus_runtime/custom_data_state.py` -- `StrategyCustomDataState` is a clean implementation of the `CustomDataSnapshotProvider` protocol. Accept.
- `nautilus_runtime/sidecar_data.py` -- `CustomDataPublisher` wraps `Actor.publish_data` with lazy `DataType` construction. The `_market_metadata` and `_timestamp_ns` helpers are stateless utilities. Accept.
- `data/polymarket_market_discovery.py` -- `MarketDiscovery` fetches raw market metadata from the Polymarket Gamma REST API. No overlap with Nautilus adapter logic (which resolves instruments from existing metadata, not discovers markets). The slug-based sliding-window market discovery is PolySignal-specific. Accept.
- `data/price_to_beat_provider.py` -- `PriceToBeatProvider` resolves price-to-beat values from 4 sources (metadata, raw payload, optional web API, text pattern). PTB is a PolySignal-specific concept with no Nautilus adapter equivalent. Accept.
- `nautilus_runtime/market_rotation.py` -- `MarketRotationActor` is correctly guarded (`spot_source != "disabled"` -> fail-fast). Timer-based refresh uses `refresh_once_sync()` (synchronous, no asyncio leakage). Publishing uses `publish_data` through the Nautilus actor bus. The `_on_spot` method correctly iterates active markets and publishes PTB updates. Accept.

### Open Questions

1. **OrderBookRegistry in `data/state.py` (outside scope)**: The `OrderBookRegistry.is_fill_eligible()` method at line 94 references `paper_fill_rejected_*` metrics and tracks book snapshot/delta sequencing with epoch validation. This pattern overlaps with the Polymarket adapter's internal order book management. If this file is still active in the bridge runtime, it may constitute a P1 repeated wheel (self-built book lifecycle management overlapping the Polymarket adapter). This file was not inspected as part of this scope pass.

2. **`MarketRotationActor._on_spot` external invocation**: `_on_spot` (line 236) is triggered when external code calls it with `SpotPrice` data. It publishes through the Nautilus bus and triggers anchor price capture. The callsite that feeds spot data into this method was not traced in this scope -- verify it originates from a Nautilus-managed data client path rather than an actor-external asyncio source, to confirm the sidecar spot publishing guard (`spot_source != "disabled"`) is not bypassed.

3. **`nautilus_runtime/native_strategy.py` at 1341 lines**: This file is well over the 400-line threshold and carries significant responsibility (strategy lifecycle, data subscription, order submission, fill handling, exit policy). While the file's specific functions were not individually flagged as oversize (>80 lines), the sheer size is a maintainability concern. Recommend a decomposition plan for `strategy/` sub-package.

---

## Agent E -- Strategy Wrapper & Alpha Boundary

### Evidence
- Primary tool: `codegraph_explore` with queries targeting `native_strategy.py`, `nautilus_runtime/strategies/base.py`, `nautilus_bridge/strategy_base.py`, `alpha/types.py`, `alpha/cross_market_core.py`, `alpha/mid_price_sizing_core.py`, `strategies/base.py`, `strategies/factory.py`, `strategies/binary_momentum.py`, `strategies/dump_hedge.py`, `strategies/ptb_diff.py`, `nautilus_runtime/exit_policy.py`, `nautilus_runtime/native_exit.py`
- Confirmed full source of every file listed above via CodeGraph line-numbered output (treated as Read)
- No degradation -- CodeGraph indexed all relevant files

### Nautilus Alignment

| Project Pattern | Nautilus Expected | Verdict | Evidence(file:line) |
|---|---|---|---|
| `PolySignalNativeStrategy.on_start/on_stop/on_data/on_save/on_load` | Strategy lifecycle callbacks | Accept (thin bridge) | `native_strategy.py:256-293` -- delegates to Nautilus pattern, does not replace it |
| `PolySignalNativeStrategy.on_order_submitted/accepted/rejected/denied/canceled/expired/filled` | Order event callbacks | Accept (thin bridge) | `native_strategy.py:428-491` -- bridges Nautilus order events to alpha core; no local order lifecycle |
| `PolySignalNativeStrategy.on_quote_tick/on_trade_tick/on_order_book/on_order_book_deltas` | Market data callbacks | Accept (thin bridge) | `native_strategy.py:372-421` -- resolves condition ID from instrument, delegates to evaluation |
| `on_save`/`on_load` delegates to `self.core.save_state()` + `encode_state()` | State persistence via Strategy on_save/on_load | Accept (thin bridge) | `native_strategy.py:283-293`; `nautilus_runtime/strategies/base.py:419-429` -- both delegate to core, no custom serialization logic outside `encode_state`/`decode_state` |
| `CompatPolySignalNautilusStrategy` on_data returns `list[NautilusOrderSpec]` | Strategy on_data returns void | Accept (test helper) | `nautilus_runtime/strategies/base.py:73-85` -- the return value is a convention for unit test assertions |
| AlphaOrderEvent, AlphaFillEvent, AlphaDecision frozen dataclasses | Message immutability | Accept | `alpha/types.py:87-153` -- all frozen=True with slots, proper frozen dataclass pattern |
| `_exit_policy_config` + `_submit_exit_position` reads Nautilus cache positions and submits exit orders | Exit engine is forbidden outside Nautilus | P0 | `native_strategy.py:537-618` -- PolySignal-owned exit engine with TP/SL/max-hold-time evaluation |
| `evaluate_exit_decision` TP/SL/max-hold detection | Nautilus owns exit/stop-loss lifecycle | P0 | `nautilus_runtime/exit_policy.py:49-73` -- custom TP/SL evaluation outside Nautilus control |
| `submit_exit_decision` via `order_factory.limit()` with reduce_only | Submit exit through Nautilus order management | P0 | `nautilus_runtime/native_exit.py:18-39` -- submits exit orders using raw order factory, not Nautilus bracket/exit mechanism |
| `bracket_attachments_for` generates TaggedBracketOrder | Bracket order attachment is Nautilus-owned | P0 | `nautilus_runtime/exit_policy.py:76-117` -- second exit model generating bracket attachments outside Nautilus |
| `MarketSubscriptionState` wire-level condition/instrument tracking | Subscription management is Nautilus adapter-owned | P1 | `native_strategy.py:91-99` -- tracks wire condition IDs, pending metadata, pending subscribes alongside what Nautilus already tracks |

### Repeated Wheels

| Severity | Project Module | Nautilus Equivalent | Evidence | Suggestion |
|---|---|---|---|---|
| P0 | `nautilus_runtime/exit_policy.py` + `native_exit.py` -- PolySignal-owned exit engine | Nautilus order lifecycle owns exit/TP/SL | `exit_policy.py:49-73` TP/SL evaluation; `native_exit.py:18-39` exit-order submission; `native_strategy.py:537-618` reading positions and submitting exits | Remove the custom exit engine. Use Nautilus bracket orders or Nautilus-managed TP/SL if available in sandbox. If sandbox does not support native bracket ordering, gate this behind a runtime flag with a compliance note |
| P1 | `PolySignalNativeStrategy` (native_strategy.py:172) + `CompatPolySignalNautilusStrategy` (nautilus_runtime/strategies/base.py:38) + `LegacyPolySignalNautilusStrategy` (nautilus_bridge/strategy_base.py:35) -- three parallel adapters | Nautilus `Strategy` base class | All three implement on_start, on_data, evaluate_condition, on_order_submitted/accepted/rejected/canceled/expired/filled, on_save/on_load | Drop `LegacyPolySignalNautilusStrategy` entirely (it is dead code used only by `is_nautilus_available()`). Merge `CompatPolySignalNautilusStrategy` into `PolySignalNativeStrategy` or make it a protocol mixin so there is exactly one adapter surface |
| P1 | Each strategy has three representations: `alpha/*_core.py`, `strategies/*.py` (BaseStrategy), and `nautilus_runtime/strategies/*.py` (CompatPolySignalNautilusStrategy) | Single Nautilus Strategy subclass per strategy | `binary_momentum_core.py` + `BinaryMomentumStrategy` (strategies/binary_momentum.py:40) + `BinaryMomentumNautilusStrategy` (nautilus_runtime/strategies/binary_momentum.py:13); same pattern for dump_hedge, ptb_diff, fibonacci, etc. | The legacy `strategies/*.py` adapters are legacy runtime only and should be collapsed into the nautilus_runtime/ adapters once the legacy scheduler is removed. Until then, mark with `LEGACY_RUNTIME_ONLY` and verify the default runtime does not import them |
| P1 | `LegacyPolySignalNautilusStrategy` in nautilus_bridge/strategy_base.py | Nautilus Strategy base class | `strategy_base.py:35-112` -- full adapter with its own state tracking (accepted_state, fill_state, cancel_state dicts) and its own evaluate_condition, on_order_submitted/accepted/rejected/canceled/expired/filled, on_save/on_load | Remove this file. It is a third parallel adapter that duplicates What CompatPolySignalNautilusStrategy and PolySignalNativeStrategy already provide. Only `is_nautilus_available()` is still useful -- inline that check into the test helper if needed |
| P1 | `MarketSubscriptionState` in native_strategy.py:91-99 | Nautilus adapter wire subscription management | `native_strategy.py:967-1038` -- subscribe/unsubscribe condition set tracking duplicates subscription state Nautilus already manages per-instrument | Remove wire-level subscription tracking. Let Nautilus adapter manage subscribe/unsubscribe fidelity. Keep only the pending-metadata-request cache if needed for deferred instrument load |
| P1 | `_condition_from_market_data` instrument-ID-to-condition-ID resolution | Polymarket adapter's own instrument registry | `native_strategy.py:378-391` -- mapping instrument ID to condition ID via MarketCatalog duplicates work done in the Polymarket adapter's data resolution layer | Consolidate with the MarketCatalog pattern already used by the data adapter; evaluate whether native_strategy needs to own this mapping at all or can rely on the catalog as sole source of truth |
| P2 | `_approved_signal_metrics` / `_forget_approved_metrics` | Nautilus order tags propagate metadata | `native_strategy.py:871-942` -- 72 lines of metric-key aliasing, lookup ID extraction, and dedupe-key tracking | Replace with a simpler pattern: tag orders with signal metadata at submission time (already done via `_submit_approved`). Remove post-submission metric lookup entirely |
| P2 | `_lookup_id_text` / `_identifier_text` double-dispatch pattern | Standard Nautilus identifier handling | `native_strategy.py:1076-1080` and `1187-1192` -- two wrapper layers for extracting text from identifiers | Consolidate into one function; use Nautilus `InstrumentId.value` directly where available |

### Oversized

| Symbol | file:line | Lines | Issue |
|---|---|---|---|
| `PolySignalNativeStrategy` class (entire file) | `native_strategy.py:1-1342` | 1342 | Far exceeds 400-line threshold. Single-file class spans lifecycle, order events, market data, position management, exit policy, instrument resolution, metadata handling, subscription management, and 20+ private helper functions |
| `CompatPolySignalNautilusStrategy` class (entire file) | `nautilus_runtime/strategies/base.py:1-560` | 560 | Exceeds 400-line threshold. Combines order event routing, policy decision recording, metrics aliasing, consensus handling, state persistence, and subscription handling |
| `evaluate_exit_decision + bracket_attachments_for` | `nautilus_runtime/exit_policy.py:49-117` | 68 | Not over 80-line threshold individually, but the two functions share identical preambles (position guard, entry_price/quantity/instrument_id extraction -- 15 lines duplicated exactly) |

### Acceptable

- **Alpha core files** (`alpha/*_core.py`, `alpha/types.py`): Pure strategy logic. `AlphaDecision`, `MarketView`, `AlphaOrderEvent`, `AlphaFillEvent` are all frozen dataclasses with slots, correctly implementing message immutability. The `StatefulAlphaCore` protocol properly separates `save_state()`/`load_state()` from evaluation.
- **State codec** (`on_save`/`on_load`): Both `PolySignalNativeStrategy` and `CompatPolySignalNautilusStrategy` delegate to `self.core.save_state()` then `encode_state()`/`decode_state()`. No custom serialization logic. The state key format `polysignal.<strategy_name>.state.v1` follows the boundary spec.
- **DecisionPolicyActor**: Thin bridge. The `_GateSnapshotAdapter` wrapping `MarketView` into the shape the gate expects is a clean adapter pattern (lines 79-108 of `decision_policy.py`).
- **BaseStrategy** (`strategies/base.py:14`): At 117 lines, this legacy ABC is appropriately sized and correctly separated from Nautilus concerns. Its `_candidate()` helper is a pure utility. The legacy runtime adapter pattern (convert `MarketSnapshot` -> `MarketView` -> `AlphaDecision` -> `SignalCandidate`) is clean.
- **StrategyScheduleEntry / DAG ordering** (`strategies/execution.py`): 101 lines, pure execution orchestration -- correctly PolySignal-owned.
- **StrategyReadiness / check_strategy_market** (`strategies/readiness.py`): 86 lines, pure gating logic -- correctly PolySignal-owned.
- **StrategyConfig** (`strategies/config.py`): Pydantic config models with `extra="forbid"` -- clean, no credential leakage.
- **AlphaDecision, OrderIntentSpec, NautilusOrderSpec** in `alpha/types.py`: All frozen dataclasses. Message immutability correctly respected.

### Open Questions

1. **Exit engine removal plan**: The `evaluate_exit_decision` + `submit_exit_decision` in `native_strategy.py:537-618` + `exit_policy.py` + `native_exit.py` collectively form a PolySignal-owned exit engine, which is explicitly forbidden. Does the Nautilus Sandbox execution client support bracket orders (`take_profit`/`stop_loss` attachment) for Polymarket instruments? If yes, the exit model should be replaced with native Nautilus bracket order attachments. If not (the sandbox config shows `support_contingent_orders=False` at `live_node.py:131`), then either (a) contingent orders must be enabled, or (b) the exit engine needs a formal compliance exception.

2. **LiveNode path uses `LiveNode.builder()` correctly per spec** (line 44: `builder_factory = live_node` then `getattr(builder_factory, "builder")`), and `SandboxLiveExecClientFactory` with `support_gtd_orders=True`. This is compliant. However, does the exit engine (IOC reduce-only limit orders) interact correctly with the sandbox netting OMS (`oms_type="NETTING"` at line 126)? If native_exit submits an IOC reduce-only limit via `order_factory.limit`, does the sandbox correctly map this to a Polymarket-style exit?

3. **Three-adapter consolidation**: The docstring for `CompatPolySignalNautilusStrategy` says "Compatibility wrapper for legacy unit tests; default runtime uses the static Nautilus strategy class." If it is truly test-only, can the ~560-line file be moved to a test helper module? And can `LegacyPolySignalNautilusStrategy` in `nautilus_bridge/` be fully removed?

4. **Alpha core `evaluate_view_from_snapshot_for_test` methods**: Found in `cross_market_core.py:243` and `mid_price_sizing_core.py:218`. These inline-import `market_view_from_snapshot` from `ptb_diff_core`, creating a cross-import dependency between alpha cores. Should these test helpers be extracted to a shared test utility module?

---

**WARNING: This report is a compliance audit against NautilusTrader design boundaries. It reflects code structure at a point in time. It is NOT a signal that any violation has occurred -- the findings document architectural risk for the reviewer.**

---

## [Agent F] Legacy Scheduler and Parallel Runtime

### Evidence
- **Primary tool**: `mcp__fast-context__fast_context_search` (project_path=/home/debian/polysignal-lab), supplemented by direct file reads for `app/scheduler*.py`, `strategies/`, `paper/`, `signal_layer/`, `nautilus_runtime/node.py`, `nautilus_runtime/decision_policy.py`, `nautilus_runtime/signal_sidecar.py`
- **Key queries**: `app/scheduler second trading runtime spec 15 legacy`, `strategies non-alpha Nautilus sandbox`, `paper/ wallet duplicate Nautilus`, `signal_layer/ order routing`, `nautilus_runtime/node.py imports legacy`
- **Degradation**: 4 of 5 parallel queries hit `resource_exhausted` errors on first pass; retried serially with success. No data loss.

### Nautilus Alignment

| Project Pattern | Nautilus Expected | Verdict | Evidence(file:line) |
|---|---|---|---|
| `PolySignalScheduler` is constructed in Nautilus mode (`node.py:554`) and holds references to market data, order books, signal pipeline, arbiter | Nautilus mode should own its own data/strategy lifecycle; scheduler is a foreign runtime | Accept (thin bridge) | `node.py:551-568` — scheduler is explicitly flagged with `_nautilus_runtime_owned_by_live_node = True` and only used as a service container for persistence, health, Telegram, and market-universe refresh |
| `scheduler.run()` event loop | Nautilus `LiveNode.run()` is the only runtime | Accept (no path to call) | `app/scheduler.py:314-315` — `run()` delegates to `scheduler_runtime.run()` which owns its own while-loop. This is NEVER called from Nautilus mode; Nautilus path uses `_initialize_nautilus_scheduler_components()` then `LiveNode.run()` |
| `scheduler_processing.evaluate_once()` pipeline | Nautilus strategy `on_data()` callbacks evaluate signals | Accept (dead path in Nautilus) | `app/scheduler_processing.py:500-505` — complete evaluation pipeline (snapshot building, candidate evaluation, strategy ordering, gate, consensus). Not called in Nautilus mode, but wired and could be invoked by mistake |
| `SignalGate` / `ConsensusEngine` / `SignalArbiter` reused in `DecisionPolicyActor` | Nautilus actor-based decision policy | Accept | `nautilus_runtime/decision_policy.py:20-22`, `node.py:676-689` — signal-layer objects are properly bridged inside a Nautilus Actor, matching spec: PolySignal retains gating/sizing/metrics logic |
| `build_strategy_schedule()` creates legacy `BaseStrategy` objects in Nautilus mode | Nautilus mode should use native strategies only | Accept (overhead, not conflict) | `node.py:702` — legacy strategies are created but never evaluated in Nautilus mode. Nautilus uses `_native_core_for()` with alpha cores. Dead Python objects, no functional overlap |
| `_generate_iteration_report()` imported from legacy `scheduler_runtime` | Reporting from Nautilus cache projections | Accept | `nautilus_runtime/signal_sidecar.py:239` — imports `_generate_iteration_report` for daily report generation. This is a read-only projection, no execution overlap |

### Repeated Wheels

| Severity | Project Module | Nautilus Equivalent | Evidence | Suggestion |
|---|---|---|---|---|
| P1 | `app/scheduler_processing.py` (657 lines) — entire `evaluate_once()` / `evaluate_candidates_ordered()` / `commit_candidates_serial()` pipeline | `NautilusPolySignalNativeStrategy.on_data()` + `DecisionPolicyActor` | `app/scheduler_processing.py:500-505` — this is a complete independent signal evaluation runtime (snapshot builder, strategy schedule with DAG ordering, gate, consensus, arbiter). Never called in Nautilus mode, but it is a fully parallel evaluation engine | Add a runtime-mode guard at the top of `evaluate_once()` that `raise RuntimeError("use Nautilus strategy callbacks")` when invoked under the Nautilus runtime. Alternatively, delete the `evaluate_once` / `process_accepted_signals` public API once the legacy scheduler path is fully retired |
| P1 | `app/services/signal_pipeline.py::SignalPipeline.evaluate_snapshot()` (66-line mini-runtime at lines 66-96) | `DecisionPolicyActor` (strategy evaluation + gate + consensus) | `app/services/signal_pipeline.py:66-96` — contains its own loop over strategies, gates candidates, runs consensus, persists rejections. This is a third independent signal evaluation engine alongside `scheduler_processing.py` and `DecisionPolicyActor` | Either remove it (it is NOT called in Nautilus mode) or add a runtime-mode guard. The `DecisionPolicyActor` is the canonical path |
| P1 | `paper/settlement.py::PaperSettlementEngine.settle()` | Nautilus sandbox position lifecycle (fills, PnL, settlement) | `paper/settlement.py:11-67` — computes PnL, ROI, position outcome from resolution value. The Nautilus runtime reads position state from cache projections (`scheduler_reporting.py:89-90` → `NautilusCacheReader.read_positions()`), NOT from `PaperSettlementEngine` | This is dead code in Nautilus mode. Remove or guard behind `@runtime_mode("legacy")` |
| P1 | `app/scheduler.py::__init__()` (126 lines, 79-204) wires a complete runtime stack | Nautilus `LiveNode.builder()` wires its own stack | `app/scheduler.py:79-204` — constructs market data clients, WebSocket feeds, order books, signal pipeline, persistence, publishing, settlement resolver, and service supervisor. Every one of these components exists in parallel in the Nautilus runtime | Acceptable as the legacy initialization path. The Nautilus mode reuses the scheduler object only for its service role (persistence, health, market universe reflection) and explicitly skips its runtime by calling `_initialize_nautilus_scheduler_components()` instead of the full init logic |
| P2 | `paper/report.py::PaperReportService` (334 lines) | Nautilus equivalent would be in `NautilusCacheReader` projections | `paper/report.py:53-136` — daily report builder that reads from Nautilus cache + SQLite projections | Acceptable bridge; reads only, no state mutation. The `check_settlements()` flow in `scheduler_reporting.py` drives resolution from cache projections, correctly bypassing `PaperSettlementEngine` |
| P2 | `app/scheduler_reporting.py` (638 lines, settlement + daily report orchestration) | Nautilus would read from Cache/Portfolio projections | `scheduler_reporting.py:38-116` — reads Nautilus cache reader positions for settlement. `scheduler_reporting.py:388-434` — reads account + portfolio projections from Nautilus cache | Acceptable bridge. This is a read-only projection layer. It correctly falls back to Nautilus `NautilusCacheReader` for order/fill data and does NOT touch `PaperSettlementEngine` |

### Oversized

| Symbol | file:line | Lines | Issue |
|---|---|---|---|
| `PolySignalScheduler.__init__` | `app/scheduler.py:79-204` | 126 | Wires 20+ services, 7 WebSocket/feed objects, and 2-level service supervisor. Tight coupling to concrete implementations. Exceeds 80-line threshold |
| `_build_daily_report_from_inputs` | `app/scheduler_reporting.py:529-620` | 92 | Orchestrates fill enrichment, execution assumptions, paper report building, Telegram publishing, SQLite/JSONL storage. Multiple responsibilities |
| `_collect_daily_report_inputs` | `app/scheduler_reporting.py:438-526` | 89 | Queries signals, orders, fills, trade results from both SQLite and Nautilus cache projections with fallback logic. Complex branching |
| `node.py::build_nautilus_runtime` | `nautilus_runtime/node.py` | 1019 total | File is at 1019 lines. Multiple responsibilities: runtime construction (L551-620), command-line orchestration (L886-1005), crash diagnostics (L740-790), signal handling (L730-738). Exceeds 400-line multi-responsibility threshold |

### Acceptable
- `signal_layer/gate.py`, `signal_layer/arbiter.py`, `signal_layer/consensus.py` — Properly bridged into `DecisionPolicyActor` in Nautilus mode. No overlap with ExecutionEngine.
- `paper/settlement_resolver.py` (`SettlementResolver`) — Orchestration service for chain/gamma/ws resolution sources. No trading or order lifecycle overlap.
- `nautilus_runtime/signal_sidecar.py` — Publish/TG/report sidecar. Uses `_generate_iteration_report` from legacy but this is a read-only report builder operating on Nautilus cache projections.
- `app/scheduler.py` as a DI container in Nautilus mode — The scheduler provides `persistence`, `health`, `ctx.markets`, and `market_universe` services. This is reasonable reuse of established infrastructure.

### Open Questions
1. **Dead code risk in `scheduler_processing.py`**: The full `evaluate_once()` pipeline (lines 500-505) is wired and could be invoked by any code path holding a scheduler reference. Should this be guarded by a runtime-mode flag that fails fast in Nautilus mode?
2. **`PaperSettlementEngine` removal path**: The engine in `paper/settlement.py` is entirely unused by the Nautilus runtime. Is it still needed for the legacy scheduler path (`app/main.py`), or can it be removed/deprecated?
3. **`SchedulePipeline.evaluate_snapshot()` vs `scheduler_processing.evaluate_once()`**: These two legacy evaluation paths (`signal_pipeline.py:66-96` and `scheduler_processing.py:500-505`) appear to duplicate each other. Which one is canonical for the legacy path, and can the other be removed?
4. **`node.py` file size at 1019 lines**: The file has grown organically as runtime construction, CLI orchestration, crash diagnostics, signal handling, and probes were accumulated. Should the construction helpers (L550-720) be extracted into a separate `node_builder.py` or `runtime_builder.py`?
