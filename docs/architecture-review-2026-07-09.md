# Architecture Review Report — 2026-07-09

> **Ultrathink review**: NautilusTrader conformance, reimplemented features, technical debt.

---

## Health Score Overview

| Metric | Score | Grade |
|--------|-------|-------|
| **Overall Health** | **86/100** | **B** |
| Coupling (CBO) | 75/100 | 👍 (7/137 high-coupling) |
| Cohesion (LCOM) | 90/100 | ✅ |
| Dependencies | 70/100 | ⚠️ (no cycles, depth=13) |
| Architecture | 81/100 | 👍 |

**Hotspots**: High coupling improved after remediation (7 classes CBO ≥ 8, down from 26). `PolySignalNativeStrategy` reduced to 513 lines / CBO 11 but remains the largest runtime class.

> **Remediation update (2026-07-10)**: See `docs/architecture-remediation-results-2026-07-09.md` for measured before/after metrics and commit list.

---

## 1. NautilusTrader Conformance

### ✅ What Conforms Well

| Area | Evidence |
|------|----------|
| **Strategy base class** | `PolySignalNativeStrategy` extends `nautilus_trader.trading.strategy.Strategy` directly (correct) |
| **Actor pattern** | `MarketRotationActor(CBO=17)`, `DecisionPolicyActor(CBO=13)` extend `nautilus_trader.trading.Actor` |
| **Custom data types** | Uses `@customdataclass` from `nautilus_trader.model.custom` — the recommended approach |
| **Data base class** | `PolySignalSpotData`, `PolySignalMarketMetaData` etc. inherit from `nautilus_trader.core.data.Data` |
| **Message immutability** | `_FrozenData` mixin enforces the Nautilus message immutability design principle |
| **LiveNode builder** | Uses Nautilus's `LiveNode.builder()` fluent API for wiring (correct pattern) |
| **Polymarket adapter** | Uses `PolymarketLiveDataClientFactory` and `PolymarketInstrumentProviderConfig` from the official adapter |
| **Config separation** | Separates `StrartegyConfig`, `ActorConfig`, `LiveDataEngineConfig`, etc. |

### ❌ What Deviates

| Issue | Location | Severity |
|-------|----------|----------|
| **Optional lazy imports for Nautilus extras** | `optional_imports.py`, `live_node.py` | 🟢 **Accepted boundary** |
| **Nautilus core types typed as `object` in stubs** | `node_builder.py` runtime placeholders | 🟡 Medium |
| **try/except wrapping Nautilus imports** | `strategy/helpers.py:21-27` wraps imports in `try: ... except ModuleNotFoundError` | 🟡 Medium |
| **No proper adapter layer** | `data/polymarket_clob_rest.py` and `data/polymarket_clob_ws.py` bypass the Nautilus adapter pattern — they should be structured as `LiveDataClient` + `InstrumentProvider` implementations, not standalone HTTP/WS clients | 🟡 Medium |
| **Custom type stubs replace inline imports** | `node_builder.py` uses stub placeholders + `_ensure_nautilus_imports()` for what should be plain `from nautilus_trader.live import LiveNode` | 🟡 Medium |

### 🔴 Dynamic Import Pattern (Detail — Accepted Optional Boundary)

`live_node.py` loads Nautilus symbols through `optional_imports.load_live_runtime_symbols()` so the default package import graph does not require `nautilus_trader`. This is an intentional optional-dependency gate, not a missing static-import refactor for the default runtime.

```python
# live_node.py — optional extra path only
from polysignal_lab.nautilus_runtime.optional_imports import load_live_runtime_symbols
```

IDE/type-checker limitations at this boundary remain acceptable tradeoffs until Nautilus becomes a hard dependency.

---

## 2. Nautilus Features Reimplemented (Unnecessary Code)

### 2.1 Custom OrderBook (🔴 Should Use Nautilus)

`domain/orderbook.py` (113 lines):
- `OrderBook(BaseModel)`, `BookLevel(BaseModel)` — Pydantic models
- Nautilus already provides: `OrderBook`, `L2OrderBook`, `L3OrderBook` with delta updates, sequence numbers, serialization, and reconciliation
- The custom `OrderBookRegistry` in `data/state.py` is a **compatibility / read-only projection path** for legacy snapshots and dashboards — not the Nautilus runtime execution truth (Cache owns live books in the Nautilus path).

