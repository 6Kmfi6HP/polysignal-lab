# Nautilus Matching Paper Migration Design

**Status:** Draft for review (revised: complete cutover policy)
**Scope:** **Complete cutover** of `runtime.engine="nautilus"` paper execution to NautilusTrader's matching engine. Production and all Nautilus-runtime paper paths use Nautilus matching only. There is no dual-backend runtime, no config toggle back to local matching, and no phased production rollout.
**Goal:** Replace inaccurate local paper matching with Nautilus `SimulatedExchange` / `OrderMatchingEngine` as the sole paper execution kernel for the Nautilus runtime, while preserving PolySignal's no-credential safety boundary, settlement/reporting outputs, and future path to live execution. Live Polymarket execution remains a separate spec.
**Migration policy:** One delivery, one runtime path. Legacy local paper modules (`PaperSimulator`, `BestAskTakerExecutor`, `PassiveGtdExecutor`, `PolySignalPaperExecutionClient`) **stay in the repository** but are **not imported or instantiated** by any default Nautilus runtime wiring after this migration lands. They may remain referenced only by legacy-scheduler tests (`runtime.engine="legacy"`) and isolated unit tests under `tests/test_paper_*`.
**Prerequisites:** The Nautilus orchestrator processing loop from `docs/superpowers/specs/2026-06-25-nautilus-runtime-fix-design.md` must be operational. Matching migration completes that runtime; it does not ship as a partial adapter behind a feature flag.

## Decision

Adopt **NautilusTrader `SimulatedExchange` / `OrderMatchingEngine` as the paper execution kernel**, not the Nautilus Polymarket live execution adapter.

Default runtime remains paper-only:

- Public Polymarket market data enters Nautilus as normalized instruments, order book updates, quotes, trades, and sidecar data.
- PolySignal strategies submit Nautilus orders through existing Nautilus strategy wrappers.
- A PolySignal-owned Nautilus paper execution adapter wraps Nautilus `SimulatedExchange` / matching internals and emits Nautilus order/fill/position events.
- Legacy local paper modules remain in the repo but are **not wired into** `runtime.engine="nautilus"` after cutover. No runtime import of `PolySignalPaperExecutionClient`, `BestAskTakerExecutor`, or `PassiveGtdExecutor` from Nautilus runtime assembly paths.
- Default code must not construct `PolymarketExecutionClient`, `PolymarketLiveExecClientFactory`, or authenticated `exec_clients`.

This is a matching-engine migration, not a live trading migration. It is also **not** a gradual A/B migration: when this work merges, Nautilus paper execution is Nautilus matching only.

**Config naming note:** `runtime.nautilus.execution_mode="paper_sandbox"` means "paper-only, no live Polymarket execution." It does **not** mean "use upstream `SandboxExecutionClient`." There is no `paper_backend` selector and no `legacy_local` runtime mode. Optional rename of `execution_mode` to `paper_only` is cosmetic only.

## Current Baseline Gaps (verified in repo)

These are not spec failures; they define what the migration must fix:

1. `PolySignalPaperExecutionClient` (`src/polysignal_lab/nautilus_runtime/execution.py`) still routes all fills through `BestAskTakerExecutor` and never instantiates `PassiveGtdExecutor`, even though passive GTD is imported. Passive GTD and resting-order ticks are not implemented in the Nautilus runtime today.
2. `NautilusOrchestrator.run_once()` has no position-exit phase. `PositionPolicyActor` is constructed in `node.py` but not invoked in the orchestrator loop. Matching migration must either wire TP/SL/max-hold through Nautilus reduce-only exits or restore an explicit orchestrator phase that reads mirrored `PaperPosition` state.
3. Production config already sets `runtime.engine: nautilus` and `runtime.nautilus.python: "3.12"`. Nautilus matching is a **Python 3.12+ runtime requirement**, not an optional dev-only path.

## Research Evidence

### Version alignment (resolve before implementation starts)

| Source | Version | Role |
|---|---|---|
| `refs/nautilus_trader` clone | `1.230.0` | Local reference for matching-engine APIs and docs |
| `uv.lock` (Python 3.11) | `1.221.0` | Legacy optional extra; not the Nautilus runtime target |
| `uv.lock` (Python 3.12+) | `1.228.0` | Current production pin — **must be bumped** as part of this migration |

