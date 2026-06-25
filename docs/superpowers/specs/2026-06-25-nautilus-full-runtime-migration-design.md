# Nautilus Full Runtime Migration Design

**Status:** Draft for review
**Scope:** 全量一步到位迁移规格：把 13 个 PolySignal 策略的执行从 `PolySignalScheduler` / `scheduler_processing.py` / `PaperSimulator` 迁到 NautilusTrader `TradingNode`，并规划旧 runtime 退役。
**Supersedes / extends:** `docs/superpowers/specs/2026-06-24-15-nautilus-strategy-bridge-design.md`。Spec 15 已完成 Wave 0-1 的 bridge 基础，本 spec 接管后续全量 runtime 切换。
**Goal:** NautilusTrader 成为唯一策略执行内核；PolySignal 保留 alpha 逻辑、Polymarket 业务语义、sidecar 数据、只读安全边界、观测与报表输出。

## Decision

采用 **完全 Nautilus 原生运行时**：

- `TradingNode` 替代 `PolySignalScheduler.run()`。
- Nautilus Polymarket data adapter 替代当前 CLOB REST/WS orderbook 执行数据通路。
- Nautilus custom `Data` 类型承载 PolySignal 额外数据：spot、price-to-beat、anchor、market metadata、health hints。
- 每个 PolySignal 策略拆成：
  - `AlphaCore`：纯策略判断，输入 `MarketView` / `MarketGroupView`，输出 `AlphaDecision` / `OrderIntentSpec`。
  - `Nautilus Strategy wrapper`：订阅 Nautilus market/custom data，调用 core，提交 Nautilus orders，处理 order/position callbacks。
- `DecisionPolicyActor` 承担跨策略 gate、dedupe、rate-limit、consensus、arbiter。
- `ObservabilityActor` 承担 Telegram、SQLite/JSONL、health snapshot、daily report。
- 默认实现仅允许 paper/emulated/sandbox execution，不接入真实 Polymarket authenticated execution。

This is not “Nautilus inside the old scheduler”. It is “PolySignal alpha inside Nautilus”.

## Current State Evidence

### What already exists

Spec 15 Wave 0-1 is partially implemented:

- `pyproject.toml` has optional extra `nautilus = ["nautilus_trader[polymarket]"]`.
- Default package import does not require Nautilus.
- `src/polysignal_lab/alpha/types.py` defines `MarketView`, `AlphaDecision`, `OrderIntentSpec`, `AlphaCore`.
- `src/polysignal_lab/alpha/ptb_diff_core.py` extracts PTB alpha logic.
- `src/polysignal_lab/nautilus_bridge/` contains:
  - `strategy_base.py`
  - `market_registry.py`
  - `market_view_assembler.py`
  - `external_data.py`
  - `state.py`
  - `strategies/ptb_diff.py`
- Tests cover dependency boundary, safety boundary, state codec, market registry, sidecar, assembler, and PTB strategy base.

### What still runs in production today

Current execution remains custom PolySignal runtime:

1. `PolySignalScheduler._initialize_trading_components()` builds `strategy_schedule`, `PaperWallet`, `PaperSimulator`, `PaperExitEngine`, `PaperSettlementEngine`.
2. `scheduler_processing.evaluate_once()` builds snapshots, calls `strategy.evaluate(snapshot)`, arbitrates, gates, and commits.
3. `scheduler_processing.process_signal()` stores signal, publishes Telegram, sends to paper simulator, processes follow-up signals.
4. Strategy callbacks are scheduler-driven:
   - `notify_signal_accepted()`
   - `notify_signal_rejected()`
   - `notify_fill()`
   - `notify_cancel()`
   - `notify_leg_failure()`
   - `follow_up_signals()`
5. Current Docker image does not install `nautilus-trader`.

Therefore the migration is runtime replacement, not an adapter toggle.

## Non-goals

1. No real Polymarket live execution in the default repo runtime.
2. No default import, construction, or registration of:
   - `PolymarketExecutionClient`
   - `PolymarketLiveExecClientFactory`
   - `exec_clients` containing live Polymarket credentials
3. No default reading of:
   - `POLYMARKET_PK`
   - `POLYMARKET_FUNDER`
   - `POLYMARKET_API_KEY`
   - `POLYMARKET_API_SECRET`
   - `POLYMARKET_PASSPHRASE`
4. No allowance helper use in default runtime:
   - `set_allowances.py`
   - `create_api_key.py`
