# PolySignal Lab 项目架构图解

> 生成日期：2026-06-23  
> 范围：当前仓库 `src/polysignal_lab/`、`config/`、`tests/`、运行入口与主要数据流。

## 1. 一句话概览

PolySignal Lab 是一个 **只读 Polymarket 短周期信号 + 纸面交易验证系统**：读取公开行情数据，生成策略信号，通过 gate/共识层过滤，默认 dry-run 发布 Telegram，并将信号、纸面订单、成交、持仓、结算和日报写入 SQLite/JSONL，最后由 FastAPI Dashboard 只读展示。

## 2. 总体架构

```mermaid
flowchart TB
  CLI["CLI 入口<br/>polysignal-lab"] --> Main["app/main.py"]

  Main --> Scheduler["Scheduler 模式"]
  Main --> Dashboard["Dashboard 模式"]
  Main --> Smoke["Smoke 检查模式"]

  Scheduler --> Data["数据采集层"]
  Data --> Gamma["Polymarket Gamma<br/>市场发现"]
  Data --> CLOB["Polymarket CLOB<br/>订单簿 REST / WS"]
  Data --> Binance["Binance WS<br/>现货价格"]

  Gamma --> Snapshot["MarketSnapshotBuilder"]
  CLOB --> Snapshot
  Binance --> Snapshot

  Snapshot --> Strategies["策略层<br/>13 个策略"]
  Strategies --> Gate["SignalGate<br/>过滤 / 去重 / 频控"]
  Gate --> Consensus["ConsensusEngine<br/>共识聚合"]

  Consensus --> Paper["纸面交易层<br/>PaperSimulator / Wallet"]
  Consensus --> Telegram["Telegram Publisher<br/>默认 dry-run"]
  Consensus --> Store["存储层<br/>SQLite + JSONL + state"]

  Paper --> Store
  Store --> DashboardApp["FastAPI 只读 Dashboard"]
  Dashboard --> DashboardApp
```

## 3. 一次调度循环

```mermaid
sequenceDiagram
  participant S as Scheduler
  participant M as MarketDiscovery
  participant B as OrderBook / Spot Feeds
  participant Snap as SnapshotBuilder
  participant Strat as Strategies
  participant Gate as SignalGate
  participant Paper as PaperSimulator
  participant DB as SQLite/JSONL
  participant Tg as Telegram

  S->>M: 刷新活跃市场
  S->>B: 同步 CLOB 订单簿 + Binance 现货
  S->>Snap: 为每个市场构造快照
  Snap-->>S: MarketSnapshot

  S->>Strat: evaluate(snapshot)
  Strat-->>S: SignalCandidate[]

  S->>Gate: 检查信号
  Gate-->>S: accepted / rejected

  alt accepted
    S->>DB: 存 signals
    S->>Tg: 发布信号，默认 dry-run
    S->>Paper: 纸面撮合
    Paper-->>S: order / fill / position
    S->>DB: 存 paper_orders / fills / positions
  else rejected
    S->>DB: 存 rejected_signals
  end

  S->>Paper: 检查 TP/SL/结算
  S->>DB: 生成日报 / leaderboard
```

## 4. 目录分层

```mermaid
flowchart LR
  Root["polysignal-lab"] --> Config["config/<br/>运行配置"]
  Root --> Src["src/polysignal_lab/"]
  Root --> Tests["tests/<br/>测试套件"]
  Root --> Docs["docs/<br/>交付/PRD 文档"]
  Root --> Scripts["scripts/<br/>安全扫描等"]

  Src --> App["app/<br/>入口 + 调度器"]
  Src --> Data["data/<br/>外部行情/市场数据"]
  Src --> Domain["domain/<br/>领域模型"]
  Src --> Strategies["strategies/<br/>策略实现"]
  Src --> Signal["signal_layer/<br/>信号过滤/共识"]
  Src --> Paper["paper/<br/>纸面交易/钱包/结算"]
  Src --> Storage["storage/<br/>SQLite/JSONL/state"]
  Src --> Dashboard["dashboard/<br/>FastAPI 只读面板"]
  Src --> Publish["publish/<br/>Telegram"]
  Src --> Observability["observability/<br/>日志/健康/安全"]
```

## 5. 数据流向