This migration **includes** bumping the pinned `nautilus_trader` wheel to a version that exposes all required `SimulatedExchange` knobs (target: refs `1.230.0`). Do not ship a cutover that implements against refs APIs absent from the installed wheel.

The local `refs/nautilus_trader` clone **does** include the Polymarket adapter tree. Treat it as an unsafe live-capable upstream reference for this migration: its factories construct `py_clob_client_v2.ClobClient`, source `POLYMARKET_*` credentials, and expose live data/execution factories. Default PolySignal paper runtime must not import or instantiate those adapter factories/classes.

### NautilusTrader matching capabilities

Primary source: `refs/nautilus_trader` at `1.230.0` (upgrade target). Verify every constructor parameter against the bumped wheel before merge.

- `BacktestVenueConfig` exposes matching behavior knobs: `book_type`, `fill_model`, `latency_model`, `fee_model`, `bar_execution`, `trade_execution`, `liquidity_consumption`, `queue_position`, `price_protection_points`, settlement prices, liquidation, and reduce-only behavior (`refs/nautilus_trader/nautilus_trader/backtest/config.py:50-180`).
- `liquidity_consumption=True` tracks per-level consumed liquidity; disabled mode allows repeated fills against the same historical book level (`refs/nautilus_trader/nautilus_trader/backtest/config.py:116-119`, `refs/nautilus_trader/docs/concepts/backtesting.md:725-793`).
- `queue_position=True` uses trade ticks to decrement quantity ahead at the resting limit price and only fills after queue clears (`refs/nautilus_trader/nautilus_trader/backtest/config.py:120-124`, `refs/nautilus_trader/docs/concepts/backtesting.md:931-1018`).
- Nautilus `FillModel` supports deterministic/probabilistic limit fills and one-tick slippage via `prob_fill_on_limit`, `prob_slippage`, and `random_seed` (`refs/nautilus_trader/nautilus_trader/backtest/config.py:457-527`, `refs/nautilus_trader/nautilus_trader/backtest/models/fill.pyx:34-157`).
- The matching engine asks `FillModel.get_orderbook_for_fill_simulation()` for a synthetic book; otherwise it falls back to standard market/limit fill logic (`refs/nautilus_trader/nautilus_trader/backtest/engine.pyx:6303-6340`, `refs/nautilus_trader/nautilus_trader/backtest/engine.pyx:6759-6786`).
- Maker limit fills are gated by `FillModel.is_limit_filled()` and then optionally capped by queue-position calculations (`refs/nautilus_trader/nautilus_trader/backtest/engine.pyx:6662-6723`).
- In L1 mode, `prob_slippage` can move fills one tick worse; with L2/L3 data, book depth determines price impact instead (`refs/nautilus_trader/nautilus_trader/backtest/engine.pyx:7379-7384`, `refs/nautilus_trader/docs/concepts/backtesting.md:689-723`).
- Nautilus sandbox execution also uses `SimulatedExchange` and `BacktestExecClient`, proving the matching engine can be used with live/sandbox data (`refs/nautilus_trader/nautilus_trader/adapters/sandbox/execution.py:58-146`).

### Nautilus sandbox limitation that affects this design

Nautilus `SandboxExecutionClientConfig` exposes `book_type`, `bar_execution`, `trade_execution`, GTD support, contingent order support, and reduce-only behavior, but it does **not** expose `liquidity_consumption`, `queue_position`, `price_protection_points`, custom `fill_model`, custom `fee_model`, or custom `latency_model` (`refs/nautilus_trader/nautilus_trader/adapters/sandbox/config.py:21-77`).

The upstream `SandboxExecutionClient` constructs `SimulatedExchange` with `FillModel()`, `MakerTakerFeeModel()`, `LatencyModel(0)`, and does not pass `liquidity_consumption` or `queue_position`, so those features remain at `SimulatedExchange` defaults (`refs/nautilus_trader/nautilus_trader/adapters/sandbox/execution.py:109-136`).

Therefore the migration must not simply toggle Nautilus sandbox adapter and call it done. It needs a PolySignal-owned Nautilus paper execution adapter that constructs `SimulatedExchange` with the required realism settings.

### Nautilus Polymarket adapter safety constraints

