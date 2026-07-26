# PolySignal Lab — PRD (Product Requirements Document)

## 1. 文档状态

| 项目 | 内容 |
|------|------|
| 产品名称 | PolySignal Lab |
| 产品类型 | Polymarket 短周期信号 + 模拟交易验证系统 |
| 当前阶段 | PRD（产品需求；**架构真相以活文档为准**） |
| 开发范围 | 只读行情、策略信号、Telegram 发布、Nautilus sandbox 纸面验证、胜负统计（报表） |
| 明确不做（默认产品） | 默认不注册 live 执行、不自建 signing/CLOB 客户端、不接触钱包密钥、不托管资金、不自动链上领取；sandbox `submit_order` 允许；gated live 仅官方 adapter |
| 核心目标 | 将 3 个独立 Polymarket 机器人重构为一个统一信号与模拟验证系统 |

架构 / 运行时边界（本 PRD 不重复维护）：

- [`ARCHITECTURE_OWNERSHIP.md`](ARCHITECTURE_OWNERSHIP.md) — 三真相与所有权
- [`RUNTIME_BOUNDARY.md`](RUNTIME_BOUNDARY.md) — 模式、禁止面、退出/结算/报表边界
- [`NAUTILUS_CAPABILITY_MATRIX.md`](NAUTILUS_CAPABILITY_MATRIX.md) — 已验证包能力
- [`nautilus_reference/developer_guide/design_principles.md`](nautilus_reference/developer_guide/design_principles.md) — Nautilus 消息不可变等设计不变量

### 1.1 与 NautilusTrader 设计对齐（禁止违反）

本产品运行在 Nautilus 之上；PRD 不得要求下列反模式：

