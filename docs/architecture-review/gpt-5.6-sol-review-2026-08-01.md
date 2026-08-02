# Oracle Browser Transcript

Conversation: https://chatgpt.com/g/g-p-6a6ca659d7f08191be9a36d214673bde-polysignal-lab/c/6a6d9965-46d0-83ec-ae8e-70baa8f0de17

## Prompt

# PolySignal Lab 架构评审请求（专业角度）

## 项目简报

PolySignal Lab 是一个只读的 Polymarket 短线信号 + NautilusTrader paper trading 验证系统（非托管、无真实下单、无钱包密钥）。核心职责：

- Polymarket 市场发现、公开行情数据抓取（Gamma/CLOB REST + WebSocket）
- 13 个 alpha 信号核心（VWAP Momentum、Late Consensus、PTB Diff、One Cent Buy 等）生成 AlphaDecision
- NautilusTrader TradingNode 运行时执行策略回调、决策策略（decision policy）、原生订单提交与沙盒 paper execution
- SQLite 规范存储 + JSONL 审计日志 + 原子状态文件
- Telegram 格式化/发布（默认 dry-run）、只读 FastAPI dashboard、容器健康探针
- 参数推广验证系统（promotion：把历史行情经真实引擎回放，验证单参数门）

技术栈：
- Python 3.12，pydantic v2，FastAPI，httpx，anyio，sqlite3（stdlib）
- nautilus_trader[polymarket]==1.231.0a20260730（PyO3 Rust FFI 绑定，精确 pin 到 alpha 版本）
- 前端：React 19 + Vite + Tailwind 4 + TanStack Router/Query/Table + i18next + recharts（dashboard 只读）

代码规模：src/polysignal_lab 共 156 个 Python 文件；nautilus_runtime 43 文件（含 strategy/ 16 文件）；domain 层 1143 行；alpha 层 13 cores；storage 层 7 文件；observability 层 8 文件。测试 980 passed / 6 skipped / 0 failed。基于pyright baseline 门禁（净增 0 错误）。

构建/测试命令：仓库根目录 `pytest -q`、`scripts/safety_scan.py .`；前端在 `frontend/` 内 npm run test / build。

## 目录结构（已对照代码核实）

- src/polysignal_lab/domain/ 领域模型（signal, market, strategy_config, reporting_models, spot, anchor_price, enums, strategy_readiness）
- src/polysignal_lab/nautilus_runtime/ 运行时（node, node_builder, live_node, backtest_node, runtime_context_factory, market_catalog, decision_policy, native_order, order_plan, projections, observability, market_rotation, configured_markets, instrument_markets, custom_data_* 等）+ strategy/ 子包（subscriptions, readiness, lifecycle, condition_evaluation, decision_pipeline, order_events, event_projection, market_data_events, data_boundary, host_init, protocols, catalog_lookups, config_deps, constants, custom_data_handlers, nautilus_objects, observability_hooks）
- src/polysignal_lab/alpha/ 13 个 alpha 核心 + types/state/stats
- src/polysignal_lab/data/ 市场发现（polymarket_market_discovery, price_to_beat_provider, anchor_price_service）
- src/polysignal_lab/storage/ sqlite_schema, sqlite_store, jsonl_store, state_store, event_projection, projection_migration
- src/polysignal_lab/observability/ health, liveness_watchdog, liveness_alert, runtime_health, metrics, logger, safety
- src/polysignal_lab/reporting/ 日报、聚合、策略统计、rejections、exit_result
- src/polysignal_lab/promotion/ 回放验证门（runner, cli, report）
- src/polysignal_lab/publish/ telegram 发布
- src/polysignal_lab/pretrade/ gate
- src/polysignal_lab/dashboard/ FastAPI + ports
- frontend/ React dashboard

## 最近架构演进

1. **PR #47（2026-08-01 合并）— 订阅/readiness 状态机收敛**
   - 背景：Nautilus 的 subscribe 命令是 fire-and-forget、无 ACK、无"订阅已生效"回调；但本运行时用"condition 是否有实时双边行情"驱动 /health 与容器 liveness（Docker healthcheck + LivenessWatchdog + Telegram 告警），必须自建"订阅确认真空"。
   - 原实现：MarketSubscriptionState 用 10 个旁路集合（intent / pending_metadata / pending_instrument / subscribed / awaiting_book / book_generation / first_bilateral / last_book ...）+ 5 个文件各自直接 add/discard，无单一状态变量、无显式迁移图。
   - 新实现：单一 per-condition 显式状态机 ConditionSubscriptionPhase：UNSUBSCRIBED → INTENT → PENDING_METADATA → PENDING_INSTRUMENT → SUBSCRIBED → AWAITING_FIRST_BOOK → READY。所有迁移只经 subscriptions.py 内的迁移函数；readiness.py 改为纯推导只读；单一清理入口 clear_condition_lifecycle_state（condition 退出 active 集的唯一路径）；正交标记（stale_orderbook 恢复、quote-depth untradable、reason、miss）与相位分离但统一清理。
   - 附带：MarketCatalog 懒构建 instrument→timeframe 索引，client_id 路由从 O(N) 全表扫描降为 O(1)；InstrumentId 规范化单点化。
2. **feed readiness 与 market tradability 分离**（commit a0f9769 / 7154b13）
3. **scheduler 模式废弃** → 显式 nautilus / dashboard / smoke 三种模式
4. **类型债清零**（basedpyright baseline 门禁，commit 61d7704）

## Bug 修复记录（git log 提取，2026-07-19 至 08-01）

