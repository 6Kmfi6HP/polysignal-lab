# Architecture Boundary Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Review status (2026-07-09):** multi-agent review → **Approve with changes**. 本版已吸收审查补丁后再执行。

**Goal:** 收口 `src/polysignal_lab` 的架构边界：删空壳、钉死行情真相源、统一 gate 输入协议、定向拆薄 `native_strategy.py`，**不改变产品行为**。

**Architecture:** 保持现有分层（`alpha` 纯决策、`signal_layer` 质控、`nautilus_bridge` 适配、`nautilus_runtime` 跑节点、`data` 做 discovery/settlement/smoke/display helpers）。重构原则是**做减法**：减少决策路径上的双轨真相源，而不是新建更多包或重写策略。

**Tech Stack:** Python 3.11+（默认 import 边界）、NautilusTrader（optional extra）、pytest、现有 `config/signal_bot.yaml` 运行路径。

## Global Constraints

- 不引入实盘 Polymarket execution client
- 不新增顶层包；优先同目录拆分
- 默认行为不变：paper sandbox + Telegram dry-run + 只读 dashboard
- **reason_code 字符串必须保持稳定**（报表/测试依赖）
- 每个 Task 结束必须有可运行测试/检查；小步提交；一 Task 一（或多次）独立 commit
- 不修改 `@refs/` 与 `docs/nautilus_reference/` 参考内容
- Nautilus 相关改动前对照 `docs/NAUTILUS_BRIDGE_BOUNDARY.md`
- **禁止**把 Telegram / smoke / 测试夹具里的 `OrderBookRegistry` 误判成 “nautilus decision truth” 而删除
- 执行前先看下方 **Already done / skip if present**，避免重复劳动

## 一句话目标图

```text
现在：空 strategies/ + gate 仍吃 MarketSnapshot 壳 + Adapter 语义残留
      + data registry 仍出现在装配/展示路径 + native_strategy 仍偏厚
目标：Nautilus cache/custom data = nautilus 决策行情真相
      gate 协议化（兼容 Snapshot 测试 + MarketView 运行）
      Adapter 语义 parity 保留后删除适配壳
      策略入口只在 alpha/ + nautilus_runtime/
      native_strategy 按职责拆薄（node 已基本拆完，不再为拆而拆）
```

## Already done / skip if present

执行任何 Task 前先核对；已完成的只做确认，不重复大改：

| 项 | 现状（2026-07-09 审查时） | 计划动作 |
|----|---------------------------|----------|
| `domain/paper_order.py` / `paper_position.py` | 已删除 | Task 6 只做残留引用确认 + 文档 Role |
| `nautilus_runtime/node_builder*.py` / `node_cli.py` / `node_crash.py` / `node_signals.py` 等 | 已存在；`node.py` ~292 行 | Task 5 **不**再大拆 node；仅 optional |
| `nautilus_runtime/strategy/helpers.py` / `subscriptions.py` | 已存在 | Task 5 优先复用，不重造 |
| `native_strategy.py` | 仍偏厚（~724 行） | Task 5 **主目标** |
| 顶层 `strategies/` | 仅 `__pycache__`，无业务 `.py` | Task 1 删除空壳 |
| `_GateSnapshotAdapter` | 仍在 `decision_policy.py`，含实质语义 | Task 4 核心，不可只改注解 |
| 工作树可能已有未提交改动 | 常见 | 每个 Task commit 前 `git status`；只 stage 本 Task 文件 |

## 不在本次范围

- 不重写 alpha 策略公式
- 不升级为实盘交易
- 不把项目拆成微服务
- 不做前端大改
- 不合并 `alpha` 与 `signal_layer`
- 不把 `data/` 整包并进 `nautilus_bridge`
- **不**把 `formatter.py` 迁到 `publish/`（可选，另开任务）
- **不**删除 `data/market_snapshot.py` 或 CLOB 客户端（除非证明零引用且另开任务）
- **不**删除 `PaperWalletSnapshot` 存储/报表 DTO

## 文件归属（重构后）

