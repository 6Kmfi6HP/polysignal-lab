# 01-08 Specs Architecture Overview and Visual Guide

**Status:** Approved
**Date:** 2026-06-23
**Commit Reference:** `da65f11`

## 1-8 设计规范 (Spec) 系统架构可视化

```mermaid
flowchart TD
    subgraph Layer1 [1. 数据输入层 (Data Ingestion)]
        Spec06[06 公共数据只读边界\n- 隔离 py-clob-client\n- 确保无凭证/只读调用] --> Spec01[01 CLOB 账本对账\n- WS 变化重构为对账账本\n- tick_size_change 触发重置]
        Spec05[05 锚定价格服务\n- 捕获边界 spot 价格并落库\n- 替代 ad-hoc 易被屏蔽 API]
    end

    subgraph Layer2 [2. 策略评估层 (Strategy Evaluation)]
        Spec07[07 策略选入与标定\n- 检查支持的币种与周期\n- 提前 Skip 不支持策略] --> Eval[策略执行 evaluate]
        Spec01 --> Snapshot[构建 MarketSnapshot\n- 包含账本/ spot/ 锚定价格]
        Spec05 --> Snapshot
        Snapshot --> Gate[SignalGate 信号中心门控]
        Spec02[02 策略新鲜度门控\n- 取全局与策略配置最严限制\n- 细化 MISSING 与 STALE 原因] --> Gate
    end

    subgraph Layer3 [3. 模拟执行层 (Paper Simulation)]
        Gate -->|生成 Accepted 信号| Spec03[03 模拟交易真实性\n- Preflight 前置校验流动性\n- TAKER_FAK/FOK/GTD 意图对齐]
    end

    subgraph Layer4 [4. 系统监控与调度 (Operations & Monitoring)]
        Spec04[04 健康与指标布线\n- 组件级状态 ok/degraded/down\n- 记录系统事件到 SQLite]
        Spec08[08 调度器解耦与生命周期管理\n- 调度器退化为 Supervisor 协调者\n- 上述各服务实现独立启停]
    end

    %% 控制与监控线
    Spec08 -.->|启动/停止生命周期控制| Layer1
    Spec08 -.->|启动/停止生命周期控制| Layer2
    Spec08 -.->|启动/停止生命周期控制| Layer3
    Layer1 -.->|汇报健康度| Spec04
    Layer2 -.->|汇报健康度| Spec04
    Layer3 -.->|汇报健康度| Spec04
```

## 各设计规范要点解析

### 1. 数据输入层 (Data Ingestion)
*   **06 公共数据只读边界 (Public Market Data Boundary)**:
    *   **概述**：隔离 `py-clob-client` 的写入操作，定义统一的只读协议 `PublicMarketDataClient`，避免敏感凭证与交易 API 泄露到策略或调度逻辑中。
*   **01 CLOB 账本对账 (CLOB Book Reconciliation)**:
    *   **概述**：将 WebSocket 增量更新与 REST 快照融合成强对账的本地账本。在发生 `tick_size_change` 等关键事件时将账本标记为过期并触发重新校对，从而避免模拟盘使用不真实的报价深度。
*   **05 锚定价格服务 (Anchor Price Service)**:
    *   **概述**：用于 5m/15m 等短周期市场的价格对齐。在判定边界点捕获币安现货价格并持久化写入 SQLite 数据库作为锚定基准，防范由于直接调用 Polymarket web 接口被 Cloudflare 拦截导致的价格数据缺失。

### 2. 策略评估层 (Strategy Evaluation)
*   **07 策略选入与标定 (Production Strategy Opt-In)**:
    *   **概述**：根据 Readiness 矩阵在调度器源头跳过不支持的交易对或周期（生成 skip 状态而不是 gate reject），减少运行时计算损耗。
*   **02 策略新鲜度门控 (Strategy Freshness Gates)**:
    *   **概述**：在 `SignalGate` 汇总检查策略特定新鲜度时限（取全局与策略配置中更严格者，例如 1.5s），并将错误细化区分出 `MISSING_ORDERBOOK` 等缺失类型。

### 3. 模拟执行层 (Paper Simulation)
*   **03 模拟交易真实性 (Paper Execution Realism)**:
    *   **概述**：在模拟交易执行前引入 preflight（起飞前检查）校验，重验流动性深度及价格变动，对 FAK、FOK、PASSIVE_GTD 等委托意图进行差异化撮合校验，并生成带有 `PAPER_` 前缀的归因拒单原因。

### 4. 系统监控与调度 (Operations & Monitoring)
*   **04 健康与指标布线 (Health & Metrics Wiring)**:
    *   **概述**：统一组件级监控数据结构，细化上报 `ok`/`degraded`/`down` 等生命周期指标，并将监控的降级或切换事件持久化记录到 SQLite `system_events` 表中。
*   **08 调度器解耦 (Scheduler Supervisor Boundaries)**:
    *   **概述**：将原来的 God-object 调度类拆分为彼此隔离且具备标准化生命周期的服务，调度层仅作为 Supervision Orchestration 容器，避免持久化或数据推送的延迟拖垮实时的行情获取与信号计算。
