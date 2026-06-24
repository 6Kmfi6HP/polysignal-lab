# 11 策略模拟交易 Parity 修复设计

**Status:** Draft
**Scope:** 一个独立的架构修复规格。先完成设计审阅，再按独立 worktree 执行实现；不要与既有 01-10 规格合并开发，也不要再拆成多个新规格。
**Goal:** 在保持 PolySignal Lab read-only/paper lab 边界的前提下，吸收 `refs/poly-btc-martingale/`、Hummingbot paper trading、CCXT order model 等更成熟系统的执行不变量，修正当前策略模拟交易链路中的执行边界、资金预留、成交/PnL、数据就绪、结算来源与风控缺口；只借鉴不变量，不复制 ref 项目的 live/runtime 混杂架构。

## 背景依据

本规格来自 2026-06-24 对比审查：主 agent 与 4 个 subagents 对 `src/polysignal_lab/` 和 `refs/poly-btc-martingale/poly_btc_martingale/` 进行并行分析，重点关注 strategy pipeline、paper/simulated execution、risk boundary、market data lifecycle。

所有审查均先尝试 `mcp__fast_context_search`；本轮 fast-context 返回 `resource_exhausted`，因此使用 CodeGraph、targeted read/search 交叉验证。结论以当前仓库源码为准。

后续严谨审查补充结论：ref 项目在模拟交易真实性上有可借鉴的不变量，但其架构不是本项目应复制的模板。ref 存在明显积债信号：`ModeStore` 约 1,900 行、`TradeOrder` 40+ 字段、`sim_executor.py` 约 900 行、`trade_db.py` 约 4,000 行，并混合 live order、wallet routing、notification、zombie order、dashboard control 等语义。本规格只借鉴 paper realism 所需的不变量，不迁移 ref 的 god-object、global mutable config、live/sim 混合字段或 dashboard live-mode 控制面。

额外参考边界：

- Hummingbot paper trading：其文档把 paper 作为独立 `paper_trade_exchange` 配置，并用 `balance paper <asset> <amount>` 管理模拟余额；源码层 `ConnectorBase` 维护 account balances、available balances、in-flight orders 和 order events，`InFlightOrder` 使用 PENDING_CREATE/OPEN/PARTIALLY_FILLED/FILLED/CANCELED/FAILED 等小而稳定状态。本规格借鉴“paper connector 边界、模拟余额、available balance/in-flight order、事件化生命周期”，不引入真实交易凭证。
- CCXT unified order model：参考其 order/fill/accounting 的通用字段语义，保持 order lifecycle 小而稳定；不把外部 exchange id / client id / trade id 提前塞进本项目 paper domain。
- NautilusTrader Polymarket adapter：作为官方 Polymarket trading-engine 参考，借鉴 `BinaryOption` instrument、market BUY quote-notional 语义、GTC/GTD/FOK/FAK 映射、tick-size-change book epoch reset、runtime instrument auto-load/hydration retry、strict settlement inference、fee model 和 cache purge/housekeeping；不引入 `PolymarketExecutionClient`、私钥/API credential 配置或 Nautilus 全引擎。
- `docs/superpowers/specs/2026-06-24-10-unified-hftbacktest-design.md`：历史 tick 级 queue/latency/partial-fill 回测由 HftBacktest 负责；本规格只修复 forward paper runtime，不自研历史回测器。

与既有规格的关系：

- Spec 01/02/03 已覆盖部分 book reconciliation、strategy freshness、paper execution realism 基础设施；实现本规格时应扩展已合并组件，而不是新增第二套 gating / reconciliation / reporting 管线。
- Spec 10 继续负责历史 tick 级 queue/latency/partial-fill 回测；本规格只修复 forward paper runtime 在真实运行时的资金、成交、状态和结算不变量。

## 问题

当前 PolySignal Lab 已具备 `SignalGate`、`PaperSimulator`、`PaperWallet`、`PaperExecutionPreflight`、order intent、RESTING order tick、settlement/reporting 等基础能力，但模拟交易真实性仍存在系统性缺口：