Nautilus Polymarket integration includes live data and live execution components:

- `PolymarketDataClient`
- `PolymarketExecutionClient`
- `PolymarketLiveDataClientFactory`
- `PolymarketLiveExecClientFactory`

Source: `refs/nautilus_trader/docs/integrations/polymarket.md:62-78`.

Both data and execution configs can source credentials from environment variables:

- `POLYMARKET_PK`
- `POLYMARKET_FUNDER`
- `POLYMARKET_API_KEY`
- `POLYMARKET_API_SECRET`
- `POLYMARKET_PASSPHRASE`

Source: `refs/nautilus_trader/docs/integrations/polymarket.md:221-234`, `refs/nautilus_trader/docs/integrations/polymarket.md:864-900`, `refs/nautilus_trader/docs/integrations/polymarket.md:952-957`.

Current project safety tests already ban live Polymarket execution symbols and credential env fallbacks in default Nautilus source (`tests/test_nautilus_platform_boundary.py:28-50`, `tests/test_nautilus_safety_boundary.py:5-29`). Current config also locks default Nautilus execution to `paper_sandbox` and rejects `allow_live_polymarket_execution=True` (`src/polysignal_lab/config.py:259-272`).

### Current PolySignal paper limitations

Current paper execution is intentionally simple and local:

- `FillModelConfig` defaults to fixed `slippage_bps=25`, full-depth requirement, and `reject_if_partial=True` (`src/polysignal_lab/config.py:198-204`).
- Default taker fills use `best_ask + slippage_bps`; depth is checked with `book.depth_until(limit_price)` but no per-level liquidity consumption is retained across orders (`src/polysignal_lab/paper/order_intent_executor.py:90-133`).
- FAK/FOK consume sorted ask levels for a single order and can produce partial FAK, but again without exchange-level order book state or global queue (`src/polysignal_lab/paper/order_intent_executor.py:135-237`).
- Passive GTD stores local `RestingOrder` objects and fills when `book.best_ask <= limit_price`; it has no queue-position model and no trade-tick-driven queue depletion (`src/polysignal_lab/paper/order_intent_executor.py:276-380`).
- `PolySignalPaperExecutionClient` is credential-free and local, but it wraps the same local paper path rather than Nautilus matching (`src/polysignal_lab/nautilus_runtime/execution.py:189-310`).

## Non-goals

1. Do not delete legacy paper modules; isolate them from Nautilus runtime imports instead.
2. Do not ship a dual-backend or rollback config for local paper matching in `runtime.engine="nautilus"`.
3. Do not run production through local paper matching while Nautilus matching matures in parallel.
4. Do not enable real Polymarket live execution.
5. Do not read `POLYMARKET_*` credentials in paper mode.
6. Do not wire Nautilus `PolymarketExecutionClient` or `PolymarketLiveExecClientFactory` into the Nautilus runtime.
7. Do not introduce a second speculative strategy abstraction; existing `AlphaCore` and Nautilus strategy wrappers remain the strategy boundary.
8. Do not migrate settlement oracle logic into Nautilus. Resolution still uses PolySignal settlement services.
9. Do not require Nautilus for default **core package** import on Python 3.11. The Nautilus matching runtime (`polysignal-nautilus`) requires Python 3.12+ and the optional extra.

## Approaches Considered

### Option A — Use upstream `SandboxExecutionClient` directly

Pros:

- Smallest code delta.
- Uses Nautilus `SimulatedExchange` and `BacktestExecClient`.
- Fits Nautilus sandbox/live environment vocabulary.

Cons:

- Upstream config does not expose `liquidity_consumption`, `queue_position`, `price_protection_points`, fee model, latency model, or custom fill model.
- Defaults are too optimistic for passive Polymarket queues.
- Harder to preserve PolySignal-specific audit fields and settlement persistence without adapter glue.

Rejected as the default because it does not meet the stated accuracy goal.

### Option B — PolySignal-owned Nautilus paper execution adapter around `SimulatedExchange`

Pros:

- Uses Nautilus matching engine for order lifecycle and fills.
- Can pass `liquidity_consumption=True`, `queue_position=True`, `trade_execution=True`, `support_gtd_orders=True`, and explicit fee/latency/fill models.
- Keeps default paper credential-free and independent of Polymarket live execution adapter.
- Lets PolySignal preserve existing telemetry, settlement, Telegram, and SQLite/JSONL outputs through event adapters.