| 能力 | 归属 |
|------|------|
| 策略公式 | `alpha/` |
| gate / dedupe / arbiter | `signal_layer/` |
| condition/token ↔ instrument、MarketView 组装 | `nautilus_bridge/` |
| LiveNode / 下单 / 投影 | `nautilus_runtime/` |
| 市场发现 / 结算 HTTP / smoke 工具 | `data/` + `app/` |
| 落库 | `storage/` via `PersistenceService` |
| Telegram | `publish/` via `PublishService` |
| 结算统计 | `paper/` |
| 只读 API | `dashboard/` |

## Market data source of truth（三分法，全计划遵守）

```text
1) nautilus decision truth（决策/下单/信号接受）
   - 只允许：Nautilus Cache + PolySignal CustomData → MarketViewAssembler → MarketView
   - 禁止：把 data.OrderBookRegistry / MarketSnapshotBuilder 当决策 book 真相源

2) discovery / settlement / smoke helpers
   - data/ 市场发现、Gamma/CTF、公开 REST、限流、CLOB 工具
   - 可保留；不喂 nautilus evaluate/submit 决策主链

3) display / reporting
   - Telegram、dashboard、SQLite 投影、空 OrderBookRegistry 占位
   - 可读，不算 decision truth；Task 3 不得当 P0 删除
```

---

### Task 1: 删除空壳 `strategies/`，修正文档入口

**为什么：** 顶层 `src/polysignal_lab/strategies/` 没有业务源码，只会把人带到错误位置。真实策略在 `alpha/` 与 `nautilus_runtime/`。

**Files:**
- Delete: `src/polysignal_lab/strategies/`（namespace package，可能无 `__init__.py`；含 `__pycache__` 一并删）
- Modify: `README.md`（仅当仍指向该目录或缺少策略入口说明）
- Modify: `src/polysignal_lab/FOLDER_INDEX.md`（若列出该目录）
- **不要**为清理历史文档去改 `docs/superpowers/plans/**` 旧计划

**Interfaces:**
- Consumes: 无
- Produces: 仓库 `src/` 中不再存在可导入的空 `polysignal_lab.strategies` 包

- [ ] **Step 1: 确认没有运行时依赖（收窄搜索，避开历史 plan 假阳性）**

```bash
rg -n "polysignal_lab\.strategies|from polysignal_lab import strategies" src tests README.md src/polysignal_lab || true
```

Expected: `src/` / `tests/` 无业务 import。  
若有，先改到 `alpha` / `nautilus_runtime`。  
`docs/superpowers/**` 历史命中可忽略。

- [ ] **Step 2: 删除空目录**

```bash
rm -rf src/polysignal_lab/strategies
```

- [ ] **Step 3: 更新文档一句话入口（若 README 尚未写明）**

```text
策略逻辑：src/polysignal_lab/alpha/
Nautilus 包装：src/polysignal_lab/nautilus_runtime/
```

- [ ] **Step 4: 跑快速回归**

```bash
.venv/bin/python -m pytest -q tests/test_nautilus_dependency_boundary.py tests/test_alpha_types.py
```

Expected: PASS

- [ ] **Step 5: Commit（只 stage 本 Task 文件）**

```bash
git add -A src/polysignal_lab/strategies README.md src/polysignal_lab/FOLDER_INDEX.md
git status
git commit -m "chore: remove empty strategies package and point docs to alpha"
```

---

### Task 2: 钉死「行情真相源」规则（文档 + 清单种子）

**为什么：** 重构成败取决于先约定谁说了算；并避免把 display registry 当成决策双轨。

**Files:**
- Modify: `docs/NAUTILUS_BRIDGE_BOUNDARY.md`
- Modify: `src/polysignal_lab/data/FOLDER_INDEX.md`
- Modify: `src/polysignal_lab/nautilus_runtime/FOLDER_INDEX.md`
- Optional: 把扫描结果附录进提交说明（不必新建长文）

- [ ] **Step 1: 写清 Source of Truth 小节（必须含三分法）**

在 `docs/NAUTILUS_BRIDGE_BOUNDARY.md` 增加：