5. No long-term dual scheduler. A migration branch may temporarily keep legacy wrappers for equivalence tests, but the final runtime has one strategy execution owner: NautilusTrader.
6. No mock exchange layer. Paper mode must use Nautilus sandbox/emulated execution or a documented Nautilus-compatible paper execution client.

## Target Architecture

```mermaid
flowchart TB
    PM[Polymarket public market data] --> PDC[Nautilus PolymarketDataClient]
    RTDS[RTDS/Binance spot] --> SIDE[SidecarDataActor]
    GAMMA[Gamma/anchor/PTB metadata] --> SIDE
    PDC --> DE[Nautilus DataEngine + Cache]
    SIDE --> DE
    DE --> S1[PolySignal Nautilus Strategies]
    S1 --> AC[AlphaCore layer]
    AC --> S1
    S1 --> POLICY[DecisionPolicyActor]
    POLICY --> EX[Nautilus paper/sandbox ExecutionEngine]
    EX --> PF[Nautilus Portfolio + Cache]
    PF --> S1
    DE --> OBS[ObservabilityActor]
    EX --> OBS
    POLICY --> OBS
    OBS --> SQL[(SQLite/JSONL/State)]
    OBS --> TG[Telegram]
    OBS --> HEALTH[/health]
```

### Runtime ownership

#### NautilusTrader owns

- Strategy lifecycle.
- Market data event dispatch.
- Instrument cache.
- Order lifecycle.
- Position and portfolio state.
- Paper/sandbox execution state.
- Strategy state save/load hooks.
- MessageBus / DataEngine / RiskEngine / ExecutionEngine orchestration.

#### PolySignal owns

- Strategy formulas.
- Strategy configuration semantics.
- Polymarket binary-market business concepts: asset, timeframe, slug, condition, UP/DOWN pair.
- PTB / anchor / spot sidecar semantics.
- Signal audit fields, reason codes, metrics.
- Telegram/report/health presentation.
- Safety scanner and default read-only contract.

#### Bridge owns

- Config mapping from `StrategyConfig` to strategy core configs.
- Nautilus instrument mapping to PolySignal market pairs.
- Nautilus cache/custom data to `MarketView` assembly.
- `AlphaDecision` to Nautilus order intent mapping.
- Nautilus order/position event to strategy state transition mapping.
- State serialization schema for migrated strategies.

## Component Design

### 1. `alpha/` strategy core layer

Every strategy must get an engine-agnostic core. The core must not import scheduler, Telegram, SQLite, Nautilus, PaperWallet, or domain snapshot objects.

#### Existing interface

`src/polysignal_lab/alpha/types.py` already defines:

```python
class AlphaCore(Protocol):
    def evaluate(self, view: MarketView) -> list[AlphaDecision]: ...
```

This remains valid for single-market strategies.

#### New interfaces

Add explicit state and group interfaces instead of overloading `AlphaCore`:

```python
class StatefulAlphaCore(AlphaCore, Protocol):
    def on_order_submitted(self, event: AlphaOrderEvent) -> None: ...
    def on_order_accepted(self, event: AlphaOrderEvent) -> None: ...
    def on_order_rejected(self, event: AlphaOrderEvent) -> None: ...
    def on_order_canceled(self, event: AlphaOrderEvent) -> None: ...
    def on_order_expired(self, event: AlphaOrderEvent) -> None: ...
    def on_order_filled(self, event: AlphaFillEvent) -> list[AlphaDecision]: ...
    def save_state(self) -> Mapping[str, object]: ...
    def load_state(self, payload: Mapping[str, object]) -> None: ...
```

```python
class GroupAlphaCore(Protocol):
    def evaluate_group(self, view: MarketGroupView) -> list[AlphaDecision]: ...
```

```python
@dataclass(frozen=True, slots=True)
class MarketGroupView:
    group_id: str
    relation_id: str
    created_at: datetime
    views_by_condition_id: Mapping[str, MarketView]
    max_source_skew_ms: int
    metrics: Mapping[str, object]
```

```python
@dataclass(frozen=True, slots=True)
class AlphaOrderEvent:
    strategy: str
    market_id: str
    condition_id: str
    token_id: str
    side: Side
    order_id: str
    client_order_id: str | None
    reason: str | None
    ts_event: datetime
    metrics: Mapping[str, object]
```

```python
@dataclass(frozen=True, slots=True)
class AlphaFillEvent(AlphaOrderEvent):
    fill_price: float
    shares: float
    liquidity_side: str | None
```