### Bug 类 #1：订阅/readiness 状态泄漏（反复复发，本次结构性地修）
- 07bd5dd / 0a4c65c / 292076a：recover stale market subscription & readiness
- 86787ed / 3dc4e74（两次同名提交）：recover stale orderbook readiness
- bb61a97：preserve shared subscriptions across staggered retries
- 36db645：fix pending instrument subscription convergence（合并前刚发生）
- 根因分析（PR #47 内）：无 ACK 确认真空 + 状态所有权分散在 5 个文件 + 三个时间尺度概念（毫秒级订阅纠偏 / 秒级陈旧恢复 / 分钟级不可交易）塞进同一批字典 + 每 5 分钟整批轮换无稳态。本次用显式状态机 + 单一清理入口从结构上消灭整类 bug。

### Bug 类 #2：promotion 回放边界泄漏（多个 commit 连续修）
- e9a9936 / f9d2831 / 3ae0334 / 9472d5c / a249553 / 8d951f9：promotion 的 replay/report 边界、oos（样本外）泄漏、sample floor 保留、settled round 计数、repo root 推导

### Bug 类 #3：Nautilus PyO3 FFI 适配脆弱
- c907537：normalise InstrumentId 到 PyO3 binding 家族；2ce9ce1：normalize recorder subscription ids；b956027：retire recorder quote subscriptions；8e29eb8：upgrade Polymarket websocket runtime；364b662：map official Nautilus BinaryOption info 供 market rotation
- 反映：nautilus_trader 每版本 API/绑定形态在变，适配层持续承受摩擦

### Bug 类 #4：其他
- d7de0be：health 在无行情到达时 fail liveness
- cb0e4bc：回放保留 recorded data event order
- 98aef9d：custom-only recorded replay 完整
- 6bb816b：recorder 无法启动时 fail open
- d6d1d5b：恢复 strategy execution 和 Telegram delivery（PR #30）
- f591538：order 元数据从 metrics 读而非不存在的 event tags

## PR 列表（已合并）
- #30 fix(runtime): restore strategy execution and Telegram delivery (07-20)
- #40 refactor(runtime): consolidate decision submission pipeline (07-20)
- #46 feat(runtime): record sandbox market data for replay (07-22)
- #47 refactor(runtime): converge subscription/readiness into explicit condition state machine (08-01)

## 具体咨询问题（专业角度，请逐条给意见）

1. **状态机建模是否到位**：ConditionSubscriptionPhase 的线性状态机是否是最合适的形式？当前仍保留约 10 个旁路派生字典（各阶段 timestamps、per-side pending、instrument bookkeeping）。对于"无 ACK 订阅确认真空 + 毫秒到分钟多时间尺度 + 每 5 分钟整批市场轮换"的场景，是否有更强的建模方式（事件溯源、不可变快照 + 派生投影、形式化状态图）？还是在当前规模下"显式状态机 + 单一清理入口"已足够、再抽象就是过度工程？

2. **FFI/PyO3 边界隔离**：nautilus_trader 版本 API 漂移频繁（InstrumentId 家族、recorder、websocket runtime 都在变）。现有 optional_imports + 适配层模式是否够？如何设计对上游版本变化更稳的适配层（如 anti-corruption layer、versioned facade、契约测试）？

3. **领域层 vs 运行时膨胀**：domain/ 仅 1143 行，而 nautilus_runtime 约 8500+ 行。领域模型是否被运行时实现淹没？是否值得把更多业务概念（readiness、subscription、tradability）提升到 domain 层，还是当前分层（domain 纯模型 + runtime 编排）是对的？

4. **存储三套方案**：SQLite 规范库 + JSONL 审计 + 原子状态文件，加事件投影。对单进程只读验证系统是否合理？有没有更简单的统一方案，还是 canonical → projection → read model 分层是对的？

5. **测试策略为何放走了结构性 bug**：980 测试仍然放走"订阅状态泄漏"这类结构性 bug（是靠修复、不是靠测试发现）。promotion 边界 bug 也反复。如何设计测试让"状态清理 / 边界隔离"类 bug 在提交前就被捕获？是否值得引入属性测试、状态机测试、迁移/不变式断言、快照测试？

6. **回放验证架构**：promotion 用真实引擎回放历史数据验证参数。边界（oos 泄漏、sample floor、settled round）反复出 bug。有没有更稳健的验证架构模式（如显式数据分区契约、回放指纹、快照隔离）？

7. **可观测性是否完备**：health + liveness watchdog + Telegram 告警 + 容器 healthcheck，全部由"condition 是否有实时双边行情"驱动。对 read-only 信号系统，这个可观测性模型还缺什么（如就绪延迟 SLO、轮换收敛统计、信号质量指标）？

8. **前端边界**：dashboard 通过 REST 只读接口读投影。前后端契约（接口/字段/类型）如何管理，才能避免前端拿不到后端字段这类问题（曾有 repair dashboard reporting data pipelines 修复）？是否值得引入契约测试或 OpenAPI 代码生成？

9. **依赖与升级**：nautilus_trader 精确 pin 到 alpha 版本（==1.231.0a20260730）。这个 pin 策略是否合理？有没有降低升级摩擦的机制（如升级 checklist、适配层快照测试、预发布通道）？

## 期望输出格式
- 按问题逐条给出专业意见；每个建议标注：改进价值（高/中/低）、实施成本、引入风险
- 明确指出哪些在当前规模下不该做（过度工程红线）
- 最后给 1-3 个最值得优先做的改进，按 ROI 排序

## Answer

# PolySignal Lab 架构评审结论

## 评审范围

本次可以直接核验的实现包括：

* 订阅状态机与 readiness：`subscriptions.py`、`readiness.py`
* Nautilus 标识映射与目录：`market_catalog.py`
* 决策管线与结构化接口：`decision_pipeline.py`、`protocols.py`
* 运行时组装与 watchdog：`node.py`
* 依赖、类型门禁与工具配置：`pyproject.toml`
* README 中声明的安全边界、三类存储和 dashboard 接口

