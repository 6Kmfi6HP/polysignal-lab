# PolySignal Lab — PRD (Product Requirements Document)

## 1. 文档状态

| 项目 | 内容 |
|------|------|
| 产品名称 | PolySignal Lab |
| 产品类型 | Polymarket 短周期信号 + 模拟交易验证系统 |
| 当前阶段 | PRD |
| 开发范围 | 只读行情、策略信号、Telegram 发布、简单模拟交易、胜负统计 |
| 明确不做 | 不真实下单、不签名、不接触钱包密钥、不托管资金、不自动链上领取 |
| 核心目标 | 将 3 个独立 Polymarket 机器人重构为一个统一信号与模拟验证系统 |

## 2. 一句话定义

PolySignal Lab 是一个只读 Polymarket 短周期市场信号系统。它把 VWAP Momentum、Late Consensus、PTB Diff 三类策略统一成信号模块，将信号发送到 Telegram 频道，同时用虚拟资金做简单模拟交易，用于记录每条信号的纸面输赢、胜率、资金曲线和策略质量。

## 3. 背景

原始仓库包含 3 个独立 Polymarket crypto Up/Down bot：

- **btc-binary-VWAP-Momentum-bot** — BTC 单资产。使用 VWAP、momentum、deviation、z-score 判断短周期方向。原始实现包含真实订单执行、hedge、链上领取、dashboard、Telegram。
- **up-down-spread-bot** — BTC / ETH / SOL / XRP 多资产。使用 late-entry、spread、ask skew、confidence、favorite side 判断方向。原始实现包含多资产 desk、stop-loss、flip-stop、Telegram command。
- **5min-15min-PTB-bot** — BTC 为主。使用 Binance spot、Polymarket price-to-beat、UP/DOWN implied probability 判断方向。原始实现包含 AUTO_TRADE、simulation、TP/SL、Web dashboard。

新项目不复用这些 bot 的真实执行逻辑，而是抽象其策略原理，统一变成：

```
Public Market Data → Nautilus Strategy Callback → Signal Gate → Telegram → Nautilus Sandbox Paper Execution → Win/Loss Report
```

## 4. 产品目标

### 4.1 核心目标

| 目标 | 说明 |
|------|------|
| 统一三套策略 | 3 个机器人不再各自运行 runtime，而是变成统一策略模块 |
| 只读安全 | 不读取私钥，不创建订单，不调用真实交易 API |
| Telegram 信号 | 每条可交易信号发送到 Telegram 频道 |
| Nautilus 纸面验证 | 每条通过 gate 的信号可由 Nautilus sandbox 生成虚拟 order/fill/position |
| 知道输赢 | 市场结束后计算每笔纸面持仓是否盈利 |
| 可审计 | 每条信号、Nautilus order/fill/position 投影、结算结果都落日志 |
| 可复盘 | 支持按策略、资产、周期统计胜率和 PnL |
| 可扩展 | 后续可加入新策略、Discord、Webhook、dashboard |

### 4.2 非目标

| 非目标 | 说明 |
|--------|------|
| 真实交易 | 不真实买卖 Polymarket token |
| 钱包管理 | 不读取钱包密钥环境变量，不创建 Polymarket API key |
| 自动链上领取 | 不做链上领取 |
| 自动平仓 | 第一版不做真实 sell；paper mode 可做虚拟 exit |
| 盈利承诺 | 只统计纸面验证结果，不承诺实盘可复制 |
| 复杂回测 | 第一版只做实时 Nautilus paper validation，不做完整历史 replay |
| 付费频道 | 第一版不做会员、订阅、支付 |

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
| 读取 Polymarket market data | 允许 |
| 读取 Binance spot | 允许 |
| 计算信号 | 允许 |
| Telegram 发消息 | 允许 |
| 虚拟资金模拟 | 允许 |
| 记录 paper orders | 允许 |
| 统计 paper win/loss | 允许 |
| 生成日报 | 允许 |

### 7.2 禁止能力