1. **执行模式不是统一 side-effect boundary**：`app.mode` 存在但没有集中控制 publish、paper order、wallet mutation。
2. **缺少 durable pause/emergency-stop**：无法在运行时 fail-closed 地阻断新订单和 resting fill。
3. **RESTING paper orders 不预留资金**：`reserved_balance` 字段存在但 `can_afford()` 忽略，PASSIVE_GTD 可过度承诺现金。
4. **订单生命周期字段不够表达真实成交**：缺少 matched amount、fee、terminal timestamps/reason；但不需要复制 ref `TradeOrder` 的 live/wallet/notification 字段。
5. **PnL 和 reporting 不含 fee / matched amount**：settlement 直接使用 `position.stake_usdc`，无法表达 partial fills、fees、net PnL。
6. **strategy state 与实际 paper execution 闭环不足**：已有 accepted/rejected/fill/cancel callbacks，但 settlement/reporting 尚未稳定输出足够的 terminal event 供策略或报表使用。
7. **placement guard 分散**：head/tail window、entry price bounds、remain window 等过滤点应进入现有 preflight/processing 链路，不能新增第二套互相竞争的 guard。
8. **orderbook top-of-book telemetry 未修正 executable ladder**：`best_bid_ask` 只进入 telemetry，不更新/prune canonical `OrderBook`。
9. **缺少 current-slot two-sided book readiness gate**：策略评估和 paper fill 可在单侧 book fresh 时继续执行。
10. **active market lifecycle 未按 slot prune/reset**：registry 只 upsert，不清理过期 active markets 和旧 token books。
11. **PTB 与 settlement provenance 不够强**：local spot anchor 可优先于 official PTB；settlement 直接信任 `Market.resolved_outcome`，缺少来源记录与冲突保护。
12. **portfolio risk gate 不完整**：已有 cash/open count/market exposure/strategy exposure，但 pending reserved exposure 未纳入；drawdown/daily loss/consecutive loss 只在已有数据足够时实现，不能为了“完整风控”引入复杂 ledger。
13. **PASSIVE_GTD resting fill crossing 条件不真实**：当前 resting tick 以 token `best_bid >= limit_price` 判断 BUY order 可成交，真实 buy-side resting limit 只有在 executable ask `best_ask <= limit_price` 或等价成交事件出现时才应成交；否则会把“市场上已有更高 bid”误当成自己订单成交。
14. **immediate fill 可能与钱包 mutation 脱节**：当前 fill result 已生成后，wallet 资金不足路径可被静默跳过，导致 `FILLED` order/position 与现金扣减不一致。
15. **RESTING order 与 reservation 缺少重启恢复语义**：PASSIVE_GTD 若持久化或恢复不完整，scheduler 重启后可能丢失 in-flight orders 或让 `reserved_balance` 与实际 resting orders 不一致。

## 非目标

- 不引入真实交易、私钥、签名、authenticated CLOB client、wallet routing 或 live executor。
- 不复制 ref 项目的 dashboard live-mode 操作面板；本项目仍保持 read-only dashboard，最多增加 paper pause/emergency control 的只写控制面需要单独审批。
- 不复制 ref 的 `ModeStore`、`TradeOrder`、`DualModeExecutor`、wallet pool、live order worker、global placement guard 或大而全 ledger。
- 不把 Hummingbot、CCXT、NautilusTrader、Backtrader、VectorBT 作为新 runtime 依赖；它们只作为模型边界参考。
- 不改变策略公式本身，不把 ref 策略直接迁移到 `src/polysignal_lab/strategies/`。
- 不实现历史回测器、queue model、latency model 或 market-impact model；历史精确回测由 Spec 10 / HftBacktest 负责。
- 不用 mock 替代真实数据路径；测试使用现有 domain objects 和 in-memory store/registry。

## 方案比较

### 方案 A：只修单点 bug

逐个修正 `reserved_balance`、fee、best_bid_ask 等明显问题。

- 优点：短期 diff 小。
- 缺点：执行边界、订单生命周期、strategy state、risk gate 仍分散；后续每加一个策略都会重新踩坑。
- 结论：拒绝。

### 方案 B：引入完整 ref live/runtime 架构

照搬 ref 的 `ModeStore`、`TradeOrder`、`DualModeExecutor`、wallet pool、live order worker。

- 优点：最大程度复用 ref 概念。
- 缺点：本项目明确是 read-only/paper lab；引入 live wallet/executor 会扩大安全面；ref 的 live/sim/order/notification 混合模型会把 28 万行项目的积债搬进 1.4 万行项目。
- 结论：拒绝。

### 方案 C：建立轻量 paper-only realism runtime（推荐）

保留本项目 read-only/paper 边界，只复制模拟交易不变量：mode side-effect boundary、pause/emergency stop、reservation-aware wallet、matched amount/fee based PnL、slot book readiness、centralized preflight placement checks、settlement provenance、reserved-exposure-aware risk gate。

- 优点：修复关键 correctness gaps，不引入 live trading；与现有 `PaperSimulator`、`PaperWallet`、`PaperExecutionPreflight`、`SignalGate`、SQLite/reporting 可渐进集成。
- 缺点：仍需要一次性升级多个 domain model 和 storage schema，测试覆盖必须完整。
- 结论：采用。实施仍属于同一个 spec，只在 rollout 内部分工作流交付，不拆出新规格。

## 目标行为

1. `app.mode` 成为唯一 publish/paper side-effect boundary：
   - `signal_only`：允许 signal storage/publish，禁止 paper order/fill/wallet mutation。
   - `paper_only`：允许 paper order/fill/report，禁止 Telegram signal publish。
   - `signal_plus_paper`：允许两者。
