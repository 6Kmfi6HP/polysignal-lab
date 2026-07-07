---
title: "Final Migration: PolySignal Lab → Full NautilusTrader Native"
status: draft
created: 2026-07-07
based_on:
  - docs/NAUTILUS_BRIDGE_BOUNDARY.md
  - docs/nautilus_reference/developer_guide/design_principles.md
  - docs/nautilus_reference/developer_guide/adapters.md
  - docs/superpowers/specs/2026-06-24-15-nautilus-strategy-bridge-design.md
  - docs/superpowers/specs/2026-06-25-nautilus-full-runtime-migration-design.md
previous_reviews:
  - workflows/wf_8642a679-267 (6-agent compliance review)
  - workflows/wf_c7b9a6c8-e10 (fix-and-verify-loop, stopped)
  - workflows/wf_59024bba-4bc (resolve-remaining-P1s, ACCEPTABLE verdict)
---

# 最终迁移提示词

> **目标**：从「可接受的过渡模式（ACCEPTABLE）」彻底转变为「完全 NautilusTrader Native（CLEAN）」。消除所有过渡债务，不留 bridge/适配器/双轨状态。

---

## 一、任务描述

本工作流执行 Polysignal Lab 代码库向 NautilusTrader 的**最终架构迁移**。前置合规审查已确认无 P0 风险、且遗留的 4 个 P1 项和 14 个 P2 项已标记为可接受的过渡模式。本工作流的目标是**将过渡模式清零**。

### 消灭目标清单

来自三次合规审查的汇总：

| # | 债务项 | 当前严重度 | 消灭方法 |
|---|--------|-----------|---------|
| 1 | `PolySignalScheduler` 作为并行 runtime 共存 | P1 | **完全退役** `app/scheduler.py`、`app/scheduler_*.py`，将必需的服务迁移到 Nautilus 生命周期 |
| 2 | `PolySignalNativeStrategy` 非 `Strategy` 子类 | P1 | 重构为真正的 `Strategy` 子类，消除 `getattr` 分发和 `runtime_classes.py` 双继承包装器 |
| 3 | `DecisionPolicyActor` 双重 gate/arbiter/consensus 实例 | P1 | 消除 `PolySignalScheduler` 中的第二组实例，`DecisionPolicyActor` 成为唯一所有者 |
| 4 | 轮询评估心跳（polling evaluation heartbeat） | P1 | 迁移到 Nautilus `Timer` / `Clock` API，消除所有 `asyncio.create_task` |
| 5 | 双继承包装器 `runtime_classes.py` | P2 | 消除 `NautilusPolySignalNativeStrategy`、`NautilusMarketRotationActor`、`LiveDecisionPolicyActor` 包装器 |
| 6 | `ObservabilityActor` 自管理 SQLite 写入器 | P2 | 合并到 `PersistenceService` |
| 7 | `scheduler_reporting.py` 膨大（650 行） | P2 | 拆分 + 解耦 from `PolySignalScheduler` |
| 8 | 自管理 WebSocket feed（`polymarket_rtds_ws.py`、`binance_spot_ws.py`） | P2 | 迁移为 Nautilus `DataSource` 模块，或通过 adapter 提供 |
| 9 | `MarketRotationActor` `_on_refresh_timer` 非托管 `asyncio.create_task` | P2 | 迁移到 Nautilus Timer API |
| 10 | `live_node.py` 惰性导入网关 | P2 | 替换为直接导入 |
| 11 | `cache_reader.py` duck-typing over Nautilus Cache | P2 | 使用 Nautilus 类型化 `Cache` 接口 |
| 12 | `custom_data_state.py` 策略本地状态累加器 | P2 | 使用 Nautilus `on_save/on_load` 序列化 |
| 13 | `scheduler.py` 向 `node.py` 注入非类型化属性 | P2 | 消除注入模式，使用显式 DI |
| 14 | `node.py` 剩余非 Nautilus 代码路径 | P2 | 消除非 Nautilus 路径 |
| 15 | `paper/` 目录中与 `signal_layer/` 的残余引用 | P2 | 确认无代码路径引用后删除 |
| 16 | `BaseStrategy` 13 个子类的遗留路径 | P2 | 确认 `alpha/*_core.py` 已完全取代，删除遗留策略文件 |

---

## 二、方法论

### 取证规则

沿用之前审查的规则：

- **奇数编号 Agent（A/C/E…）：CodeGraph only** — `codegraph_explore` / shell `codegraph explore`
- **偶数编号 Agent（B/D/F…）：Fast Context only** — `mcp__fast_context_search`，`project_path` 为仓库根目录
- 工具失败时：记录原因，使用 targeted `read` 补充
- **禁止**修改 `@refs/` 目录
- **禁止**跨域合并审查；每个 Agent 只审自己的范围