```markdown
## Market data source of truth

### 1. Nautilus decision truth
- Runtime decisions (evaluate / submit / accept signal) use only:
  Nautilus cache + PolySignal custom data assembled into MarketView.
- No parallel `OrderBookRegistry` / `MarketSnapshotBuilder` as decision
  order-book truth in nautilus mode.

### 2. Discovery / settlement / smoke
- `data/` keeps market discovery, Gamma/CTF settlement clients, public REST,
  rate limiters, and smoke helpers.

### 3. Display / reporting
- Telegram, dashboard, and SQLite projections may read projected state or hold
  an empty/display `OrderBookRegistry`.
- Display wiring is not decision truth and must not be deleted just because
  the symbol name matches a legacy registry.
```

- [ ] **Step 2: 更新 `data/FOLDER_INDEX.md` Role**

```markdown
**Role**: public market discovery, settlement clients, smoke helpers,
and non-decision display/tooling support.
Not the nautilus-mode order-book source of truth for evaluate/submit.
```

- [ ] **Step 3: 更新 `nautilus_runtime/FOLDER_INDEX.md` Role 一句**

写明：决策行情来自 cache + custom data + `MarketViewAssembler`。

- [ ] **Step 4: 扫描并为 Task 3 准备种子命中（写入 commit message 或 PR 笔记）**

```bash
rg -n "OrderBookRegistry|MarketSnapshotBuilder|MarketSnapshot\b|_GateSnapshotAdapter" \
  src/polysignal_lab/nautilus_runtime \
  src/polysignal_lab/signal_layer \
  src/polysignal_lab/publish \
  src/polysignal_lab/app \
  -g'*.py'
```

至少预期会看到（审查时存在）：

- `nautilus_runtime/decision_policy.py` → `_GateSnapshotAdapter`（**Task 4**，不是 Task 3 删除目标）
- `nautilus_runtime/runtime_context_factory.py` → `OrderBookRegistry()` 给 Telegram（**display**）
- `publish/telegram_bot.py` → `OrderBookRegistry` 参数（**display**）
- `signal_layer/gate.py` → `MarketSnapshot` 类型（**Task 4**）
- `data/market_snapshot.py` / tests → builder（**smoke/test keep**）

- [ ] **Step 5: Commit**

```bash
git add docs/NAUTILUS_BRIDGE_BOUNDARY.md \
  src/polysignal_lab/data/FOLDER_INDEX.md \
  src/polysignal_lab/nautilus_runtime/FOLDER_INDEX.md
git commit -m "docs: define market data source of truth (decision vs display)"
```

---

### Task 3: 收缩 `data/` 在 **nautilus 决策路径** 上的角色

**为什么：** `data/` 不是要删，而是要确保 **evaluate/submit 不把它当 book 真相源**。

**硬门闩（Done 定义）：**
1. 产出下面的 **固定清单表**（填实，不是只跑 rg）
2. 对标记为 `cut from decision path` 的点完成切断或确认已切断
3. **禁止删除** `data/` 文件
4. **本 Task 未完成清单前，禁止开始 Task 4**

**Files:**
- Review（至少）:
  - `src/polysignal_lab/nautilus_runtime/runtime_context_factory.py`
  - `src/polysignal_lab/nautilus_runtime/market_rotation.py`（若引用 SpotRegistry/旧状态）
  - `src/polysignal_lab/publish/telegram_bot.py`
  - `src/polysignal_lab/data/market_snapshot.py`
  - `src/polysignal_lab/data/state.py`
  - `src/polysignal_lab/data/polymarket_clob_ws.py`
  - `src/polysignal_lab/data/polymarket_clob_rest.py`
- Modify: **仅** nautilus **decision** 路径上仍把 registry/snapshot 当 book 真相的代码
- Keep: discovery / settlement / smoke / Telegram display wiring
- Test: `tests/test_nautilus_cache_market_data.py`、`tests/test_nautilus_market_view_assembler.py`、`tests/test_market_data.py`、`tests/test_market_parsing.py`、`tests/test_nautilus_full_paper_runtime_smoke.py`

**预填清单模板（Step 1 必须填完）：**