2. `paper_trading.pause_state` 或等价 runtime control 在 new paper order 和 resting fill tick 前 fail-closed 检查。
3. RESTING order 被接受时立即 reserve stake；fill/cancel/expiry/reject 时释放或转换 reserve。
4. `PaperOrder` / `PaperFill` / `PaperPosition` / `PaperTradeResult` 显式保存 matched amount、fee、terminal timestamps/reason；不新增 live-only 字段。
5. Paper PnL 使用 matched amount 和 fee 计算：`gross_pnl_usdc = settlement_value - matched_amount_usdc`，`net_pnl_usdc = gross_pnl_usdc - fee_usdc`。
6. Strategy state 不因 gate rejected / placement rejected 消耗；accepted order、actual fill、cancel 继续通过现有 callbacks 推进，settlement terminal event 先进入 reporting/domain record，只有真实策略需求出现时再加新 callback。
7. Placement guard 并入 `PaperExecutionPreflight` 或 `process_signal()` 最早 paper side-effect 前，不新增全局 mutable guard。
8. `best_bid_ask` 事件必须更新/prune canonical `OrderBook`，或者标记该 token book stale 并触发 reseed。
9. 策略评估和 paper fill 之前必须存在 current-slot market-level readiness：UP/DOWN 两侧 token、fresh snapshots/best asks、WS/REST source freshness。
10. Market registry 刷新时 prune expired active markets，并在 slot transition 清理旧 token books。
11. PTB/settlement 使用 official source 优先，并在 result/report 中保留 provenance；多源冲突才进入 ambiguous，不为单一来源提前设计复杂仲裁器。
12. Risk gate 覆盖 open + reserved exposure；drawdown、daily realized loss、consecutive losses 只有在现有 wallet/reporting 数据能稳定计算时才启用。
13. Immediate taker fill 在 wallet `available_cash` 不足时必须 reject，并持久化 `PAPER_WALLET_INSUFFICIENT_CASH`；不得产生 fill/position 后再跳过 wallet mutation。
14. PASSIVE_GTD BUY fill 条件使用 executable ask crossing：只有 current-slot book ready 且 `best_ask <= limit_price` 时才可成交；`best_bid >= limit_price` 不能作为 BUY resting order 的成交条件。
15. RESTING orders 与 reservations 在 scheduler 重启后必须可恢复或可重算：恢复后 `reserved_balance == sum(active_resting_order.unmatched_amount_usdc)`，不允许现金永久锁定或重复释放。

## 设计概览

```mermaid
flowchart LR
    Snapshot[MarketSnapshot + readiness metrics] --> Strategy[Strategy schedule]
    Strategy --> Gate[SignalGate + Arbiter]
    Gate --> Preflight[PaperExecutionPreflight + placement checks]
    Preflight --> Boundary[Mode/Pause boundary]
    Boundary --> Order[Small paper lifecycle record]
    Order --> Reserve[PaperWallet reservation]
    Reserve --> Fill[PaperFill / RESTING tick]
    Fill --> Position[PaperPosition]
    Position --> Settlement[Settlement provenance]
    Settlement --> PnL[matched amount + fee PnL]
    PnL --> Report[DailyReport + Dashboard]
```

核心原则：所有 paper side effects 都必须通过 mode/pause boundary；所有资金占用都必须通过 `PaperWallet` reservation；所有成交/PnL 都必须从 typed lifecycle fields 派生，不从 ad-hoc metrics JSON 推断；新增字段和组件只服务当前 paper realism，不为未来 live trading 预留架构。

## Proposed components

### Mode / pause boundary

优先放在现有 `src/polysignal_lab/app/scheduler_processing.py::process_signal()` 与 resting tick 调用处；只有当重复逻辑超过两个调用点时，才新增 `src/polysignal_lab/app/services/paper_execution_boundary.py`。

最小接口：

```python
def allow_signal_publish(settings: Settings) -> bool: ...
def allow_new_paper_order(settings: Settings, pause: PaperPauseState | None) -> tuple[bool, str | None]: ...
def allow_resting_fill_tick(settings: Settings, pause: PaperPauseState | None) -> tuple[bool, str | None]: ...
```

规则：

- `allow_signal_publish()` 只看 `settings.app.mode` 和 `settings.telegram.send_signals`。
- `allow_new_paper_order()` 同时检查 `settings.app.mode`、`settings.paper_trading.enabled`、pause/emergency state。
- `allow_resting_fill_tick()` 与 new order 同样检查 pause/emergency；settlement/reporting 不被 pause 阻断，因为它们是 terminal accounting/read-side work。
- 若无法读取 pause state，默认 fail-closed 并记录 `PAPER_PAUSE_STATE_UNREADABLE`，避免“控制面损坏时继续成交”。

### Paper pause state

最小实现优先使用本地 JSON state file，避免引入 dashboard write API。

```python
class PaperPauseState(BaseModel):
    paused: bool = False
    reason: str = ""
    actor: str = ""
    updated_at: datetime | None = None
    emergency: bool = False
```

第一版只读取 `state/paper_pause.json`。写入控制面另起审批；本规格只要求 runtime 能 fail-closed 地读取并阻断 new paper order / resting fill。不存在 pause 文件时视为未暂停；文件存在但 JSON 无效时视为暂停。

### `PaperWallet` reservation contract

修改 `src/polysignal_lab/paper/wallet.py`。

新增不变量：