promotion、storage 内部实现、dashboard 路由模型、前端类型和测试文件未包含在本轮直接附件中。因此第 4、5、6、8 项属于基于项目简报和缺陷历史的架构评估，不是逐行实现确认。

## 总体判断

当前架构**不需要推翻重做**。主要分层方向是正确的：

* Nautilus callback host 与决策管线已经出现清晰的 Port/Adapter 形态。
* 精确 pin 上游 alpha 版本是合理的生产策略。
* 订阅状态所有权向单模块集中，是对历史问题的正确修复方向。
* SQLite canonical、JSONL audit、原子状态文件可以共存，前提是明确三者的权威级别。

但 PR #47 之后仍有一个重要事实需要澄清：

> 当前实现是“显式 phase + 集中式状态变更”，还不是严格的单一事实源状态机。

`phase` 会通过 `pending_instrument_ids` 和 `awaiting_book_sides_by_condition` 反向重算。因此这些旁路容器事实上仍参与决定主状态。它们不是单纯只读投影。

最合理的后续不是事件溯源，也不是把全部 runtime 模型搬进 domain，而是：

1. 将状态收敛成 **per-condition 聚合对象**；
2. 为聚合定义可执行不变式和状态机属性测试；
3. 把 promotion 数据边界和 Nautilus FFI 契约也改成“由结构保证”，而不是依赖调用约定。

---

# 1. ConditionSubscriptionPhase 状态机是否建模到位

## 结论

**方向到位，但模型尚未完全闭合。**

它已经显著优于原来的十组散布集合：phase 有明确枚举，状态变更集中在 `subscriptions.py`，readiness 基本变成只读推导，condition 退出也有统一清理入口。这些都是结构性进步。 

但从代码看，有五个残余问题。

### 1.1 phase 并非真正的单一事实源

`_phase_from_derived_state()` 根据：

* `pending_condition_instrument_ids()`
* `awaiting_book_sides_by_condition`
* 当前是否已经是 `READY`

重新决定 phase。

也就是说，phase 更接近一个**缓存后的状态摘要**；pending/awaiting 容器仍然是部分权威状态。代码注释同时使用了“single source of truth”和“phase shadows derived bookkeeping”两种相反表述，需要二选一。

### 1.2 当前并不是实际的线性状态机

标准 active condition 路径更接近：

```text
UNSUBSCRIBED
  ├─> PENDING_METADATA
  └─> AWAITING_FIRST_BOOK
          ├─> PENDING_INSTRUMENT
          └─> READY
```

instrument 到达后还会从 `PENDING_INSTRUMENT` 回到 `AWAITING_FIRST_BOOK`；恢复和轮换也会形成环。

因此它是**带循环的 lifecycle graph**，不是严格的单向线性状态机。

另外：

* `INTENT` 在所附文件中没有实际写入点；
* `allow_deferred` 参数存在但未使用；
* 标准 active 路径中 `SUBSCRIBED` 也不是稳定、清晰的必经状态。

这意味着枚举声明的状态空间和实际可达状态空间目前不一致。

### 1.3 `SUBSCRIBED` 命名不符合无 ACK 语义

代码明确声明“never claim wire confirmation”，但 phase 仍名为 `SUBSCRIBED`。readiness 输出又把包括 `READY` 在内的大多数非初始状态映射为 `subscribe_requested`。这说明实际语义是：

```text
subscription commands issued locally
```

而不是：

```text
wire subscription confirmed
```

建议将 `SUBSCRIBED` 改成 `SUBSCRIBE_ISSUED` 或 `SUBSCRIBE_REQUESTED`，并让 `READY` 明确输出为 `ready`。否则 dashboard、health 和日志使用者容易误解 `subscription_state`。

### 1.4 readiness helper 存在危险的“缺失即成功”语义

`market_book_generation_ready()` 通过“没有 awaiting sides”判断 ready。对从未订阅或已被清理的 condition，它同样会返回 `True`。

是否已有调用点造成实际错误，当前附件不足以确认；但该 predicate 的语义本身不安全。它应改为：

```python
condition_phase(strategy, condition_id) is ConditionSubscriptionPhase.READY
```

或者重命名成：

```python
not_awaiting_book_generation()
```

避免把“不存在 generation”当成“generation ready”。

### 1.5 清理仍有两个例外路径

`clear_condition_lifecycle_state()` 确实清除了 orthogonal readiness markers，但：

* 默认 `clear_history=False`，会保留 `last_book_*`；
* `unsubscribe_market_conditions()` 使用了这个默认值；
* `unsubscribe_all_market_instruments()` 只清理 pending、intent 和 phases，没有清理 awaiting、generation、stale、untradable、reason/miss 等状态。

如果全量 unsubscribe 后对象立即销毁，这不构成运行时错误；如果实例可重启、复用，或者长期轮换保留历史，则仍可能形成状态或内存残留。函数注释中的“no tracked state outlives the condition”与默认行为并不完全一致。

## 推荐形式

不建议上完整事件溯源。建议将十组按 condition key 平行存储的容器收敛为：

```python
@dataclass(slots=True)
class ConditionRuntimeState:
    lifecycle: SubscriptionLifecycle
    feed: FeedEvidence
    tradability: TradabilityState
```

其中：

```python
@dataclass(slots=True)
class SubscriptionLifecycle:
    phase: ConditionSubscriptionPhase
    generation: int
    intent_started_at: datetime | None
    pending_instrument_ids: set[InstrumentKey]
    subscribe_issued_instrument_ids: set[InstrumentKey]
    awaiting_book_sides: set[Side]
    generation_started_at: datetime | None
```