### 修改规则

- **所有修改 agent 禁用 `isolation: 'worktree'`** — 直接修改工作目录
- 每个 fix agent 操作**不相交的文件集**（已在前次审查中验证）
- 修改后立即验证：`python3 -c "import ast; ast.parse(open(path).read())"`
- 修改后运行相关测试：`cd /home/debian/polysignal-lab && python3 -m pytest tests/test_<affected>.py -x -q 2>&1 | tail -5`

### 成功标准

最终合规审查必须输出：

```
P0=0, P1=0, P2=0 (or acceptable minimal), no transition artifacts remain
```

即「CLEAN」判决，不再有 ACCEPTABLE。

---

## 三、工作流结构

### Phase 0: Pre-flight

- 读取本文档、所有设计文档、前三次审查的输出

### Phase 1: 遗留调度器退役（Legacy Scheduler Retirement）

**目标**：完全消除 `PolySignalScheduler` 及其配套文件。

**Agent A（CodeGraph）— 映射调度器调用图**
- 查找所有 `PolySignalScheduler` 的实例化点、方法调用、属性访问
- 识别调度器提供的 6-8 个被 Nautilus 路径消费的服务
- 输出：调度器调用图 + 服务依赖映射

**Agent B（Fast Context）— 迁移调度器提供的服务**
- 对于 Agent A 识别的每个服务：
  - `persistence_service` → 确认由 Nautilus 生命周期管理
  - `health_service` → 迁移到 Nautilus `HealthMonitor` 或 ObservabilityActor
  - `market_discovery` → 迁移到 `MarketDiscoveryActor` 或保持独立但由 `node.py` 直接管理
  - `nautilus_cache_reader` → 由 Nautilus Cache 直接提供
  - `settlement_resolver` → 适配为只读查询，不经过调度器
  - 其他 → 逐一映射
- 输出：服务迁移映射表

**Agent C（CodeGraph）— 执行调度器退役**
- 删除 `app/scheduler.py`、`app/scheduler_*.py`（scheduler_health.py 除外，如仍需要）
- 将所有必需的服务初始化移到 `node.py`（或 `node_builder.py`）
- 删除从 `node.py` 到 `PolySignalScheduler` 的所有引用
- 删除对调度器的所有测试引用（更新或删除测试）

**Agent D（Fast Context）— 清理调度器残留**
- 删除 `scheduler_runtime.py`（若前次修复未删除）
- 清理 `scheduler_processing.py` 中依赖调度器的部分
- 更新所有导入路径
- 验证 `python3 -c "from polysignal_lab.app.scheduler import PolySignalScheduler"` 失败（已删除）

### Phase 2: Strategy 与 Actor 原生化

**目标：所有策略为 `Strategy` 子类，所有 Actor 为 `Actor` 子类，无包装器。**

**Agent E（CodeGraph）— 消除 dual-inheritance 包装器**
- 读取 `runtime_classes.py`
- 删除 `NautilusPolySignalNativeStrategy` — 使 `PolySignalNativeStrategy` 直接继承 `Strategy`
- 删除 `NautilusMarketRotationActor` — 使 `MarketRotationActor` 直接继承 `Actor`
- 删除 `LiveDecisionPolicyActor` — 使 `DecisionPolicyActor` 直接继承 `Actor`
- 更新所有引用这些包装器的代码路径
- 删除 `runtime_classes.py` 中不再需要的部分

**Agent F（Fast Context）— 使 `PolySignalNativeStrategy` 直接继承 `Strategy`**
- 这是最大的重构项
- 将 `native_strategy.py` 中的类定义改为 `class PolySignalNativeStrategy(Strategy):`
- 用 Nautilus 原生 API 替换 `getattr` 分发：
  - `self.subscribe_data()` 代替自定义分发
  - `self.order_factory.*()` 保持（已经是 Nautilus API）
  - `self.submit_order()` 保持（已经是 Nautilus API）
- 用 `on_save/on_load` 替换所有自定义状态序列化
- 从 `strategies/base.py` 迁移任何重复的回调逻辑
- 删除 `strategies/base.py` 中已被原生 Strategy 取代的部分

**Agent G（CodeGraph）— 消除 Actor 中的非 Nautilus 异步模式**
- `MarketRotationActor._on_refresh_timer`：替换 `asyncio.create_task` 为 Nautilus `Timer` API
- `ObservabilityActor._run_telemetry_writer`：迁移到 Nautilus 管理的后台任务
- 确保所有 Actor 的 `on_stop` 正确清理任务

### Phase 3: 数据管道与状态原生化