- `available_cash = cash_balance - reserved_balance`。
- `can_afford(stake)` 使用 `available_cash`。
- `reserve(order_id, amount)` 增加 `reserved_balance` 并记录 `reservations[order_id] = amount`；余额不足抛 `PAPER_WALLET_INSUFFICIENT_CASH`。
- `release(order_id)` 幂等释放；未知 `order_id` 返回 `0.0`。
- `apply_reserved_fill(order_id, position)` 将 reserve 转为 spent cash，并写入 open position；同一 `order_id` 重复调用不得重复扣款。
- `apply_fill(position)` 仅用于 immediate taker fills；它也必须检查 `available_cash`。

Reservation key 第一版使用 `paper_order_id`。不引入 deterministic `client_order_id`；没有外部交易系统对账需求时，该字段是 YAGNI。
Reservation 第一版依赖当前 scheduler 单进程、单 event-loop 的 paper side-effect 顺序；如果后续把 order acceptance / resting tick 改成并发消费，`reserve/release/apply_reserved_fill` 必须加同一把锁或事务边界。重启恢复时不要盲信旧 wallet snapshot 的 `reserved_balance`：要么从持久化 RESTING orders 重建 reservations，要么在启动时把 `reserved_balance` 重算为 active resting orders 的 unmatched amount 总和。

### Typed paper lifecycle fields

修改：

- `src/polysignal_lab/domain/paper_order.py`
- `src/polysignal_lab/domain/paper_position.py`
- `src/polysignal_lab/domain/paper_result.py`
- `src/polysignal_lab/storage/sqlite_schema.py`
- `src/polysignal_lab/storage/sqlite_store.py`

保留现有 `stake_usdc` 作为 requested/display stake，不新增 `requested_stake_usdc` alias。新增字段只覆盖真实需要：

```python
matched_amount_usdc: float = 0.0
unmatched_amount_usdc: float = 0.0
fee_usdc: float = 0.0
filled_at: datetime | None = None
cancelled_at: datetime | None = None
expires_at: datetime | None = None
terminal_reason: str | None = None
```

字段归属：

- `PaperOrder`: request intent、matched/unmatched amount、terminal timestamps/reason。
- `PaperFill`: 已有 `fill_price`、`stake_usdc`、`shares`；新增 `fee_usdc`，必要时新增 `matched_amount_usdc` 作为 `stake_usdc` 的兼容别名。
- `PaperPosition`: `stake_usdc` 表示实际 matched amount，不再表示 requested stake。
- `PaperTradeResult`: 增加 `gross_pnl_usdc`、`fee_usdc`、`net_pnl_usdc`；兼容字段 `pnl_usdc` 在迁移后等于 net PnL。

不新增 `execution_price`、`fee_rate_bps`、`trader_side`、`fill_origin`、`client_order_id`，除非实现时发现现有 `PaperFill.fill_price` 或 config 无法表达所需信息。当前项目没有 live CLOB order、maker rebate、trade IDs 或外部 idempotency 对账，这些字段不应提前进入 domain model。

### Nautilus-derived Polymarket invariants

本规格从 NautilusTrader 只吸收 Polymarket 专属不变量：

- Instrument 语义：YES/NO outcome token 是 binary option；本项目继续使用现有 domain model，但 snapshot/order 字段不得把 outcome token 当普通 spot asset。
- Quantity 语义：market BUY 的 size 是 quote notional/pUSD，LIMIT 与 market SELL 才是 outcome-token shares；当前 `stake_usdc` 对 BUY paper order 表示 notional，`shares` 只能由 price/fill 计算得出。
- TIF 语义：本项目现有 FAK/FOK/PASSIVE_GTD 与 Polymarket 的 IOC/FAK、FOK、GTD/GTC resting limit 对齐；不新增 stop、bracket、OCO、reduce-only 等 Polymarket 不支持的 order types。
- Book epoch：`tick_size_change` 或等价 tick-grid 变化必须 drop local executable book，等待 fresh snapshot；snapshot 前的 incremental delta 不能参与 strategy snapshot 或 paper fill。
- Instrument hydration：Gamma 已 active 但 CLOB token/book 未就绪时，只允许 bounded retry / skipped readiness，不允许凭空生成 token/book。

这些是不变量，不是依赖边界：不安装 NautilusTrader，不调用 execution client，不读取或配置私钥/API credentials。

### Order quantity semantics

保持当前 domain 字段最少化：

- `PaperOrder.stake_usdc`：requested quote notional for BUY-style paper intents。
- `PaperFill.shares`：实际 matched outcome-token shares，必须由 fill price 与 matched notional 计算。
- `PaperPosition.stake_usdc`：实际 matched notional；不要在 position 里保存 requested-but-unfilled stake。
- RESTING LIMIT/PASSIVE_GTD 若后续需要 sell-side 模拟，再显式增加 side-specific quantity 规则；本规格不为未实现 sell flow 预留字段。

市场 BUY quote-notional 规则必须进入 fee/PnL 测试，避免把 `$10` 误解释成 `10 shares`。

### Tick-size and hydration handling

`best_bid_ask` repair 之外，book lifecycle 还必须处理两个 Polymarket 专属状态：

