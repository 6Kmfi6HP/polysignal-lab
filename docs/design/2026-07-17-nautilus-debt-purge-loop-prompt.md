# Loop Prompt: NautilusTrader Debt Purge (Delete-First)

> **用途**：交给编码 Agent **循环运行**，直到清理完成或触发停机条件。  
> **姿态**：非生产 lab — **优先大规模删除**，不做兼容补丁、不做双轨、不留“以后再说”的死代码。  
> **硬目标**：运行时与代码结构 **完全符合** NautilusTrader 设计 + 本仓库三真相边界。

---

## 0. 如何循环运行

每一轮复制 **§1–§9 整段** 作为用户消息（或 `/nautilus-debt-purge`），并附上上一轮的 `STATE.md` 摘要。

```
Round N = AUDIT → CLASSIFY → PURGE → VERIFY → REPORT → CONTINUE|STOP
```

- 默认 **最多 12 轮**。第 12 轮若仍未 STOP，输出阻塞清单，禁止空转。
- 每轮只做 **一个主题批次**（见 §4 批次表），禁止一轮改遍全仓。
- 每轮必须留下可续跑的状态文件（见 §8）。

状态文件（本轮必须更新）：

| 路径 | 作用 |
|------|------|
| `docs/design/_purge_state/STATE.md` | 进度、批次、STOP 判定 |
| `docs/design/_purge_state/LEDGER.md` | 已删/已迁/已拒删条目账本 |
| `docs/design/_purge_state/DIFF_NOTES.md` | 本轮行为变化说明（应几乎为“无行为变化”） |

首次运行时创建目录与空文件。

---

## 1. 角色与成功定义

你是 **NautilusTrader 对齐清理 Agent**，在 `polysignal-lab` 仓库内工作。

### 成功（全部满足才允许 STOP）

1. **三真相纯净**
   - **Runtime 真相** 仅来自 Nautilus：Cache / Portfolio / Account / Order / Position / ExecutionEngine / RiskEngine / DataEngine。
   - **Decision 真相** 仅来自 PolySignal：`MarketCatalog`、`MarketViewAssembler`、alpha、进程内 `DecisionPolicy`/`SignalGate`、`native_order`、`NativeExitPolicy`（无 DecisionPolicyActor / arbiter / consensus 总线）。
   - **Reporting 真相** 仅投影：SQLite/JSONL/Telegram/Dashboard；**永不**恢复或驱动交易状态。
2. **无第二交易真相**  
   运行时/决策/交易路径不存在：本地 book registry、CLOB 直连 book、paper matching、shadow wallet、伪造 settlement fill、`PositionClosed` 手搓、Portfolio 手搓。
3. **无 NT 已提供却仍自建的运行时能力**（见 §3 删除白名单 / 对齐表）。
4. **无历史残骸**  
   - 无“有 pyc 无 py”的僵尸模块  
   - 无指向已删 API 的活文档（尤其 `DecisionPolicyActor` 若代码不存在则文档必须改）  
   - 无只服务旧路径的测试/工厂，除非改为 Cache 投影测试  
5. **Strategy 是薄宿主**  
   `PolySignalNativeStrategy` 只保留 Nautilus 回调与依赖装配；多步逻辑在 `nautilus_runtime/strategy/*` 协作者中。
6. **质量门全绿**（§7）。
7. **`LEDGER.md` 覆盖** 每一项删除/拒绝删除的理由，且拒绝删除必须映射到 §2「禁止误删」。

### 非目标（禁止借机扩张）

- 不上 live 真钱、不接私有账户 E2E  
- 不发明 settlement/redeem 权限  
- 不启用 Polymarket contingent/bracket（能力未验证）  
- 不把 `SignalGate` 塞进 RiskEngine  
- 不重写 alpha 公式语义（可抽公共样板，不可改信号含义）  
- 不修改 `@refs/`  
- 不为“分数好看”拆纯 Protocol/接口

---

## 2. 权威依据（只信这些）

按优先级阅读；**冲突时以下游锁版本与活文档为准，旧 archive 一律不指导实现**。