Cons:

- More integration code than upstream sandbox client.
- Requires careful mapping between Polymarket binary tokens and Nautilus instruments.
- Requires robust tests around event ordering, precision, and matching correctness.

**Selected.** This is the only paper execution path for `runtime.engine="nautilus"`.

### Option C — Full Nautilus `TradingNode` with Nautilus Polymarket data client and custom paper execution

Pros:

- Cleanest long-term architecture.
- Same strategy/data/execution event flow as future live mode.
- Least long-term dependency on old scheduler runtime.

Cons:

- Nautilus Polymarket data config has credential fallback hazards.
- Larger migration surface: data client, execution client, node config, state, observability, tests, deployment.
- Harder to prove paper correctness before data path correctness.

Deferred to the future live-execution spec. Paper matching uses Option B only; live later reuses the same adapter shape where possible.

## Target Architecture

```mermaid
flowchart TB
    PMWS[Public Polymarket CLOB WS/REST] --> DATA[PolySignal Nautilus Public Data Adapter]
    RTDS[RTDS/Binance Spot] --> SIDE[Sidecar Data Adapter]
    GAMMA[Gamma / Anchor / PTB] --> SIDE
    DATA --> CACHE[Nautilus Cache + DataEngine-compatible Events]
    SIDE --> CACHE
    CACHE --> STRAT[PolySignal Nautilus Strategy Wrappers]
    STRAT --> CORE[AlphaCore]
    CORE --> STRAT
    STRAT --> POLICY[DecisionPolicyActor]
    POLICY --> ORDER[NautilusOrderSpec via strategy submitter]
    ORDER --> MATCH[PolySignal Nautilus Paper Execution Adapter]
    MATCH --> SIM[Nautilus SimulatedExchange + OrderMatchingEngine]
    SIM --> EVENTS[Nautilus Order / Fill / Position Events]
    EVENTS --> STRAT
    EVENTS --> OBS[Observability Adapter]
    OBS --> SQL[(SQLite / JSONL)]
    OBS --> SETTLE[PolySignal SettlementResolver]
    OBS --> TG[Telegram / Reports]
```

### Runtime ownership

Nautilus owns:

- Order objects and identifiers.
- Order state transitions.
- Time-in-force behavior for IOC/FOK/GTD where supported.
- Matching, partial fills, price/size precision, queue-position gating, liquidity-consumption gating.
- Fill, order, and position events.

PolySignal owns:

- Public Polymarket data ingestion safety boundary.
- Market discovery, condition/token mapping, asset/timeframe/slug metadata.
- Strategy alpha logic and decision policy.
- Paper risk limits that are not represented by Nautilus account state.
- Settlement oracle, Telegram templates, reports, health, and persistence.
- Safety scanner rules.

### Orchestrator integration (PolySignal-owned loop, not `TradingNode`)

The default runtime keeps the existing `NautilusOrchestrator` phase model. Do **not** require `TradingNode.run()` for paper matching in this migration (Option C remains deferred).

Recommended phase wiring:

| Phase | Current behavior | Matching migration change |
|---|---|---|
| `_phase_market_refresh` | Gamma/discovery | unchanged |
| `_phase_sync` | `NautilusDataIngestor.sync_all()` updates bridge + book cache | push Nautilus `OrderBookDeltas` / `TradeTick` into `SimulatedExchange`; advance matching `TestClock` to wall-clock or book timestamp |
| `_phase_strategy_eval` | wrappers call injected submitter | submitter is **only** `NautilusMatchingPaperExecutionClient.submit_spec()`; drain pending Nautilus fill/cancel events before/after each strategy batch |
| `_phase_resting_orders` | missing today — **must ship with cutover** | drain exchange events, process resting GTD orders after book/trade updates, and expire GTD orders before the next strategy eval; IOC/FOK never rest |
| `_phase_position_exits` | missing today — **must ship with cutover** | evaluate open mirrored positions; wire `PositionPolicyActor` or Nautilus reduce-only exits |
| `_phase_settlement` | `scheduler.check_settlements()` | unchanged; reads mirrored `PaperPosition` / wallet state |
| observability phases | SQLite/JSONL/Telegram | unchanged inputs, new event bridge |