- tick-size/grid change：mark token book stale, clear executable ladder, wait for full snapshot/reseed。
- CLOB hydration miss：market metadata 存在但 token ID 或 book snapshot 缺失时，记录 readiness reason（例如 `CLOB_HYDRATION_PENDING`）并跳过策略/成交；可以重试，但不能用旧 slot book 或 telemetry 填补。

这两个状态进入 market-level readiness；不新增独立 book manager。

### Fee calculation

新增 `src/polysignal_lab/paper/fees.py`，使用模块级函数，不建只有一个方法的 class。

```python
def compute_polymarket_binary_taker_fee_usdc(
    *,
    shares: float,
    price: float,
    fee_rate: float,
) -> float: ...
```

默认：

- 当前 paper runtime 首先只实现 taker fee；maker fee 先保持 `0.0`，直到本项目真实模拟 maker queue/rebate。
- Polymarket 官方费用文档给出的 binary fee 公式是 `shares * fee_rate * price * (1 - price)`，费用以 USDC 计，match time 计算并 round 到 5 位小数；不要继续沿用 ref 中未核对的平方项公式。
- `fee_rate` 是 fraction，不是 bps。配置字段使用 `paper_trading.taker_fee_rate: float`；若以后确实需要 bps，再单独命名 `taker_fee_rate_bps`，不能混用。
- 第一版默认值必须显式来自配置，并记录来源日期。若选择跟随当前 Polymarket fee schedule，2026-06-24 官方文档中 Crypto category taker fee rate 为 `0.07`；更严谨实现应在 market metadata / CLOB `getClobMarketInfo(conditionID)` 的 fee params 可用时优先使用 per-market `fd.r` / fee schedule。历史 ref 示例 `0.25` 只能作为测试 scale guard，不能作为默认值。

### Placement checks in existing preflight

不新增全局 `PaperPlacementGuard`。扩展 `src/polysignal_lab/paper/preflight.py::PaperExecutionPreflight` 或在 `process_signal()` 中 paper side-effect 前增加一次纯函数检查。

配置加入 `PaperTradingConfig`：

```python
placement_guard_enabled: bool = True
tail_seconds: int = 10
head_seconds: int = 3
entry_min_price: float = 0.20
entry_max_price: float = 0.80
enforce_remain_window: bool = False
remain_min_sec: int = 60
remain_max_sec: int = 240
```

失败时写 `RejectedSignal` 或 rejected `PaperOrder`，reason code 使用 `PAPER_PLACEMENT_HEAD_WINDOW`、`PAPER_PLACEMENT_TAIL_WINDOW`、`PAPER_ENTRY_PRICE_OUT_OF_BOUNDS`、`PAPER_REMAIN_WINDOW_OUT_OF_BOUNDS`。失败记录不能进入 `PaperSimulator`，也不能触发 strategy fill/cancel callback。

### Market-level readiness

优先扩展 `src/polysignal_lab/data/state.py` 与 `src/polysignal_lab/data/market_snapshot.py` 的 metrics/stable fields；只有多个调用点需要强类型对象时，才新增 dataclass。

最小语义：

```python
book_ready: bool
book_readiness_reason: str | None
up_lag_ms: int | None
down_lag_ms: int | None
```

策略评估前若 `book_ready=False`，普通 data-dependent strategies 不执行并记录 skipped/rejected reason。`PASSIVE_GTD` 的 existing resting tick 也必须检查 readiness，避免 stale fill。

### `best_bid_ask` canonical book repair

修改 `src/polysignal_lab/data/polymarket_clob_ws.py` 和 `OrderBookRegistry`：

- `best_bid_ask` 到达时，如果 canonical book 存在：
  - 更新 book `received_at`；
  - 删除 asks 中 `price < best_ask` 的 stale levels；
  - 删除 bids 中 `price > best_bid` 的 stale levels；
  - 必要时插入/更新 best level 的 top-of-book marker 仅在 size 可知时进行；无 size 时只 prune，不凭空造 depth。
- 如果 canonical book 不存在：mark stale/reseed，而不是让 telemetry 参与 fill。

### Market registry pruning

修改 `MarketRegistry.upsert_many()` 或新增 `replace_active_set()`：

- 本轮发现 active set 后，旧 active market 若 `market_id` 不在 active set，标记 `status=EXPIRED` 或从 active view 排除。
- `active()` 必须同时检查 `status == ACTIVE` 与时间窗口；`start_ts is None` 视为已开始，`end_ts is None` 视为未知结束但不能因此剔除，否则 Gamma 字段缺失会误杀可交易市场。
- slot transition 时旧 token book mark stale，避免旧 ladder 被新 slot 复用。

### Settlement provenance

优先扩展 `src/polysignal_lab/paper/settlement.py`，不新增复杂 resolver class，除非第二个 settlement source 上线。

最小模型：

```python
class SettlementProvenance(BaseModel):
    status: Literal["verified", "provisional", "unresolved", "ambiguous"]
    source: str
    price_to_beat: float | None = None
    final_price: float | None = None
    conflict_reason: str | None = None
```