```python
@dataclass(slots=True)
class FeedEvidence:
    first_bilateral_at: datetime | None
    first_bilateral_latency_ms: int | None
    last_book_at_by_side: dict[Side, datetime]
    last_received_at_by_side: dict[Side, datetime]
```

这样仍然保留 readiness、tradability 的正交性，但清理时只需要删除一个 aggregate，不再对十余个字典进行 key join。

| 建议                                                        | 改进价值 | 实施成本 | 引入风险               |
| --------------------------------------------------------- | ---- | ---- | ------------------ |
| 删除不可达的 `INTENT`、未使用参数，重命名 `SUBSCRIBED`，修正 ready predicate | 高    | 低    | 低；主要风险是日志/API 字段兼容 |
| 建立显式 allowed-transition table，并拒绝非法迁移                     | 高    | 低至中  | 低；可能暴露现有隐式跳转       |
| 收敛为 `condition_id -> ConditionRuntimeState` 聚合            | 高    | 中    | 中；迁移期间容易遗漏观测字段     |
| 增加每 condition 最近 16～32 次迁移的内存 ring trace                  | 中    | 低    | 低；注意日志基数           |
| 完整持久化事件溯源、TLA+ 模型或工作流引擎                                   | 低    | 高    | 高；当前属于过度工程         |

**判断：**“显式状态机 + 单一清理入口”作为总体模式已经足够；但应完成 per-condition 聚合和不变式闭合。完整 Event Sourcing 不值得做。

---

# 2. Nautilus FFI / PyO3 边界隔离

## 结论

现有模式是一个**良好起点，但不足以抵御持续 API 漂移**。

正面部分包括：

* `MarketCatalog` 允许注入 `instrument_id_resolver`，具备测试替身入口；
* 官方 `get_polymarket_instrument_id` 被集中调用，而不是本地拼字符串；
* DecisionPipeline 已经通过 `DecisionPolicyPort`、`OrderSubmitter`、`DecisionTelemetry` 隔离决策与提交。 

不足在于：

* `MarketCatalog` 内仍直接动态 import Nautilus；
* `object`、`getattr`、`cast` 和字符串归一化散布在多个边界；
* `_Assembler` 等接口依赖运行时反射兼容两种对象形态，静态检查无法验证真实能力。
* optional import 只能解决“模块是否存在”，不能验证 PyO3 类型族、方法签名、返回形态和行为语义。

## 推荐架构

建立一个小型、能力分割的 anti-corruption layer：

```text
nautilus_compat/
  identifiers.py      # InstrumentKey <-> PyO3 InstrumentId
  subscriptions.py    # subscribe/unsubscribe API
  recorder.py         # recorder config / recorded data
  node.py             # node/config construction
  capabilities.py     # startup probes
  v1_231/             # 当前版本实现
```

不要建立一个数千行的 `NautilusFacade`。按 capability 拆分更容易测试和替换。

项目内部只流通自有类型，例如：

```python
InstrumentKey = NewType("InstrumentKey", str)
```

或者不可变 dataclass：

```python
@dataclass(frozen=True, slots=True)
class InstrumentRef:
    key: str
```

PyO3 `InstrumentId` 只允许出现在 compat implementation 和 Nautilus callback host 中。`MarketCatalog` 应保存项目自有 `InstrumentKey`，不应负责导入 Nautilus。

## 必须增加的契约测试

契约测试必须加载真实 pinned wheel，而不是 fake：

1. 官方 Polymarket ID helper 可以 import；
2. condition/token 到 canonical ID 的结果稳定；
3. string、`.id` 对象和 PyO3 ID 能归一化到同一项目 key；
4. subscribe/unsubscribe 方法名称、关键字参数和 `managed=True` 可调用；
5. instrument provider 回调对象可解析；
6. recorder 可以启动、写入、再读取；
7. recorded event 顺序保持；
8. sandbox order、fill、position 的关键字段可投影。

启动时再做一次轻量 capability probe，输出：

```text
nautilus_version
adapter_version
available_symbols
identifier_family
subscription_api_family
recorder_capable
polymarket_adapter_capable
```

不满足即在 TradingNode 启动前 fail fast。

| 建议                                        | 改进价值 | 实施成本 | 引入风险                |
| ----------------------------------------- | ---- | ---- | ------------------- |
| 项目自有 `InstrumentKey`，PyO3 对象只留在 compat 层  | 高    | 中    | 中；涉及较多函数签名          |
| capability 分割的 ACL，而不是散布 optional imports | 高    | 中    | 低至中                 |
| 针对真实 pinned wheel 的契约测试                   | 高    | 中    | 低；CI 环境需能安装对应 wheel |
| 启动时 capability probe 和兼容性报告               | 高    | 低    | 低                   |
| 同时兼容大量 Nautilus 历史版本                      | 低    | 高    | 高；会制造条件分支矩阵         |

**过度工程红线：**只支持“当前生产版本 + 下一个候选版本”。不要建设通用多版本兼容框架。

---

# 3. domain 层与 nautilus_runtime 膨胀

## 结论

**1143 行 domain 对 8500+ 行 runtime，本身不是架构问题。**

这类系统的复杂度主要来自：

* 外部数据生命周期；
* Nautilus callback 和 PyO3 适配；
* cache、order、fill、position 投影；
* 轮换、恢复、通知和 observability；
* paper execution 编排。

因此 runtime 大于 domain 是正常的。真正需要检查的是**依赖方向和概念归属**，而不是行数比例。

从附件看，runtime 依赖 domain/alpha，而不是反向依赖；DecisionPipeline 也已经使用 Port 隔离策略、订单提交和 telemetry。这是健康信号。

## 哪些概念不应搬进 domain