**Impact**: Missing Nautilus features like correct book reconstruction, out-of-order delta handling, and serialization for replay.

### 2.2 Custom Market Registry (🟡 Redundant With Nautilus Cache)

`data/state.py:46-62` — `MarketRegistry`:
- `markets: dict[str, Market]` with thread-safe `upsert_many`, `active`, `get`
- Nautilus's `Cache` already manages instruments, orders, positions, and accounts
- The Polymarket adapter's `InstrumentProvider` already caches instruments

### 2.3 Custom SQLite Persistence (🟡 Partially Redundant)

`storage/sqlite_store.py` (639 lines) — `SQLiteStore`:
- Custom schema management, JSON column queries, position/order event storage
- Nautilus provides `Cache` + `Database` abstractions for persistence
- The custom SQLite is the primary observability backend and would be expensive to replace
- **Worth keeping** for dev tooling, but production should use Nautilus's database

### 2.4 Order Mapping / Native Order Wrapping (🟡 Thin Wrapper)

`nautilus_runtime/native_order.py` — `submit_approved_decision`:
- Wraps Nautilus's own `order_factory.limit(...)` and `submit_order(...)` calls
- This is a **thin adapter** between the project's `ApprovedDecision` and Nautilus's order types — acceptable but verify it's not doing redundant work

### 2.5 Custom Observability / Health (🟢 Considered Application Code)

`observability/health.py`, `nautilus_runtime/observability.py`:
- Nautilus doesn't expose a health/observability framework at this granularity
- The `ObservabilityService` wrapping SQLite + JSONL + Telegram is genuinely application-specific
- **Keep** — appropriate for a bot project

---

## 3. Large / Fat Classes (Refactoring Targets)

### 🏆 Top 5 Classes by Coupling

| Class | CBO | Lines | File | Problem |
|-------|-----|-------|------|---------|
| **PolySignalNativeStrategy** | **11** | **513** | `nautilus_runtime/native_strategy.py:108` | 🟡 Still large (LCOM4=31) but reduced — shared policy injection and pipeline extraction helped |
| **TelegramBotService** | **11** | **713** | `publish/telegram_bot.py:45` | 🔴 Mixes rendering, callback routing, bot lifecycle, rate limiting, inline keyboard building |
| **MarketRotationActor** | **10** | **~405** | `nautilus_runtime/market_rotation.py` | 🟡 Discovery now offloaded to `MarketDiscoveryWorker` |
| **DecisionPolicyActor** | **9** | — | `nautilus_runtime/decision_policy.py` | 🟡 Shared policy owner |
| **SQLiteStore** | **9** | **639** | `storage/sqlite_store.py` | 🟡 Observability projection store |

### 🟡 PolySignalNativeStrategy (LCOM4=31, 513 lines)

Still the largest runtime class. Responsibilities include:
- Strategy lifecycle (`on_start`, `on_stop`)
- Market data subscription management
- Market condition evaluation
- Decision pipeline integration
- Order submission (`_submit_approved`)
- Order event handling (`on_order_filled`, `on_order_expired`, etc.)
- Position event handling
- Fill processing and decision re-entry
- Instrument resolution (`_resolved_instrument`)
- Observability recording
- Signal sidecar notification
- State persistence (`save/load`)

**Recommendation**: Split into 3-5 focused classes (e.g., `StrategyLifecycle`, `MarketDataHandler`, `OrderManager`, `DecisionIntegrator`, `ObservabilityAdapter`).

---

## 4. High Complexity Functions

### Cyclomatic Complexity ≥ 10