| 路径 | 当前角色 | 分类 | 本 Task 动作 |
|------|----------|------|----------------|
| `nautilus_runtime/**` 中 evaluate/submit 读 `OrderBookRegistry` 的点 | decision? | decision / display / smoke / none | cut / already clean / n/a |
| `runtime_context_factory.py` `books=OrderBookRegistry()` | Telegram 装配 | display | **keep**（标注 helper，不删） |
| `publish/telegram_bot.py` `books: OrderBookRegistry` | 展示 | display | **keep** |
| `data/market_snapshot.py` | 测试/smoke 构建 | smoke/test | **keep** |
| `data/polymarket_clob_ws.py` 等 | 工具/非主决策 | helper | **keep**（除非证明在 decision 主链） |
| `decision_policy._GateSnapshotAdapter` | gate 适配 | gate scar | **defer Task 4**（本 Task 不动） |

**Keep / Retire 速查：**

| 文件 | 建议 |
|------|------|
| `polymarket_market_discovery.py` | Keep |
| `gamma_resolution_client.py` / `ctf_resolution_client.py` | Keep |
| `public_market_data_client.py` | Keep（smoke） |
| `binance_spot_ws.py` / PTB / anchor | Keep 作为 custom data 源或辅助 |
| `market_snapshot.py` | Keep 为 test/smoke helper |
| CLOB WS/REST | Keep 为工具；不在本 Task 删除 |
| 任何 decision 路径上的平行 book 真相读取 | **cut** 到 cache + MarketView |

- [ ] **Step 1: 填固定清单表（硬前置产出物）**

```bash
rg -n "MarketSnapshotBuilder|OrderBookRegistry|books_for_market|MarketSnapshot\b" \
  src/polysignal_lab/nautilus_runtime src/polysignal_lab/publish src/polysignal_lab/app \
  -g'*.py'
```

把每个命中标成：`decision` / `display` / `smoke` / `test` / `defer-task-4`。  
将填好的表贴进 commit message 正文或 `docs/superpowers/plans/` 本计划附录（可选短附录）。

- [ ] **Step 2: 只处理 `decision` 类命中**

对每个 `decision` 命中二选一：

1. 改为 `MarketViewAssembler` + `NautilusCacheMarketDataProvider` + custom data  
2. 若误判：降级标注为 display/smoke helper，并改清单分类  

**禁止**对 `display` / `smoke` / `test` 做删除式“清理”。

- [ ] **Step 3: 决策路径回归**

```bash
.venv/bin/python -m pytest -q \
  tests/test_nautilus_cache_market_data.py \
  tests/test_nautilus_market_view_assembler.py \
  tests/test_nautilus_full_paper_runtime_smoke.py
```

Expected: PASS

- [ ] **Step 4: 确认 discovery/smoke 未误伤**

```bash
.venv/bin/python -m pytest -q tests/test_market_data.py tests/test_market_parsing.py
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git commit -m "refactor: cut data-layer books from nautilus decision path only"
```

**完成检查：** 清单表已填；无 `data/` 文件删除；Task 4 仍未开始改 gate。

---

### Task 4: `signal_layer` 协议化输入 + Adapter 语义 parity

**为什么：** runtime 已在用 `MarketView`；真正疤痕是 `decision_policy._GateSnapshotAdapter` 的**实质语义**，不是单纯类型名。

**硬前提：** Task 3 清单完成。

**Files:**
- Modify: `src/polysignal_lab/signal_layer/gate.py`
- Modify: `src/polysignal_lab/nautilus_runtime/decision_policy.py`
- Test create/modify: `tests/test_signal_gate.py`（新增 MarketView / parity 用例）
- Test: `tests/test_signal_arbiter.py`、`tests/test_order_intent.py`、`tests/test_health_metrics.py`、`tests/test_nautilus_strategy_base.py`
- 若存在：`tests/test_nautilus_decision_policy.py` 或 decision_policy 相关测试一并跑
- **不做：** `formatter.py` 搬家