以下属于运行时控制平面，应继续留在 runtime 或 application/runtime-model：

* subscribe intent；
* pending instrument；
* Nautilus cache visibility；
* wire callback；
* reconnect/retry；
* first book generation；
* PyO3 ID 归一化。

这些是基础设施生命周期，不是业务领域概念。

## 哪些概念可以提升

以下是项目自有、引擎无关并且可能被 health、dashboard、promotion 共同使用的概念：

* `FeedReadinessAssessment`
* `TradabilityAssessment`
* 标准化 reason code
* `StrategyStatus`
* `MarketDataFreshness`
* rotation convergence result

不过建议放在：

```text
polysignal_lab/application/readiness/
```

或：

```text
polysignal_lab/runtime_model/
```

而不是为了平衡 LOC 全部塞入 `domain/`。

`MarketCatalog` 是当前较明显的混合点：`MarketPairMeta` 是项目模型，而 Nautilus ID helper 是基础设施适配。应拆成项目 registry 与 Nautilus resolver。

Generic `DecisionPipeline` 也可以视为 application service，而 `NautilusOrderSubmitter` 留在 Nautilus adapter；但除非 promotion 或其他引擎需要重用，不必立即搬文件。

| 建议                                                              | 改进价值 | 实施成本 | 引入风险     |
| --------------------------------------------------------------- | ---- | ---- | -------- |
| 用 import/AST 规则锁定 `domain -> runtime` 禁止依赖                      | 高    | 低    | 低        |
| 拆分 project-owned `MarketRegistry` 与 Nautilus ID resolver        | 高    | 中    | 中        |
| 将跨运行时复用的 readiness/tradability assessment 提升到 application model | 中    | 中    | 低至中      |
| 为了平衡行数进行大规模目录重组                                                 | 低    | 高    | 高        |
| 将 subscribe/cache/reconnect 状态搬入核心 domain                       | 低    | 中    | 中；污染领域模型 |

---

# 4. SQLite + JSONL + 原子状态文件

## 结论

**三套方案可以合理共存，不建议仅为了“统一”而合并。**

README 已明确声明 SQLite canonical、JSONL audit 和 atomic state files；运行时又使用原子 startup marker 和 heartbeat。这表明三者实际上服务于不同耐久性和访问模式。 

推荐明确成以下权威矩阵：

| 存储     | 正确定位                                                  | 不应承担          |
| ------ | ----------------------------------------------------- | ------------- |
| SQLite | canonical business state、事件序列、事务、projection source    | 纯文本人工审计替代品    |
| JSONL  | append-only forensic mirror / 导出日志                    | 恢复业务状态的第一权威源  |
| 原子状态文件 | heartbeat、startup marker、current operational snapshot | 订单、成交、报告等业务事实 |

## 主要风险不是“三套”，而是“双写一致性”

如果 SQLite commit 成功、JSONL append 失败，需要明确定义：

* SQLite 是否仍为成功；
* JSONL 是否允许缺口；
* 如何发现和补写；
* 两边如何通过 `event_id`、`sequence` 对账。

推荐所有 canonical event 先进入 SQLite，并带：

```text
event_id
stream
sequence
occurred_at
recorded_at
schema_version
payload
```

JSONL 从已提交事件导出，并保存 exporter checkpoint。这样 JSONL 是可恢复的 audit projection，而不是与 SQLite 竞争权威。

原子状态文件只应由 canonical/health 状态生成；进程启动时不能以它重建业务账本。

| 建议                                                     | 改进价值 | 实施成本 | 引入风险 |
| ------------------------------------------------------ | ---- | ---- | ---- |
| 编写 source-of-truth 与恢复矩阵                               | 高    | 低    | 低    |
| SQLite event ID/sequence 与 JSONL exporter checkpoint   | 高    | 中    | 低至中  |
| crash-point 测试：commit 前后、JSONL append 前后、projection 中断 | 高    | 中    | 低    |
| 所有 projection 可幂等重建并有 checksum/count 对账                | 高    | 中    | 低    |
| 全面改成事件溯源平台或外部消息队列                                      | 低    | 高    | 高    |

**判断：**保留 canonical → projection → read model。不要引入 Kafka、独立 event store 或分布式 CQRS。

---

# 5. 为什么 980 个测试仍放走结构性 bug

## 结论

测试数量没有覆盖两个关键维度：

1. **事件序列空间**；
2. **全局不变式与状态所有权**。

示例式测试通常覆盖：

```text
subscribe -> instrument -> book -> ready
```

但真实缺陷来自：

```text
subscribe
-> metadata delayed
-> one instrument arrives
-> rotate out
-> delayed second callback
-> stale recovery
-> rotate back
-> duplicate instrument callback
```

单个函数和单条 happy path 都可能正确，但组合后状态泄漏。

## 应采用的测试组合

### 5.1 Hypothesis stateful testing

值得引入 `RuleBasedStateMachine`。动作至少包括：

* activate condition；
* metadata absent/arrives；
* UP/DOWN instrument 任意顺序到达；
* duplicate instrument callback；
* UP/DOWN book 任意顺序到达；
* old/delayed book；
* stale；
* recover；
* rotate out；
* rotate back；
* unsubscribe all；
* registry replacement；
* subscribe API 抛异常。

每一步执行后都调用同一个：

```python
assert_subscription_invariants(strategy)
```

核心不变式应包括：

```text
PENDING_INSTRUMENT => pending instruments 非空
AWAITING_FIRST_BOOK => awaiting sides 非空且 generation_started_at 存在
READY => awaiting sides 为空且 first_bilateral_at 存在
pending 与 subscribe-issued instrument 不重叠
inactive condition 不得拥有 active readiness markers
cleanup 后迟到 callback 不得复活 lifecycle
重复 callback 不改变最终状态
rotation A -> B -> A 与 fresh A 的有效状态等价
长期轮换后 state cardinality 有上界
```