| 优先级 | 材料 |
|--------|------|
| 1 | 已安装锁定包：`nautilus_trader[polymarket]`（见 `pyproject.toml` / `docs/NAUTILUS_CAPABILITY_MATRIX.md`） |
| 2 | `docs/ARCHITECTURE_OWNERSHIP.md`、`docs/RUNTIME_BOUNDARY.md`、`docs/NAUTILUS_CAPABILITY_MATRIX.md` |
| 3 | `docs/nautilus_reference/developer_guide/`（design_principles, adapters, python, testing） |
| 4 | 官方文档（context7 `/websites/nautilustrader_io` 或 nautilus_trader site）：Strategy/Actor/Cache/Portfolio/CustomData/Clock/order_factory |
| 5 | `docs/design/2026-07-12-nautilus-architecture-cutover-spec.md` |
| 6 | `docs/archive/*` — **仅作考古**，禁止当作当前要求 |

### NautilusTrader 设计不变量（必须落实）

1. **消息不可变** — 不修改已创建的事件/命令/CustomData 字段。  
2. **Strategy = 回调宿主** — 用 `on_*` 响应；业务编排下沉到协作者。  
3. **下单唯一路径** — `order_factory.*` + `submit_order`（及 NT 提供的 cancel/modify）。  
4. **时间来自 `clock`** — 决策/定时/过期不用 wall-clock 偷换框架时间。  
5. **行情经 DataEngine** — 禁止策略内私自 REST/WS 当 live book。  
6. **仓位/订单经 Cache/Portfolio** — 禁止本地 ledger 当交易真相。  
7. **CustomData / Signal** — 跨组件数据用 NT 机制；payload 冻结、可序列化。  
8. **适配器边界** — instrument id / parse 优先官方 Polymarket helpers。

### 禁止误删（Accepted boundaries）

删除前若命中下列项，**默认保留**，除非能证明零引用且有替代投影：

- `Side` UP/DOWN、`OrderIntent`  
- `MarketCatalog`、`MarketViewAssembler`、`SideBookView`/`MarketView`  
- alpha cores 与其配置  
- `SignalGate`（业务资格；非 RiskEngine；无 arbiter/consensus 总线）  
- `native_order` + `PolymarketEnumParser`  
- `NativeExitPolicy`（Cache 上 reduce-only；sandbox）  
- `MarketRotationActor` + discovery worker + CustomData 类型  
- report-only settlement 与 `report_*` SQLite 投影（可拆分，不可变成交易真相）  
- safety scan 对双路径的 **拦截规则本身**（可更新符号列表，不可拆除防护）

---

## 3. 识别规则：什么叫“NT 已有却自建”

对每个候选符号/模块，填写分类（写入 `LEDGER.md`）：

| 标签 | 含义 | 默认动作 |
|------|------|----------|
| `NT_DUP_RUNTIME` | NT 引擎/Cache/Portfolio/Data/Exec 已提供的运行时能力 | **删除自建**，改读 NT |
| `NT_DUP_ADAPTER` | Polymarket adapter 已提供（parse/instrument id/data client） | **删除/收敛** 到官方 API |
| `LEGACY_DUAL` | 迁移遗留双轨（paper、CLOB book、OrderBookRegistry、EmptyBook…） | **删除** + 修测试/文档 |
| `DOC_DRIFT` | 活文档描述已不存在的架构 | **改文档对齐代码**（或极少情况下改代码对齐已锁定设计——以代码+capability matrix 为准） |
| `CLONE` | 重复实现（pyscn clones / 复制粘贴） | **抽公共或删副本**；不改语义 |
| `GOD_OBJECT` | 过厚 Strategy/Store | **削薄/拆分**，禁止再堆 |
| `KEEP_DOMAIN` | 预测市场/研究域合理自建 | **保留** 并在账本注明 |
| `REPORT_ONLY` | 仅报告层 | 可重构；**不得**升格为 runtime 真相 |

### 当前已知债务种子（开局必扫；以代码为准，过时则从账本注销）

**高优先级删除/对齐**

1. 僵尸 bytecode：`find src -type d -name '__pycache__'` 中对应 `.py` 已不存在的模块（clob/paper/legacy/decision_policy_actor 等）  
2. `domain/orderbook.py` 若运行时无消费者 → 删除或迁到 tests-only  
3. 活文档中的 `DecisionPolicyActor` / “Strategy↔Actor native Signal 决策总线” — 若注册路径仅有 `MarketRotationActor` + Strategy 内 `DecisionPolicy`，**改文档**  
4. `FOLDER_INDEX.md` / 索引中的幽灵文件名（如 `cache_reader.py`）  
5. 测试工厂仍构造 legacy OrderBook 作为 **决策真相** 的路径 → 改为 Cache 投影假数据  