These events replace legacy scheduler callbacks.

### 2. Strategy extraction inventory

| Strategy | Current state | Callbacks | New core | Complexity | Notes |
|---|---:|---|---|---|---|
| `ptb_diff` | none | none | `PTBDiffAlphaCore` exists | done | Keep as baseline equivalence suite. |
| `skew_mean_reversion` | none | none | `SkewMeanReversionAlphaCore` | simple | Pure evaluate extraction. |
| `binary_momentum` | `_spot_prices`, `_vwap_stats`, `_entered_markets` | none | `BinaryMomentumAlphaCore` | medium | State save/load required; current code pre-commits `_entered_markets` during evaluate, so migrated core must move irreversible entry marking to order accepted/fill event. |
| `fibonacci_bot` | ZigZagBot `_prices`, `_swing_highs`, `_swing_lows`, `_current_trend`, `_extreme_price` | none | `FibonacciAlphaCore` | medium | Serialize deques and trend state. |
| `one_cent_buy` | `_submitted_levels` | none | `OneCentBuyAlphaCore` | medium | Mark submitted levels on order accepted, not candidate creation. |
| `ninety_nine_cent_sniper` | `_sniped_markets` | none | `NinetyNineCentSniperAlphaCore` | medium | Mark sniped side on accepted/fill, not candidate creation. |
| `late_consensus` | `_last_favorite`, `_last_entry_at`, `_accepted_counts` | `notify_signal_accepted` | `LateConsensusAlphaCore` | hard | Map accepted callback to `on_order_submitted` or `on_order_accepted` exactly; frequency gate must not mutate on rejected candidates. |
| `vwap_momentum` | `TradeHistory`, `_can_enter`, `_pending_signal_samples`, `_last_trade_signatures`, `_seen_trade_signatures`, `_pending_hedges` | accepted, rejected, fill, cancel, follow-up | `VWAPMomentumAlphaCore` | hard | Follow-up hedge becomes direct order submission from `on_order_filled`; GTD expiry clears pending hedge via `on_order_expired`. |
| `dump_hedge` | `_price_stats`, `_entered_markets`, `_positions`, `_dump_detected`, `_last_price` | fill, leg_failure | `DumpHedgeAlphaCore` | hard | Multi-leg failure maps to order/position event plus pair_id state. |
| `mid_price_sizing` | `_layer_count`, `_entry_prices` | fill | `MidPriceSizingAlphaCore` | hard | Layer count increments on actual fill only. |
| `pre_order_market` | `_pre_ordered`, `_entered_markets`, `_positions`, `_reconciled` | fill | `PreOrderMarketAlphaCore` | hard | Pre-open orders must map to GTD expiry/cancel semantics. |
| `low_side_dual_reversion` | `_entered_markets`, `_positions` | fill | `LowSideDualReversionAlphaCore` | hard | Hedge/stop decisions consume actual position state. |
| `cross_market_bot` | `_relations`, `_market_to_relations`, `_active_baskets` | fill, leg_failure, `evaluate_group` | `CrossMarketAlphaCore` | hard | Requires `MarketGroupView` and multi-order/basket coordination. |

### 3. Nautilus wrapper layer

Create one wrapper base and one wrapper per migrated strategy:

```text
src/polysignal_lab/nautilus_runtime/
  node.py
  config.py
  sidecar_data.py
  decision_policy.py
  observability.py
  market_data.py
  execution.py
  state.py
  strategies/
    base.py
    ptb_diff.py
    skew_mean_reversion.py
    binary_momentum.py
    fibonacci.py
    one_cent_buy.py
    ninety_nine_cent_sniper.py
    late_consensus.py
    vwap_momentum.py
    dump_hedge.py
    mid_price_sizing.py
    pre_order_market.py
    low_side_dual_reversion.py
    cross_market_bot.py
```

Keep existing `src/polysignal_lab/nautilus_bridge/` as low-level adapter utilities or move it under `nautilus_runtime/bridge/` with compatibility imports during the migration branch. Final code should have one named Nautilus runtime package.

#### Base strategy wrapper responsibilities

`PolySignalNautilusStrategy` must:

1. Subscribe to relevant Nautilus instrument data.
2. Subscribe to custom sidecar data.
3. On market/orderbook/trade/custom data events, ask `MarketViewAssembler` for a coherent view.
4. Call the `AlphaCore` / `StatefulAlphaCore`.
5. Send candidate decisions to `DecisionPolicyActor`.
6. Submit approved orders through Nautilus strategy order APIs.
7. Translate Nautilus order events into `AlphaOrderEvent` / `AlphaFillEvent`.
8. Persist core state through `on_save()` / `on_load()`.