规则：
- official PTB / official resolved outcome 优先于 local spot anchor。
- 优先使用 Gamma strict binary result：同一 condition 必须 closed、exactly two token IDs、exactly two outcomes，且 outcome/prices shape 能唯一推出 winner。
- Gamma 无严格结果时才允许 CLOB `GET /markets/{condition_id}` / `tokens[].winner` fallback。
- 单一 official source 有 outcome 时 `verified`；只有 local/derived source 时 `provisional`；无可用 source 时 `unresolved`。
- `CANCELLED` / void market 是官方 terminal state：标记 `verified` 或 `provisional` 时必须关闭 position 为 VOID，并记录 `source`，不能落入 ambiguous/unresolved 后永久占用风险。
- non-binary、malformed、两个来源 winner 冲突或无法唯一推出 winner 时标记 `ambiguous`。
- Settlement engine 只在 `status in {"verified", "provisional"}` 且无 conflict 时关闭 position。`ambiguous/unresolved` 保持 open 或生成 UNKNOWN result，不释放/关闭 position。

### Portfolio risk extension

不新增大而全 risk engine。扩展现有 paper preflight / portfolio service：

- exposure 计算必须包含 open positions + reserved orders。
- `max_open_positions` 继续按 open filled positions 计算；RESTING pending order 单独进入 `reserved_exposure_usdc`。
- drawdown、daily realized loss、consecutive losses 只有在 `PaperWalletSnapshot` / daily report 已持久化足够字段后启用；否则配置默认 disabled，并在 health/report 中标记 `risk_history_ready=false`。

## Data flow changes

### Accepted signal path

1. Strategy emits `SignalCandidate`.
2. `SignalGate` accepts.
3. Placement checks run inside `PaperExecutionPreflight` / earliest `process_signal()` paper path.
4. Mode/pause boundary checks side-effect permission.
5. `PaperSimulator.build_paper_order()` creates small typed `PaperOrder` with request stake and timestamps.
6. Immediate intent 在 fill 前检查 `available_cash`；不足则 reject 并不生成 fill/position。Resting intent 接受时 reserve cash、持久化 RESTING order，并保存 unmatched amount 供重启恢复。
7. Fills update wallet, position, lifecycle fields, storage, reports, and existing strategy fill/cancel callbacks.

### Resting order tick path

1. Scheduler calls resting tick only if mode/pause boundary allows.
2. Tick checks market-level readiness for both sides.
3. For each RESTING order:
   - expired: cancel, release reservation, persist terminal fields;
   - crossed and fillable: for BUY resting orders, only `best_ask <= limit_price` may convert reservation to filled position; write matched amount/fill price/fee;
   - blocked by risk: cancel/reject with terminal reason and release reservation.

### Settlement path

1. Settlement path attaches `SettlementProvenance` from official/local source inspection.
2. `PaperSettlementEngine` computes gross PnL from matched amount and outcome.
3. `compute_polymarket_binary_taker_fee_usdc()` supplies fee recorded on fill/result.
4. Wallet closes position with settlement value and net PnL.
5. Report aggregates gross PnL, fee, net PnL, matched amount, reserved exposure, reject/cancel reasons, and settlement provenance.

### Restart recovery path

1. Scheduler startup loads active RESTING orders from SQLite or existing persistence source before accepting new paper orders.
2. Wallet reservations are rebuilt from active RESTING orders' unmatched amounts; stale wallet snapshot `reserved_balance` is not trusted as a source of truth.
3. Missing or corrupt active resting order state fails closed for new paper side effects and records a diagnostic, rather than continuing with uncertain cash availability.

## Acceptance criteria

- `app.mode=signal_only` produces no new `paper_orders`, `paper_fills`, `paper_positions`, or wallet mutations for accepted signals.
- `app.mode=paper_only` suppresses Telegram signal publish while still allowing paper execution.
- A pause/emergency state blocks new paper orders and resting fills but does not block settlement/reporting of already terminal positions.
- Invalid/unreadable pause state fails closed for new paper side effects and records `PAPER_PAUSE_STATE_UNREADABLE`.
- Two RESTING orders cannot reserve more than available cash; rejected order stores `PAPER_WALLET_INSUFFICIENT_CASH`.
- RESTING fill converts reservation into spent cash exactly once; expiry/cancel releases reservation exactly once.
- `PaperOrder`, `PaperFill`, `PaperPosition`, and `PaperTradeResult` persist matched amount, fee, fill/cancel/expiry timestamps, terminal reason where applicable.
- PnL reports include gross PnL, fee, and net PnL; existing `pnl_usdc` means net PnL after migration.
- Fee tests prove `fee_rate` is treated as a fraction, not bps; include a synthetic `0.25` case only as a scale guard, not as the default rate.
- Immediate wallet insufficiency rejects before fill creation; no persisted `PaperFill`/`PaperPosition` may exist without the matching wallet mutation.
- PASSIVE_GTD BUY order does not fill merely because `best_bid >= limit_price`; it fills only when executable ask crosses `best_ask <= limit_price` under current-slot readiness.
- `best_bid_ask` cannot leave executable asks below announced best ask in the canonical book used by strategy snapshots or paper fills.
- Strategy evaluation and paper fills are skipped when current-slot two-sided book readiness is false.
- Tick-size/grid change or CLOB hydration miss marks the current-slot book not ready until a fresh executable snapshot exists.
- Expired markets are not returned by `MarketRegistry.active()` after their window ends.
- Settlement `ambiguous` or `unresolved` does not close paper positions as WIN/LOSS.
- Risk checks reject new paper orders when open + reserved exposure exceeds market or strategy exposure thresholds.
- Drawdown, daily loss, and consecutive loss gates are disabled unless risk history is available; when disabled they must be visible in health/report diagnostics.
- Scheduler restart recovery rebuilds reservations from active RESTING orders or fails closed; `reserved_balance` cannot diverge from active unmatched resting amount.