| CC | Cognitive | Function | File:Line |
|----|-----------|----------|-----------|
| 17 | 22 | `parse_paper_trade_result_row` | `domain/paper_result.py:120` |
| 15 | 13 | `PolymarketMarketWebSocket.handle_message` | `data/polymarket_clob_ws.py:80` |
| 14 | 37 | `_calibration_from_reports` | `dashboard/app.py:102` |
| 14 | 19 | `_try_settle_projection` | `app/_settlement_check.py:90` |
| 14 | 30 | `_paper_trade_result_from_projection` | `app/_settlement_check.py:182` |
| 13 | 15 | `_status_from_gamma` | `domain/market.py:284` |
| 13 | 29 | `FibonacciAlphaCore.load_state` | `alpha/fibonacci_core.py:315` |
| 12 | 26 | `json_safe_state` | `alpha/state.py:23` |
| 11 | 26 | `SQLiteStore.query_json` | `storage/sqlite_store.py:494` |
| 11 | 30 | `_valid_position_event` | `storage/sqlite_store.py:79` |
| 11 | 26 | `CrossMarketAlphaCore._evaluate_relation` | `alpha/cross_market_core.py:159` |
| 11 | 26 | `ZigZagDetector.push` | `alpha/fibonacci_core.py:54` |
| 11 | 25 | `_collect_daily_report_inputs` | `app/scheduler_reporting_sources.py:178` |
| 10 | 24 | `BinaryMomentumAlphaCore._evaluate_direction` | `alpha/binary_momentum_core.py:155` |

### Highest Cognitive Complexity (Hard to Maintain)

| Cog | Function | File:Line |
|-----|----------|-----------|
| **37** | `_calibration_from_reports` | `dashboard/app.py:102` |
| **35** | `MarketUniverseService.fetch_resolved` | `app/services/market_universe_service.py:138` |
| **30** | `_paper_trade_result_from_projection` | `app/_settlement_check.py:182` |
| **30** | `_valid_position_event` | `storage/sqlite_store.py:79` |
| **29** | `FibonacciAlphaCore.load_state` | `alpha/fibonacci_core.py:315` |
| **26** | `SQLiteStore.query_json` | `storage/sqlite_store.py:494` |
| **26** | `scan` | `observability/safety.py:94` |
| **26** | `ZigZagDetector.push` | `alpha/fibonacci_core.py:54` |
| **26** | `CrossMarketAlphaCore._evaluate_relation` | `alpha/cross_market_core.py:159` |
| **25** | `_collect_daily_report_inputs` | `app/scheduler_reporting_sources.py:178` |
| **25** | `PaperReportService._paper_execution_aggregates` | `paper/report.py:126` |

---

## 5. Module Organization

### 5.1 nautilus_bridge — After Recent Cleanup

The bridge originally had many more files. After refactoring (`7adf7f5`), it's now 5 files (449 total lines):
- `enum_parser.py` — Enum mapping between Nautilus and project (good)
- `market_catalog.py` — Market→MarketPairMeta conversion (valid bridge function)
- `market_view_assembler.py` — Assembles views from market data (valid bridge function)
- `state.py` — Strategy state serialization (thin wrapper)

**Verdict**: The bridge is now lean and focused. No further reduction needed.

### 5.2 signal_layer — Well-Modularized

6 files: `gate.py`, `arbiter.py`, `consensus.py`, `deduper.py`, `rate_limit.py`, `formatter.py`

**Verdict**: Good separation of concerns. The one concern is `SignalGate` (CBO=15, LCOM=7) — its 10 check methods could be extracted into separate policy objects.

### 5.3 nautilus_runtime/strategy/ — Small Files, Clear Purpose

6 files: `custom_data_handlers.py`, `data_boundary.py`, `decision_pipeline.py`, `event_projection.py`, `helpers.py`, `subscriptions.py`

The decision pipeline (`decision_pipeline.py:133`) has LCOM issues (`NativeDecisionSink` LCOM=7, `NativeDecisionSinkImpl` LCOM=7) suggesting it mixes protocols, state management, and implementation.

---

## 6. Dead Code Status

### ✅ Remediated in 2026-07-10 plan

Also deleted during `refactor/nautilus-architecture-remediation`:
- `nautilus_runtime/projection_recorder.py`
- `nautilus_runtime/strategies/cross_market_bot.py`
- Unused helpers in `decision_pipeline.py`, `native_strategy.py`, `persistence_service.persist_state()`