**目标：所有数据通过 Nautilus Data Catalog，所有状态通过 `on_save/on_load`。**

**Agent H（Fast Context）— 自定义数据源迁移**
- 将 `polymarket_rtds_ws.py` 和 `binance_spot_ws.py` 适配为 Nautilus `DataSource` 模块
- 或确认它们被 `spot_source: disabled` 门控，且当重新启用时必须通过 adapter 提供
- 更新 `sidecar_data.py` 使用 Nautilus 标准发布路径（已基本正确）

**Agent I（CodeGraph）— 状态管理统一**
- `custom_data_state.py` → 使用 `on_save/on_load` 序列化
- 确认 `ObservabilityActor` 的 SQLite 写入已合并到 `PersistenceService`
- 确认 `cache_reader.py` 使用 Nautilus 类型化 `Cache` 接口（删除 duck-typing）
- 确认所有状态只有唯一的事实来源（Nautilus Cache，非 SQLite + Cache 双读）

**Agent J（Fast Context）— 死代码与遗留文件删除**
- 删除所有 `strategies/base.py` 中已被 Nautilus Strategy 取代的回调逻辑
- 删除所有 13 个 legacy `strategies/*.py`，确认其 `alpha/*_core.py` 等价物已完全覆盖
- 清理 `paper/` 目录中不再使用的文件
- 清理 `signal_layer/` 中被 DecisionPolicyActor 吸收的部分
- 删除 `trading_node.py`（若前次修复未删除）

### Phase 4: 杀戮列表追查（Kill List Sweep）

**Agent K（CodeGraph）— 追查所有已标记的债务项**
- 对债务清单中的每一项，搜索代码库确认已被消除
- 输出：「未消灭」列表 + 其文件:行号

**Agent L（Fast Context）— 验证架构完整性**
- 确认 `node.py` 不再导入或引用任何调度器模块
- 确认 `runtime_classes.py` 为空或已被删除
- 确认无代码路径使用 `strategies/base.py` 中的 legacy callbacks
- 确认无代码路径使用 `paper/` 或 `signal_layer/` 中的旧模块

### Phase 5: 最终合规审查

**运行 6-agent 并行合规审查**（复用之前的审查 workflow）
- 使用与之前审查相同的脚本和配置
- 所有 6 个 Agent 覆盖范围相同

### Phase 6: 判决

**综合 Agent — 输出最终报告**
- 审查最后一次合规审查的结果
- 满足「CLEAN」标准（P0=0, P1=0, 无过渡构件）→ 完成
- 不满足 → 列出剩余的债务项作为后续工作项

---

## 四、输出格式

### 最终迁移报告

```markdown
# Final Migration Report

## Executive Summary
(状态：CLEAN / PARTIAL，整体成就概述)

## Phase Results
### Phase 1: Legacy Scheduler Retirement
- 调度器文件删除状态
- 服务迁移状态
- 保留/迁移的服务列表

### Phase 2: Strategy & Actor Nativization
- Strategy 子类化状态
- 包装器删除状态
- Actor 生命周期合规性

### Phase 3: Data Pipeline & State Nativization
- 自定义数据源状态
- 状态管理统一状态
- 死代码删除统计

### Phase 4: Kill List Sweep
- 未消灭的债务项列表 + 文件:行号

## Final Compliance Review
(6-agent 审查的输出摘要)
- P0: 0
- P1: 0
- P2: (可接受的最小值)
- 判决: CLEAN

## Remaining Work (if any)
- ...
```

---

## 五、先决条件与风险

### 先决条件
- 前次合规审查的输出（本文档中已汇总）
- 所有设计文档的最新版本
- NautilusTrader adapter 的完整功能（包括 LiveDataClient、HttpClient、InstrumentProvider）
- 完整测试套件可用

### 风险与缓解
| 风险 | 可能性 | 影响 | 缓解 |
|------|--------|------|------|
| Strategy 子类化破坏 alpha core 集成 | 中 | 高 | 渐进式：先添加 Nautilus Strategy 子类作为并行实现，再切换 |
| 调度器删除破坏 dashboard 报告 | 高 | 中 | 报告逻辑作为独立模块保留，仅删除调度器编排 |
| WebSocket feed 迁移不完整 | 中 | 低 | 当前已被 `spot_source: disabled` 门控，不阻塞 |
| 测试套件因删除文件而失败 | 中 | 中 | 删除前更新/删除相关测试 |

### 回滚计划
- 每个 Phase 完成后使用 `git commit` 创建检查点
- 如果验证失败，回滚到上一个检查点
- 关键检查点：Phase 1 完成后，Phase 2 完成后，Phase 5 完成后