## Test strategy

### Unit tests

- `tests/test_paper_wallet.py`
  - reserve/release idempotency;
  - available cash excludes reserved balance;
  - fill converts reserved balance to open position once;
  - expiry releases reserved balance once.
  - immediate fill with insufficient available cash rejects before position creation;
  - startup rebuild computes reserved balance from active resting orders.
- `tests/test_paper_execution_boundary.py`
  - all `app.mode` combinations;
  - pause/emergency blocks new order and resting fill;
  - unreadable pause state fails closed;
  - settlement/reporting path remains allowed.
- `tests/test_paper_lifecycle.py`
  - immediate fill populates matched amount, fee, fill timestamp;
  - cancellation/expiry populates terminal reason and timestamp;
  - no `requested_stake_usdc` alias is required for historical compatibility.
- `tests/test_paper_fees.py`
  - taker fee uses configured fraction rate;
  - `fee_rate=0.25` produces the expected Polymarket binary fee;
  - settlement net PnL subtracts fee.
- `tests/test_order_intent_executor.py`
  - PASSIVE_GTD BUY remains resting when only `best_bid >= limit_price`;
  - PASSIVE_GTD BUY fills when `best_ask <= limit_price` and readiness is true;
  - restart recovery rebuilds reservations from persisted RESTING orders.
- `tests/test_paper_preflight.py`
  - head window, tail window, min/max price, remain window;
  - placement rejection happens before paper wallet mutation.
- `tests/test_book_reconciliation.py`
  - best_bid_ask prunes stale asks/bids;
  - missing canonical book marks stale/reseed-needed.
- `tests/test_market_registry.py`
  - active view excludes expired markets;
  - refresh prunes markets absent from latest active set.
  - active view handles missing `start_ts` / `end_ts` conservatively without excluding otherwise active markets.
- `tests/test_settlement_provenance.py`
  - verified/provisional outcome closes position;
  - ambiguous/unresolved outcome leaves position open or UNKNOWN.
  - cancelled/void official market closes as VOID with provenance.

### Integration tests

- `tests/test_scheduler_paper.py`
  - accepted signal in `signal_only` stores signal but no paper order;
  - accepted signal in `paper_only` creates paper order but no Telegram publish call;
  - pause state prevents paper side effects.
- `tests/test_scheduler_reports.py`
  - daily report aggregates matched amount, fees, gross/net PnL, reserved exposure, terminal reasons.
- `tests/test_market_data.py`
  - current-slot readiness false when one side book is missing/stale;
  - strategy evaluation receives no candidate from stale two-sided market.

## Storage and migration

SQLite migration must be additive:

- Add nullable columns only for new lifecycle/report fields actually introduced: matched amount, fee, terminal timestamps/reason, provenance, gross/net PnL.
- Continue reading historical rows from `payload_json` when explicit columns are null.
- Backfill `matched_amount_usdc = stake_usdc` only for historical FILLED orders where no better data exists.
- Historical reports remain readable; new reports include additional fields.
- Active RESTING orders must either be persisted as rows with unmatched amount and expiry, or startup must explicitly discard them and release reservations with an audit event; silent in-memory loss is not allowed.

No destructive migration is allowed in this spec.

## Rollout

This remains one spec. The rollout is internal sequencing, not spec splitting:

1. Add small lifecycle fields and additive SQLite migration while preserving current behavior.
2. Add `PaperWallet` reservation APIs, route PASSIVE_GTD through them, correct BUY resting crossing to executable `best_ask <= limit_price`, and define startup reservation rebuild.
3. Add mode/pause boundary checks at publish, new paper order, and resting tick call sites.
4. Extend existing `PaperExecutionPreflight` with placement checks.
5. Add fee function and convert settlement/reporting to gross/fee/net PnL.
6. Add book readiness and best_bid_ask canonical repair.
7. Add market registry pruning and slot stale-book reset.
8. Add settlement provenance and ambiguous/unresolved fail-closed behavior.
9. Add reserved-exposure-aware risk checks; enable drawdown/daily/consecutive gates only when persisted risk history exists.
10. Run targeted tests, then full pytest; for formal runtime use rebuild/recreate Docker before considering behavior live.

## Current evidence references

Current project:

- `src/polysignal_lab/config.py:67-72,197-207`
- `src/polysignal_lab/app/scheduler_processing.py:429-470,573-620,680-753`
- `src/polysignal_lab/app/services/paper_portfolio_service.py:70-84`
- `src/polysignal_lab/paper/wallet.py:14-17,31-38,51-60`
- `src/polysignal_lab/paper/simulator.py:63-138,195-204`
- `src/polysignal_lab/paper/order_intent_executor.py:278-372`
- `src/polysignal_lab/paper/settlement.py:15-69`
- `src/polysignal_lab/domain/paper_order.py:12-50`
- `src/polysignal_lab/domain/signal.py:13-40`
- `src/polysignal_lab/data/polymarket_clob_ws.py:146-152`
- `src/polysignal_lab/data/state.py:35-42,88-106,158-216`
- `src/polysignal_lab/data/market_snapshot.py:17-47`
- `src/polysignal_lab/strategies/base.py:37-94`
- `src/polysignal_lab/strategies/mid_price_sizing.py:97-108,223-265`

Reference project:

- `refs/poly-btc-martingale/poly_btc_martingale/domain/mode_store.py:1034-1070,1436-1553,1692-1797`
- `refs/poly-btc-martingale/poly_btc_martingale/domain/trade_order.py:66-115,160-184`
- `refs/poly-btc-martingale/poly_btc_martingale/domain/ledger.py:43-58,61-98,281-385`
- `refs/poly-btc-martingale/poly_btc_martingale/domain/usdc_reservation.py:42-78,94-138`
- `refs/poly-btc-martingale/poly_btc_martingale/adapters/polymarket/sim_executor.py:263-283,607-627,768-811`
- `refs/poly-btc-martingale/poly_btc_martingale/order_builder.py:153-159,226-300,542-590,982-1030`
- `refs/poly-btc-martingale/poly_btc_martingale/placement_guard.py:1-19,47-55,149-210`
- `refs/poly-btc-martingale/poly_btc_martingale/runtime_market_tick.py:116-130,173-217,341-632`
- `refs/poly-btc-martingale/poly_btc_martingale/domain/slot_transition.py:498-558`
- `refs/poly-btc-martingale/poly_btc_martingale/domain/pending_fill.py:95-114,196-217`
- `refs/poly-btc-martingale/poly_btc_martingale/domain/slot_settlement_fill_context.py:100-149`

External reference boundaries:

- Hummingbot docs/source via Context7: `docs/client/global-configs/paper-trade.md` 中 `paper_trade.paper_trade_exchange` 配置与 `balance paper` 模拟余额；`hummingbot/connector/connector_base.pyx` 中 account balances、available balances、in-flight orders 和 market events；`hummingbot/core/data_type/in_flight_order.py` 中小型 order state lifecycle。
- CCXT docs: unified API order/accounting vocabulary as field vocabulary reference, not dependency.
- `docs/superpowers/specs/2026-06-24-10-unified-hftbacktest-design.md`: historical queue/latency/partial-fill realism belongs to HftBacktest, not this forward paper runtime.
- Polymarket official docs:
  - Fees: <https://docs.polymarket.com/trading/fees.md>，用于 binary fee formula、per-category fee schedule、5-decimal fee rounding、`getClobMarketInfo(conditionID)` per-market fee params。
  - Market WebSocket channel: <https://docs.polymarket.com/market-data/websocket/market-channel>，用于 `book`、`price_change`、`best_bid_ask`、`tick_size_change`、`market_resolved` 事件语义。
- NautilusTrader Polymarket docs/source:
  - Official integration docs: <https://nautilustrader.io/docs/nightly/integrations/polymarket/>，用于 `BinaryOption`、market BUY quote quantity、GTC/GTD/FOK/FAK order mapping、tick-size-change book epoch reset、runtime instrument auto-load/hydration retry、strict Gamma/CLOB settlement inference、`PolymarketFeeModel`、cache purge/housekeeping。
  - Docs source: <https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/integrations/polymarket.md>。
  - Adapter source paths used for spot-checking implementation shape: `nautilus_trader/adapters/polymarket/data.py`、`execution.py`、`fee_model.py`、`order_fill_tracker.py`、`config.py`、`factories.py` and `crates/adapters/polymarket/README.md` in <https://github.com/nautechsystems/nautilus_trader>.
  - Boundary: 本规格只借鉴这些不变量，不引入 live execution client、credentials、allowance scripts 或 Nautilus engine runtime。

## Open implementation notes

- Keep the first implementation boring: helper functions before classes; one reservation map; one fee function; placement checks inside existing preflight.
- Avoid introducing large functions; split orchestration from calculation/persistence helpers once a function stops fitting on one screen.
- Do not introduce a generic live/sim abstraction layer until live trading is explicitly in scope.
- Do not add domain fields copied from ref unless a current acceptance criterion requires them.
- Use additive schema changes and compatibility readers; avoid one-shot destructive migration.
- Prefer one source of truth per invariant: mode boundary at scheduler side-effect call sites, cash in wallet, lifecycle in small typed domain fields, readiness in registry/snapshot metrics, provenance in settlement result.