The wrapper must not re-implement gate, paper wallet, settlement, or Telegram behavior.

### 4. Market data and sidecar data

#### Nautilus Polymarket data

Use the Nautilus Polymarket data adapter for:

- `BinaryOption` instruments.
- CLOB order books.
- Quote/trade ticks.
- Instrument hydration.
- Polymarket WebSocket connection management.

The default runtime may register `PolymarketLiveDataClientFactory` because it is public market data. It must not register the live execution factory.

#### PolySignal custom data types

Nautilus docs support custom data via `Data` subclasses and `DataType` subscriptions:

```python
@customdataclass
class PolySignalSpotData(Data):
    asset: str
    symbol: str
    price: float
    source: str
    freshness_ms: int | None
```

```python
@customdataclass
class PolySignalPriceToBeatData(Data):
    condition_id: str
    value: float
    source: str
    verified: bool
    from_anchor_service: bool
    anchor_source: str | None
    anchor_lag_ms: int | None
```

```python
@customdataclass
class PolySignalMarketMetaData(Data):
    market_id: str
    market_slug: str
    condition_id: str
    asset: str
    timeframe: str
    start_ts_ns: int | None
    end_ts_ns: int | None
    up_token_id: str
    down_token_id: str
```

`SidecarDataActor` publishes these through Nautilus MessageBus:

```python
self.publish_data(DataType(PolySignalSpotData), spot_data)
self.publish_data(DataType(PolySignalPriceToBeatData), ptb_data)
self.publish_data(DataType(PolySignalMarketMetaData), market_data)
```

Strategies subscribe:

```python
self.subscribe_data(DataType(PolySignalSpotData))
self.subscribe_data(DataType(PolySignalPriceToBeatData))
self.subscribe_data(DataType(PolySignalMarketMetaData))
```

`MarketViewAssembler` consumes Nautilus cache + sidecar registries to build `MarketView`.

### 5. DecisionPolicyActor

Legacy scheduler currently mixes strategy evaluation, gate, consensus, arbiter, dedupe, and persistence. In the Nautilus runtime these become a separate policy actor.

Responsibilities:

1. Receive `AlphaDecision` events from strategy wrappers.
2. Apply market readiness and freshness constraints.
3. Apply per-strategy `FreshnessPolicy`.
4. Apply max entry price, confidence, spread, GTD expiry, dedupe, and rate limits.
5. Apply cross-strategy conflict suppression using existing `SignalArbiter` semantics.
6. Apply consensus if still enabled.
7. Emit exactly one outcome:
   - approved order intent back to the originating strategy wrapper;
   - rejected decision event to ObservabilityActor and strategy core if needed;
   - consensus decision event if a consensus signal is formed.

Policy output must be order-oriented, not Telegram-oriented.

```python
@dataclass(frozen=True, slots=True)
class ApprovedDecision:
    decision: AlphaDecision
    order_spec: NautilusOrderSpec
    policy_trace: tuple[str, ...]
```

```python
@dataclass(frozen=True, slots=True)
class RejectedDecision:
    decision: AlphaDecision
    reason_code: str
    detail: str
    policy_trace: tuple[str, ...]
```

### 6. Order and execution mapping

Legacy `OrderIntent` maps to Nautilus order instructions:

| PolySignal intent | Nautilus target | Notes |
|---|---|---|
| `TAKER_FAK` | IOC/FAK buy order against best ask | Must reject if depth cannot satisfy configured shares. |
| `TAKER_FOK` | FOK buy order | Must fill completely or reject. |
| `PASSIVE_GTD` | Limit GTD order | Expiry maps to Nautilus time-in-force / expire time. |
| no intent | default paper-safe taker order | Preserve current fixed stake / sizing semantics through `NautilusOrderSpec`. |

`OrderIntentSpec` must be extended or wrapped to include quantity sizing:

```python
@dataclass(frozen=True, slots=True)
class NautilusOrderSpec:
    instrument_id: str
    side: Side
    price: float
    quantity: float
    intent: OrderIntent
    expiry_seconds: int | None
    pair_id: str | None
    reduce_only: bool
    hedge_leg: bool
    tags: Mapping[str, str]
```

Sizing source of truth:

- Strategy-specific sizing metrics remain in alpha core when they are part of alpha semantics, e.g. LateConsensus contract tiers.
- Portfolio/risk caps move to Nautilus RiskEngine / DecisionPolicyActor.
- Default fixed-stake sizing maps from `settings.paper_trading.fixed_stake_usdc` when a core emits price but no explicit quantity.

### 7. Paper execution

Default runtime must be paper-safe.

Preferred target:

- Nautilus `TradingNode` with Polymarket data client.
- No live Polymarket execution client.
- Paper/sandbox execution via Nautilus-compatible execution engine or sandbox adapter.
- Account type cash, OMS type netting for per-instrument positions unless a specific strategy requires hedging semantics.

Spec acceptance requires proving one of these supported paths in code:

1. Nautilus sandbox execution can run live data + simulated fills for Polymarket `BinaryOption` instruments, or
2. A minimal Nautilus `ExecutionClient` implementation for paper-only Polymarket binary options is implemented under `nautilus_runtime/execution.py`, with no credentials, no network order submission, and all fills driven by Nautilus market data/cache.

If path 2 is required, it is not a second scheduler. It is an execution client plugged into Nautilus `ExecutionEngine`.

### 8. Settlement and exits

Legacy `PaperExitEngine` and `PaperSettlementEngine` cannot stay as scheduler-owned execution. Their logic splits:

#### Exit logic

- Strategy-specific exits in metrics (`tp_sl_tp_prob`, `tp_sl_stop_prob`, `flip_stop_price`, `stop_loss_config`) become order/position management in strategy cores or a `PositionPolicyActor`.
- Global paper exits (`take_profit_price`, `stop_loss_price`, `max_hold_time_sec`) become `PositionPolicyActor` rules operating on Nautilus positions and current orderbook bids.

#### Settlement logic

Polymarket final resolution remains a PolySignal responsibility because current resolver is already 3-source and domain-specific:

- CTF chain source.
- Gamma source.
- WS hint source.

`SettlementActor` must:

1. Subscribe to Nautilus position/account state.
2. Periodically resolve markets with open positions.
3. Emit close/settle commands through Nautilus order/position APIs or paper execution client.
4. Preserve existing fallback behavior:
   - resolver unknown/error with local `CANCELLED` / `RESOLVED` market status still settles/refunds.

### 9. Observability, storage, Telegram, dashboard

Create `ObservabilityActor` to replace scheduler-side write/publish calls.

Inputs:

- approved/rejected decisions from `DecisionPolicyActor`.
- order events from Nautilus execution.
- fill events.
- position events.
- settlement events.
- health events.
- sidecar feed state.

Outputs:

- SQLite tables currently used by dashboard:
  - `signals`
  - `rejected_signals`
  - `paper_orders`
  - `paper_fills`
  - `paper_positions`
  - `paper_trade_results`
  - `paper_wallet_snapshots`
  - `system_events`
  - `anchor_prices`
  - `strategy_status`
  - `telegram_publishes`
- JSONL streams for audit.
- Telegram signal/paper/daily messages through existing `TelegramPublisher`.
- Interactive Telegram bot service, with runtime control wired to Nautilus strategy/policy actors rather than `SignalPipeline`.
- `/health` endpoint with components renamed to Nautilus ownership:
  - `nautilus_node`
  - `polymarket_data_client`
  - `sidecar_spot_feed`
  - `sidecar_ptb_feed`
  - `decision_policy`
  - `paper_execution`
  - `settlement_actor`
  - `observability_actor`

The dashboard should not know whether events came from legacy scheduler or Nautilus, but health component names must make the new runtime explicit.

### 10. State persistence

Use Nautilus `Strategy.on_save() -> dict[str, bytes]` and `on_load(state: dict[str, bytes]) -> None` for strategy state.

Rules:

- Key format: `polysignal.<strategy_name>.state.v<version>`.
- Payload format: UTF-8 JSON bytes.
- No pickle.
- Enums stored by `.value`.
- Datetimes stored as UTC ISO strings.
- Deques stored as lists.
- Sets stored as sorted lists.
- Dict keys use strings.
- Unknown same-strategy future version fails closed.
- Missing state returns cold-start payload with a migration reason.
- State schema must be tested per strategy before that strategy can run in Nautilus production mode.

State split:

- Strategy alpha state: Nautilus strategy save/load.
- Market metadata registry: rebuildable from discovery + instrument provider, but persisted for restart latency.
- Observability DB: SQLite/JSONL as today.
- Policy dedupe/rate limit state: `DecisionPolicyActor` save/load with the same versioned schema rules.