**结构性清理**

6. `PolySignalNativeStrategy` 过厚 → 编排迁入 `nautilus_runtime/strategy/*`  
7. `SQLiteStore` 巨石 → 按 report 聚合拆分；删除死 CRUD  
8. alpha 间 `_decision` / hedge-stop 样板克隆 → 抽 helper，删重复  
9. `Market.from_gamma` 手写解析 → 最大化 `parse_polymarket_instrument` / 官方字段，删除失效启发式  
10. 任何重新引入的 CLOB/paper/matching/wallet 符号 → 删除  

**禁止把下列误判为 NT_DUP**

- alpha 公式、gate 业务规则、市场轮换 universe 规则、Telegram/Dashboard 文案、report 投影 schema  

---

## 4. 批次表（每轮只做一个 `BATCH-ID`）

| BATCH-ID | 主题 | 允许触碰的树 | 主要动作 |
|----------|------|--------------|----------|
| B0 | 取证基线 | 只读 + 写 `_purge_state/*` | 跑扫描、建账本，不改业务代码 |
| B1 | 残骸清除 | `src/**/__pycache__`、空目录、损坏索引 | 删 pyc/空壳；修 FOLDER_INDEX |
| B2 | 文档对齐 | `docs/ARCHITECTURE_OWNERSHIP.md`, `RUNTIME_BOUNDARY.md`, 相关 INDEX | 删除过时 Actor/双轨叙述；与代码一致 |
| B3 | Legacy 模型与测试 | `domain/orderbook*`, tests factories, safety 符号列表 | 删无用模型；测试改 Cache 投影 |
| B4 | Strategy 削薄 | `nautilus_runtime/native_strategy.py`, `strategy/*` | 迁出多步逻辑；删除死方法 |
| B5 | NT 适配收敛 | `domain/market.py`, `market_catalog.py`, `polymarket_adapter.py` | 删重复 parse/id 逻辑 |
| B6 | 存储拆分/删死代码 | `storage/*` | 删未用 API；拆分仅在有测试护栏时 |
| B7 | Alpha 去重 | `alpha/*`, `alpha/helpers.py` | 抽公共；删重复块 |
| B8 | 边界硬化 | `observability/safety.py`, platform tests | 更新 forbid 列表；确保双轨不可 import |
| B9 | 全量验证与收口 | 全仓 | 质量门；更新 STATE 为 STOP 或阻塞 |

规则：

- **未完成 B0 不得进入删除批次。**  
- B4/B6/B7 若导致质量门红，**本轮回滚该批次**（`git checkout -- <paths>` 或 revert 本轮 diff），记入 LEDGER，换更小切片重来。  
- 删除优先于重构：能删就不封装“兼容层”。

---

## 5. 单轮强制流程

### 5.1 AUDIT（只读）

必须执行（工具可用则用；失败则降级到 rg/read）：

```bash
# 代码图 / 语义（若可用）
codegraph explore "PolySignalNativeStrategy DecisionPolicy MarketRotationActor Cache order_factory"

# 双轨与遗留符号
rg -n "OrderBookRegistry|EmptyBookDataProvider|PaperOrder|PaperFill|PaperPosition|polymarket_clob_|shadow.?wallet|MatchingEngine|DecisionPolicyActor|nautilus_bridge" src tests docs -g'!docs/archive/**'

# 下单路径审计
rg -n "submit_order|order_factory|submit_approved_decision" src/polysignal_lab

# 僵尸 pyc
# 列出有 .pyc 无对应 .py 的模块路径

# 克隆与耦合
uvx pyscn@latest analyze --select clones,cbo,lcom,deps --clone-threshold 0.7 --json src/polysignal_lab
```

对照 §2 文档 + 锁定 NT API，输出本轮 **候选处置表**（不少于 5 条，除非已接近 STOP）：

```text
PATH | TAG | EVIDENCE | ACTION(delete|move|docfix|keep) | RISK
```

### 5.2 CLASSIFY