### 5.2 mutation ownership 架构门禁

`pyproject.toml` 已包含 `ast_grep_cli`，非常适合用于结构约束。

建议禁止在 `subscriptions.py` 之外直接执行：

```text
condition_phases[...]
pending_instrument_ids.add/discard
awaiting_book_sides_by_condition[...]
book_generation_started_at_by_condition[...]
```

同时禁止从非 lifecycle 模块直接删除 `_active_condition_ids`。

这样以后即使新文件加入逻辑，也不能重新形成“五个文件各自 add/discard”。

### 5.3 模型对照测试

写一个极简纯函数 reference reducer：

```python
state2 = reduce(state1, event)
```

然后让真实实现和 reference model 接收同一随机事件序列，比较最终 lifecycle 和 readiness。模型不需要包含 Nautilus，只表达预期状态图。

### 5.4 promotion 边界测试

对 promotion 使用 boundary table，而不是仅测完整报告：

* boundary 前 1 ns；
* boundary 等于起点；
* boundary 等于终点；
* 终点后 1 ns；
* sample floor −1、等于、+1；
* settled、unsettled、late-settled；
* 相同 timestamp 不同原始 sequence；
* 重复 event；
* train/OOS 重叠与空洞。

### 5.5 快照测试的适用范围

快照测试适合：

* OpenAPI schema；
* promotion manifest；
* promotion report；
* dashboard response fixture；
* readiness detail 的序列化格式。

它不适合作为 subscription correctness 的主测试，因为快照只能证明某一个固定序列的输出，没有证明任意序列下的不变式。

| 建议                                    | 改进价值 | 实施成本 | 引入风险          |
| ------------------------------------- | ---- | ---- | ------------- |
| Hypothesis state machine + invariants | 高    | 中    | 低；主要成本在构建模型   |
| AST/ast-grep 状态所有权门禁                  | 高    | 低    | 低             |
| 10k～100k 次轮换的 deterministic soak test | 高    | 低至中  | 低；注意测试运行时间    |
| 关键模块选择性 mutation testing              | 中    | 中    | 低             |
| 大量新增普通 example tests                  | 中低   | 中    | 低，但不能解决序列空间问题 |
| 依赖快照测试验证状态清理                          | 低    | 低    | 中；容易产生虚假安全感   |

---

# 6. promotion 回放验证架构

## 结论

重复出现 OOS、sample floor、settled round 和 event order 问题，说明当前主要风险不是回放引擎，而是：

> 数据集、分区、资格集合和报告分母之间缺少一个不可变的共同契约。

## 推荐架构

### 6.1 不可变 DatasetManifest

每次 promotion 首先生成：

```python
@dataclass(frozen=True, slots=True)
class DatasetManifest:
    dataset_id: str
    schema_version: int
    source_fingerprint: str
    ordered_event_fingerprint: str
    event_count: int
    condition_count: int
    min_event_at: datetime
    max_event_at: datetime
    partition_spec: PartitionSpec
    settlement_cutoff: datetime
```

fingerprint 应覆盖：

```text
canonical event payload
原始顺序号
event timestamp
received timestamp
condition/instrument ID
schema version
```

数据 fingerprint 与 run fingerprint 分开：

```text
run_fingerprint =
  dataset_fingerprint
  + partition_spec
  + promoted_parameter
  + complete strategy config
  + code commit
  + Nautilus version
  + engine options
```

### 6.2 分区先于引擎和候选参数

不要把完整数据集传给 runner，再由 runner 内部过滤。

应先构造不同类型：

```python
InSamplePartition
ValidationPartition
OutOfSamplePartition
```

OOS runner 的函数签名只能接收 `OutOfSamplePartition`。这不是为了类型美观，而是让 OOS 泄漏在结构上更难发生。

所有区间统一使用半开区间：

```text
[start, end)
```

遇到缺失时间、重叠、空洞、重复归属时 fail closed。

### 6.3 单一 RoundEligibilityLedger

settled round、sample floor 和 report denominator 必须来自同一份 ledger：

```python
@dataclass(frozen=True)
class RoundEligibility:
    condition_id: str
    partition: PartitionName
    settled: bool
    eligible: bool
    exclusion_reasons: tuple[str, ...]
```

报告、promotion gate 和 sample floor 只能查询该 ledger，禁止各自重新统计。

### 6.4 物理隔离回放实例

每个 partition 和 candidate 使用：

* 新 TradingNode/engine；
* 新临时 SQLite；
* 清空 cache/state；
* 只读输入 snapshot；
* 明确时钟起点；
* 固定 event total order。

不要复用同一 engine instance 先跑 in-sample 再跑 OOS，否则 cache、position、settlement 和统计对象都可能越界残留。

### 6.5 报告必须自证边界

promotion report 应包含：

```text
dataset_id
dataset_fingerprint
run_fingerprint
partition start/end
input event count
eligible round count
settled round count
excluded count by reason
parameter before/after
code version
Nautilus version
```

| 建议                                             | 改进价值 | 实施成本 | 引入风险      |
| ---------------------------------------------- | ---- | ---- | --------- |
| DatasetManifest + PartitionSpec + fingerprints | 高    | 中    | 低         |
| typed partition，OOS runner 不接触全量数据             | 高    | 中    | 低至中       |
| 单一 RoundEligibilityLedger                      | 高    | 中    | 低         |
| 每 partition 使用全新 engine/DB/cache               | 高    | 中    | 低；运行资源会上升 |
| 报告内嵌可验证 manifest                               | 高    | 低至中  | 低         |
| 引入 MLflow、Airflow、feature store                | 低    | 高    | 高；当前规模不合适 |