## Migration Waves

This is all one full-runtime migration program, but implementation must be staged so each wave has a working verification boundary.

### Wave 0 — Platform and runtime boundary proof

Deliver:

- Python 3.12+ Nautilus runtime environment definition.
- Default Python 3.11 app still imports and tests without Nautilus.
- Confirm `nautilus_trader[polymarket]` on Linux ARM64 / glibc >= 2.35.
- Confirm `import nautilus_trader.adapters.polymarket` in Nautilus env.
- Confirm default Docker image does not install Nautilus unless explicitly building Nautilus runtime target.

Acceptance:

- Dependency boundary tests pass.
- Safety boundary tests pass.
- A small `TradingNode` can be constructed in a test-only process without Polymarket live execution config.

### Wave 1 — Core data model and custom data bus

Deliver:

- `PolySignalSpotData`, `PolySignalPriceToBeatData`, `PolySignalMarketMetaData` custom data types.
- Serializable registration for those data types.
- `SidecarDataActor` publishing spot/PTB/market metadata.
- `MarketViewAssembler` reading Nautilus cache + sidecar registry.
- `PolymarketMarketRegistry` hydration from current market discovery and Nautilus instrument provider.

Acceptance:

- Missing book leg returns no view.
- Missing spot/PTB returns no view for strategies requiring it.
- Freshness and source metrics match current `MarketSnapshotBuilder` semantics.
- Market pair lookup by condition and token works for all active binary markets.

### Wave 2 — Extract all alpha cores with legacy equivalence tests

Extract cores in this order:

1. `SkewMeanReversionAlphaCore`
2. `BinaryMomentumAlphaCore`
3. `FibonacciAlphaCore`
4. `OneCentBuyAlphaCore`
5. `NinetyNineCentSniperAlphaCore`
6. `LateConsensusAlphaCore`
7. `VWAPMomentumAlphaCore`
8. `DumpHedgeAlphaCore`
9. `MidPriceSizingAlphaCore`
10. `PreOrderMarketAlphaCore`
11. `LowSideDualReversionAlphaCore`
12. `CrossMarketAlphaCore`

Keep `PTBDiffAlphaCore` as the baseline.

Acceptance per strategy:

- Same semantic input produces equivalent alpha output to legacy strategy.
- Equivalence fields:
  - side
  - confidence
  - max_entry_price
  - reason_codes
  - metrics
  - order_intent
  - expiry_seconds
  - pair_id
  - hedge_leg
- Exclude host-generated fields:
  - signal_id
  - snapshot_id/view_id
  - created_at
  - dedupe_key unless the strategy explicitly owns a suffix.
- Mutable state only changes on the same logical event as legacy behavior, and never earlier than gate/order acceptance where legacy previously depended on `notify_signal_accepted`.

### Wave 3 — Nautilus strategy wrappers for all single-market strategies

Deliver wrappers for 12 single-market strategies:

- `ptb_diff`
- `skew_mean_reversion`
- `binary_momentum`
- `fibonacci_bot`
- `one_cent_buy`
- `ninety_nine_cent_sniper`
- `late_consensus`
- `vwap_momentum`
- `dump_hedge`
- `mid_price_sizing`
- `pre_order_market`
- `low_side_dual_reversion`

Acceptance:

- Each wrapper subscribes to required data.
- Each wrapper builds `MarketView` and invokes its core.
- Each wrapper routes decisions to `DecisionPolicyActor`.
- Each wrapper handles order/fill/cancel/expiry events needed by its core.
- Each stateful wrapper round-trips state through `on_save/on_load`.
- VWAP follow-up hedge is submitted directly from fill event, not through a global queue.

### Wave 4 — Cross-market strategy support

Deliver:

- `MarketGroupView` assembly.
- Relation registry for `CrossMarketBot`.
- Cross-market skew threshold equivalent to current `max_source_skew_ms` logic.
- Basket order coordination with pair/group IDs.
- Leg failure propagation into `CrossMarketAlphaCore`.

Acceptance:

- `CrossMarketAlphaCore.evaluate_group()` matches legacy `evaluate_group()` on controlled relation fixtures.
- Multi-leg baskets submit as linked orders with traceable relation IDs.
- Leg failure marks basket failed and prevents silent partial success.

### Wave 5 — DecisionPolicyActor parity

Deliver:

- Freshness gate.
- Spread gate.
- Max entry gate.
- Confidence gate.
- GTD expiry gate.
- Dedupe gate.
- Rate limit gate.
- Conflict arbiter.
- Consensus signal policy.
- Strategy manual disable/dependency disable support.