**关键现状（审查确认）：**
- `gate.evaluate(candidate, snapshot: MarketSnapshot)`（`signal_layer/gate.py`）
- `_GateSnapshotAdapter`（`decision_policy.py`）含至少：
  - `market.is_active` 来自 `view.metrics["market_is_active"|"is_active"]`
  - 空 book（bid/ask/spread/freshness 全空）→ `None`（影响 `MISSING_ORDERBOOK` / spread 等）
  - book/spot `freshness_ms(now)` 协议适配
- 现有 `tests/test_signal_gate.py` **全是** `MarketSnapshot` 路径；**没有**可用的 `-k market_view` 存量用例

**兼容策略（写死）：**
- Gate 使用 **Protocol / duck-typing**（“GateMarket” 协议面），**过渡期同时兼容**：
  - 现有测试里的 `MarketSnapshot`
  - 运行路径的 `MarketView`（及具备相同方法的对象）
- **禁止**把签名改成“只接受 `MarketView` 类型”导致 Snapshot 测试全炸
- **禁止**只改类型注解、不搬 Adapter 语义

**Gate 最小协议面（实现时以现有 check 实际读取为准）：**

```text
created_at
market.is_active
spot（含 freshness 可读）
book_for(side) / ask_for(side)
（以及 gate 现有 check 已用到的等价字段）
```

**成功标准（硬）：**
- 同一组输入下，旧 `_GateSnapshotAdapter(view)` 路径与新 gate 直接路径的：
  - `accepted` / `rejected`
  - `reason_code`
  - 关键 details 键（至少 `reason_code`）
  **parity 一致**
- 旧 `MarketSnapshot` 全量 gate 测试继续 PASS
- reason_code 字符串不重命名

- [ ] **Step 1: 先写 parity 测试（必须先红/先锁定行为）**

在 `tests/test_signal_gate.py`（或邻近测试文件）新增用例，覆盖至少：

1. `test_gate_accepts_market_view_without_snapshot_type`  
2. `test_gate_market_view_parity_with_adapter_empty_book`（空 book → 与 Adapter 相同 reason）  
3. `test_gate_market_view_parity_active_flag_from_metrics`（is_active 映射）  
4. 保留并继续运行现有 Snapshot 用例

Parity 测试应直接对比：

```python
# 概念：同一 view
legacy = gate.evaluate(candidate, _GateSnapshotAdapter(view))  # 或抽取纯函数
new = gate.evaluate(candidate, view)  # 协议化后
assert legacy.accepted == new.accepted
assert reason_codes_equal(legacy, new)
```

若测试阶段仍需 import 私有 Adapter，允许临时测试访问；实现完成后 Adapter 可删。

- [ ] **Step 2: 跑新测试，确认当前基线**

```bash
.venv/bin/python -m pytest -q tests/test_signal_gate.py -k "market_view or parity" -v
```

Expected: 新用例在改实现前失败或明确锁定旧行为；**不要**用假想的存量 `-k market_view` 当唯一信号。

- [ ] **Step 3: 最小改动 gate（协议化 + 吸收 Adapter 语义）**

- 将 `evaluate` 第二参数改为协议/duck-type（仍可传入 `MarketSnapshot`）
- 把空 book → missing、active metrics、freshness 协议等语义放进 gate 或小型纯函数
- **保持** reason_code 字符串不变

- [ ] **Step 4: 改 `DecisionPolicyActor.evaluate` 直接传 view**

- 删除或收窄 `_GateSnapshotAdapter`（仅当 parity 全绿后）
- 去掉 `cast(MarketSnapshot, ...)` 权宜之计

- [ ] **Step 5: 回归（双轨：Snapshot 旧面 + View 新面 + runtime）**

```bash
.venv/bin/python -m pytest -q \
  tests/test_signal_gate.py \
  tests/test_signal_arbiter.py \
  tests/test_order_intent.py \
  tests/test_health_metrics.py \
  tests/test_nautilus_strategy_base.py
```

若有 decision_policy 专项测试一并加入。

Expected: PASS；无 reason_code 漂移。

- [ ] **Step 6: Commit**

```bash
git commit -m "refactor: protocolize SignalGate input with adapter semantic parity"
```

---

### Task 5: 定向拆薄 `native_strategy.py`（同目录拆，不改行为）