---

# 7. 可观测性是否完备

## 结论

当前可观测性基础较强，但**liveness、readiness、dependency health 和 signal quality 需要进一步分层**。

运行时已经有：

* startup marker；
* heartbeat；
* `LivenessWatchdog`；
* Telegram health alert；
* per-condition readiness detail；
* subscribe intent age；
* generation age；
* first bilateral latency；
* per-side freshness。

因此新增 SLO 不需要重新采集核心数据。 

## 必须分开的四类状态

### Process liveness

只回答：

```text
进程、事件循环、核心线程是否还能前进
```

不应因为某一个外部市场长时间无双边行情而判定进程死亡。

### Runtime readiness

回答：

```text
是否已完成配置加载、instrument 准备和必要订阅收敛
```

可以设置 startup/rotation grace period。

### Dependency/data health

回答：

```text
Polymarket feed 是否断线、陈旧、单边、反复 flap
```

这是 degraded，而不一定是 dead。

### Signal/business telemetry

回答：

```text
有多少 condition 被评估、多少生成信号、为什么拒绝、paper 表现如何
```

不应直接控制容器重启。

## 建议指标

优先增加：

```text
subscription_to_first_bilateral_ms p50/p95/p99
rotation_to_ready_ms
ready_conditions / expected_active_conditions
pending_metadata_duration
pending_instrument_duration
one_sided_book_duration
stale_duration
feed_recovery_duration
readiness_flap_count
late_or_out_of_order_event_count
market_data_event_lag_ms
projection_lag
telemetry_queue_backlog/drop
Telegram delivery failure
```

信号质量另设：

```text
evaluations
alpha candidates
rejection count by reason
accepted decisions
paper fill ratio
reference-to-fill slippage
strategy/timeframe hit rate
calibration by confidence bucket
```

Alert 应采用 duration/quorum：

```text
某 condition 不 ready 30 秒：记录 degraded
某 asset/timeframe readiness 低于 quorum 持续一段时间：告警
process heartbeat 停止：立即 liveness failure
```

轮换 grace、preloaded market 和预期开盘时间必须抑制误报。

| 建议                                          | 改进价值 | 实施成本 | 引入风险                 |
| ------------------------------------------- | ---- | ---- | -------------------- |
| 将 `/live`、`/ready`、`/health/status` 分离      | 高    | 中    | 低；需调整 healthcheck 语义 |
| 暴露现有 timing/freshness 数据为 histogram/counter | 高    | 低    | 低                    |
| rotation convergence 与 readiness flap 指标    | 高    | 低至中  | 低                    |
| signal funnel 和 paper quality 指标            | 中高   | 中    | 低                    |
| 对每个 condition 单独即时 Telegram 告警              | 低    | 低    | 高；会产生告警风暴            |
| 立即引入完整 OTel/Prometheus/Grafana 体系           | 中低   | 高    | 中；单进程阶段可能过重          |

尤其需要避免：

> 上游市场无数据 → liveness failed → 容器重启 → 重新订阅 → readiness 再失败

这种自激式恢复循环。

---

# 8. 前后端契约

## 结论

**值得引入 OpenAPI 代码生成；不需要 Pact 或 GraphQL。**

README 已公开七个只读接口，且前后端在同一仓库、同一部署边界内。这是 OpenAPI-first contract 最合适的场景。

## 推荐流程

### 后端

每个 FastAPI endpoint 都必须：

* 指定 Pydantic response model；
* 禁止返回无模型约束的任意 `dict`；
* 明确 nullable、enum、datetime、decimal、pagination；
* 关键响应模型使用稳定字段名；
* projection 缺失与合法 `null` 分开表达。

### Schema

CI 中：

1. 从 FastAPI app 导出 `openapi.json`；
2. 与仓库中的 schema artifact 比较；
3. 使用 breaking-change checker；
4. 删除字段、改类型、required 变化时 fail；
5. 新增 optional 字段允许通过。

### 前端

使用 `openapi-typescript` 或 Orval 生成：

* TypeScript 类型；
* API client；
* 可选的 TanStack Query hooks。

前端禁止手写重复的 DTO interface。

### 端到端契约测试

至少建立一条真实链路：

```text
seed SQLite/projection
-> 启动 FastAPI TestClient
-> 请求 endpoint
-> response 通过 OpenAPI/Pydantic 验证
-> frontend fixture 由该 response 生成
-> frontend build/typecheck
```

测试以下特殊情况：

* 空列表；
* nullable 字段；
* 未完成 position；
* rejected signal detail；
* UTC datetime；
* 大整数/decimal；
* 新 enum value；
* projection incomplete reason。

TypeScript codegen 解决编译时契约，但不解决运行时数据错误。高风险接口可额外生成 Zod validator；不必全部接口都做 runtime validation。

| 建议                                        | 改进价值 | 实施成本 | 引入风险       |
| ----------------------------------------- | ---- | ---- | ---------- |
| 所有 endpoint 使用明确 Pydantic response model  | 高    | 低至中  | 低          |
| 提交 OpenAPI schema 并做 breaking diff        | 高    | 低    | 低          |
| 生成 TypeScript client/types/TanStack hooks | 高    | 中    | 低          |
| 后端 projection 到真实 endpoint 的集成契约测试        | 高    | 中    | 低          |
| 全量 Zod runtime validation                 | 中    | 中    | 低至中        |
| Pact、GraphQL、独立 BFF                       | 低    | 高    | 高；当前属于过度工程 |

---

# 9. Nautilus 精确 pin 与升级机制

## 结论

`nautilus_trader[polymarket]==1.231.0a20260730` 的精确 pin 是正确的，尤其考虑到：