Implementation should follow the upstream sandbox wiring pattern: `MessageBus`, `Cache`, `PortfolioFacade`, `TestClock`, `SimulatedExchange`, `BacktestExecClient`, and event subscription — without importing `SandboxExecutionClient` (which omits accuracy knobs).

## Component Design

### 1. `NautilusMatchingPaperExecutionClient`

Create a new execution adapter under `src/polysignal_lab/nautilus_runtime/` that owns a Nautilus `SimulatedExchange` instance (via the sandbox wiring pattern above, not via upstream `SandboxExecutionClient`).

Responsibilities:

- Construct `SimulatedExchange` with explicit paper realism settings from the active accuracy mode:
  - `account_type="CASH"`
  - `oms_type="NETTING"` unless strategy hedging requires per-position IDs.
  - `book_type` from accuracy mode (`L1_MBP` for `fast_l1`, `L2_MBP` for `depth_l2` / `queue_l2`).
  - `trade_execution=True`
  - `bar_execution=False` for short-cycle Polymarket unless later historical bars are introduced.
  - `liquidity_consumption=True` for L2 modes; disabled only in `fast_l1`.
  - `queue_position=True` only for `queue_l2`; production-default `depth_l2` keeps it `False` until trade tick side/size quality is proven.
  - `support_gtd_orders=True`
  - `support_contingent_orders=False` initially; strategies continue to manage paired/hedge semantics explicitly.
  - `use_reduce_only=True`
  - nonzero `price_protection_points` only after precision tests prove the mapping.
- Register instruments before any order submission.
- Convert `NautilusOrderSpec` / strategy order intents into real Nautilus orders.
- Feed order book deltas, quote ticks, and trade ticks into the exchange before strategy evaluation or matching cycles.
- Emit execution results to existing observability without creating local `PaperFill` directly as source of truth.
- Mirror Nautilus fills into `PaperWallet` / `PaperPosition` immediately after each matching cycle so settlement, position policy, and daily reports keep working without waiting for a separate port.

Non-responsibilities:

- It does not call Polymarket CLOB order endpoints.
- It does not read private keys or API credentials.
- It does not decide strategy acceptance; `DecisionPolicyActor` remains upstream.

### 2. Public Polymarket Nautilus data adapter

Do not use Nautilus `PolymarketDataClient` in default paper mode until credential-free construction is proven in tests.

Instead, reuse the current public data sources and translate them into Nautilus-compatible data:

- Current CLOB REST/WS books become Nautilus order book snapshots/deltas or quote/depth events.
- Current last-trade fields become Nautilus `TradeTick` where side/size/timestamp is available.
- Current RTDS/Binance spot and PTB/anchor metadata remain sidecar custom data.

Requirements:

- Preserve current `PublicCLOBClient` alias convention and avoid blocked `ClobClient(` source token.
- Preserve freshness metadata and reject stale books before they reach matching if staleness would violate `max_book_staleness_ms`.
- Generate stable Nautilus instrument IDs from Polymarket token IDs.
- Store condition ID, market ID, slug, UP/DOWN side, tick size, and min order size in a registry available to strategies and observability.

### 3. Instrument model mapping

Each Polymarket outcome token maps to a Nautilus `BinaryOption` (`nautilus_trader.model.instruments.BinaryOption`) when present in the bumped wheel. Construct it in PolySignal-owned adapter code; do not import upstream Polymarket live data/execution factories in default paper runtime. If the bumped wheel lacks a compatible `BinaryOption`, implementation must stop and revise this spec instead of inventing a second instrument abstraction silently.

Minimum required fields:

- venue: paper-only venue, e.g. `POLYSIGNAL_PM_PAPER`.
- instrument ID: stable token-derived ID.
- price precision: derived from Polymarket tick size; default 0.001 only if metadata is missing and safety tests mark the fallback.
- size precision: derived from CLOB size increments; default must be explicit and tested.
- quote currency: USD/USDC-equivalent account currency.
- expiry: market close/end timestamp when available.

The mapping must be deterministic. A token ID must never map to a different Nautilus instrument ID across restarts.

### 4. Order intent mapping

Current intent semantics map to Nautilus order types/time-in-force:

| PolySignal intent | Nautilus order shape | Matching expectation |
|---|---|---|
| default taker | Limit buy at `max_entry_price`, submitted aggressive when `best_ask <= max_entry_price` | fills through book depth, with matching-engine price impact |
| `TAKER_IOC` | Limit IOC | partial or cancel remainder according to Nautilus IOC behavior |
| `TAKER_FAK` | Limit IOC | Nautilus has no native FAK type; IOC with partial fill allowed is the closest mapping |
| `TAKER_FOK` | Limit FOK | all-or-none; reject/cancel if insufficient matchable depth |
| `PASSIVE_GTD` | Limit GTD | rests in matching engine; fills only when book/trade events clear price and queue conditions |

Important correction from current runtime: LateConsensus `max_entry_price` remains a ceiling, not the execution price. The submitted Nautilus order can use `max_entry_price` as limit, while actual fills must come from matching against current book/trade liquidity.

### 5. Legacy paper isolation (not deletion)

These modules **remain in the repository** but are **removed from the Nautilus runtime import graph**:

- `src/polysignal_lab/paper/simulator.py`
- `src/polysignal_lab/paper/fill_model.py`
- `src/polysignal_lab/paper/order_intent_executor.py`
- `src/polysignal_lab/nautilus_runtime/execution.py` — `PolySignalPaperExecutionClient` may remain for isolated unit tests but must not be constructed by `node.py`, `orchestrator.py`, or `data_ingestor.py`

Cutover rules:

- `node.py` wires `NautilusMatchingPaperExecutionClient` only. No factory branch, no config fallback.
- `NautilusDataIngestor` feeds the matching client only; it must not call `PolySignalPaperExecutionClient.update_book()`.
- Add a safety test (`tests/test_nautilus_platform_boundary.py` or sibling) that fails if `src/polysignal_lab/nautilus_runtime/**/*.py` imports `BestAskTakerExecutor`, `PassiveGtdExecutor`, `PaperSimulator`, or constructs `PolySignalPaperExecutionClient` outside explicit test-only modules.
- Legacy scheduler (`runtime.engine="legacy"`) may continue using `PaperSimulator` in its own path; that path is not part of this migration's deliverable but must not be selected by production config.

### 6. Observability and persistence bridge

Nautilus events become the source of truth for order/fill/position state. The bridge converts events into existing storage rows for compatibility:

- `OrderSubmitted` / `OrderAccepted` / `OrderRejected` -> existing paper order/audit records.
- `OrderFilled` partial/full -> existing paper fill and position records.
- `OrderCanceled` / `OrderExpired` -> existing rejection/cancel fields.
- Strategy tags carry `strategy`, `asset`, `timeframe`, `condition_id`, `market_id`, `market_slug`, `signal_id`, `max_entry_price`, `entry_reference_price`, `order_intent`, `pair_id`, `hedge_leg`.

Settlement remains PolySignal-owned:

- Open Nautilus-filled paper positions must be mirrored into the shared paper position state used by `scheduler.check_settlements()` until settlement is itself ported.
- The three-source `SettlementResolver` remains unchanged: CTF chain -> Gamma exact lookup -> WS cache hints.

### 7. Accuracy modes

Provide three explicit modes. Do not hide assumptions behind one `paper` label.

#### `fast_l1`

- `book_type="L1_MBP"`
- `trade_execution=True`
- `queue_position=False`
- used only for quick smoke and environments without depth.

#### `depth_l2` production default

- `book_type="L2_MBP"`
- `trade_execution=True`
- `liquidity_consumption=True`
- `queue_position=False` when trade side/size quality is insufficient.

#### `queue_l2` production target when data supports it

- `book_type="L2_MBP"`
- `trade_execution=True`
- `liquidity_consumption=True`
- `queue_position=True`
- requires trade ticks with price, size, timestamp, and usable aggressor side or an explicit documented fallback.

Accuracy mode is a **configuration choice**, not a migration phase. Production ships with one selected mode at cutover; switching modes later is config-only and does not re-enable local matching.

## Data Flow