Acceptance:

- Current gate first-failure ordering is preserved where the same rule exists.
- Rejection reason codes preserve existing dashboard/JSONL semantics.
- Strategy disable from Telegram affects Nautilus strategies/policy actor.
- Consensus no longer mutates paper wallet directly; it emits an order decision only after policy approval.

### Wave 6 — Paper execution and position policy

Deliver:

- Nautilus paper execution path selected and proven.
- `NautilusOrderSpec` mapping from every supported `OrderIntent`.
- Fixed stake and strategy sizing integration.
- PositionPolicyActor for TP/SL/max hold where not owned by strategy core.
- SettlementActor using current three-source resolver.

Acceptance:

- TAKER_FAK/FOK/PASSIVE_GTD behavior is covered by tests.
- Exposure and cash caps are enforced before order submission or by Nautilus risk engine.
- Fill/cancel/expiry events update the correct alpha core state.
- Settlement fallback for `CANCELLED` / `RESOLVED` local market status remains intact when resolver returns unknown/error.

### Wave 7 — Observability and operator surfaces

Deliver:

- ObservabilityActor writing existing SQLite/JSONL tables.
- TelegramPublisher integration.
- TelegramBotService control integration.
- Dashboard health endpoint with Nautilus component names.
- Daily report generation from Nautilus position/fill events.

Acceptance:

- Existing dashboard can read current tables.
- `/health?fresh=<cachebuster>` shows Nautilus runtime components.
- Telegram slash commands respond with the immediate placeholder/edit behavior already fixed in current runtime.
- Startup/shutdown notifications still work in Docker with SIGTERM handling.

### Wave 8 — Cutover and legacy retirement

Deliver:

- New entry point: `polysignal-nautilus`.
- Docker target for Nautilus runtime.
- Production config flag selecting Nautilus runtime as default.
- Legacy scheduler entry point marked test-only or archived.
- Remove long-term calls to `strategy.evaluate(snapshot)` from production runtime.
- Keep legacy wrappers only for equivalence tests until final cleanup.

Acceptance:

- Formal runtime starts through Nautilus entry point.
- Runtime no longer constructs `PaperSimulator`, `PaperWallet`, or strategy schedule in `PolySignalScheduler` for production.
- No production health component reports legacy `signal_pipeline` as active executor.
- Full migration tests pass.
- Docker rebuild and health verification prove the live service is using Nautilus runtime.

## Configuration Design

Add explicit runtime config:

```yaml
runtime:
  engine: nautilus
  nautilus:
    trader_id: PolySignal-Nautilus-001
    python: "3.12"
    execution_mode: paper_sandbox
    allow_live_polymarket_execution: false
    data_clients:
      polymarket:
        enabled: true
        ws_max_subscriptions_per_connection: 200
    sidecar:
      spot_source: polymarket_rtds
      price_to_beat_source: anchor_or_gamma
    decision_policy:
      preserve_gate_first_failure_order: true
      consensus_enabled: true
      arbiter_policy: suppress_ambiguous
```

Safety rule: `allow_live_polymarket_execution: true` is invalid in the default app/Docker target. It requires a separate approved live-execution target not covered by this spec.

## Testing Strategy

### Unit tests

- Alpha core equivalence per strategy.
- State codec per strategy.
- MarketViewAssembler edge cases.
- Custom data serialization and subscription.
- DecisionPolicyActor first-failure ordering.
- OrderIntent to NautilusOrderSpec mapping.

### Integration tests

- TradingNode construction without live execution client.
- Polymarket data client registration without execution client registration.
- Sidecar data publication to strategy subscription.
- One stateless strategy end-to-end: PTBDiff.
- One stateful no-callback strategy end-to-end: BinaryMomentum or OneCentBuy.
- One callback strategy end-to-end: VWAPMomentum.
- CrossMarketBot relation end-to-end.

### Runtime smoke tests

- Docker Nautilus target starts.
- `/health?fresh=<timestamp>` shows `nautilus_node` and `polymarket_data_client`.
- No `PolymarketExecutionClient` safety finding in default runtime.
- Telegram `/status` returns Nautilus runtime status.
- SQLite tables receive signal/order/fill/health rows.

### Non-regression tests

- Legacy strategy wrappers remain equivalent until retired.
- Current production config still enables exactly the intended strategies during staged cutover.
- Default Python 3.11 test suite still imports `polysignal_lab` without Nautilus installed.