**为什么：** 边界正确，但 `native_strategy.py` 仍偏厚。`node.py` 已基本拆完，**不要为拆而拆**。

**范围（收缩后）：**
- **In scope:** `src/polysignal_lab/nautilus_runtime/native_strategy.py` 剩余厚面
- **Optional:** 仅当 `node.py` 仍有明确可迁且未外置的职责时动 `node.py`
- **Out of scope:** 重写决策、改下单语义、顺手重构 alpha

**Files:**
- Modify/Split: `src/polysignal_lab/nautilus_runtime/native_strategy.py`
- Prefer existing:
  - `strategy/helpers.py`
  - `strategy/subscriptions.py`
  - 可新增同级小模块（如 evaluation / order events），但 **不**新建顶层包
- Test: `tests/test_nautilus_static_native_strategy.py`、`tests/test_nautilus_strategy_base.py`、`tests/test_nautilus_node.py`

**完成标准（可判定，满足其一主标准 + 行为标准）：**
- 主标准 A：`native_strategy.py` 行数明显下降（目标：**< 500 行**，或单次迁出 ≥1 个完整职责面且该文件净减少）
- 主标准 B：明确迁出函数/方法清单写进 commit message（例如 heartbeat evaluation、order event handlers）
- 行为标准：
  - 公开类名 `PolySignalNativeStrategy` 不变
  - 不改回调语义
  - 相关测试全绿
  - diff 以搬家为主（无夹带功能修改）

**建议拆法（一次只拆一个面）：**

```text
native_strategy.py
  ├─ lifecycle: on_start/on_stop/on_save/on_load   (可留)
  ├─ subscriptions: 复用 strategy/subscriptions.py
  ├─ evaluation: evaluate_condition / heartbeat    (优先迁出候选)
  └─ orders/events: submit + order/fill callbacks (次优迁出候选)

node.py
  └─ already split → optional only
```

- [ ] **Step 1: 量体积并列出可迁符号**

```bash
wc -l src/polysignal_lab/nautilus_runtime/native_strategy.py src/polysignal_lab/nautilus_runtime/node.py
rg -n "^class |^    def " src/polysignal_lab/nautilus_runtime/native_strategy.py | head -80
```

若 `node.py` 已 < 350 行且职责已外置 → **跳过 node 拆分**。

- [ ] **Step 2: 一次只拆一个职责面（纯搬家）**

规则：

- 不改函数语义
- 不改公开类名 `PolySignalNativeStrategy`
- 不在拆分时夹带功能修改
- 优先复用已有 `strategy/helpers.py` / `subscriptions.py`

- [ ] **Step 3: 每拆一块就跑对应测试**

```bash
.venv/bin/python -m pytest -q \
  tests/test_nautilus_static_native_strategy.py \
  tests/test_nautilus_strategy_base.py
```

- [ ] **Step 4: 可选 node 回归（仅当碰了 node）**

```bash
.venv/bin/python -m pytest -q tests/test_nautilus_node.py
```

- [ ] **Step 5: Commit（可多次；message 写明迁出清单）**

```bash
git commit -m "refactor: extract native_strategy evaluation helpers without behavior change"
```

---

### Task 6: 收紧 `domain/` 与 `paper/` 职责话术（确认残留，不重开账本清理）

**为什么：** domain 应是业务形状；paper 只做结算/统计；订单/持仓真相在 Nautilus。  
**现状：** `paper_order` / `paper_position` 已删；残留主要是 `PaperWalletSnapshot` DTO、safety 禁符测试、alpha 测试辅助。

**Files:**
- Review: `src/polysignal_lab/domain/paper_result.py`
- Review: `src/polysignal_lab/paper/*`
- Modify: `src/polysignal_lab/domain/FOLDER_INDEX.md`、`src/polysignal_lab/paper/FOLDER_INDEX.md`
- **不要**删除 `PaperWalletSnapshot`
- **不要**在本 Task 大改 alpha 的 `market_view_from_snapshot` helper（optional 另开）

**规则：**