- 每个 `delete` 必须回答：  
  1) 谁在 import？ 2) 替代真相是什么？ 3) 哪个测试证明可删？  
- 若“不知道谁在用” → 先补 rg/codegraph，**禁止盲删**。  
- `KEEP_DOMAIN` 必须写清 NT 为何不负责。

### 5.3 PURGE（本轮唯一 BATCH）

删除/修改时遵守：

1. **Read before write**；diff 只服务本批次。  
2. **先删调用方/测试，再删定义**（或同提交内一起删干净）。  
3. 删除公共 API 后：更新 re-export、`__init__.py`、FOLDER_INDEX、活文档。  
4. 禁止新增兼容 shim（`*_legacy.py`、条件 import 双路径）。  
5. 禁止 `TODO: remove later` 残留；要么删掉要么本轮做完。  
6. Strategy 削薄：禁止在 `native_strategy.py` 新增业务分支；只允许外迁。

### 5.4 VERIFY

按 §7 执行与本批次相关的最小集，再视情况扩大。  
失败 → 修复或回滚本批次；**不得**带着红测试进入下一 BATCH 主题。

### 5.5 REPORT

更新三个状态文件，并在对话输出中给出 §8 模板。

### 5.6 CONTINUE | STOP

**STOP** 当且仅当 §1 成功条件全部为真，且：

- `rg` 遗留符号在 `src/` 与非 archive `docs/` 无不当命中  
- pyscn：无 dependency cycles；克隆率较 B0 基线下降或已无 critical clone 建议  
- `PolySignalNativeStrategy` 行数显著低于开局（目标：**≤ 400 行** 或可证明仅剩回调+DI）  
- 质量门 §7 全绿  

**CONTINUE** 时：明确下一轮 `BATCH-ID` 与 3 条以内待删清单。

---

## 6. 大规模删除作战手册

### 6.1 优先删除清单（见到就动手，先取证）

```text
# 运行时双轨
OrderBookRegistry, EmptyBookDataProvider
polysignal_lab.data.polymarket_clob_rest / polymarket_clob_ws
PaperOrder, PaperFill, PaperPosition, paper_risk, local matching/wallet
decision_policy_actor.py, decision_messages.py（若已无源码则清 pyc + 文档）
nautilus_bridge（若仍有残留引用）

# 文档谎言
“DecisionPolicyActor sole owner” — 以 runtime_registration 实际注册为准
“native Signal candidate/approval bus” — 以代码路径为准

# 索引谎言
FOLDER_INDEX 中不存在的文件名
```

### 6.2 替换模式（删之前先接线）

| 删什么 | 换成什么 |
|--------|----------|
| 本地 book 真相 | `NautilusCacheMarketDataProvider` / Cache order book |
| 本地订单/仓位账本 | `cache_trading_state.trading_state_from_cache` / Portfolio |
| 手搓 instrument id 字符串 | `get_polymarket_instrument_id` via `MarketCatalog` |
| 手搓 Gamma→BinaryOption | `parse_polymarket_instrument` + 业务 enrichment |
| wall clock 决策时间 | `self.clock` / framework now |
| 策略内多步 if-ladder | `strategy/*` 协作者函数 |
| 重复 alpha `_decision` | `alpha/helpers.py` 已有 builder |

### 6.3 删除后必做

```bash
rg -n "DeletedSymbol|deleted_module" src tests
# 修到零命中（archive 除外）
```

---

## 7. 质量门（PASS 标准）

在仓库根目录：

```bash
# 1) 安全边界
uv run polysignal-safety-scan .

# 2) 平台/安全测试（始终跑）
uv run pytest tests/test_safety.py tests/test_nautilus_platform_boundary.py tests/test_nautilus_safety_boundary.py tests/test_nautilus_dependency_boundary.py -q

# 3) 本批次相关测试（示例，按触碰面替换）
uv run pytest tests/test_nautilus_strategy_base.py tests/test_nautilus_decision_policy.py tests/test_nautilus_market_view_assembler.py tests/test_nautilus_cache_market_data.py -q

# 4) 收口轮全量
NAUTILUS_REQUIRED=1 uv run pytest -q

# 5) 静态与重复（收口轮）
uvx pyscn@latest analyze --select deps,clones,cbo --clone-threshold 0.7 --json src/polysignal_lab
```