| 能力 | 是否禁止 |
|------|----------|
| 读取钱包私钥 | 禁止 |
| 创建真实 Polymarket 订单 | 禁止 |
| 取消真实订单 | 禁止 |
| 签名 EIP-712 order | 禁止 |
| 自动链上领取 | 禁止 |
| 自动转账 | 禁止 |
| CEX 真实下单 | 禁止 |

## 8. 产品形态

PolySignal Lab 是一个后台常驻服务，第一版不要求完整 Web UI。

```
┌────────────────────────────┐
│ Public Polymarket Data      │
│ Nautilus CustomData Payloads│
└──────────────┬─────────────┘
               ↓
┌────────────────────────────┐
│ Nautilus TradingNode     │
│ - DataEngine callbacks   │
│ - Strategy lifecycle     │
└──────────────┬─────────────┘
               ↓
┌────────────────────────────┐
│ PolySignal Alpha Cores      │
│ - VWAP Momentum             │
│ - Late Consensus            │
│ - PTB Diff                  │
└──────────────┬─────────────┘
               ↓
┌────────────────────────────┐
│ DecisionPolicyActor         │
│ Gate / dedupe / consensus   │
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
4. 初始化 Nautilus `TradingNode` / `TradingNodeConfig` paper runtime，并注册 data/exec client factories。
5. 发现当前 Polymarket crypto Up/Down 市场。
6. Nautilus data path 接收 Polymarket market data。
7. Nautilus `CustomData` callbacks 接收 spot、price-to-beat、market metadata；managed RTDS spot data client 负责现货 ingress。
8. Nautilus strategy callbacks 构造 market view 并运行 alpha core。
9. 信号通过 `DecisionPolicyActor` 的 gate / dedupe / consensus。
10. 通过 gate 后发送 Telegram。
11. Strategy wrapper 通过 Nautilus order factory / `submit_order` 提交 paper order。
12. Nautilus sandbox 生成 paper fills / positions / account state。
13. 市场结束后结算 paper position projection。
14. 更新胜率、PnL、资金曲线。

### 9.2 信号流程

```
Nautilus Data / Custom Data Callback
  → PolySignal AlphaCore.evaluate()
  → AlphaDecision
  → DecisionPolicyActor
  → TelegramMessage
  → Nautilus native order
  → Nautilus sandbox fill / position
  → SettlementResolver / `_settlement_check` position projection
```

### 9.3 纸面交易流程

1. 通过 gate 的信号由 Nautilus strategy wrapper 映射为 Nautilus native order 参数。
2. Strategy wrapper 调用 Nautilus `order_factory.limit(...)` 和 `submit_order(...)`。
3. Nautilus sandbox 根据当前 instrument、book、trade 数据处理 paper order。
4. 订单状态、成交、持仓、账户状态来自 Nautilus cache/portfolio。
5. PolySignal 将 Nautilus events/projected cache rows 写入 SQLite/JSONL、Telegram、日报和 dashboard。
6. 市场结束后的 win/loss 计算只读取 Nautilus position projection 和 Polymarket outcome resolution，不维护本地 PaperWallet。
7. 写入 PaperTradeResult projection。
8. 更新统计报表。

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
| UP / DOWN best bid ask | Polymarket CLOB |
| last trade price | Polymarket CLOB |
| orderbook depth | Polymarket CLOB |
| BTC spot | Nautilus `CustomData` spot payload；checked-in default disables actor-owned `polymarket_rtds` until a managed Nautilus data-client lifecycle exists |
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
- 当前 market active、未 closed、CLOB order book enabled、accepting_orders=true。
- 当前 orderbook fresh，且 UP / DOWN token ids 可映射到 WebSocket asset ids。
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
| UP / DOWN ask | Polymarket CLOB |
| best bid ask | Polymarket CLOB |
| ask sum | Derived |
| ask skew | Derived |
| spread | Derived |
| asset spot movement | Nautilus `CustomData` spot payload；actor-owned RTDS source is disabled by default and explicit `polymarket_rtds` is fail-fast |
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
| BTC spot price | Nautilus `CustomData` spot payload；actor-owned RTDS source is disabled by default and explicit `polymarket_rtds` is fail-fast |
| price_to_beat | 本地 market window anchor；若使用 Polymarket price-to-beat endpoint，必须标记为未正式 API ref 依赖 |
| UP / DOWN implied price | Polymarket CLOB |
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

所有策略输出统一 SignalCandidate。

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
| 真实公开行情 | 使用 Polymarket public market data 和 Nautilus `CustomData` spot/PTB/market metadata payloads |
| Nautilus 纸面账户 | 使用 Nautilus sandbox/cache/portfolio state，不接触真实资金 |
| 可解释成交 | 每笔 paper fill 必须能追溯到 Nautilus order/fill/position 投影 |
| 保守标注 | 不承诺 paper result 可复制到真实交易 |
| 可复盘 | 所有 paper order / fill / result 投影都写日志 |
| 可关闭 | paper validation 可配置关闭，只保留信号 |

### 13.3 Nautilus Paper Account Projection

```yaml
paper_trading:
  enabled: true
  starting_balance_usdc: 1000.0
  stake_mode: fixed
  fixed_stake_usdc: 10.0
  max_open_positions: 10
  max_market_exposure_usdc: 30.0
  max_strategy_exposure_usdc: 100.0
