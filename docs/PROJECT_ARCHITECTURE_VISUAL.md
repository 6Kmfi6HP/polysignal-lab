# PolySignal Lab 项目架构图解

> 生成日期：2026-06-23  
> 范围：当前仓库 `src/polysignal_lab/`、`config/`、`tests/`、运行入口与主要数据流。

## 1. 一句话概览

PolySignal Lab 是一个 **只读 Polymarket 短周期信号 + Nautilus 纸面交易验证系统**：读取公开 Polymarket 行情和 Nautilus `CustomData` 业务数据，在 Nautilus `LiveNode` strategy callbacks 中运行策略，通过 gate/共识层过滤，默认 dry-run 发布 Telegram，并将 Nautilus order/fill/position/account 投影、结算和日报写入 SQLite/JSONL，最后由 FastAPI Dashboard 只读展示。

## 2. 总体架构

```mermaid
flowchart TB
  CLI["CLI 入口<br/>polysignal-lab"] --> Main["app/main.py"]

  Main --> Nautilus["Nautilus Runtime"]
  Main --> Dashboard["Dashboard 模式"]
  Main --> Smoke["Smoke 检查模式"]

  Nautilus --> TN["Nautilus LiveNode"]
  PM["Polymarket public market data"] --> TN
  CustomData["Spot / PTB / Market Metadata<br/>Nautilus CustomData"] --> TN

  TN --> Strategies["Nautilus Strategy Wrappers"]
  Strategies --> Alpha["PolySignal Alpha Cores"]
  Alpha --> Policy["DecisionPolicyActor<br/>gate / dedupe / consensus"]
  Policy --> Orders["Nautilus native orders"]
  Orders --> Sandbox["Nautilus Sandbox<br/>paper execution"]
  Sandbox --> Cache["Nautilus Cache / Portfolio"]

  Cache --> Projection["PolySignal projections"]
  Projection --> Store["存储层<br/>SQLite + JSONL + state"]
  Projection --> Telegram["Telegram Publisher<br/>默认 dry-run"]
  Store --> DashboardApp["FastAPI 只读 Dashboard"]
  Dashboard --> DashboardApp
```

## 3. 一次 Nautilus 纸面交易循环

```mermaid
sequenceDiagram
  participant N as Nautilus LiveNode
  participant D as DataEngine / Custom Data
  participant Strat as Nautilus Strategy Wrapper
  participant Core as PolySignal AlphaCore
  participant Policy as DecisionPolicyActor
  participant Ex as Nautilus Sandbox Execution
  participant Cache as Nautilus Cache/Portfolio
  participant Proj as PolySignal Projection
  participant Tg as Telegram
  participant DB as SQLite/JSONL

  D->>N: Polymarket market data + Nautilus CustomData
  N->>Strat: on_data / on_order_book_deltas / on_trade_tick
  Strat->>Core: evaluate(MarketView)
  Core-->>Strat: AlphaDecision[]
  Strat->>Policy: gate / dedupe / consensus

  alt accepted
    Strat->>Tg: 发布信号，默认 dry-run
    Strat->>Ex: order_factory.limit + submit_order
    Ex->>Cache: order / fill / position / account state
    Cache->>Proj: read-only projection
    Proj->>DB: 存 Nautilus order/fill/position projection
  else rejected
    Policy->>Proj: rejected decision
    Proj->>DB: 存 rejected_signals
  end

  Proj->>DB: 结算 / 日报 / leaderboard
```

## 4. 目录分层

```mermaid
flowchart LR
  Root["polysignal-lab"] --> Config["config/<br/>运行配置"]
  Root --> Src["src/polysignal_lab/"]
  Root --> Tests["tests/<br/>测试套件"]
  Root --> Docs["docs/<br/>交付/PRD 文档"]
  Root --> Scripts["scripts/<br/>安全扫描等"]

  Src --> App["app/<br/>入口 + scheduler"]
  Src --> NautilusRuntime["nautilus_runtime/<br/>LiveNode / strategy / order / projections"]
  Src --> NautilusBridge["nautilus_bridge/<br/>MarketCatalog / view assembly / state codec"]
  Src --> Alpha["alpha/<br/>策略核心逻辑"]
  Src --> Data["data/<br/>外部行情/市场数据"]
  Src --> Domain["domain/<br/>领域模型"]
  Src --> Signal["signal_layer/<br/>信号过滤/共识"]
  Src --> Paper["paper/<br/>settlement / reporting projections"]
  Src --> Storage["storage/<br/>SQLite/JSONL/state"]
  Src --> Dashboard["dashboard/<br/>FastAPI 只读面板"]
  Src --> Publish["publish/<br/>Telegram"]
  Src --> Observability["observability/<br/>日志/健康/安全"]
```

## 5. 数据流向

```mermaid
flowchart TD
  External["外部公开数据源"] --> PM["Polymarket public market data"]
  External --> CustomData["Spot / PTB / market metadata<br/>Nautilus CustomData"]

  PM --> TN["Nautilus LiveNode"]
  CustomData --> TN

  TN --> Wrapper["Nautilus Strategy Wrapper"]
  Wrapper --> Core["PolySignal AlphaCore"]
  Core --> Decision["AlphaDecision"]
  Decision --> Policy["DecisionPolicyActor"]

  Policy -->|通过| Order["Nautilus native order"]
  Policy -->|拒绝| Rejected["RejectedSignal"]

  Order --> Sandbox["Nautilus sandbox paper execution"]
  Sandbox --> Cache["Nautilus Cache / Portfolio"]
  Cache --> Projection["Read-only projection"]

  Projection --> Audit["SQLite + JSONL"]
  Rejected --> Audit
  Projection --> Dashboard["只读 Dashboard"]
  Projection --> Report["日报 / Leaderboard"]
  Projection --> Telegram["Telegram 消息"]
```