* alpha 版本；
* PyO3 类型族变化；
* recorder 和 websocket API 漂移；
* adapter 行为可能变化。

不应改成 `>=`、`~=` 或浮动最新版本。

## 当前配置中的一个小问题

同一个精确版本同时声明在：

* 基础 dependencies；
* `nautilus` optional dependency。

目前二者一致，但以后升级时存在只改一处的风险。

如果 Nautilus 是生产运行必需依赖，建议保留基础 dependency，删除重复 extra。

如果希望 dashboard-only 安装不包含 Nautilus，则应从基础依赖移除，并明确安装：

```text
.[dev,nautilus]
```

不要双重声明。

附件未显示 lockfile，无法确认当前是否已经锁定 transitive dependencies。若没有，需要增加 lock 和 wheel/hash 固定；直接依赖精确 pin 并不能保证全部传递依赖完全可复现。

## 推荐双通道

### Production lane

* 当前生产 pin；
* 所有测试必须通过；
* bounded smoke 必须通过；
* safety scan 必须通过；
* 生成兼容性 manifest。

### Candidate lane

定时或手动测试一个候选 alpha：

* 允许 CI 非阻断失败；
* 运行真实 wheel 契约测试；
* 输出与 production 的 compatibility diff；
* 只有全绿时才发升级 PR。

## 升级 checklist

每次升级至少验证：

```text
import paths and symbols
InstrumentId canonicalization and round-trip
Polymarket helper output
client_id routing
instrument provider/cache callbacks
subscribe/unsubscribe signatures
book type conversion
managed book behavior
recorder start/write/read
recorded event ordering
websocket connection/recovery
sandbox order submission
fill/position/account projections
paper settlement/reporting
bounded live read-only smoke
```

| 建议                                       | 改进价值 | 实施成本 | 引入风险 |
| ---------------------------------------- | ---- | ---- | ---- |
| 继续精确 pin production version              | 高    | 低    | 低    |
| 去除重复 dependency 声明                       | 中    | 低    | 低    |
| 锁定 transitive dependency 和 artifact hash | 高    | 低至中  | 低    |
| production/candidate 双 CI 通道             | 高    | 中    | 低    |
| 自动兼容性 manifest diff                      | 高    | 中    | 低    |
| 生产环境自动跟随最新 alpha                         | 低    | 低    | 极高   |
| 长期维护多个 Nautilus 版本实现                     | 低    | 高    | 高    |

---

# 当前规模下不应该做的事项

以下均属于明确的过度工程红线：

| 不应做                                          | 原因                                           |
| -------------------------------------------- | -------------------------------------------- |
| 为订阅状态建立持久化 Event Sourcing/CQRS 系统            | 问题是聚合和不变式，不是缺少事件基础设施                         |
| 引入 Kafka、Redis Streams 或工作流引擎                | 单进程 paper-validation 系统没有分布式协调需求             |
| 为状态机立即采用 TLA+、模型检查器或形式化证明                    | transition table + property testing 已能覆盖主要风险 |
| 为平衡 LOC 把 runtime 概念批量搬入 domain              | 会污染领域层而不降低耦合                                 |
| 建设支持任意 Nautilus 版本的通用兼容框架                    | 版本组合爆炸；只支持 production + candidate            |
| 将 SQLite、JSONL、state file 强行统一成一个抽象          | 三者耐久性和用途不同                                   |
| 引入 MLflow、Airflow、feature store 管理 promotion | 当前问题是分区契约，不是实验平台不足                           |
| 为同仓库 dashboard 引入 Pact、GraphQL 或独立 BFF       | OpenAPI + codegen 已足够                        |
| 因单个 feed condition stale 直接重启整个容器            | 容易形成外部故障驱动的重启循环                              |
| 以更多普通单元测试替代状态机/属性测试                          | 无法覆盖序列组合和状态残留                                |

---

# ROI 最高的三个改进

## 1. 生命周期不变式套件

范围：

* 修正不可达/歧义 phase；
* 建立 transition table；
* `assert_subscription_invariants()`；
* Hypothesis stateful test；
* ast-grep 禁止旁路状态写入；
* 长时间轮换 cardinality 测试。

| 改进价值 | 实施成本 | 引入风险 |
| ---- | ---- | ---- |
| 极高   | 中    | 低至中  |

这是直接针对反复复发的状态泄漏根因，而不是再增加一批固定路径测试。

## 2. Promotion DatasetManifest + PartitionContract

范围：

* typed partition；
* dataset/run fingerprint；
* RoundEligibilityLedger；
* fresh engine/DB per partition；
* 报告自带 manifest。

| 改进价值 | 实施成本 | 引入风险 |
| ---- | ---- | ---- |
| 极高   | 中    | 低    |

它能同时压住 OOS 泄漏、sample floor、settled round 和 event ordering 四类历史问题。

## 3. Nautilus 真实 wheel 契约测试与 candidate lane

范围：

* project-owned ID type；
* capability-based compat layer；
* startup probe；
* production/candidate CI；
* upgrade manifest diff。

| 改进价值 | 实施成本 | 引入风险 |
| ---- | ---- | ---- |
| 高    | 中    | 低    |

它不能消除上游变化，但可以把“运行后发现 API 漂移”提前为“升级 PR 阶段确定失败”。

---

## 最终定性

PolySignal Lab 当前不是“分层错误”，而是已经进入下一阶段：

> 主要风险从局部实现错误，转移到了状态生命周期、边界契约和外部适配契约。

因此下一轮不应继续扩大抽象层数。应优先把三个高风险边界做成可执行契约：

```text
subscription lifecycle invariants
promotion partition invariants
Nautilus compatibility contracts
```

这三项完成后，现有 architecture 足以支撑当前单进程、只读信号和 paper-validation 规模。