```mermaid
flowchart TD
  External["外部公开数据源"] --> A["Polymarket Gamma<br/>市场元数据"]
  External --> B["Polymarket CLOB<br/>订单簿"]
  External --> C["Binance WS<br/>现货价格"]

  A --> Registry["内存 Registry<br/>markets/books/spots"]
  B --> Registry
  C --> Registry

  Registry --> Snapshot["标准化 MarketSnapshot"]
  Snapshot --> Strategy["策略判断"]
  Strategy --> Candidate["SignalCandidate"]
  Candidate --> Gate["SignalGate"]

  Gate -->|通过| Signal["Accepted Signal"]
  Gate -->|拒绝| Rejected["RejectedSignal"]

  Signal --> Paper["纸面订单 / 持仓 / 盈亏"]
  Signal --> Telegram["Telegram 消息"]
  Signal --> Audit["SQLite + JSONL"]
  Rejected --> Audit
  Paper --> Audit

  Audit --> Dashboard["只读 Dashboard"]
  Audit --> Report["日报 / Leaderboard"]
```

## 6. 安全边界

```mermaid
flowchart TB
  subgraph Allowed["允许"]
    PublicData["公开行情数据读取"]
    SignalOnly["信号生成"]
    PaperOnly["纸面交易模拟"]
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
| CLI 入口 | `src/polysignal_lab/app/main.py` | 解析 runtime mode，启动 scheduler/dashboard/smoke |
| 调度器 facade | `src/polysignal_lab/app/scheduler.py` | 组装数据源、策略、gate、纸面交易、存储、发布器 |
| 调度循环 | `src/polysignal_lab/app/scheduler_runtime.py` | 主循环、周期刷新、信号处理、结算、日报 |
| 市场数据 | `src/polysignal_lab/app/scheduler_market_data.py` | 市场发现、CLOB book、WS 订阅、resolved market 拉取 |
| 信号处理 | `src/polysignal_lab/app/scheduler_processing.py` | strategy evaluate、gate、持久化、Telegram、纸面撮合 |
| 报告/结算 | `src/polysignal_lab/app/scheduler_reporting.py` | TP/SL/settlement、daily report、leaderboard |
| 配置模型 | `src/polysignal_lab/config.py` | Pydantic 配置、安全环境校验、YAML/env override |
| 策略注册 | `src/polysignal_lab/strategies/factory.py` | config 名称到策略类的 registry |
| 策略接口 | `src/polysignal_lab/strategies/base.py` | `BaseStrategy.evaluate()` 与候选信号构造 |
| Gate | `src/polysignal_lab/signal_layer/gate.py` | 市场、时间、book/spot 新鲜度、价差、置信度、去重、频控 |
| 纸面交易 | `src/polysignal_lab/paper/simulator.py` | taker/passive/multi-leg paper execution |
| Dashboard | `src/polysignal_lab/dashboard/app.py` | FastAPI 只读 API 与 HTML 首页 |
| SQLite schema | `src/polysignal_lab/storage/sqlite_schema.py` | canonical 表结构和索引 |
| 运行配置 | `config/signal_bot.yaml` | asset/timeframe、数据源、策略、paper、telegram、dashboard 配置 |

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
  Wallet["paper_wallet_snapshots"]
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
  Wallet --> Reports
  Telegram --> Reports
  Events --> Reports
```

## 9. 当前值得关注的架构风险

```mermaid
flowchart TD
  R1["风险 1<br/>refs/ 旧 bot 代码污染代码索引"] --> Fix1["建议<br/>从索引/扫描范围排除 refs/"]
  R2["风险 2<br/>README 仍只写 3 个策略"] --> Fix2["建议<br/>同步到当前 13 策略架构"]
  R3["风险 3<br/>SimulationResult 有 extra_fills/positions"] --> Fix3["建议<br/>确认是否全部持久化"]
  R4["风险 4<br/>调度循环容错后继续运行"] --> Fix4["建议<br/>失败写入 system_events / health 状态"]
```

## 10. 总结

当前架构已经是完整产品化骨架，不是临时脚本：

- 入口清楚：`app/main.py`。
- 调度主线清楚：market discovery → snapshot → strategies → gate → consensus → paper/storage/publish。
- 安全边界清楚：只读、无 secret、无真实交易客户端、无下单/撤单/赎回。
- 审计链路完整：SQLite canonical storage + JSONL audit + state snapshots。
- Dashboard 明确只读。

优先改进项：

1. 复查 `extra_fills/extra_positions` 是否漏存。
2. 隔离 `refs/`，避免旧 bot 代码污染代码索引和安全扫描。
3. 更新 README，使策略数量和当前运行架构一致。
4. 将 scheduler 持续失败状态显式写入 `system_events` 或 health surface。