```text
domain:
  Keep Side / OrderIntent / SignalCandidate / Market 业务字段
  Keep paper_result DTO（含 PaperWalletSnapshot 作为存储/报表快照）
  Shrink 厚 venue JSON 解析仅在有明确外移收益时（本 Task 可不做代码搬迁）

paper:
  Keep settlement_resolver / report / strategy_stats
  Never reintroduce PaperWallet runtime ledger / PaperSimulator / 第二套 order ledger
```

- [ ] **Step 1: 确认旧 paper ledger 符号不在 runtime 源码路径**

```bash
rg -n "PaperOrder|PaperPosition|PaperWallet\(|PaperSimulator" src/polysignal_lab || true
rg -n "PaperWalletSnapshot|PaperWallet|PaperSimulator" tests src/polysignal_lab | head
```

Expected:

- runtime `src/polysignal_lab` **无** `PaperSimulator` / 运行时 wallet ledger
- `PaperWalletSnapshot` 可出现在 domain DTO / 测试 fixture
- safety 测试可继续 **禁止** 危险符号（这是好事）

- [ ] **Step 2: 分类残留（文档记录即可）**

| 符号 | 允许位置 | 动作 |
|------|----------|------|
| `PaperWalletSnapshot` | domain DTO / storage / tests | keep |
| safety 测试中的 `PaperWallet`/`PaperSimulator` 字符串 | tests 禁符清单 | keep |
| runtime 新引入 ledger | 任何 src 运行路径 | **禁止** |

- [ ] **Step 3: 写清 FOLDER_INDEX Role**

`domain/`：纯业务形状与结果 DTO，不拥有执行账本。  
`paper/`：结算解析、结果规范化、策略统计；不拥有 Nautilus 订单真相。

- [ ] **Step 4: 回归**

```bash
.venv/bin/python -m pytest -q tests/test_market_parsing.py tests/test_persistence_service.py
```

- [ ] **Step 5: Commit**

```bash
git commit -m "docs: clarify domain and paper ownership after nautilus projections"
```

---

### Task 7: 全量验收与安全边界复查

**为什么：** 重构以“行为不变 + 边界不回退”为成功标准。

**Files:**
- No feature changes
- Verify: tests + safety scan + import boundary

- [ ] **Step 1: 默认环境依赖边界（3.11 / 无强制 Nautilus）**

```bash
.venv/bin/python -c "import polysignal_lab; print(polysignal_lab.__version__)"
.venv/bin/python -m pytest -q \
  tests/test_nautilus_dependency_boundary.py \
  tests/test_nautilus_safety_boundary.py
```

Expected: import 成功；边界测试 PASS

- [ ] **Step 2: 核心套件（含 gate / assembler / smoke）**

```bash
.venv/bin/python -m pytest -q \
  tests/test_alpha_types.py \
  tests/test_signal_gate.py \
  tests/test_signal_arbiter.py \
  tests/test_nautilus_cache_market_data.py \
  tests/test_nautilus_market_view_assembler.py \
  tests/test_nautilus_strategy_base.py \
  tests/test_nautilus_static_native_strategy.py \
  tests/test_nautilus_node.py \
  tests/test_market_data.py \
  tests/test_nautilus_full_paper_runtime_smoke.py
```

- [ ] **Step 3: 安全扫描**

```bash
.venv/bin/python scripts/safety_scan.py .
```

Expected: Safety scan passed

- [ ] **Step 4: 人工核对清单**

- [ ] 顶层无空 `strategies/`
- [ ] 文档写明 alpha / nautilus_runtime 入口
- [ ] SoT 三分法已写入 boundary 文档
- [ ] nautilus **decision** 路径不以 `OrderBookRegistry` 为 book 真相源
- [ ] display/smoke 的 registry 未被误删
- [ ] gate 协议化：Snapshot 测试 + MarketView 运行均可用
- [ ] `_GateSnapshotAdapter` 语义已 parity 并移除或不再位于热路径
- [ ] `native_strategy.py` 完成可判定拆薄；`node.py` 未无意义大拆
- [ ] 未恢复 live execution / PaperWallet **runtime** ledger / reverse instrument registry
- [ ] `PaperWalletSnapshot` DTO 仍在且仅作存储/报表