```

字段名中的 `usdc` 表示 paper USD-equivalent accounting，不表示真实 Polymarket 钱包余额。Polymarket 外部抵押/赎回术语以官方 docs 的 pUSD 为准；paper 报表必须标注为 synthetic paper accounting。

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

Paper order 是 Nautilus strategy wrapper 通过 order factory / `submit_order` 提交的虚拟订单投影。

```json
{
  "paper_order_id": "nautilus_order_20260621_0001",
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

1. Strategy wrapper 将 approved decision 映射为 Nautilus native paper order。
2. Nautilus sandbox 根据当前 instrument、book、trade 数据处理 order。
3. 订单状态、成交、持仓、账户状态来自 Nautilus cache/portfolio。
4. PolySignal 将 Nautilus events/projected cache rows 写入 SQLite/JSONL、Telegram、日报和 dashboard。
5. 如果数据过旧、instrument 缺失或 policy 不通过，则记录 rejected decision / rejected order projection。
6. V1 paper PnL 默认 fee-free，必须写入 `fee_model=ignored_v1`；如果启用 Polymarket fee parity，则用 CLOB market fee schedule 计算 taker fee。

**当前配置：**

```yaml
runtime:
  engine: nautilus
  nautilus:
    execution_mode: paper_sandbox
    allow_live_polymarket_execution: false
    sidecar:
      spot_source: polymarket_rtds
      price_to_beat_source: anchor_or_gamma
```

Checked-in runtime uses the Nautilus-managed RTDS `LiveDataClient` for spot ingress. Setting `spot_source: disabled` while enabling a spot-dependent native strategy fails fast; it does not silently fall back to an actor-owned sidecar.

**成交拒绝原因示例：**

| 原因 | 说明 |
|------|------|
| ASK_ABOVE_MAX_ENTRY | ask 已超过信号最高价 |
| INSUFFICIENT_DEPTH | orderbook depth 不足 |
| STALE_ORDERBOOK | orderbook 过旧 |
| ACCOUNT_INSUFFICIENT_CASH | Nautilus paper account 余额不足 |
| EXPOSURE_LIMIT_REACHED | 达到 paper exposure 限制 |

### 13.6 Paper Position Projection

Nautilus fill 后创建 position projection。

```json
{
  "paper_position_id": "pp_20260621_0001",
  "signal_id": "20260621-BTC-5m-UP-ptb_diff-0001",
  "paper_order_id": "po_20260621_0001",
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

第一版默认使用"持有到结算"。

**默认模式：Hold To Resolution**

| 结果 | 结算 |
|------|------|
| 预测正确 | 每 share 兑付 1.00 paper USD-equivalent |
| 预测错误 | 每 share 兑付 0.00 paper USD-equivalent |

**PnL 计算：**

```
shares = stake_usdc / entry_price
entry_fee = 0.0  # V1 fee_model=ignored_v1
settlement_value = shares * outcome_value
pnl = settlement_value - stake_usdc - entry_fee
roi = pnl / stake_usdc
```

其中：
- outcome_value = 1.0 if side wins else 0.0
- outcome_value = 0.0 if side loses
- 如果开启 fee parity，entry_fee 必须按 Polymarket market fee schedule 计算并写入 result。

**胜负判断：**

| 条件 | 结果 |
|------|------|
| side = UP 且市场最终 UP | WIN |
| side = DOWN 且市场最终 DOWN | WIN |
| side = UP 且市场最终 DOWN | LOSS |
| side = DOWN 且市场最终 UP | LOSS |
| 市场取消 / unresolved | VOID |
| 无法获取结算结果 | UNKNOWN |

### 13.8 Paper TP/SL（已交付）

默认由 `NativeExitPolicy` 在 Nautilus Cache 持仓上评估；触发后提交 **reduce-only** paper sell，并写入 `paper_trade_results`。

```yaml
paper_trading:
  exit_model:
    mode: hold_to_resolution_with_optional_tp_sl
    take_profit_enabled: true
    stop_loss_enabled: true
    take_profit_price: 0.90
    stop_loss_price: 0.35
    max_hold_time_sec: 900
```

架构约束：
- 不使用 Nautilus contingent / bracket 子单（sandbox `support_contingent_orders=false`）。
- 只影响 paper result，不发送真实卖单。
- V1 fee：`fee_model=ignored_v1`，`entry_fee=0.0`。

### 13.9 Paper Trade Result

```json
{
  "paper_trade_id": "pt_20260621_0001",
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
| paper_orders | paper order 数 |
| paper_fills | paper 成交数 |
| rejected_paper_orders | paper 拒绝数 |
| open_positions | 当前虚拟持仓 |
| closed_positions | 已结算持仓 |
| win_count | 赢的次数 |
| loss_count | 输的次数 |
| void_count | void 次数 |
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
  paper_trade_results.jsonl   # 历史 PRD 名 paper_results.jsonl 已废弃
  telegram_publishes.jsonl    # 历史 PRD 名 telegram_publish.jsonl 已废弃
  daily_reports.jsonl
  system_events.jsonl         # 可选 / best-effort telemetry
```

Runtime state 以 Nautilus Cache/Portfolio 为准；`state/` 下保留 heartbeat / monitor 等进程级快照，不再把 `open_positions.json` 当作持仓真相。

### 15.2 SQLite 表（当前）

| 表 | 用途 |
|----|------|
| signals | 所有通过 gate 的信号 |
| rejected_signals | 被拒绝信号 |
| paper_trade_results | 纸面验证结果（含 resolution 与 early TP/SL exit） |
| paper_wallet_snapshots | Nautilus account/portfolio projection 快照 |
| paper_order_states | order 最新生命周期状态（current-state projection） |
| paper_position_states | position 最新生命周期状态（current-state projection） |
| daily_reports | 每日报告（可 revision） |
| report_publish_outbox | 日报 Telegram 投递 outbox |
| system_events | Nautilus order/fill/position 等审计事件 |
| telegram_publishes | Telegram 发布审计 |
| markets | 市场元数据缓存 |
| anchor_prices | price-to-beat anchor 缓存 |

历史 PRD 中的独立 `paper_orders` / `paper_fills` / `paper_positions` 表已收敛为 `system_events` 事件流 + `paper_*_states` 当前状态投影。

## 16. 架构设计

### 16.1 目录结构

```
polysignal-lab/
  config/
    signal_bot.yaml

  src/polysignal_lab/
    app/
      main.py
      _settlement_check.py
      scheduler_health.py
      scheduler_reporting.py
      scheduler_reporting_storage.py
      scheduler_shared.py
      readonly_smoke.py
      readonly_smoke_public.py
      readonly_smoke_runtime.py
      readonly_smoke_types.py
      services/
        market_universe_service.py
        persistence_service.py
        publish_service.py

    alpha/
      vwap_momentum_core.py
      late_consensus_core.py
      ptb_diff_core.py
      binary_momentum_core.py
      cross_market_core.py
      dump_hedge_core.py
      fibonacci_core.py
      low_side_dual_reversion_core.py
      mid_price_sizing_core.py
      ninety_nine_cent_sniper_core.py
      one_cent_buy_core.py
      pre_order_market_core.py
      skew_mean_reversion_core.py
      types.py
      state.py

    config.py
    healthcheck.py

    data/
      polymarket_market_discovery.py
      binance_spot_ws.py
      market_snapshot.py
      market_discovery_helpers.py
      anchor_price_service.py
      book_reconciliation.py
      ctf_resolution_client.py
      gamma_resolution_client.py
      price_to_beat_provider.py
      public_market_data_client.py
      rate_limiter.py
      spot_tick.py
      state.py

    domain/
      market.py
      orderbook.py
      signal.py
      paper_order.py
      paper_position.py
      paper_result.py
      anchor_price.py
      enums.py
      freshness.py
      snapshot.py
      snapshot_batch.py
      spot.py
      strategy_config.py
      strategy_readiness.py
      trade.py

    nautilus_bridge/
      market_catalog.py
      market_view_assembler.py
      instrument_mapping.py
      state.py

    nautilus_runtime/
      node.py
      live_node.py
      native_strategy.py
      native_order.py
      cache_reader.py
      cache_market_data.py
      decision_policy.py
      decision_policy_actor.py
      observability.py
      node_builder.py
      node_cache_projection.py
      node_cli.py
      node_crash.py
      node_lifecycle.py
      node_probes.py
      node_shared.py
      node_sidecar.py
      node_signals.py
      node_trader_registration.py
      market_data.py
      market_rotation.py
      strategy_builder.py
      strategy_schedule.py
      custom_data_state.py
      custom_data_types.py
      group_views.py
      observability_persistence.py
      order_mapping.py
      order_plan.py
      projection_recorder.py
      projections.py
      runtime_context_factory.py
      sidecar_data.py
      signal_sidecar.py
      telemetry_writer.py
      strategy/
        custom_data_handlers.py
        data_boundary.py
        decision_pipeline.py
        event_handlers.py
        event_projection.py
        helpers.py
        subscriptions.py
      strategies/
        cross_market_bot.py

    observability/
      logger.py
      health.py
      metrics.py
      runtime_health.py
      safety.py

    paper/
      settlement_resolver.py
      settlement_sources.py
      report.py
      strategy_stats.py

    publish/
      telegram_publisher.py
      telegram_bot.py
      telegram_qa.py

    signal_layer/
      gate.py
      deduper.py
      consensus.py
      arbiter.py
      formatter.py
      rate_limit.py

    storage/
      jsonl_store.py
      sqlite_store.py
      sqlite_schema.py
      state_store.py

    dashboard/
      app.py

    utils.py

  tests/
  logs/  (generated)
  state/  (generated)
  data/  (generated)
```

### 16.2 主要模块职责

| 模块 | 职责 |
|------|------|
| app/main.py | CLI 入口, runtime mode 分派 |
| AlphaCore (alpha/) | 产生 engine-agnostic AlphaDecision |
| Nautilus TradingNode | 拥有 strategy lifecycle、DataEngine/ExecutionEngine、cache、portfolio 和 paper order lifecycle |
| PolySignalNativeStrategy | 在 Nautilus callbacks 中运行 alpha core, 处理 order/fill/position events |
| DecisionPolicyActor | gate / dedupe / consensus / arbiter 检查 |
| NautilusDecisionPolicyActor | DecisionPolicyActor 的 Nautilus Actor 生命周期封装 |
| NautilusSandboxExecution | 处理 paper orders, fills, positions, account state |
| NautilusCacheReader | 只读投影 Nautilus orders/fills/positions/account/portfolio |
| NautilusProjectionRecorder | 将 Nautilus events 持久化到 SQLite system_events |
| MarketCatalog (nautilus_bridge/) | 业务 key 查找, condition/token 映射 |
| MarketViewAssembler | 从 cache 投影 + custom data 组装只读 market view |
| TelegramPublisher | 发送信号, 结果, 日报 |
| SignalGate (signal_layer/) | 市场活跃, 时间窗口, 新鲜度, spread, 去重, 频控 |
| SettlementResolver / `_settlement_check` | 从 Nautilus open position projection 和 Polymarket resolution evidence 生成 PaperTradeResult projection；不伪造 native payout 或 PositionClosed |
| Dashboard API | FastAPI 只读 JSON API + HTML 首页 |
| Storage | SQLite + JSONL + state |

## 17. 配置设计

```yaml
app:
  name: PolySignal Lab
  mode: signal_plus_paper
  timezone: Asia/Bangkok
  log_level: INFO

telegram:
  enabled: true
  bot_token_env: TELEGRAM_BOT_TOKEN
  channel_id_env: TELEGRAM_CHANNEL_ID
  send_signals: true
  send_paper_results: true
  send_daily_report: true

markets:
  assets: [BTC, ETH, SOL, XRP]
  timeframes: [5m, 15m]
  refresh_interval_sec: 10

data:
  polymarket:
    use_market_ws: true
    max_book_staleness_ms: 1500

runtime:
  nautilus:
    sidecar:
      spot_source: polymarket_rtds
      price_to_beat_source: anchor_or_gamma

signal:
  min_confidence_to_publish: 0.50
  dedupe_enabled: true
  consensus_enabled: true
  max_signals_per_market: 3
  max_signals_per_hour: 60

paper_trading:
  enabled: true
  starting_balance_usdc: 1000.0
  stake_mode: fixed
  fixed_stake_usdc: 10.0
  max_open_positions: 10
  max_market_exposure_usdc: 30.0
  max_strategy_exposure_usdc: 100.0
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

每条信号必须经过 gate。

| Gate | 拒绝原因 |
|------|----------|
| Market Active Gate | MARKET_NOT_ACTIVE |
| Market Closed Gate | MARKET_CLOSED |
| Order Book Enabled Gate | ORDER_BOOK_NOT_ENABLED |
| Accepting Orders Gate | MARKET_NOT_ACCEPTING_ORDERS |
| Token Mapping Gate | CLOB_TOKEN_IDS_MISSING |
| Book Freshness Gate | STALE_ORDERBOOK |
| Spot Freshness Gate | STALE_SPOT_PRICE |
| Spread Gate | SPREAD_TOO_WIDE |
| Max Entry Gate | ASK_ABOVE_MAX_ENTRY |
| Confidence Gate | CONFIDENCE_TOO_LOW |
| Dedupe Gate | DUPLICATE_SIGNAL |
| Rate Limit Gate | CHANNEL_RATE_LIMIT |

## 19. Paper Policy Gates

每条 approved signal 进入 Nautilus order submission 前还要经过 paper policy gates。

| Gate | 拒绝原因 |
|------|----------|
| Account Gate | ACCOUNT_INSUFFICIENT_CASH |
| Exposure Gate | EXPOSURE_LIMIT_REACHED |
| Depth Gate | INSUFFICIENT_DEPTH |
| Price Gate | ASK_ABOVE_MAX_ENTRY |
| Position Limit Gate | MAX_OPEN_POSITIONS_REACHED |

## 20. 胜负判断

### 20.1 市场结算来源

优先级：
1. Polymarket market WebSocket `market_resolved.winning_asset_id` / `winning_outcome`。
2. CLOB / public market token metadata 中的 `tokens[].winner`。
3. UMA / Gamma resolution status 只作为 lifecycle/status 信号；除非官方 schema 明确提供 winner 字段，否则不得用它直接推断 WIN/LOSS。
4. 本地 market close 后轮询上述 winner source。
5. 如果无法确认，则标记 UNKNOWN。

### 20.2 结果状态

| 状态 | 说明 |
|------|------|
| WIN | paper side 与最终 outcome 一致 |
| LOSS | paper side 与最终 outcome 不一致 |
| VOID | 市场取消、无效、无法正常结算 |
| UNKNOWN | 暂时无法确认结果 |

### 20.3 二元市场 PnL

```
shares = stake_usdc / entry_price
entry_fee = 0.0  # V1 fee_model=ignored_v1

if WIN:
  settlement_value = shares * 1.0
if LOSS:
  settlement_value = shares * 0.0

pnl = settlement_value - stake_usdc - entry_fee
roi = pnl / stake_usdc
```

## 21. Telegram 发布规则

| 事件 | 默认是否发送 |
|------|-------------|
| BUY_UP / BUY_DOWN signal | 是 |
| Paper fill | 可选，默认否 |
| Paper rejected | 否 |
| Paper result | 是 |
| Daily report | 是 |
| Debug | 否 |
| Watch signal | 否 |

## 22. 安全要求

| 要求 | 标准 |
|------|------|
| 无钱包密钥 | 配置和环境变量不得包含私钥 |
| 无真实交易客户端 | 不创建需认证的 Polymarket/CLOB 交易客户端 |
| 无真实交易方法 | 不调用 authenticated Polymarket/CLOB create/post/cancel order、EIP-712 signing 或 live execution API；允许 Nautilus sandbox 内部 `order_factory` / `submit_order` |
| Telegram token 脱敏 | 日志不得输出完整 bot token |
| Paper 明确标注 | 所有结果必须写明 paper only |
| 信号非建议声明 | Telegram 消息必须写明不是收益保证 |

## 23. 验收标准

### 23.1 功能验收

| 编号 | 验收项 | 标准 |
|------|--------|------|
| AC-001 | 能启动服务 | 无钱包密钥也可启动 |
| AC-002 | 能发现市场 | 当前 BTC 5m/15m market cache 包含 active、未 closed、enableOrderBook、accepting_orders、UP/DOWN token ids |
| AC-003 | 能接收 orderbook | 通过 UP/DOWN asset ids 订阅后 best bid ask 持续更新 |
| AC-004 | 能处理 spot 边界 | 默认 actor-owned RTDS spot source 为 disabled；显式 `polymarket_rtds` 配置 fail fast，直到 Nautilus-managed data-client lifecycle 存在 |
| AC-005 | 能生成信号 | 至少一个策略可输出 SignalCandidate |
| AC-006 | 能发送 Telegram | 频道收到格式化信号 |
| AC-007 | 能创建 paper order | 信号发布后生成 paper order |
| AC-008 | 能模拟成交 | 符合 fill model 时生成 paper fill |
| AC-009 | 能创建 position | 成交后 open position 存在 |
| AC-010 | 能结算胜负 | market resolved 后 position 转 WIN/LOSS/VOID |
| AC-011 | 能统计胜率 | 日报包含 win rate |
| AC-012 | 能统计 PnL | 日报包含 paper PnL 和 equity |

### 23.2 安全验收

| 编号 | 验收项 | 标准 |
|------|--------|------|
| SEC-001 | 不存在真实下单路径 | 搜索不到 authenticated Polymarket/CLOB create/post order、EIP-712 signing 或 live execution client registration；允许 Nautilus sandbox `submit_order` |
| SEC-002 | 不存在真实取消订单路径 | 搜索不到 authenticated Polymarket/CLOB cancel order 调用 |
| SEC-003 | 不存在钱包密钥 | 配置 schema 拒绝钱包密钥 |
| SEC-004 | 不存在链上领取模块 | 无链上领取模块 |
| SEC-005 | 不存在真实 sell | 无真实 sell execution |
| SEC-006 | Telegram token 不泄露 | 日志脱敏 |

### 23.3 Nautilus paper 验收

| 编号 | 验收项 | 标准 |
|------|--------|------|
| SIM-001 | Nautilus account 正确变化 | fill 后 account/portfolio projection 更新 |
| SIM-002 | shares 计算正确 | fills/positions projection 中 shares 与 fill price 一致 |
| SIM-003 | WIN 结算正确 | settlement = shares |
| SIM-004 | LOSS 结算正确 | settlement = 0 |
| SIM-005 | PnL 正确 | pnl = settlement - stake - entry_fee |
| SIM-006 | fee model 明确 | V1 写入 `fee_model=ignored_v1` 与 `entry_fee=0.0`；fee parity 仍为后续可选增强 |
| SIM-007 | stale book 不成交 | stale 时 paper order rejected |
| SIM-008 | ask 超价不成交 | ask > max_entry_price 时 rejected |
| SIM-009 | 余额不足不成交 | account cash 不足时 rejected |
| SIM-010 | 结果写入日志 | `paper_trade_results`（SQLite + JSONL）有完整记录 |

## 24. 实施阶段（已完成）

> 以下所有阶段均已完成并交付。详细的当前架构见 `docs/PROJECT_ARCHITECTURE_VISUAL.md`。

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
- Polymarket market WebSocket。
- Binance spot feed。
- Normalized market snapshot。

### Phase 3：策略信号层 ✅

交付：
- VWAP Momentum core。
- PTB Diff core。
- Late Consensus core。
- Signal gate。
- Dedupe。

### Phase 4：Telegram 信号层 ✅

交付：
- Signal formatter。
- Telegram publisher。
- Signal publish log。
- Rate limit。

### Phase 5：Nautilus Paper Runtime ✅

交付：
- Nautilus `TradingNode` / `TradingNodeConfig` runtime。
- Nautilus native order submission。
- Nautilus sandbox paper execution。
- Nautilus order/fill/position/account projections。
- Hold-to-resolution settlement。
- Paper result log。

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
- ✅ Binance BTC spot。
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
- ✅ Late Consensus — 已实现。
- ✅ Consensus signal — 已实现。
- ✅ SQLite — 已实现 canonical storage。
- ✅ Web dashboard — 已实现。
- ✅ Daily report — 已实现。
- ✅ TP/SL paper exit — `NativeExitPolicy` + `paper_trading.exit_model`（reduce-only submit_order；非 Nautilus bracket）。
- ⏳ 历史 replay — 不在当前范围。
- ⏳ 付费频道 — 不适用。

## 26. 第二版范围（大部分已完成）

> 第二版项已在迁移至 Nautilus Runtime 和最终合规修复过程中交付。

- ✅ Late Consensus — 已交付。
- ✅ 多资产 BTC / ETH / SOL / XRP — 已交付。
- ✅ Consensus signal — 已交付。
- ✅ SQLite — 已交付。
- ✅ Daily report — 已交付。
- ✅ Paper TP/SL — `NativeExitPolicy` 已交付；early exit 写入 `paper_trade_results`（`exit_mode` = TAKE_PROFIT / STOP_LOSS / MAX_HOLD_TIME）。策略 YAML 中的 per-strategy exit 字段为 advisory metadata，全局阈值以 `paper_trading.exit_model` 为准。
- ✅ Dashboard — 已交付。
- ✅ Strategy leaderboard — 已交付。

### 当前额外交付项（超出原始第二版范围）

- 13+ AlphaCore 策略实现（超过原始 3 个）。
- Nautilus L1/L2 market data 订阅。
- Polymarket resolution 预言机集成（CTF + Gamma）。
- Nautilus 可观测性 Actor（system_events、telemetry）。
- 调度器健康检查和自动化报告。
- 生产级容器化（Docker Compose 多阶段构建）。
- 安全扫描和合规性 CI/CD。

## 27. 成功指标

| 指标 | 目标 |
|------|------|
| 真实下单路径 | 0 |
| 钱包密钥使用 | 0 |
| Telegram 信号成功率 | >= 99% |
| paper order 创建率 | >= 95% |
| stale paper fill | 0 |
| paper result 可结算率 | >= 95% |
| signal log 完整率 | 100% |
| paper result log 完整率 | 100% |
| 重复信号率 | < 2% |
| 每日统计生成率 | 100% |

## 28. 最终产品定义

PolySignal Lab 是一个非托管、只读、安全边界清晰的 Polymarket 短周期信号与模拟验证系统。它不会替用户下单，只会从实时市场数据中生成结构化信号，发送到 Telegram，并用虚拟资金记录这些信号如果被执行后的纸面输赢。系统的核心价值不是自动交易，而是把策略信号、人工参考、paper PnL、胜率统计和策略淘汰机制统一在一个可审计框架中。