## 6. 安全边界

```mermaid
flowchart TB
  subgraph Allowed["允许"]
    PublicData["公开行情数据读取"]
    SignalOnly["Nautilus strategy 信号生成"]
    PaperOnly["Nautilus sandbox 纸面交易"]
    ReadDashboard["只读 Dashboard"]
    DryTelegram["Telegram dry-run 默认"]
  end

  subgraph Blocked["明确禁止"]
    Secrets["钱包私钥 / seed / mnemonic"]
    SecureClient["Authenticated CLOB client"]
    LiveOrders["真实下单 / 撤单"]
    Redeem["链上赎回"]
    AdminAPI["Dashboard 写操作"]
  end

  PublicData --> SignalOnly --> PaperOnly --> ReadDashboard
```

## 7. 核心文件地图

| 区域 | 文件/目录 | 职责 |
|---|---|---|
| CLI 入口 | `src/polysignal_lab/app/main.py` | 解析 runtime mode；生产配置默认启动 Nautilus |
| Nautilus 入口 | `src/polysignal_lab/nautilus_runtime/node.py` | 组装 LiveNode、actor、strategy、cache projection |
| Nautilus 配置 | `src/polysignal_lab/nautilus_runtime/live_node.py` | 通过 LiveNode builder 注册 Polymarket data client 与 sandbox paper execution client |
| Nautilus 策略 | `src/polysignal_lab/nautilus_runtime/native_strategy.py` | 在 Nautilus callbacks 中运行 alpha core、处理 order/fill/position events |
| Nautilus 下单 | `src/polysignal_lab/nautilus_runtime/native_order.py` | 将 approved decision 映射为 Nautilus native limit order |
| Nautilus 投影 | `src/polysignal_lab/nautilus_runtime/cache_reader.py` | 只读读取 Nautilus orders/fills/positions/account/portfolio |
| Bridge | `src/polysignal_lab/nautilus_bridge/` | `MarketCatalog` business-key lookup、market view assembly、state codec |
| Alpha core | `src/polysignal_lab/alpha/` | engine-agnostic 策略判断 |
| 报告/结算 | `src/polysignal_lab/app/scheduler_reporting.py` | settlement、daily report、leaderboard；读取 Nautilus projections |
| 配置模型 | `src/polysignal_lab/config.py` | Pydantic 配置、安全环境校验、YAML/env override |
| Gate | `src/polysignal_lab/signal_layer/gate.py` | 市场、时间、book/spot 新鲜度、价差、置信度、去重、频控 |
| Dashboard | `src/polysignal_lab/dashboard/app.py` | FastAPI 只读 API 与 HTML 首页 |
| SQLite schema | `src/polysignal_lab/storage/sqlite_schema.py` | canonical 表结构和索引 |
| 运行配置 | `config/signal_bot.yaml` | asset/timeframe、数据源、策略、Nautilus、paper、telegram、dashboard 配置 |

## 8. 存储模型

```mermaid
flowchart LR
  Markets["markets"]
  Signals["signals"]
  Rejected["rejected_signals"]
  Orders["paper_orders"]
  Fills["paper_fills"]
  Positions["paper_positions"]
  Results["paper_trade_results"]
  Account["paper_wallet_snapshots<br/>account/portfolio projection"]
  Reports["daily_reports"]
  Telegram["telegram_publishes"]
  Events["system_events"]

  Markets --> Signals
  Signals --> Orders
  Signals --> Rejected
  Orders --> Fills
  Fills --> Positions
  Positions --> Results
  Results --> Reports
  Account --> Reports
  Telegram --> Reports
  Events --> Reports
```

## 9. 当前值得关注的架构风险

```mermaid
flowchart TD
  R1["风险 1<br/>refs/ 旧 bot 代码污染代码索引"] --> Fix1["建议<br/>从索引/扫描范围排除 refs/"]
  R2["风险 2<br/>SimulationResult 有 extra_fills/positions"] --> Fix2["建议<br/>确认是否全部持久化"]
  R3["风险 3<br/>调度循环容错后继续运行"] --> Fix3["建议<br/>失败写入 system_events / health 状态"]
```

## 10. 总结

当前架构已经是完整产品化骨架，不是临时脚本：

- 入口清楚：`app/main.py`。
- 调度主线清楚：Nautilus data callbacks → alpha cores → gate → consensus → Nautilus sandbox order/fill → cache/portfolio projection → storage/publish。
- 安全边界清楚：只读、无 secret、无真实交易客户端、无下单/撤单/赎回。
- 审计链路完整：SQLite canonical storage + JSONL audit + state snapshots。
- Dashboard 明确只读。

优先改进项：

1. 复查 `extra_fills/extra_positions` 是否漏存。
2. 隔离 `refs/`，避免旧 bot 代码污染代码索引和安全扫描。
3. 将 scheduler 持续失败状态显式写入 `system_events` 或 health surface。（注：Legacy Scheduler 模式已在最终迁移中移除）