| 不变量 | PRD / 实现要求 |
|--------|----------------|
| **消息不可变** | `AlphaDecision` / `SignalCandidate` / `GateDecision` / CustomData / native events 一经产生不得就地改写（含 `metrics` / `reason_codes` 等容器字段）；需要新事实就发新消息或写本地派生状态（见 Nautilus [design_principles](nautilus_reference/developer_guide/design_principles.md) / [message integrity](https://nautilustrader.io/docs/latest/concepts/message_bus/#message-integrity)） |
| **Cache / Portfolio / Account 是交易真相** | 不得用 SQLite/`report_*`/JSONL 恢复或驱动持仓、余额、敞口；报表 PnL 的 shares/entry/stake 读 Cache 投影 |
| **RiskEngine 拥有账户/敞口风险** | `submit_order` 进入 RiskEngine（见 [Strategies](https://nautilustrader.io/docs/latest/concepts/strategies)）；不得再实现第二套 paper Account/Exposure/Position-limit gate；`SignalGate` 只做业务资格检查 |
| **Strategy 是回调宿主** | 多步逻辑在 `nautilus_runtime/strategy/*`；下单只经 `order_factory` + `submit_order` |
| **Adapter 拥有 venue I/O** | 不得自建 CLOB/book/signing 第二真相；spot 仅 managed RTDS `LiveDataClient`（见 [adapters](nautilus_reference/developer_guide/adapters.md)） |
| **无第二决策总线** | `DecisionPolicy` 为 Strategy 内纯逻辑（当前为 **gate-only**）；禁止 `DecisionPolicyActor` / candidate Signal 总线 |
| **时间来自 Nautilus Clock** | 决策定时器与交易事件时间戳用引擎 Clock；报表层 `report_results.closed_at` 等投影戳允许墙钟，但不得回写交易状态（见 [`RUNTIME_BOUNDARY.md`](RUNTIME_BOUNDARY.md)） |
| **结算不得伪造 native 生命周期** | sandbox/live 的 WIN/LOSS 只写 `report_results`；不得合成 fill / `PositionClosed` / Portfolio·Account 突变 |

## 2. 一句话定义

PolySignal Lab 是一个默认 sandbox 的 Polymarket 短周期信号与纸面验证系统。它把 VWAP Momentum、Late Consensus、PTB Diff 等策略统一为 AlphaCore，经 Strategy 内 `SignalGate` 后发往 Telegram，并用 Nautilus sandbox（Cache / Portfolio / Account 为交易真相）记录若执行后的纸面输赢；结算只写 `report_results`，不伪造 native payout。

## 3. 背景

原始仓库包含 3 个独立 Polymarket crypto Up/Down bot：

- **btc-binary-VWAP-Momentum-bot** — BTC 单资产。使用 VWAP、momentum、deviation、z-score 判断短周期方向。原始实现包含真实订单执行、hedge、链上领取、dashboard、Telegram。
- **up-down-spread-bot** — BTC / ETH / SOL / XRP 多资产。使用 late-entry、spread、ask skew、confidence、favorite side 判断方向。原始实现包含多资产 desk、stop-loss、flip-stop、Telegram command。
- **5min-15min-PTB-bot** — BTC 为主。使用 Binance spot、Polymarket price-to-beat、UP/DOWN implied probability 判断方向。原始实现包含 AUTO_TRADE、simulation、TP/SL、Web dashboard。

新项目不复用这些 bot 的真实执行逻辑，而是抽象其策略原理，统一变成：

```
Public Market Data → Nautilus Strategy Callback → Signal Gate → Telegram → Nautilus Sandbox (Cache) → report-only Win/Loss
```

## 4. 产品目标

### 4.1 核心目标

| 目标 | 说明 |
|------|------|
| 统一三套策略 | 3 个机器人不再各自运行 runtime，而是变成统一策略模块 |
| 默认安全边界 | 不读私钥；默认不注册 live 执行；sandbox 经 `order_factory`/`submit_order` 验证 |
| Telegram 信号 | 每条可交易信号发送到 Telegram 频道 |
| Nautilus 纸面验证 | 每条通过 gate 的信号可由 sandbox 生成 native order/fill/position（Cache 真相） |
| 知道输赢 | 市场结束后以 **report-only** 写入 `report_results`（不伪造 native payout） |
| 可审计 | 每条信号、Nautilus order/fill/position 投影、结算结果都落日志 |
| 可复盘 | 支持按策略、资产、周期统计胜率和 PnL（报表层） |
| 可扩展 | 后续可加入新策略、Discord、Webhook、dashboard |

### 4.2 非目标

| 非目标 | 说明 |
|--------|------|
| 默认 live 交易 | 默认配置不买卖真实 Polymarket token；live 仅双开关 + 校验后才可注册（非默认产品承诺） |
| 钱包管理 | 不读取钱包密钥环境变量；凭证解析归 Polymarket adapter（Rust），Python 不注入 secrets |
| 自动链上领取 | 不做链上领取 / redeem |
| Venue contingent / bracket 平仓 | 不做 venue 级 contingent/bracket 子单；sandbox 可由 `NativeExitPolicy` 经原生 `submit_order` 做 paper exit。live 若启用，exit 仍走官方 ExecutionClient，且不得依赖 reduce-only（adapter 不支持） |
| 盈利承诺 | 只统计纸面验证结果，不承诺实盘可复制 |
| 完整历史回测产品化 | 当前默认是实时 sandbox 验证；`BacktestEngine` 路径存在但不作为 V1 产品承诺 |
| 付费频道 | 不做会员、订阅、支付 |

## 5. 项目名称

正式项目名：**PolySignal Lab**

命名理由：
- **Poly**：指向 Polymarket。
- **Signal**：核心产品是信号，不是自动交易。
- **Lab**：强调研究、模拟、验证，不暗示稳赚。

## 6. 用户画像

| 用户 | 需求 |
|------|------|
| 人工 Polymarket 交易者 | 收到结构化信号后手动判断是否交易 |
| 策略研究者 | 知道每个策略在实时市场中的胜率和纸面收益 |
| 项目维护者 | 统一 3 个 bot 的策略逻辑，删除真实执行风险 |
| 风控审计者 | 检查每条信号的触发原因、行情快照和模拟结果 |

## 7. 产品边界

### 7.1 允许能力

| 能力 | 是否允许 |
|------|----------|
| 读取 Polymarket market data（Nautilus DataEngine / Cache） | 允许 |
| 读取 Polymarket RTDS spot（managed `LiveDataClient` → CustomData） | 允许 |
| 计算信号 | 允许 |
| Telegram 发消息 | 允许 |
| Nautilus sandbox 纸面模拟 | 允许 |
| 记录 report 投影（orders/fills/positions/results） | 允许 |
| 统计 paper win/loss（report-only） | 允许 |
| 生成日报 / 只读 dashboard | 允许 |

### 7.2 禁止能力

默认产品（`execution_mode=sandbox`）下全部禁止。gated `live` 仅在 Runtime Boundary 双开关 + 校验通过后才可注册官方 execution factory；**不得**自建第二套 CLOB/signing/wallet 路径。

| 能力 | 是否禁止 |
|------|----------|
| 读取钱包私钥 / Python 注入 secrets | 禁止（凭证归 Polymarket adapter Rust） |
| 默认配置下创建/取消真实 Polymarket 订单 | 禁止（live 未授权时 fail-closed） |
| 自建 EIP-712 signing / 私有 CLOB 客户端 | 禁止（仅官方 adapter 执行面） |
| 自动链上领取 / redeem / 自动转账 | 禁止 |
| CEX 真实下单 | 禁止 |
| 本地 paper matching / wallet ledger | 禁止（sandbox 成交真相属 Nautilus） |

## 8. 产品形态

PolySignal Lab 是一个后台常驻服务；另有只读 Dashboard API（非交易控制面）。

```
┌────────────────────────────┐
│ Public Polymarket Data      │
│ Nautilus CustomData Payloads│
└──────────────┬─────────────┘
               ↓
┌────────────────────────────┐
│ Nautilus LiveNode (sandbox) │
│ - DataEngine / Cache        │
│ - Strategy lifecycle        │
└──────────────┬─────────────┘
               ↓
┌────────────────────────────┐
│ PolySignal Alpha Cores      │
│ - VWAP Momentum             │
│ - Late Consensus            │
│ - PTB Diff (+ more)         │
└──────────────┬─────────────┘
               ↓
┌────────────────────────────┐
│ DecisionPolicy (in-process) │
│ SignalGate (business quals) │
└──────────────┬─────────────┘
               ↓
┌──────────────┴─────────────┐
│                            │
↓                            ↓
Telegram Publisher            Nautilus Sandbox Paper Execution
│                            │
↓                            ↓
Signal Channel                Nautilus Cache / Portfolio Projection
```

## 9. 核心流程

### 9.1 启动流程

1. 读取配置文件。
2. 校验 Telegram bot token 和 channel id。
3. 加载启用资产、周期、策略。
4. 组装 Nautilus `LiveNode`（sandbox 默认）：官方 Polymarket data factory + sandbox execution；注册 `MarketRotationActor` 与 `PolySignalNativeStrategy`。
5. `MarketRotationActor` / discovery worker 发现当前 crypto Up/Down 市场并发布 universe/metadata/PTB CustomData。
6. Nautilus data path 接收 Polymarket market data 写入 Cache。
7. Managed RTDS `LiveDataClient` 提供 spot CustomData；Strategy 订阅 CustomData（spot / PTB / metadata）。
8. Strategy callbacks 经 `MarketViewAssembler` 构造 market view 并运行 alpha core。
9. 信号通过 Strategy 内 in-process `DecisionPolicy`（`SignalGate` 业务资格；账户/敞口由 RiskEngine）。
10. 通过 gate 后发送 Telegram。
11. Strategy 经 `native_order`（`order_factory` + `submit_order`）提交 sandbox order。
12. Nautilus sandbox 生成 fills / positions / account state（Cache / Portfolio 为真相）。
13. 市场结束后以 **report-only** 方式写入 `report_results` 投影（不伪造 native payout / PositionClosed）。
14. 更新胜率、PnL、资金曲线（报表层）。

### 9.2 信号流程

```
Nautilus Data / Custom Data Callback
  → PolySignal AlphaCore.evaluate()
  → AlphaDecision
  → DecisionPolicy / SignalGate (in-process on PolySignalNativeStrategy)
  → TelegramMessage
  → Nautilus native order
  → Nautilus sandbox fill / position
  → report-only settlement projection
```

### 9.3 纸面交易流程

1. 通过 gate 的信号由 Strategy 映射为 Nautilus native order 参数。
2. Strategy 调用 Nautilus `order_factory.limit(...)` 和 `submit_order(...)`。
3. Nautilus sandbox 根据当前 instrument、book、trade 数据处理 paper order。
4. 订单状态、成交、持仓、账户状态来自 Nautilus Cache/Portfolio。
5. PolySignal 将事件投影写入 SQLite `report_*` / JSONL、Telegram、日报和 dashboard。
6. 市场结束后的 win/loss 只读 Nautilus position projection 与 resolution evidence（report-only；不伪造 native payout）。
7. 写入 `report_results` 投影并更新统计报表。

## 10. 策略模块

### 10.1 Strategy A：VWAP Momentum

**来源：** 原 btc-binary-VWAP-Momentum-bot

**支持范围：**

| 项目 | 第一版 |
|------|--------|
| 资产 | BTC |
| 周期 | 5m / 15m |
| 输出 | BUY_UP / BUY_DOWN |
| 是否 paper trade | 是 |

**输入：**

| 输入 | 来源 |
|------|------|
| UP / DOWN best bid ask | Nautilus Cache（Polymarket DataClient） |
| last trade price | Nautilus Cache trades 投影 |
| orderbook depth | Nautilus Cache book 投影 |
| BTC spot | Nautilus Cache/`CustomData`；checked-in config 使用 managed RTDS（`runtime.nautilus.spot_data.source: polymarket_rtds`） |
| market start / end | Polymarket metadata |

**指标：**

| 指标 | 说明 |
|------|------|
| VWAP | 当前窗口的加权价格 |
| deviation_pct | 当前价格相对 VWAP 的偏离 |
| momentum | 最近 N 秒价格动量 |
| z_score | 标准化偏离 |
| favorite_side | 当前盘口强侧 |
| seconds_to_close | 距离结束秒数 |

**触发规则：**

必须满足：
- 当前 market active、未 closed、order book enabled、accepting_orders=true（元数据；book 真相仍在 Nautilus Cache）。
- Cache book fresh，且 UP / DOWN token ids 可经 `MarketCatalog` 映射到 Nautilus instrument id。
- 当前处于允许入场窗口。
- target ask 在允许价格区间内。
- VWAP deviation 达标。
- momentum 与方向一致。
- z_score 达标。
- spread 未超过上限。

### 10.2 Strategy B：Late Consensus

**来源：** 原 up-down-spread-bot

**支持范围：**

| 项目 | 第一版 |
|------|--------|
| 资产 | BTC / ETH / SOL / XRP |
| 周期 | 5m / 15m |
| 输出 | BUY_UP / BUY_DOWN |
| 是否 paper trade | 是 |

**输入：**

| 输入 | 来源 |
|------|------|
| UP / DOWN ask | Nautilus Cache book 投影 |
| best bid ask | Nautilus Cache book 投影 |
| ask sum | Derived |
| ask skew | Derived |
| spread | Derived |
| asset spot movement | Nautilus Cache/`CustomData` via managed RTDS（`spot_data.source: polymarket_rtds`） |
| seconds_to_close | Derived |

**触发规则：**

必须满足：
- 当前处于 late-entry window。
- confidence >= min_confidence。
- spread <= max_spread。
- ask_sum <= max_ask_sum。
- target ask <= max_entry_price。
- 最近无 flip risk。
- 行情未 stale。

### 10.3 Strategy C：PTB Diff

**来源：** 原 5min-15min-PTB-bot

**支持范围：**

| 项目 | 第一版 |
|------|--------|
| 资产 | BTC |
| 周期 | 5m / 15m |
| 输出 | BUY_UP / BUY_DOWN |
| 是否 paper trade | 是 |

**输入：**

| 输入 | 来源 |
|------|------|
| BTC spot price | Nautilus Cache/`CustomData` via managed RTDS（`spot_data.source: polymarket_rtds`） |
| price_to_beat | 本地 market window anchor；若使用 Polymarket price-to-beat endpoint，必须标记为未正式 API ref 依赖 |
| UP / DOWN implied price | Nautilus Cache book 投影 |
| seconds_to_close | Derived |
| trigger rows | Config |

**触发规则：**

BUY_UP：
- BTC spot > PTB。
- diff_usd >= min_diff_usd。
- UP ask <= max_token_price。
- probability_edge >= min_probability_edge。
- seconds_to_close 在 trigger window 内。

BUY_DOWN：
- BTC spot < PTB。
- abs(diff_usd) >= min_diff_usd。
- DOWN ask <= max_token_price。
- probability_edge >= min_probability_edge。
- seconds_to_close 在 trigger window 内。

## 11. 统一信号模型

所有策略输出统一不可变 `AlphaDecision` → `SignalCandidate`（构造新对象，不改写已发出的候选）。

```json
{
  "schema_version": 1,
  "signal_id": "20260621-BTC-5m-UP-ptb_diff-0001",
  "created_at": "2026-06-21T09:30:12.340Z",
  "strategy": "ptb_diff",
  "asset": "BTC",
  "timeframe": "5m",
  "market_id": "string",
  "market_slug": "string",
  "condition_id": "string",
  "token_id": "string",
  "action": "BUY",
  "side": "UP",
  "confidence": 0.81,
  "entry_reference_price": 0.62,
  "max_entry_price": 0.68,
  "seconds_to_close": 145,
  "data_freshness_ms": 420,
  "reason_codes": ["SPOT_ABOVE_PTB", "DIFF_THRESHOLD_OK", "ORDERBOOK_FRESH"],
  "metrics": {
    "spot_price": 105240.5,
    "price_to_beat": 105150.0,
    "diff_usd": 90.5,
    "spread": 0.03
  },
  "dedupe_key": "BTC:5m:market_id:UP:ptb_diff"
}
```

## 12. Telegram 消息

### 12.1 基础信号模板

```
[PolySignal Lab]

Market: BTC Up/Down 5m
Strategy: PTB Diff
Action: BUY UP

Reference Entry: 0.62
Max Entry: 0.68
Paper Stake: 10.00 PAPER_USD
Confidence: 81%
Time Left: 02:25

Why:
- Spot above PTB by $90.5
- Probability edge passed
- Orderbook fresh
- Spread acceptable

Nautilus Paper Validation:
- A Nautilus sandbox paper order will be submitted when the signal passes policy.
- This is not a real Polymarket order.

Risk:
- Manual execution only.
- Do not chase above max entry.
- This is a signal, not financial advice.

Signal ID:
20260621-BTC-5m-UP-ptb_diff-0001
```

### 12.2 模拟结算模板

```
[PolySignal Lab Result]

Signal: 20260621-BTC-5m-UP-ptb_diff-0001
Market: BTC Up/Down 5m
Paper Side: UP
Paper Entry: 0.62
Paper Stake: 10.00 PAPER_USD
Paper Shares: 16.1290

Result: WIN
Settlement Value: 16.1290 PAPER_USD
Paper PnL: +6.1290 PAPER_USD
ROI: +61.29%

Strategy:
PTB Diff

Note:
Paper result only. No real order was placed.
```

## 13. Nautilus 纸面验证系统

### 13.1 设计目标

Nautilus 纸面验证系统用于回答：
- 这条信号如果按 Nautilus sandbox 规则提交 paper order，最后是赢还是输？
- 每个策略的 paper win rate 是多少？
- 每个策略的 paper PnL 是多少？
- Telegram 信号是否有实际参考价值？
- 哪些策略、资产、周期应该保留或降低权重？

### 13.2 核心原则

| 原则 | 说明 |
|------|------|
| 真实公开行情 | 使用 Polymarket DataClient → Cache 与 managed RTDS/`CustomData`，无第二 book 真相 |
| Nautilus 纸面账户 | 使用 sandbox Cache/Portfolio/Account，不接触真实资金；不自建 paper wallet |
| RiskEngine 拥有风险 | 账户/名义/速率约束不在 `SignalGate` 复刻 |
| 可解释成交 | 每笔 paper fill 必须能追溯到 Nautilus order/fill/position 事件 |
| 报表只读 | `report_*` 可复盘，但不可恢复或驱动交易状态 |
| 保守标注 | 不承诺 paper result 可复制到真实交易 |

### 13.3 Nautilus Paper Account Projection

账户/余额真相来自 Nautilus Cache / Portfolio / Account（sandbox 起始资金由 `trading.starting_balance_usdc` 注入引擎）。**不在 PolySignal 内维护第二套 paper wallet 或 exposure ledger。**

```yaml
trading:
  starting_balance_usdc: 1000.0
  stake_mode: fixed
  fixed_stake_usdc: 10.0
  exit_model:
    mode: hold_to_resolution_with_optional_tp_sl
```

字段名中的 `usdc` 表示 paper USD-equivalent accounting，不表示真实 Polymarket 钱包余额。账户不足、名义上限等由 **Nautilus RiskEngine / ExecutionEngine** 拒绝，不以本地 gate 复刻。

账户投影字段：

```json
{
  "source": "nautilus_cache",
  "currency": "PAPER_USD_EQUIVALENT",
  "starting_balance": 1000.0,
  "cash_balance": 970.0,
  "reserved_balance": 0.0,
  "realized_pnl": 12.4,
  "unrealized_pnl": 3.1,
  "equity": 985.5,
  "open_position_count": 3
}
```

### 13.4 Nautilus Paper Order Projection

Paper order 是 `PolySignalNativeStrategy` 经 `order_factory` / `submit_order` 提交后、由 Cache 事件投影到 `report_orders` 的只读行（非交易真相）。

```json
{
  "report_order_id": "nautilus_order_20260621_0001",
  "signal_id": "20260621-BTC-5m-UP-ptb_diff-0001",
  "asset": "BTC",
  "timeframe": "5m",
  "market_id": "string",
  "token_id": "string",
  "side": "UP",
  "order_type": "LIMIT",
  "time_in_force": "IOC",
  "limit_price": 0.68,
  "reference_price": 0.62,
  "stake_usdc": 10.0,
  "status": "PENDING"
}
```

### 13.5 Nautilus Sandbox Fill Model

默认 runtime 使用 Nautilus sandbox paper execution。PolySignal 不再把本地简化成交模型作为默认成交真相。

1. Strategy 经 `native_order` 将 approved decision 映射为 Nautilus native paper order。
2. Nautilus sandbox 根据当前 instrument、book、trade 数据处理 order。
3. 订单状态、成交、持仓、账户状态来自 Nautilus Cache/Portfolio。
4. PolySignal 将事件投影写入 SQLite `report_*` / JSONL、Telegram、日报和 dashboard。
5. 如果数据过旧、instrument 缺失或 policy 不通过，则记录 rejected decision / rejected order projection。
6. V1 paper PnL 默认 fee-free，必须写入 `fee_model=ignored_v1`；如果启用 Polymarket fee parity，则用 CLOB market fee schedule 计算 taker fee。

**当前配置：**

```yaml
runtime:
  nautilus:
    execution_mode: sandbox
    allow_live_polymarket_execution: false
    spot_data:
      source: polymarket_rtds
```

Checked-in config uses the Nautilus-managed RTDS `LiveDataClient` for spot ingress (`spot_data.source: polymarket_rtds`). Setting `source: disabled` while enabling a spot-dependent strategy fails fast; MarketRotation must not republish spot as a second truth.

**拒绝责任划分（禁止混写为“paper policy gate”）：**

| 原因 / 类别 | 所有者 |
|------|------|
| `STALE_ORDERBOOK` / `ASK_ABOVE_MAX_ENTRY` / freshness / spread / confidence 等 | `SignalGate`（业务资格） |
| 账户余额不足、submit/modify rate、`max_notional_per_order` | **Nautilus RiskEngine** |
| sandbox matching 拒单（深度/价格不可成交等） | **Nautilus ExecutionEngine / sandbox** |
| 映射失败 / in-flight 重复提交 | Strategy pipeline（非第二账户账本） |

### 13.6 Report Position Projection

Nautilus fill 后，将 Cache position **投影**到 `report_positions`（只读报表行，非交易真相）。

```json
{
  "report_position_id": "pp_20260621_0001",
  "signal_id": "20260621-BTC-5m-UP-ptb_diff-0001",
  "report_order_id": "po_20260621_0001",
  "asset": "BTC",
  "timeframe": "5m",
  "market_id": "string",
  "side": "UP",
  "entry_price": 0.622,
  "shares": 16.0771,
  "stake_usdc": 10.0,
  "opened_at": "2026-06-21T09:30:13.000Z",
  "status": "OPEN"
}
```

### 13.7 Exit / Settlement Model

默认模式：**Hold To Resolution**，sandbox/live 下结算为 **`native_settlement_mode=report_only`**。

| 结果 | 报表层记账（写入 `report_results`） |
|------|------|
| 预测正确 | `outcome_value=1.0` → `settlement_value = shares` |
| 预测错误 | `outcome_value=0.0` → `settlement_value = 0` |

约束（禁止违反 Nautilus 所有权）：
- 上述公式只生成 **报表行**；不得合成 fill、`PositionClosed`，不得改写 Cache / Portfolio / Account。
- 开仓数量、均价、是否仍 open 一律读 Nautilus Cache 投影。
- backtest 可 replay 原生 `InstrumentClose`；PolySignal 不得在 sandbox/live 自行复刻该突变。

**PnL 计算（report-only；数量/均价来自 Cache 投影，禁止用 stake/price 自造持仓）：**

```
shares      = Cache position projection.shares|quantity
entry_price = Cache position projection.entry_price|avg_entry_price
stake_usdc  = Cache position projection.stake_usdc   # 缺失时才可派生 entry_price * shares
entry_fee   = 0.0  # V1 fee_model=ignored_v1
settlement_value = shares * outcome_value
pnl = settlement_value - stake_usdc - entry_fee
roi = pnl / stake_usdc
```

其中：
- outcome_value = 1.0 if side wins else 0.0（仅报表字段）
- 如果开启 fee parity，entry_fee 必须按 Polymarket market fee schedule 计算并写入 result。

**胜负判断（写入 `report_results.result`，不改 native Position 状态机）：**

| 条件 | 结果 |
|------|------|
| side = UP 且市场最终 UP | WIN |
| side = DOWN 且市场最终 DOWN | WIN |
| side = UP 且市场最终 DOWN | LOSS |
| side = DOWN 且市场最终 UP | LOSS |
| 市场取消 / unresolved | VOID |
| 无法获取结算结果 | UNKNOWN |

### 13.8 Paper TP/SL（已交付）

默认由 `NativeExitPolicy` 在 Nautilus Cache 持仓上评估，再经 `order_factory` + `submit_order` 发出原生 exit order；结果投影写入 `report_results`。sandbox 可使用 reduce-only；**Polymarket live adapter 不支持 reduce-only / contingent bracket**——不得把 venue 级 TP/SL 子单当作产品承诺。

```yaml
trading:
  exit_model:
    mode: hold_to_resolution_with_optional_tp_sl
    take_profit_enabled: true
    stop_loss_enabled: true
    take_profit_price: 0.90
    stop_loss_price: 0.35
    max_hold_time_sec: 900
```

架构约束：
- 不使用 venue contingent / bracket 子单（sandbox `support_contingent_orders=false`）。
- Exit 决策读 Cache 持仓，经原生 `submit_order`；live Polymarket 不得依赖 reduce-only。
- 只影响 paper / report 结果，默认不发送真实卖单。
- V1 fee：`fee_model=ignored_v1`，`entry_fee=0.0`。

### 13.9 Report Result（`report_results`）

```json
{
  "report_result_id": "pt_20260621_0001",
  "signal_id": "20260621-BTC-5m-UP-ptb_diff-0001",
  "strategy": "ptb_diff",
  "asset": "BTC",
  "timeframe": "5m",
  "market_id": "string",
  "side": "UP",
  "entry_price": 0.622,
  "shares": 16.0771,
  "stake_usdc": 10.0,
  "exit_mode": "RESOLUTION",
  "outcome_value": 1.0,
  "settlement_value": 16.0771,
  "pnl_usdc": 6.0771,
  "roi": 0.6077,
  "result": "WIN",
  "opened_at": "2026-06-21T09:30:13.000Z",
  "closed_at": "2026-06-21T09:35:05.000Z"
}
```

## 14. 统计报表

### 14.1 必须统计

| 指标 | 说明 |
|------|------|
| total_signals | 总信号数 |
| report_orders | 投影到 `report_orders` 的 paper order 数 |
| report_fills | 投影到 `report_fills` 的成交数 |
| rejected_orders | 被拒绝的 order/decision 投影数 |
| open_positions | Cache 当前 open 持仓投影数 |
| closed_positions | 已写入 `report_results` 的已结算笔数 |
| win_count | 赢的次数（`report_results`） |
| loss_count | 输的次数（`report_results`） |
| void_count | void 次数（`report_results`） |
| win_rate | win / closed |
| total_pnl_usdc | 累计模拟 PnL |
| average_roi | 平均 ROI |
| max_drawdown | 最大资金回撤 |
| profit_factor | gross_profit / gross_loss |
| strategy_breakdown | 按策略统计 |
| asset_breakdown | 按资产统计 |
| timeframe_breakdown | 按周期统计 |

### 14.2 日报模板

```
[PolySignal Lab Daily Paper Report]

Date: 2026-06-21
Starting Equity: 1000.00 PAPER_USD
Ending Equity: 1024.35 PAPER_USD
Paper PnL: +24.35 PAPER_USD
Paper ROI: +2.44%

Signals: 38
Paper Filled: 24
Closed Trades: 21
Wins: 13
Losses: 8
Win Rate: 61.90%

By Strategy:
- PTB Diff: 8 trades, 6W / 2L, +18.20 PAPER_USD
- VWAP Momentum: 7 trades, 4W / 3L, +3.10 PAPER_USD
- Late Consensus: 6 trades, 3W / 3L, +3.05 PAPER_USD

Notes:
Paper results only. No real trades were placed.
```

## 15. 数据存储

### 15.1 JSONL 审计流（当前）

```
logs/
  signals.jsonl
  rejected_signals.jsonl
  nautilus_orders.jsonl
  nautilus_fills.jsonl
  nautilus_positions.jsonl
  nautilus_decisions.jsonl
  report_results.jsonl        # settlements / early-exit 结果投影
  telegram_publishes.jsonl
  daily_reports.jsonl
  system_events.jsonl         # 可选 / best-effort telemetry
```

Runtime state 以 Nautilus Cache/Portfolio 为准；`state/` 下保留 heartbeat / monitor 等进程级快照，不再把 `open_positions.json` 当作持仓真相。

### 15.2 SQLite 表（当前）

| 表 | 用途 |
|----|------|
| signals | 所有通过 gate 的信号 |
| rejected_signals | 被拒绝信号 |
| strategy_status | 策略启用/状态投影 |
| report_results | 纸面验证结果（resolution 与 early exit） |
| report_account_snapshots | Nautilus account/portfolio 投影快照 |
| report_orders / report_fills / report_positions | order/fill/position 当前状态投影 |
| daily_reports | 每日报告（可 revision） |
| report_publish_outbox | 日报 Telegram 投递 outbox |
| system_events | Nautilus order/fill/position 等审计事件 |
| telegram_publishes | Telegram 发布审计 |
| markets | 市场元数据缓存 |
| anchor_prices | price-to-beat anchor 缓存 |

历史 `paper_*` 表名经 `projection_migration` 收敛为 `report_*`。报表存储是 disposable 投影，不可恢复交易状态（见 [`RUNTIME_BOUNDARY.md`](RUNTIME_BOUNDARY.md)）。

## 16. 架构设计

产品级数据流见 §8–§9。**所有权、禁止面、注册面、结算模式不以本节为权威**，统一见：

| 文档 | 内容 |
|------|------|
| [`ARCHITECTURE_OWNERSHIP.md`](ARCHITECTURE_OWNERSHIP.md) | 三真相、依赖方向、质量门 |
| [`RUNTIME_BOUNDARY.md`](RUNTIME_BOUNDARY.md) | sandbox/live/backtest、forbid list、exit/settlement/reporting |
| [`NAUTILUS_CAPABILITY_MATRIX.md`](NAUTILUS_CAPABILITY_MATRIX.md) | 已验证 Nautilus 能力 |
| [`STRATEGY_INDICATOR_FLOW.md`](STRATEGY_INDICATOR_FLOW.md) | 指标/行情进入 Strategy 的链路 |

包级布局（文件清单以源码为准，PRD 不维护完整树）：

```
src/polysignal_lab/
  app/                 # CLI / reporting / services
  alpha/               # 纯 AlphaCore
  nautilus_runtime/    # Node、Strategy 宿主、Cache 投影、DecisionPolicy、MarketRotation
  signal_layer/        # SignalGate / formatter（业务资格；非 RiskEngine）
  domain/              # Market、Side、OrderIntent、reporting models
  data/                # discovery / PTB / rate limit（非 live book 真相）
  storage/             # SQLite report_* + JSONL
  reporting/           # 日报与聚合
  publish/             # Telegram
  observability/       # health / metrics / safety scan
  dashboard/           # 只读 API
```

## 17. 配置设计

```yaml
app:
  name: PolySignal Lab
  timezone: Asia/Bangkok
  log_level: INFO

telegram:
  enabled: true
  bot_token_env: TELEGRAM_BOT_TOKEN
  channel_id_env: TELEGRAM_CHANNEL_ID
  send_signals: true
  send_report_results: true
  send_daily_report: true

markets:
  assets: [BTC, ETH, SOL, XRP]
  timeframes: [5m, 15m]
  refresh_interval_sec: 10

data:
  polymarket:
    max_book_staleness_ms: 60000
    # live books come from Nautilus Polymarket DataClient → Cache（非独立 CLOB WS 真相）

runtime:
  nautilus:
    execution_mode: sandbox
    allow_live_polymarket_execution: false
    spot_data:
      source: polymarket_rtds

signal:
  min_confidence_to_publish: 0.50

trading:
  starting_balance_usdc: 1000.0
  stake_mode: fixed
  fixed_stake_usdc: 10.0
  exit_model:
    mode: hold_to_resolution_with_optional_tp_sl
    take_profit_enabled: true
    stop_loss_enabled: true
    take_profit_price: 0.90
    stop_loss_price: 0.35
    max_hold_time_sec: 900

strategies:
  vwap_momentum:
    enabled: true
    assets: [BTC]
    timeframes: [5m, 15m]
    min_price: 0.35
    max_price: 0.85
    min_deviation_pct: 0.015
    min_momentum: 0.01
    min_z_score: 1.2
    min_elapsed_sec: 45
    no_entry_before_end_sec: 20

  late_consensus:
    enabled: true
    assets: [BTC, ETH, SOL, XRP]
    timeframes: [5m, 15m]
    entry_window_sec: 240
    min_confidence: 0.30
    max_spread: 0.08
    max_ask_sum: 1.05
    max_entry_price: 0.92
    flip_guard_enabled: true

  ptb_diff:
    enabled: true
    assets: [BTC]
    timeframes: [5m, 15m]
    triggers:
      - name: strong_up_late
        side: UP
        min_diff_usd: 80
        max_token_price: 0.78
        min_probability_edge: 0.08
        min_seconds_to_close: 30
        max_seconds_to_close: 180
      - name: strong_down_late
        side: DOWN
        min_diff_usd: 80
        max_token_price: 0.78
        min_probability_edge: 0.08
        min_seconds_to_close: 30
        max_seconds_to_close: 180
```

## 18. Signal Gate

每条信号必须经过 Strategy 内 `SignalGate`（顺序与拒绝码见 [`SIGNAL_GATE_RULES.md`](SIGNAL_GATE_RULES.md)）。产品级摘要：**市场活跃、时间窗、book/spot 新鲜度、价差、max entry、GTD expiry、confidence**。

`SignalGate` **不是** RiskEngine：不做账户余额、敞口、持仓上限。配置里若仍残留 `dedupe_*` / `consensus_*` / `max_signals_*` 字段，不得解释为第二套运行时决策总线；跨策略 arbiter/consensus 已移除。

## 19. 下单前风险与成交（Nautilus 拥有）

Approved 候选提交后：

1. Strategy 仅做 `order_factory` + `submit_order` 映射。
2. **RiskEngine** 执行账户/名义/速率类约束（见 `LiveRiskEngineConfig`；官方路径：无 emulation 时 `SubmitOrder` → RiskEngine）。
3. **ExecutionEngine / sandbox** 决定是否成交；拒单与 fill 进入 Cache。
4. PolySignal 只投影到 `report_*`，不得本地重算一条并行 exposure 真相。

Telegram 发布发生在 gate 通过之后、RiskEngine 裁决之前或并行——**信号 ≠ 成交**；余额不足等仍由 RiskEngine 拒绝，不得在 `SignalGate` 预判账户。

## 20. 胜负判断

### 20.1 市场结算来源（report-only evidence）

以下来源只用于写入 `report_results`，**不得**合成 fill、`PositionClosed`，不得改写 Cache / Portfolio / Account：

优先级：
1. Polymarket resolution / market-resolved evidence（adapter 或只读 public metadata）中的 `winning_asset_id` / `winning_outcome`。
2. Public market token metadata 中的 `tokens[].winner`。
3. UMA / Gamma resolution status 只作为 lifecycle/status 信号；除非官方 schema 明确提供 winner 字段，否则不得用它直接推断 WIN/LOSS。
4. market close 后轮询上述 winner source。
5. 如果无法确认，则标记 UNKNOWN。

不得把独立 CLOB/WS 客户端当作 live book 或交易真相；结算证据路径与 DataEngine book 路径分离。

### 20.2 结果状态

| 状态 | 说明 |
|------|------|
| WIN | paper side 与最终 outcome 一致 |
| LOSS | paper side 与最终 outcome 不一致 |
| VOID | 市场取消、无效、无法正常结算 |
| UNKNOWN | 暂时无法确认结果 |

### 20.3 二元市场 PnL（report-only）

与 §13.7 相同：`shares` / `entry_price` / `stake_usdc` **必须**来自 Nautilus Cache position 投影（见 `report_result_from_projection`），不得用 `stake / entry_price` 发明持仓规模。

```
shares, entry_price, stake_usdc  ← Cache position projection
entry_fee = 0.0  # V1 fee_model=ignored_v1

if WIN:
  settlement_value = shares * 1.0
if LOSS:
  settlement_value = shares * 0.0

pnl = settlement_value - stake_usdc - entry_fee
roi = pnl / stake_usdc
```

该计算只写入 `report_results`；sandbox/live 下不得据此改写 Nautilus Account / Portfolio / Position。

## 21. Telegram 发布规则

Telegram 只消费 Reporting 投影，不得回写交易状态。

| 事件 | 默认是否发送 |
|------|-------------|
| BUY_UP / BUY_DOWN signal | 是 |
| Fill 投影（`report_fills`） | 可选，默认否 |
| Rejected decision/order 投影 | 否 |
| Result 投影（`report_results`） | 是 |
| Daily report | 是 |
| Debug | 否 |
| Watch signal | 否 |

## 22. 安全要求

| 要求 | 标准 |
|------|------|
| 无钱包密钥 | 配置和环境变量不得包含私钥 |
| 无真实交易客户端（默认） | 默认 `execution_mode=sandbox`，不注册 live Polymarket execution factory |
| 无真实交易方法（默认） | 不调用 authenticated create/post/cancel、EIP-712 signing；sandbox 允许 `order_factory` / `submit_order`。live 仅在双开关 + 配置校验通过后才可注册（见 Runtime Boundary） |
| Telegram token 脱敏 | 日志不得输出完整 bot token |
| Paper 明确标注 | 所有结果必须写明 paper only |
| 信号非建议声明 | Telegram 消息必须写明不是收益保证 |

## 23. 验收标准

### 23.1 功能验收

| 编号 | 验收项 | 标准 |
|------|--------|------|
| AC-001 | 能启动服务 | 无钱包密钥也可启动 |
| AC-002 | 能发现市场 | 当前 BTC 5m/15m market cache 包含 active、未 closed、enableOrderBook、accepting_orders、UP/DOWN token ids |
| AC-003 | 能接收 orderbook | 经 Nautilus DataClient → Cache；UP/DOWN best bid/ask 可持续投影到 MarketView |
| AC-004 | 能处理 spot 边界 | checked-in `spot_data.source=polymarket_rtds` 经 managed RTDS 入 Cache；`disabled` + 依赖 spot 的策略 fail-fast；MarketRotation 不二次发布 spot |
| AC-005 | 能生成信号 | 至少一个策略可输出 SignalCandidate |
| AC-006 | 能发送 Telegram | 频道收到格式化信号 |
| AC-007 | 能创建 paper order | 信号发布后经 `submit_order` 进入 sandbox；Cache 有 order |
| AC-008 | 能模拟成交 | sandbox 成交后 Cache fill/position 更新，并投影到 `report_*` |
| AC-009 | 能创建 position | 成交后 Cache open position 存在 |
| AC-010 | 能结算胜负 | market resolved 后写入 `report_results`（WIN/LOSS/VOID）；**不**伪造 native PositionClosed |
| AC-011 | 能统计胜率 | 日报包含 win rate（来自 `report_results`） |
| AC-012 | 能统计 PnL | 日报包含 paper PnL 和 equity（报表层） |

### 23.2 安全验收

| 编号 | 验收项 | 标准 |
|------|--------|------|
| SEC-001 | 默认无真实下单路径 | 默认配置不注册 live execution；sandbox `submit_order` 允许；live 路径 fail-closed（双开关） |
| SEC-002 | 无 Python 自建取消订单路径 | 默认不注册 live；源码无绕过 adapter 的 authenticated CLOB cancel 客户端 |
| SEC-003 | 不存在钱包密钥 | 配置 schema 拒绝钱包密钥 |
| SEC-004 | 不存在链上领取模块 | 无链上领取模块 |
| SEC-005 | 默认无真实 sell | 默认 sandbox：无真实 venue sell；sandbox exit 仅经 `order_factory`/`submit_order`；gated live 若启用，sell/exit 仅官方 ExecutionClient 且不得依赖 reduce-only |
| SEC-006 | Telegram token 不泄露 | 日志脱敏 |

### 23.3 Nautilus paper 验收

| 编号 | 验收项 | 标准 |
|------|--------|------|
| SIM-001 | Nautilus account 正确变化 | fill 后 Cache account/portfolio 更新；`report_account_snapshots` 投影 |
| SIM-002 | shares 来自 Cache | `report_results.shares` 等于 Cache position projection（非 `stake/entry` 自造） |
| SIM-003 | WIN 结算正确（报表） | `report_results.settlement_value = shares`；不改 Account |
| SIM-004 | LOSS 结算正确（报表） | `report_results.settlement_value = 0`；不改 Account |
| SIM-005 | PnL 正确（报表） | `report_results.pnl = settlement - stake - entry_fee`（inputs 来自 Cache 投影） |
| SIM-006 | fee model 明确 | V1 写入 `fee_model=ignored_v1` 与 `entry_fee=0.0`；fee parity 仍为后续可选增强 |
| SIM-007 | stale book 不成交 | `SignalGate` 拒绝 `STALE_ORDERBOOK`；不进入 `submit_order` |
| SIM-008 | ask 超价不成交 | `SignalGate` 拒绝 `ASK_ABOVE_MAX_ENTRY` |
| SIM-009 | 余额不足不成交 | **RiskEngine** 拒绝；非本地 Account gate |
| SIM-010 | 结果写入日志 | `report_results`（SQLite + JSONL）有完整记录 |

## 24. 实施阶段（已完成）

> 以下阶段为历史交付叙事（部分命名已过时）。**当前架构真相**见 [`ARCHITECTURE_OWNERSHIP.md`](ARCHITECTURE_OWNERSHIP.md)、[`RUNTIME_BOUNDARY.md`](RUNTIME_BOUNDARY.md)。

### Phase 1：项目骨架与安全边界 ✅

交付：
- 项目名 PolySignal Lab。
- 配置 schema。
- 禁止钱包密钥和真实交易客户端。
- JSONL storage。
- Telegram test message。

### Phase 2：市场数据层 ✅

交付：
- Polymarket market discovery。
- Polymarket market data via Nautilus DataClient / Cache。
- Spot via managed Polymarket RTDS `LiveDataClient`（非 Binance 直连）。
- `MarketView` 投影（取代独立 MarketSnapshot 真相）。

### Phase 3：策略信号层 ✅

交付：
- VWAP Momentum core。
- PTB Diff core。
- Late Consensus core。
- Signal gate（业务资格）。
- ~~Dedupe / rate-limit gate~~（已从 `SignalGate` 移除；不得再当作第二决策总线）。

### Phase 4：Telegram 信号层 ✅

交付：
- Signal formatter。
- Telegram publisher。
- Signal publish log。
- ~~Gate 内 channel rate limit~~（已移除；发布侧保留产品节奏控制，非 RiskEngine）。

### Phase 5：Nautilus Paper Runtime ✅

交付：
- Nautilus `LiveNode` + sandbox execution（默认）。
- Nautilus native order submission（`order_factory` / `submit_order`）。
- Nautilus sandbox paper execution。
- Nautilus order/fill/position/account Cache 投影 + `report_*` 存储。
- Hold-to-resolution **report-only** settlement。
- `report_results` 日志 / SQLite。

### Phase 6：统计与日报 ✅

交付：
- win/loss report。
- strategy breakdown。
- asset breakdown。
- timeframe breakdown。
- Telegram daily paper report。

## 25. 第一版范围（已完成）

以下项在初始实施中交付；当前系统已包含更多功能（见 Section 26）。

**第一版必须包含：**
- ✅ 项目名：PolySignal Lab。
- ✅ BTC 5m / 15m market discovery。
- ✅ Polymarket market data。
- ✅ Polymarket RTDS BTC spot（managed LiveDataClient）。
- ✅ VWAP Momentum。
- ✅ PTB Diff。
- ✅ Telegram signal。
- ✅ Nautilus paper account projection。
- ✅ Nautilus paper order projection。
- ✅ Nautilus sandbox fill / position projection。
- ✅ Hold-to-resolution result。
- ✅ Win/Loss/PnL 日志。
- ✅ Telegram paper result。

**第一版暂缓（后已交付）：**
- ✅ ETH / SOL / XRP — 已增加多资产支持。
- ✅ Late Consensus（策略 alpha）— 已实现。
- ❌ 跨策略 Consensus / Arbiter 总线 — **已移除**；不得再当作产品能力。
- ✅ SQLite — 已实现 canonical `report_*` storage。
- ✅ Web dashboard — 已实现（只读）。
- ✅ Daily report — 已实现。
- ✅ TP/SL paper exit — `NativeExitPolicy` + `trading.exit_model`（sandbox 可 reduce-only；非 venue bracket）。
- ⏳ 历史 replay 产品化 — 不在当前默认范围。
- ⏳ 付费频道 — 不适用。

## 26. 第二版范围（大部分已完成）

> 第二版项已在迁移至 Nautilus Runtime 和最终合规修复过程中交付。

- ✅ Late Consensus（策略 alpha）— 已交付。
- ✅ 多资产 BTC / ETH / SOL / XRP — 已交付。
- ❌ 跨策略 Consensus / Arbiter 总线 — **已移除**（与 Nautilus 单决策路径对齐）。
- ✅ SQLite — 已交付。
- ✅ Daily report — 已交付。
- ✅ Paper TP/SL — `NativeExitPolicy` 已交付；early exit 写入 `report_results`（`exit_mode` = TAKE_PROFIT / STOP_LOSS / MAX_HOLD_TIME）。全局阈值以 `trading.exit_model` 为准；非 venue bracket。
- ✅ Dashboard — 已交付（只读）。
- ✅ Strategy leaderboard — 已交付。

### 当前额外交付项（超出原始第二版范围）

- 13+ AlphaCore 策略实现（超过原始 3 个）。
- Nautilus L1/L2 market data 订阅（Cache 真相）。
- Resolution evidence via Gamma / public market metadata（report-only；无 redeem/payout 权限）。
- Observability / telemetry（`system_events`、JSONL best-effort）。
- 健康检查与自动化日报。
- 生产级容器化（Docker Compose）。
- 安全扫描（`polysignal-safety-scan`）与合规 CI。
- Strategy 内 in-process `DecisionPolicy` / `SignalGate`（gate-only；账户风险归 RiskEngine）。

## 27. 成功指标

| 指标 | 目标 |
|------|------|
| 默认配置真实 live 下单路径 | 0（未满足双开关前不得注册 live factory） |
| 钱包密钥使用 | 0 |
| Telegram 信号成功率 | >= 99% |
| paper order 创建率（sandbox submit） | >= 95% |
| stale paper fill | 0 |
| paper result 可结算率（`report_results`） | >= 95% |
| signal log 完整率 | 100% |
| paper result log 完整率 | 100% |
| 重复 in-flight 提交率 | 由 Strategy pipeline 抑制 |
| 每日统计生成率 | 100% |

## 28. 最终产品定义

PolySignal Lab 是一个非托管、默认 sandbox、安全边界清晰的 Polymarket 短周期信号与模拟验证系统。默认配置不会替用户在真实 venue 下单；它从 Nautilus Cache / CustomData 生成结构化信号，发送到 Telegram，并用 sandbox Cache/Portfolio 记录这些信号若被执行后的纸面输赢，结算结果以 **report-only** 写入报表层。系统的核心价值不是自动交易，而是把策略信号、人工参考、paper PnL、胜率统计和策略淘汰机制统一在一个可审计、且不违反 Nautilus 交易真相所有权的框架中。