附加不变量断言（可用 rg 自检）：

```bash
# 决策/运行时不得 import 遗留 book/CLOB
rg -n "polymarket_clob_|OrderBookRegistry" src/polysignal_lab/nautilus_runtime src/polysignal_lab/signal_layer src/polysignal_lab/alpha && exit 1 || true

# 下单不得绕过 native_order / order_factory（人工审查新增 submit 点）
rg -n "submit_order\(" src/polysignal_lab --glob'*.py'
```

Python / Nautilus 版本以 `ARCHITECTURE_OWNERSHIP.md` 锁定为准。

---

## 8. 每轮输出模板（必须按此结构）

```markdown
## Round N — BATCH-ID

### Audit findings
- ...

### Classification table
| path | tag | action | reason |
|------|-----|--------|--------|

### Changes
- deleted: ...
- moved: ...
- docs: ...
- kept (with reason): ...

### Verify
- commands + pass/fail
- invariants: OK/FAIL

### Metrics
- native_strategy_loc: before → after
- clone_fragment_pct: before → after (if measured)
- forbidden_symbol_hits_src: N

### Decision
CONTINUE → next BATCH-ID: Bx — top deletes: ...
OR STOP — success criteria checklist all [x]
```

同时写入 `STATE.md` / `LEDGER.md` / `DIFF_NOTES.md`。

---

## 9. 给 Agent 的系统约束（粘贴区）

```text
你正在执行 docs/design/2026-07-17-nautilus-debt-purge-loop-prompt.md。

硬性规则：
1. 先读 docs/ARCHITECTURE_OWNERSHIP.md、docs/RUNTIME_BOUNDARY.md、docs/NAUTILUS_CAPABILITY_MATRIX.md、docs/nautilus_reference/developer_guide/design_principles.md。
2. 以已安装 nautilus_trader 与活文档为准；docs/archive 不指导实现。
3. 本轮只做一个 BATCH-ID；优先删除，禁止新兼容层。
4. 禁止误删 §2 Accepted boundaries。
5. 任何删除必须有引用取证 + 替代真相 + 测试门。
6. 质量门红则回滚本批次，不得带红进入下一主题。
7. 结束时更新 docs/design/_purge_state/{STATE,LEDGER,DIFF_NOTES}.md 并给出 CONTINUE/STOP。
8. 不得修改 @refs/。不得启用 live 真钱路径。
9. 目标不是“迁就旧代码”，而是“完全符合 NautilusTrader 设计 + 三真相”。
10. 若活文档与代码冲突：用 runtime_registration 与 capability matrix 判定真相，然后删掉错误的一侧（通常是文档或死代码），禁止双轨并存。

现在执行：读取 docs/design/_purge_state/STATE.md（若无则从 B0 开始），进入下一轮。
```

---

## 10. 人工启动示例

**第一轮：**

```text
执行 Nautilus 债务清除循环。从 B0 开始。
严格遵循 docs/design/2026-07-17-nautilus-debt-purge-loop-prompt.md。
```

**续跑：**

```text
继续 Nautilus 债务清除循环。
读取 docs/design/_purge_state/STATE.md，执行其指定的下一 BATCH。
严格遵循 docs/design/2026-07-17-nautilus-debt-purge-loop-prompt.md。
```

**强制只删残骸：**

```text
继续清除循环，BATCH=B1 only。只删除僵尸 pyc/空壳/幽灵索引，不改业务逻辑。
```

---

## 11. STOP 检查清单（收口轮打印）

- [ ] `runtime_registration` 仅注册设计允许的 Actor/Strategy  
- [ ] 无 `DecisionPolicyActor` 源码 **或** 有源码且文档/注册一致（禁止半吊子）  
- [ ] `src/` 无 CLOB book / OrderBookRegistry / Paper* 交易路径  
- [ ] MarketView 书仅 Cache 投影  
- [ ] 订单仅 `order_factory`+`submit_order`  
- [ ] 结算 report-only（sandbox/live）  
- [ ] Strategy 薄宿主达标  
- [ ] 活文档与代码一致  
- [ ] FOLDER_INDEX 无幽灵文件  
- [ ] 无僵尸 pyc  
- [ ] safety-scan + pytest 全绿  
- [ ] LEDGER 完整  

全部勾选 → `STOP: CLEAN`。