1. Market refresh loads active Polymarket markets and builds token -> instrument mappings.
2. Public order book snapshots/deltas update Nautilus matching books.
3. Trade ticks update Nautilus matching state and drive passive order queue depletion.
4. Sidecar spot/PTB/anchor updates feed strategy views.
5. Strategy wrappers evaluate `AlphaCore` and produce `AlphaDecision`.
6. `DecisionPolicyActor` applies freshness, dedupe, consensus, and exposure policy.
7. Accepted decisions become Nautilus orders with strategy tags.
8. Nautilus matching engine accepts, rejects, fills, partially fills, cancels, or expires orders.
9. Execution events update strategy callbacks, observability, persistence, wallet mirror, settlement queue, Telegram, and reports.
10. No Nautilus-runtime order path invokes local paper executors.

The runtime must log the active accuracy mode and `paper_engine=nautilus_matching` in startup, health, daily report, and paper execution assumptions.

## Safety Requirements

1. Default paper mode must pass the current safety boundary tests banning `PolymarketExecutionClient`, `PolymarketLiveExecClientFactory`, `exec_clients`, and `POLYMARKET_*` fallback tokens in default runtime source.
2. If future live mode is added, it must live behind a separate explicit `runtime.nautilus.execution_mode="live_polymarket"` or equivalent, not a boolean.
3. `allow_live_polymarket_execution=True` must remain invalid for default config.
4. No default runtime path may instantiate Nautilus `PolymarketExecClientConfig`.
5. No default runtime path may call allowance or API-key helper scripts.
6. Public data adapter failures must degrade paper trading, not silently switch to authenticated Nautilus data clients.
7. The safety scanner must keep flagging blocked live symbols in default runtime code.
8. The safety scanner must fail if Nautilus runtime source re-imports local paper executors or constructs `PolySignalPaperExecutionClient`.

## Testing Strategy

Tests prove matching correctness and runtime isolation. **No legacy parity gate** blocks merge.

### Unit tests

- Instrument mapping determinism: token ID -> Nautilus instrument ID remains stable.
- Price/size precision: 0.001-style binary market ticks round correctly and reject invalid prices.
- Order intent mapping:
  - default taker uses limit ceiling but fills at book-derived price.
  - IOC allows partial/cancel behavior.
  - FOK rejects if full depth is unavailable.
  - GTD rests and expires.
- Event translation: Nautilus order/fill/cancel events produce existing SQLite-compatible payloads.
- Runtime isolation: `nautilus_runtime` source contains no imports of `BestAskTakerExecutor`, `PassiveGtdExecutor`, `PaperSimulator`, or default construction of `PolySignalPaperExecutionClient`.

### Matching correctness tests

Use synthetic L2 book and trade tick sequences:

- best ask below max entry, full depth available -> filled at book-derived price, not fixed slippage model.
- best ask above max entry -> rejected/canceled.
- malformed or stale book -> rejected before matching.
- FOK insufficient depth -> no fill.
- LateConsensus max-entry ceiling -> actual fill from best ask/depth, not a hardcoded price.
- Two orders against the same level with `liquidity_consumption=True`: second order only fills remaining displayed liquidity.
- Passive BUY GTD with queue ahead: first trade clears queue; second trade fills excess when `queue_l2` is active.
- Trade tick inside stale spread: fill quantity capped by trade size.
- L1 `prob_slippage` mode (`fast_l1` smoke only): slippage moves one tick worse.

### Safety tests

- Default Nautilus matching source contains no forbidden live Polymarket execution symbols.
- Config validation rejects live execution in default mode.
- Default core import still works without Nautilus installed on Python 3.11.
- Nautilus-dependent tests are isolated behind Python 3.12+ / optional extra checks.

### Runtime smoke (required before merge)

- Run one bounded Nautilus matching paper cycle against fixture data through the full orchestrator.
- Verify fills produce SQLite/JSONL order/fill/position rows.
- Verify settlement closes a mirrored Nautilus-filled paper position.
- Verify Telegram signal/result formatting still uses existing message formatter path.
- Verify daily report includes `paper_engine=nautilus_matching` and accuracy mode.
- Verify source-boundary tests and safety scan show no local paper executor wired in `nautilus_runtime`.

## Single Delivery Scope (complete cutover)

All items below ship in **one migration**. Partial merge states that still route Nautilus-runtime orders through local paper matching are **not allowed**.