The following were deleted in recent commits (`7adf7f5`, `5bf737dc`, `643c9e4`):
- **17 legacy strategies** from `src/polysignal_lab/strategies/` (entire directory)
- **6 app services**: `book_feed_service`, `health_service`, `paper_portfolio_service`, `runtime_service`, `signal_pipeline`, `snapshot_service`, `spot_feed_service`
- **nautilus_runtime dead code**: `cache_reader.py`, `runtime_classes.py`, `scheduler_bridge.py`, `state.py`, `instrument_mapping.py`, `book_data.py`, `data_ingestor.py`, `execution.py`, `execution_types.py`, `exit_policy.py`, `market_data.py`, `matching.py`, `native_exit.py`, `orchestrator.py`, `position_policy.py`, `patch_nautilus_polymarket_autoload.py`, `scheduler_compat.py`, `settlement.py`
- **nautilus_bridge/strategies/** — moved to `nautilus_runtime/strategies/`
- **27 legacy test files**
- **domain**: `paper_order.py`, `paper_position.py`
- **data**: `spot_tick.py`
- **scripts**: `__init__.py`

### 🔍 Suspicious: `strategies/` Directory Empty But Present

`src/polysignal_lab/strategies/` exists with only `__pycache__/` (no .py files). The `_compat.py` and `base.py` from git HEAD were also deleted. This is the remains of the old strategy layer that hasn't been fully cleaned up.

**Verify**: Remove the empty `src/polysignal_lab/strategies/` directory.

### 🔍 Check: `nautilus_runtime/node_crash.py` (81 lines)

Contains `_CrashHandler` and related utilities. Check if imported anywhere and whether crash handling is already covered by the main runtime loop.

### 🔍 Check: `nautilus_runtime/telemetry_writer.py` (99 lines)

`TelemetryWriter` is imported in `observability.py:31` — it's used, but verify it isn't a thin wrapper around `logging` that introduces unnecessary indirection.

---

## 7. Dependency Structure

**No circular dependencies found** ✅ (0 cycles — good).

Dependency depth: 12 layers (was 13). Some areas to watch:

- `nautilus_runtime/` is the deepest module — its files depend on `nautilus_bridge/`, `domain/`, `alpha/`, `signal_layer/`, `storage/`, `observability/`, `config`, `utils`
- `PolySignalNativeStrategy` (CBO=11) imports from fewer internal modules after pipeline extraction
- BOTTLENECK: `nautilus_runtime/decision_policy.py` is imported by both `native_strategy.py` and `decision_pipeline.py`, creating a wide surface area

---

## 8. Recommendations by Priority

### 🔴 Must Fix (Architecture) — Deferred

1. **Further decompose `PolySignalNativeStrategy` (513 lines, CBO=11, LCOM4=31)** — Partial remediation complete; additional splits still recommended.

### 🟡 Should Fix (Quality)

2. **Break up `TelegramBotService` (713 lines, CBO=11)** — Extract rendering, inline keyboard building, and callback routing into separate modules.

### 🟢 Nice to Have

7. **Replace custom `OrderBook` with Nautilus's `L2OrderBook`** — If the project starts using Nautilus's built-in book reconciliation and serialization.

8. **Reduce `nautilus_runtime/` file count** — 38 non-init files is high. Some single-purpose files like `node_probes.py`, `node_signals.py`, `node_crash.py` could merge into `node_shared.py`.

9. **Consider Nautilus `Cache` for Market/OrderBook registries** — Reduces maintenance burden of thread-safe in-memory dictionaries.

10. **Improve test coverage uncovered by codegraph** — `Trade` (domain/trade.py) and `trades` in `dashboard/app.py:493` have no covering tests.

---

## 9. Codebase Stats Summary

| Metric | Value |
|--------|-------|
| Total Python files | 150 |
| Test lines | ~49,685 |
| Largest runtime module | `nautilus_runtime/` (38 files) |
| Largest file | `nautilus_runtime/native_strategy.py` (513 lines) |
| Second largest | `publish/telegram_bot.py` (713 lines) |
| Third largest | `alpha/vwap_momentum_core.py` (556 lines; history/state extracted) |
| High-coupling classes (CBO ≥ 8) | 7 |
| Total modules | 14 (alpha, app, dashboard, data, domain, nautilus_bridge, nautilus_runtime, observability, paper, publish, signal_layer, storage, strategies(empty), utils) |
| Dependency cycles | 0 ✅ |

---

*Generated by pyscn + manual codebase exploration on 2026-07-09. Metrics refreshed after remediation on 2026-07-10 — see `docs/architecture-remediation-results-2026-07-09.md`.*