## Acceptance Criteria

### Architecture

- NautilusTrader is the production strategy execution owner.
- `PolySignalScheduler` no longer owns strategy evaluation, paper order simulation, or fill callbacks in production runtime.
- All 13 strategies have `AlphaCore` or `GroupAlphaCore` implementations.
- All 13 strategies have Nautilus wrappers or explicit decommission decisions. Under this spec, no current strategy is decommissioned.

### Safety

- Default runtime has no live Polymarket execution client.
- Safety scanner blocks forbidden live execution symbols in default runtime paths.
- Presence of `POLYMARKET_*` environment variables cannot activate live execution.
- Credential/allowance helpers are absent from default runtime.

### Behavior

- Strategy outputs match legacy alpha semantics on equivalence fixtures.
- Stateful strategies mutate state only on correct Nautilus order/position events.
- Paper fills/cancels/expiry feed back into alpha cores through event handlers.
- Settlement cancellation/resolution fallback remains intact.

### Operations

- Docker rebuild is required and verified before formal runtime use.
- `/health` identifies Nautilus runtime components.
- Telegram operator UX remains compatible with current interactive bot behavior.
- SQLite/JSONL continuity is preserved for dashboard and historical analysis.

## Risks and Mitigations

### Risk: Nautilus paper execution path may not support live-data sandbox for Polymarket exactly as needed

Mitigation: Wave 6 first proves sandbox/emulated path. If unsupported, implement a minimal paper-only Nautilus execution client. This remains inside Nautilus ExecutionEngine, not the legacy scheduler.

### Risk: Alpha extraction changes state mutation timing

Mitigation: Every stateful strategy gets red/green tests around mutation timing. Pre-commit mutations in `evaluate()` must move to acceptance/fill events where legacy behavior depended on scheduler callbacks.

### Risk: Sidecar data becomes hidden coupling

Mitigation: Sidecar uses explicit Nautilus custom data types and `DataType` subscriptions. `MarketViewAssembler` returns no view when required sidecar data is missing.

### Risk: Cross-strategy policy becomes a scheduler clone

Mitigation: `DecisionPolicyActor` accepts and emits typed decision events only. It does not build snapshots, execute wallets, publish Telegram directly, or own market data.

### Risk: Long-lived dual runtime

Mitigation: Wave 8 cutover removes production calls to legacy strategy scheduling and paper simulator. Legacy wrappers remain only for tests until behavior parity is proven and then are removed or archived.

### Risk: Platform friction on ARM64 / Python version

Mitigation: Wave 0 validates `nautilus_trader[polymarket]` in a Python 3.12+ environment on the target ARM64/glibc platform before runtime work proceeds.

## References

- `docs/superpowers/specs/2026-06-24-15-nautilus-strategy-bridge-design.md` — existing bridge design and Wave 0-1 foundation.
- `src/polysignal_lab/app/scheduler.py` — current component wiring and legacy trading component initialization.
- `src/polysignal_lab/app/scheduler_processing.py` — current evaluate/gate/process/fill callback flow.
- `src/polysignal_lab/alpha/types.py` — current `MarketView`, `AlphaDecision`, `OrderIntentSpec`, `AlphaCore` seam.
- `src/polysignal_lab/nautilus_bridge/` — current bridge utilities.
- `src/polysignal_lab/strategies/factory.py` — 13 registered strategy implementations.
- NautilusTrader nightly docs: custom `Data` / `DataType` publish-subscribe, `TradingNodeConfig`, Polymarket data and execution clients.
- NautilusTrader Polymarket docs: `PolymarketDataClient`, `PolymarketExecutionClient`, `PolymarketLiveDataClientFactory`, `PolymarketLiveExecClientFactory`, `BinaryOption` instruments, and credential-sensitive execution config.

## Final Recommendation

Implement this as a dedicated Nautilus runtime migration branch in a fresh worktree. Do not continue expanding `PolySignalScheduler` except for correctness fixes needed to keep the existing production bot stable during migration.

The right sequence is:

1. Prove Nautilus platform/runtime boundary.
2. Build custom data + view assembly.
3. Extract all alpha cores with legacy equivalence tests.
4. Wrap all strategies as Nautilus strategies.
5. Move gate/consensus/arbiter into `DecisionPolicyActor`.
6. Prove paper execution and settlement in Nautilus.
7. Move observability surfaces.
8. Cut production runtime to Nautilus and retire legacy scheduler execution.