1. **Dependency:** Bump `uv.lock` `nautilus_trader` to verified `1.230.0` (or latest confirmed equivalent) on Python 3.12+.
2. **Instrument registry:** Polymarket outcome token -> Nautilus `BinaryOption` mapping with deterministic IDs.
3. **Data bridge:** Public CLOB books and trades -> Nautilus `OrderBookDeltas` / `TradeTick` fed into `SimulatedExchange`.
4. **Execution adapter:** `NautilusMatchingPaperExecutionClient` owning configured `SimulatedExchange` + event bridge.
5. **Runtime rewiring:** `node.py`, `orchestrator.py`, `data_ingestor.py`, and strategy submitter injection use matching client only.
6. **Orchestrator completeness:** resting-order phase, position-exit phase, and event drain integrated in the same delivery.
7. **Observability mirror:** Nautilus events -> existing SQLite/JSONL/Telegram/settlement read models via `PaperWallet` mirror.
8. **Legacy isolation:** safety test enforcing no local paper executor imports in `nautilus_runtime` default paths.
9. **Tests:** unit + matching correctness + runtime smoke above all green.

Post-cutover calibration (recorded book/trade replay, `depth_l2` vs `queue_l2` tuning) may continue **after** merge but must not block the cutover itself and must not reintroduce local matching.

## Acceptance Criteria

1. `runtime.engine="nautilus"` submits all paper orders through Nautilus matching only; Nautilus order/fill/position events are the execution source of truth.
2. `node.py` / `orchestrator.py` / `data_ingestor.py` do not import or construct local paper executors or `PolySignalPaperExecutionClient`.
3. Passive GTD orders are resting Nautilus orders, not local `RestingOrder` objects.
4. Orchestrator includes resting-order and position-exit phases wired to the matching client.
5. L2 depth mode prevents repeated consumption of the same displayed liquidity when `liquidity_consumption=True`.
6. Queue mode uses trade ticks to delay passive fills when `queue_l2` is selected.
7. Existing settlement, Telegram, SQLite/JSONL, and daily report outputs work from Nautilus matching events via the mirror bridge.
8. Default runtime remains credential-free and does not instantiate Nautilus Polymarket live execution classes.
9. Core package import on Python 3.11 remains Nautilus-free; `polysignal-nautilus` runs on Python 3.12+ with the bumped optional extra.
10. Safety tests enforce both live-execution symbol bans and local-paper isolation in `nautilus_runtime`.
11. No config flag exists to route Nautilus-runtime paper orders back to local matching.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Nautilus Python support is 3.12+ while core package still supports 3.11 | Production Nautilus runtime targets 3.12; keep core imports Nautilus-free on 3.11. |
| Pinned wheel behind refs APIs | Bump `uv.lock` to `1.230.0` in the same PR as the cutover. |
| Orchestrator missing resting-order and exit phases | Required deliverables in the single cutover; merge blocked without them. |
| Accidental re-import of local paper executors | Safety test on `nautilus_runtime` import graph. |
| Upstream sandbox config lacks accuracy knobs | PolySignal-owned adapter around `SimulatedExchange`; never use upstream sandbox defaults. |
| Polymarket data client can source credentials | Public data adapter only in Nautilus runtime. |
| Trade ticks lack reliable aggressor side | Ship `depth_l2` at cutover; enable `queue_l2` via config when data quality is proven. |
| Event translation duplicates or loses fills | Nautilus order/fill IDs as idempotency keys; test duplicate-event replay. |
| Settlement reads wallet mirror | Mirror Nautilus fills into `PaperWallet` immediately after each matching cycle. |

## Open Decisions for Review

1. Production accuracy mode at cutover: recommended `depth_l2`; switch to `queue_l2` via config when trade tick quality is proven.
2. Venue/account model: recommended `CASH` + `NETTING`; use `HEDGING` only if strategy pair semantics require separate position IDs.
3. Fee model: start with explicit zero-fee mode if current paper ignores fees.
4. Live roadmap: separate spec after paper matching cutover is stable.

## Review Checklist

- Complete cutover: no dual-backend, no `legacy_local`, no migration waves.
- Legacy paper modules remain in repo but are isolated from `nautilus_runtime` imports.
- Default runtime remains paper-only and credential-free.
- Nautilus matching realism settings are explicit.
- Upstream sandbox limitations are called out.
- Tests prove matching correctness and runtime isolation, not legacy parity.