- [ ] **Step 5: 最终提交（若还有文档收尾）**

```bash
git commit -m "docs: record architecture boundary cleanup completion notes"
```

---

## 执行顺序（别打乱）

```text
Task 1 删空壳
  → Task 2 写清真相源（三分法）
  → Task 3 填清单并只切断 decision 路径   ← 硬门闩
  → Task 4 gate 协议化 + Adapter parity   ← 依赖 Task 3
  → Task 5 只拆 native_strategy（node optional）
  → Task 6 domain/paper 文档确认
  → Task 7 全量验收
```

原因：先减少认知噪音，再钉规则，再切断决策双轨，再改 gate 语义，最后才机械拆文件。

---

## 每阶段完成的“人话定义”

| 阶段 | 完成标准 |
|------|----------|
| Task 1 | 新人不会再打开空的 `strategies/` |
| Task 2 | 能回答 book 以谁为准，且知道 display registry 不是 decision truth |
| Task 3 | 有填实清单；decision 路径不读平行 book 真相；未误删 Telegram/smoke |
| Task 4 | gate 兼容 Snapshot 测试 + MarketView 运行；Adapter 语义 parity 通过 |
| Task 5 | `native_strategy` 更薄/职责外置；行为不变 |
| Task 6 | domain/paper Role 清晰；无 runtime 第二套账本回流 |
| Task 7 | 核心测试 + safety + import 边界全绿 |

---

## 风险与回滚

| 风险 | 规避 |
|------|------|
| 误删 Telegram/smoke 的 `OrderBookRegistry` | Task 3 清单分类 + 禁止删 data 文件 |
| gate reason_code 变更 | Task 4 parity 硬门槛 + 旧 Snapshot 测试必须绿 |
| 只改类型注解导致行为变 | 明确吸收 Adapter 空 book / active / freshness 语义 |
| 拆文件夹带逻辑修改 | Task 5 纯搬家；公开 API 不变；每步测试 |
| 重复拆已完成的 node | Already done 表 + node optional |
| 破坏默认无 Nautilus 依赖 | Task 7 + 每阶段 dependency boundary |
| 脏工作树混 commit | 每 Task 只 stage 相关文件 |

回滚策略：每个 Task 独立 commit；出问题只 revert 单个 Task，不一次 squash。

---

## 审查补丁记录（已吸收）

来自 2026-07-09 多 agent 审查（Approve with changes）：

1. Task 3 必须产出决策/非决策清单，禁止宽泛删改  
2. Task 4 以 Adapter 语义 parity 为硬门槛；Protocol 兼容 Snapshot  
3. Task 5 收缩为 `native_strategy` 定向拆分；node optional  
4. SoT 增加 display/reporting 第三类  
5. Task 1 `rg` 避开历史 docs 假阳性  
6. Task 6 降为确认 + 文档；保留 `PaperWalletSnapshot` DTO  
7. Task 7 加宽 gate/assembler/smoke/safety/import 验收  
8. 增加 Already done / skip if present，对齐半完成工作树  

---

## Self-Review

1. **Spec coverage:** 覆盖 P0/P1：空 `strategies`、data decision 收缩、MarketView/协议化 gate、runtime 定向拆薄、domain/paper 收口。formatter 搬家明确不做。  
2. **Placeholder scan:** 无 TBD；清单模板、parity 用例名、命令、完成标准可执行。  
3. **Type consistency:** 运行目标以 `MarketView` / 协议对象为准；测试可继续用 `MarketSnapshot`；不引入第二套 ledger 模型名。  
4. **Review fixes:** 已处理“Adapter 非空壳”“node 已半拆”“display registry 误伤”“假想 market_view 测试”四类踩坑。

---

## 完成后你会得到什么

- 目录语义和运行时语义基本一致  
- 决策路径单一行情真相源  
- gate 输入干净且行为不漂  
- `native_strategy` 更可维护  
- 后续加策略主要只碰 `alpha/` + 配置 + 少量 runtime 注册  
- 后续改 Nautilus 集成主要只碰 `nautilus_bridge/` + `nautilus_runtime/`
