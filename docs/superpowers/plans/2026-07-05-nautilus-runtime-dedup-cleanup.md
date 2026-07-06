# Nautilus 去重清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 彻底删除 PolySignal Nautilus runtime 中与 NautilusTrader 平台职责重叠的本地撮合、钱包、调度、盘口缓存、vendor patch 和 engine monkeypatch，让默认 runtime 的平台状态只依赖 Nautilus node、Polymarket data client、Sandbox execution client、Cache、Portfolio、Strategy/Actor callback；legacy `TradingNode` 作为非 wheel 设计偏差单独记录迁移门槛。

**Architecture:** 去重路径保留当前 node wiring 的 Nautilus-owned platform responsibilities：Polymarket data client、Sandbox execution client、Cache、Portfolio、Strategy/Actor callback；策略只通过 Nautilus callbacks、`order_factory`、`submit_order`、`cache`、`portfolio` 交互。业务扩展仅限不可由 Nautilus 提供的内容：market rotation、spot/PTB/market metadata custom data、alpha `MarketView` read-only projection、dashboard/report read-only projection。所有本地 platform truth source（matching client、manual orchestrator、manual ingestor、PaperWallet mirror、PaperExecutionResult、手写 SimulatedExchange session、installed-source patch、engine exception monkeypatch、外部 book/trade state mirror）删除，不保留 shim。

**Tech Stack:** Python 3.11 default package, Python 3.12 Nautilus optional runtime, `nautilus_trader[polymarket]==1.229.0`, Pydantic v2, pytest, basedpyright, Docker multi-stage target `nautilus-runtime`, existing `uv run` test workflow.

## Global Constraints

- 默认 repo runtime 仍然 read-only / paper-safe；不得注册 live Polymarket execution client。
- 默认代码不得读取 `POLYMARKET_PK`、`POLYMARKET_FUNDER`、`POLYMARKET_API_KEY`、`POLYMARKET_API_SECRET`、`POLYMARKET_PASSPHRASE`。
- 去重任务不得把 legacy `TradingNode` 当作重复造轮子删除；Task 8 单独记录 `TradingNode` → `LiveNode.builder` 设计迁移的 deferred acceptance criteria。
- 当前去重路径必须保留 Polymarket data client、sandbox execution client、Cache、Portfolio、Strategy/Actor callback 这些 Nautilus-owned platform responsibilities。
- 当前去重路径必须继续注册 `PolymarketLiveDataClientFactory` 和 `SandboxLiveExecClientFactory`。
- 不新增 dependency。
- 不保留 deprecated alias、compat shim、fallback branch、dual backend、rollback config。
- 删除代码优先；只有 Nautilus 没有提供的业务 projection 才允许保留。
- `matching_accuracy_mode` 当前驱动 sandbox `book_type`；删除该字段时必须用 `sandbox_book_type` 保留 `L1_MBP` / `L2_MBP` 行为。
- 所有新/改测试命令使用每个任务列出的具体 `uv run pytest` 命令。
- Python 源码任务完成后运行 `uv run python -m py_compile` 覆盖变更模块。
- 完成前运行 `uv run basedpyright src/polysignal_lab/nautilus_runtime src/polysignal_lab/nautilus_bridge tests/test_nautilus_platform_boundary.py tests/test_nautilus_runtime_config.py`。

---

## Scope Check

本计划横跨配置、runtime wiring、observability、market data projection、instrument mapping、Docker、测试清理。它们不是独立可发布子系统，因为目标是一次性消除 Nautilus runtime 的重复平台职责；留下任一旧路径都会继续允许重复造轮子。任务按可审查边界拆分：先加 fail-fast 边界测试，再移除配置术语，再删除 duplicate runtime modules，再把剩余默认路径改成 Nautilus cache/portfolio/read-only projections，再移除 vendor patch 和 engine monkeypatch，最后把 legacy `TradingNode` 归档为非 wheel 设计偏差并记录 `LiveNode.builder` 迁移验收标准。

## Audit Classification Carried Into This Plan

| Item | Active default path | Classification | Plan coverage |
|---|---:|---|---|
| `NautilusBookDataProvider` + `MarketViewAssembler` + `native_strategy` callbacks maintaining book/trade state outside Nautilus | Yes | 重复维护 Nautilus 外部市场数据状态 | Task 1 adds boundary assertions; Task 4 deletes `book_data.py`, removes callback writes, and keeps `MarketViewAssembler` only as a read-only projection from Nautilus cache plus business custom data. |
| Legacy `nautilus_trader.live.node.TradingNode` surface | Yes | 设计偏差，不是 wheel | Task 8 documents the deferred `LiveNode.builder` migration gate and keeps it separate from duplicate-runtime deletion. |
| `paper_engine=nautilus_matching` startup/config metadata | Yes | 配置/元数据偏差，不是 wheel | Task 2 removes `paper_engine` and `matching_accuracy_mode`, adds `sandbox_book_type`, and forbids stale keys. |
| `matching.py` manual `MessageBus` / `Cache` / `Portfolio` / `ExecutionEngine` / `SimulatedExchange` / `BacktestExecClient` session | No | 重大重复造轮子 | Task 1 boundary assertions plus Task 3 deletion. |
| `NautilusOrchestrator` + `NautilusDataIngestor` manual sync/evaluate phase loop | No | 重复 Nautilus callback/DataEngine 驱动模型 | Task 1 boundary assertions plus Task 3 deletion. |

---

## File Structure

### 创建

- `src/polysignal_lab/nautilus_runtime/cache_market_data.py`
  - 唯一职责：从 Nautilus `Cache` + PolySignal business catalog 读取当前 order book / trades，按需转换成 alpha `SideBookView` / `TradeView`；不持有 `_books`、`_trades`、`OrderBookRegistry`。

### 修改

- `src/polysignal_lab/config.py`
  - 删除 `NautilusRuntimeConfig.paper_engine` 和 `matching_accuracy_mode`。
  - 新增 `sandbox_book_type: Literal["L1_MBP", "L2_MBP"] = "L2_MBP"`。
  - 对 `NautilusRuntimeConfig` 启用 `extra="forbid"`，旧配置键 fail-fast。

- `config/signal_bot.yaml`
  - 删除 `runtime.nautilus.matching_accuracy_mode: fast_l1`。
  - 新增 `runtime.nautilus.sandbox_book_type: L1_MBP`。

- `config/signal_bot.lab.yaml`
  - 新增 `runtime.nautilus.sandbox_book_type: L2_MBP`。

- `src/polysignal_lab/nautilus_runtime/trading_node.py`
  - `_book_type_for()` 改为接受 `sandbox_book_type`。
  - `SandboxExecutionClientConfig` 的 `book_type` constructor argument 使用 `settings.runtime.nautilus.sandbox_book_type`。

- `src/polysignal_lab/nautilus_runtime/node.py`
  - 删除 duplicate imports、precision guard monkeypatch、installed-source patch references、`paper_execution_metadata`、`paper_engine` / `accuracy_mode` startup metadata。
  - `build_trading_node()` 改用 `NautilusCacheMarketDataProvider`。
  - `run_nautilus_cli()` / `run_nautilus_cli_async()` 不再 patch Nautilus internals。

- `src/polysignal_lab/nautilus_runtime/native_strategy.py`
  - 不再把 Nautilus callbacks 复制进 `NautilusBookDataProvider`。
  - market data callbacks 只标记 subscription confirmed 并触发 evaluation；MarketView 从 cache-backed provider 读取。
  - 使用 `settings.runtime.nautilus.sandbox_book_type`。

- `src/polysignal_lab/nautilus_bridge/market_view_assembler.py`
  - 保持 read-only alpha `MarketView` assembly；不得拥有 `_books`、`_trades`、callback-updated state，输入只能来自 Nautilus cache-backed provider 和业务 custom data。

- `src/polysignal_lab/nautilus_runtime/instrument_mapping.py`
  - 删除 `build_binary_option()` 和 `instrument_id_for_token()` production fallback。
  - `polymarket_instrument_id()` 必须使用 Nautilus Polymarket adapter helper；缺失 helper 时抛出清晰 `RuntimeError`。

- `src/polysignal_lab/nautilus_runtime/observability.py`
  - 删除 `PaperOrder` / `PaperFill` / `PaperPosition` / `PaperTradeResult` 写路径。
  - 仅保留 signals、rejected_signals、Nautilus telemetry projections、health、notifications。
  - startup notification 使用 `sandbox_book_type`，不再输出 `paper_engine=nautilus_matching` 或陈旧 accuracy metadata。

- `Dockerfile`
  - 删除 `python -m polysignal_lab.nautilus_runtime.patch_nautilus_polymarket_autoload`。
  - 保持 `--only-binary=nautilus-trader` 安装。

- `tests/test_nautilus_platform_boundary.py`
  - 新增 hard boundary tests，要求 duplicate files 不存在、默认 runtime 不引用 PaperWallet/PaperExecutionResult/matching/orchestrator/data_ingestor/patch/precision guard。
  - 新增 active default market-data mirror boundary tests，禁止 `NautilusBookDataProvider`、callback `update_book` / `update_trade` 写入、`_books` / `_trades` 自维护状态。

- `tests/test_nautilus_runtime_config.py`
  - 更新配置测试：`sandbox_book_type` 保留 L1/L2 行为，旧字段 fail-fast。

- `tests/test_nautilus_node.py`
  - 删除 precision guard tests。
  - 更新 startup notification / runtime metadata assertions。
  - 更新 L1/L2 strategy book type tests。

- `tests/test_nautilus_default_runtime_integration.py`
  - 去掉 `build_binary_option()`，改用 Nautilus adapter/provider 已加载 instrument 或 test-kit instrument fixture。

- `tests/test_nautilus_full_paper_runtime_smoke.py`
  - 更新 `book_data_provider` 断言为 cache-backed provider。

- `tests/test_nautilus_observability.py`
  - 删除 `PaperExecutionResult` / paper model recording tests。
  - 保留 Nautilus projected order/fill/position telemetry tests。

- `tests/test_nautilus_trading_node_runtime.py`
  - 更新 `matching_accuracy_mode` 为 `sandbox_book_type`。

- `docs/NAUTILUS_BRIDGE_BOUNDARY.md`
  - 更新 verification list 与 implemented-components summary；移除 matching/orchestrator/data_ingestor/patch 描述。
  - 明确 legacy `TradingNode` 是 active default-path 设计偏差但不是 duplicate wheel；记录 `LiveNode.builder` 迁移 acceptance criteria。

### 删除

- `src/polysignal_lab/nautilus_runtime/matching.py`
- `src/polysignal_lab/nautilus_runtime/orchestrator.py`
- `src/polysignal_lab/nautilus_runtime/data_ingestor.py`
- `src/polysignal_lab/nautilus_runtime/execution_types.py`
- `src/polysignal_lab/nautilus_runtime/scheduler_compat.py`
- `src/polysignal_lab/nautilus_runtime/position_policy.py`
- `src/polysignal_lab/nautilus_runtime/settlement.py`
- `src/polysignal_lab/nautilus_runtime/book_data.py`
- `src/polysignal_lab/nautilus_runtime/patch_nautilus_polymarket_autoload.py`
- `tests/test_nautilus_matching_execution.py`
- `tests/test_nautilus_matching_runtime_smoke.py`
- `tests/test_nautilus_orchestrator.py`
- `tests/test_nautilus_data_ingestor.py`
- `tests/test_nautilus_book_data.py`
- `tests/test_nautilus_wheel_patch.py`
- `tests/test_nautilus_settlement_actor.py`

---

### Task 1: 写入重复平台层边界测试

**Files:**
- Modify: `tests/test_nautilus_platform_boundary.py:1-166`

**Interfaces:**
- Consumes: existing repository paths under `src/polysignal_lab/nautilus_runtime`.
- Produces: `test_nautilus_runtime_duplicate_platform_modules_are_deleted() -> None`, `test_nautilus_runtime_source_has_no_platform_truth_source_terms() -> None`, `test_nautilus_runtime_does_not_mirror_market_data_outside_nautilus_cache() -> None`, `test_nautilus_runtime_does_not_patch_nautilus_installed_sources() -> None`.

- [ ] **Step 1: 追加失败测试**

Append this exact code to `tests/test_nautilus_platform_boundary.py`:

```python


def test_nautilus_runtime_duplicate_platform_modules_are_deleted() -> None:
    duplicate_modules = (
        Path("src/polysignal_lab/nautilus_runtime/matching.py"),
        Path("src/polysignal_lab/nautilus_runtime/orchestrator.py"),
        Path("src/polysignal_lab/nautilus_runtime/data_ingestor.py"),
        Path("src/polysignal_lab/nautilus_runtime/execution_types.py"),
        Path("src/polysignal_lab/nautilus_runtime/scheduler_compat.py"),
        Path("src/polysignal_lab/nautilus_runtime/position_policy.py"),
        Path("src/polysignal_lab/nautilus_runtime/settlement.py"),
        Path("src/polysignal_lab/nautilus_runtime/book_data.py"),
        Path("src/polysignal_lab/nautilus_runtime/patch_nautilus_polymarket_autoload.py"),
    )

    assert [str(path) for path in duplicate_modules if path.exists()] == []


def test_nautilus_runtime_source_has_no_platform_truth_source_terms() -> None:
    forbidden = (
        "NautilusMatchingPaperExecutionClient",
        "OwnedNautilusMatchingBoundary",
        "PaperWallet",
        "PaperExecutionResult",
        "PaperSettlementEngine",
        "PaperSimulator",
        "NautilusOrchestrator",
        "NautilusDataIngestor",
        "evaluate_all_conditions(",
        "matching_boundary",
        "process_resting_orders",
        "drain_events",
        "cache.add_order",
        "MessageBus(",
        "SimulatedExchange(",
        "BacktestExecClient(",
    )
    allowed_files = {
        Path("src/polysignal_lab/nautilus_runtime/cache_reader.py"),
        Path("src/polysignal_lab/nautilus_runtime/projections.py"),
    }
    findings: list[str] = []
    for path in Path("src/polysignal_lab/nautilus_runtime").rglob("*.py"):
        if path in allowed_files:
            continue
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []


def test_nautilus_runtime_does_not_mirror_market_data_outside_nautilus_cache() -> None:
    forbidden_by_file = {
        Path("src/polysignal_lab/nautilus_runtime/node.py"): (
            "NautilusBookDataProvider",
            "book_data_provider =",
        ),
        Path("src/polysignal_lab/nautilus_runtime/native_strategy.py"): (
            ".update_book(",
            ".update_trade(",
            "_domain_order_book(",
        ),
        Path("src/polysignal_lab/nautilus_bridge/market_view_assembler.py"): (
            "self._books",
            "self._trades",
            "update_book(",
            "update_trade(",
        ),
    }
    findings: list[str] = []
    for path, forbidden in forbidden_by_file.items():
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []


def test_nautilus_runtime_does_not_patch_nautilus_installed_sources() -> None:
    forbidden = (
        "patch_nautilus_polymarket_autoload",
        "patch_source(",
        "EXPECTED_VERSION",
        "_handle_queue_exception",
        "_polysignal_precision_guard",
        "_install_polymarket_precision_runtime_guards",
        "_polymarket_precision_guarded_queue_exception_handler",
    )
    scanned_paths = (
        Path("Dockerfile"),
        Path("src/polysignal_lab/nautilus_runtime/node.py"),
    )
    findings: list[str] = []
    for path in scanned_paths:
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
uv run pytest \
  tests/test_nautilus_platform_boundary.py::test_nautilus_runtime_duplicate_platform_modules_are_deleted \
  tests/test_nautilus_platform_boundary.py::test_nautilus_runtime_source_has_no_platform_truth_source_terms \
  tests/test_nautilus_platform_boundary.py::test_nautilus_runtime_does_not_mirror_market_data_outside_nautilus_cache \
  tests/test_nautilus_platform_boundary.py::test_nautilus_runtime_does_not_patch_nautilus_installed_sources \
  -q
```

Expected: FAIL. The failure list includes existing duplicate files and terms such as `matching.py`, `orchestrator.py`, `data_ingestor.py`, `book_data.py`, `patch_nautilus_polymarket_autoload.py`, `PaperWallet`, `MessageBus(`, `NautilusBookDataProvider`, `.update_book(`, `.update_trade(`, and `_handle_queue_exception`.

- [ ] **Step 3: 提交失败测试**

```bash
git add tests/test_nautilus_platform_boundary.py
git commit -m "test: define nautilus duplicate platform boundary"
```

---

### Task 2: 删除 matching 配置术语并保留 sandbox book type 行为

**Files:**
- Modify: `src/polysignal_lab/config.py:1-318`
- Modify: `config/signal_bot.yaml:219-245`
- Modify: `config/signal_bot.lab.yaml:205-230`
- Modify: `src/polysignal_lab/nautilus_runtime/trading_node.py:45-88`
- Modify: `src/polysignal_lab/nautilus_runtime/node.py:436-472, 790-795, 1185-1190, 1283-1289`
- Test: `tests/test_nautilus_runtime_config.py`
- Test: `tests/test_nautilus_trading_node_runtime.py`
- Test: `tests/test_nautilus_node.py`

**Interfaces:**
- Consumes: `Settings.runtime.nautilus`.
- Produces: `NautilusRuntimeConfig.sandbox_book_type: Literal["L1_MBP", "L2_MBP"]`, `build_paper_trading_node_config(settings: Settings | None = None, *, instrument_config: object) -> object` preserving sandbox `book_type`.

- [ ] **Step 1: 写配置失败测试**

Add this code to `tests/test_nautilus_runtime_config.py`:

```python


def test_nautilus_runtime_uses_sandbox_book_type_not_matching_engine() -> None:
    settings = Settings()

    assert settings.runtime.nautilus.execution_mode == "paper_sandbox"
    assert settings.runtime.nautilus.sandbox_book_type == "L2_MBP"
    assert not hasattr(settings.runtime.nautilus, "paper_engine")
    assert not hasattr(settings.runtime.nautilus, "matching_accuracy_mode")


def test_removed_nautilus_matching_keys_fail_fast() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "runtime": {
                    "nautilus": {
                        "paper_engine": "nautilus_matching",
                    }
                }
            }
        )

    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "runtime": {
                    "nautilus": {
                        "matching_accuracy_mode": "depth_l2",
                    }
                }
            }
        )


def test_yaml_runtime_book_type_values_are_explicit() -> None:
    production = Settings.from_yaml("config/signal_bot.yaml")
    lab = Settings.from_yaml("config/signal_bot.lab.yaml")

    assert production.runtime.nautilus.sandbox_book_type == "L1_MBP"
    assert lab.runtime.nautilus.sandbox_book_type == "L2_MBP"
```

- [ ] **Step 2: 运行配置测试确认失败**

Run:

```bash
uv run pytest \
  tests/test_nautilus_runtime_config.py::test_nautilus_runtime_uses_sandbox_book_type_not_matching_engine \
  tests/test_nautilus_runtime_config.py::test_removed_nautilus_matching_keys_fail_fast \
  tests/test_nautilus_runtime_config.py::test_yaml_runtime_book_type_values_are_explicit \
  -q
```

Expected: FAIL. Current model still exposes `paper_engine` / `matching_accuracy_mode`, ignores unknown nested keys, and production YAML uses `matching_accuracy_mode: fast_l1`.

- [ ] **Step 3: 修改 `config.py`**

In `src/polysignal_lab/config.py`, replace the pydantic import block with this block:

```python
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    field_validator,
    model_validator,
)
```

Replace the whole `NautilusRuntimeConfig` class with this code:

```python
class NautilusRuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trader_id: str = "PolySignal-Nautilus-001"
    python: str = "3.12"
    execution_mode: Literal["paper_sandbox"] = "paper_sandbox"
    sandbox_book_type: Literal["L1_MBP", "L2_MBP"] = "L2_MBP"
    l1_book_snapshot_interval_ms: int = 1000
    allow_live_polymarket_execution: bool = False
    intercept_os_signals: bool = False
    polymarket_data: NautilusDataClientConfig = Field(
        default_factory=NautilusDataClientConfig
    )
    sidecar: NautilusSidecarConfig = Field(default_factory=NautilusSidecarConfig)
    decision_policy: NautilusDecisionPolicyConfig = Field(
        default_factory=NautilusDecisionPolicyConfig
    )
    market_rotation: NautilusMarketRotationConfig = Field(
        default_factory=NautilusMarketRotationConfig
    )

    @model_validator(mode="after")
    def validate_paper_safe(self) -> "NautilusRuntimeConfig":
        if self.allow_live_polymarket_execution:
            raise ValueError(
                "live Polymarket execution is invalid in the default runtime"
            )
        return self
```

- [ ] **Step 4: 修改生产 YAML**

In `config/signal_bot.yaml`, replace:

```yaml
    matching_accuracy_mode: fast_l1
```

with:

```yaml
    sandbox_book_type: L1_MBP
```

- [ ] **Step 5: 修改实验 YAML**

In `config/signal_bot.lab.yaml`, insert this line immediately after `intercept_os_signals: false`:

```yaml
    sandbox_book_type: L2_MBP
```

- [ ] **Step 6: 修改 TradingNode sandbox book type**

In `src/polysignal_lab/nautilus_runtime/trading_node.py`, replace line 81:

```python
                book_type=_book_type_for(settings.runtime.nautilus.matching_accuracy_mode),
```

with:

```python
                book_type=settings.runtime.nautilus.sandbox_book_type,
```

Delete the whole `_book_type_for()` function from `src/polysignal_lab/nautilus_runtime/trading_node.py`:

```python
def _book_type_for(mode: str) -> str:
    if mode == "fast_l1":
        return "L1_MBP"
    return "L2_MBP"
```

- [ ] **Step 7: 修改 node strategy book type**

In `src/polysignal_lab/nautilus_runtime/node.py`, replace this block in `_build_native_strategies`:

```python
    strategy_book_type = (
        "L1_MBP"
        if settings.runtime.nautilus.matching_accuracy_mode == "fast_l1"
        else "L2_MBP"
    )
```

with:

```python
    strategy_book_type = settings.runtime.nautilus.sandbox_book_type
```

Replace every `settings.runtime.nautilus.matching_accuracy_mode` startup metadata reference with `settings.runtime.nautilus.sandbox_book_type`. The startup notification arguments become:

```python
            await bundle.observability.notify_startup(
                strategy_names,
                sandbox_book_type=bundle.scheduler.settings.runtime.nautilus.sandbox_book_type,
            )
```

and:

```python
                bundle.observability.notify_startup(
                    strategy_names,
                    sandbox_book_type=bundle.scheduler.settings.runtime.nautilus.sandbox_book_type,
                )
```

- [ ] **Step 8: 修改 observability startup signature**

In `src/polysignal_lab/nautilus_runtime/observability.py`, replace `notify_startup()` with this implementation:

```python
    async def notify_startup(
        self,
        strategy_names: Sequence[str] = (),
        *,
        sandbox_book_type: str = "L2_MBP",
    ) -> None:
        msg = (
            f"Nautilus runtime started — {len(strategy_names)} strategies loaded — "
            f"sandbox_book_type={sandbox_book_type}"
        )
        self.health.mark_ok(
            "observability_actor",
            sandbox_book_type=sandbox_book_type,
        )
        if self.notifier is None:
            return
        await self.notifier.send(msg, "startup")
```

- [ ] **Step 9: 更新测试断言**

In `tests/test_nautilus_node.py`, replace tests that set or assert `matching_accuracy_mode` with `sandbox_book_type`. The L1 test setup becomes:

```python
    settings.runtime.nautilus.sandbox_book_type = "L1_MBP"
    settings.runtime.nautilus.l1_book_snapshot_interval_ms = 250
```

The expected startup metadata dicts become:

```python
{
    "sandbox_book_type": "L2_MBP",
}
```

In `tests/test_nautilus_observability.py`, replace `test_startup_message_includes_matching_engine_metadata` with:

```python
def test_startup_message_includes_sandbox_book_type() -> None:
    publisher = FakePublisher()
    actor = ObservabilityActor(notifier=NautilusNotifierAdapter(publisher))

    asyncio.run(
        actor.notify_startup(
            ["ptb_diff"],
            sandbox_book_type="L2_MBP",
        )
    )

    assert publisher.sent == [
        (
            "Nautilus runtime started — 1 strategies loaded — sandbox_book_type=L2_MBP",
            "startup",
        )
    ]
    component = actor.health.components["observability_actor"]
    assert component.metrics["sandbox_book_type"] == "L2_MBP"
```

- [ ] **Step 10: 运行测试确认通过**

Run:

```bash
uv run pytest \
  tests/test_nautilus_runtime_config.py \
  tests/test_nautilus_trading_node_runtime.py \
  tests/test_nautilus_node.py::test_build_trading_node_passes_l1_snapshot_interval_to_native_strategies \
  tests/test_nautilus_observability.py::test_startup_message_includes_sandbox_book_type \
  -q
```

Expected: PASS.

- [ ] **Step 11: 编译并提交**

```bash
uv run python -m py_compile \
  src/polysignal_lab/config.py \
  src/polysignal_lab/nautilus_runtime/trading_node.py \
  src/polysignal_lab/nautilus_runtime/node.py \
  src/polysignal_lab/nautilus_runtime/observability.py
git add \
  src/polysignal_lab/config.py \
  config/signal_bot.yaml \
  config/signal_bot.lab.yaml \
  src/polysignal_lab/nautilus_runtime/trading_node.py \
  src/polysignal_lab/nautilus_runtime/node.py \
  src/polysignal_lab/nautilus_runtime/observability.py \
  tests/test_nautilus_runtime_config.py \
  tests/test_nautilus_trading_node_runtime.py \
  tests/test_nautilus_node.py \
  tests/test_nautilus_observability.py
git commit -m "refactor: replace nautilus matching config with sandbox book type"
```

---

### Task 3: 删除本地 matching、manual orchestration、manual sync、PaperWallet runtime 模块

**Files:**
- Remove: `src/polysignal_lab/nautilus_runtime/matching.py`
- Remove: `src/polysignal_lab/nautilus_runtime/orchestrator.py`
- Remove: `src/polysignal_lab/nautilus_runtime/data_ingestor.py`
- Remove: `src/polysignal_lab/nautilus_runtime/execution_types.py`
- Remove: `src/polysignal_lab/nautilus_runtime/scheduler_compat.py`
- Remove: `src/polysignal_lab/nautilus_runtime/position_policy.py`
- Remove: `src/polysignal_lab/nautilus_runtime/settlement.py`
- Remove: `tests/test_nautilus_matching_execution.py`
- Remove: `tests/test_nautilus_matching_runtime_smoke.py`
- Remove: `tests/test_nautilus_orchestrator.py`
- Remove: `tests/test_nautilus_data_ingestor.py`
- Remove: `tests/test_nautilus_settlement_actor.py`
- Modify: `src/polysignal_lab/nautilus_runtime/node.py:1-220, 774-807, 908-920`
- Modify: `src/polysignal_lab/nautilus_runtime/observability.py:1-760`
- Modify: `scripts/repair_settlement_results.py`
- Modify: `tests/test_repair_settlement_results.py`
- Test: `tests/test_nautilus_platform_boundary.py`

**Interfaces:**
- Consumes: Task 1 boundary tests.
- Produces: Nautilus runtime source tree with no local paper execution client, no manual loop, no manual data ingestor, no `PaperWallet` runtime ledger, no `PaperExecutionResult`.

- [ ] **Step 1: 运行边界测试确认失败仍指向 duplicate modules**

Run:

```bash
uv run pytest \
  tests/test_nautilus_platform_boundary.py::test_nautilus_runtime_duplicate_platform_modules_are_deleted \
  tests/test_nautilus_platform_boundary.py::test_nautilus_runtime_source_has_no_platform_truth_source_terms \
  -q
```

Expected: FAIL with duplicate module paths and forbidden terms.

- [ ] **Step 2: 删除 duplicate modules 和 tests**

Run:

```bash
git rm \
  src/polysignal_lab/nautilus_runtime/matching.py \
  src/polysignal_lab/nautilus_runtime/orchestrator.py \
  src/polysignal_lab/nautilus_runtime/data_ingestor.py \
  src/polysignal_lab/nautilus_runtime/execution_types.py \
  src/polysignal_lab/nautilus_runtime/scheduler_compat.py \
  src/polysignal_lab/nautilus_runtime/position_policy.py \
  src/polysignal_lab/nautilus_runtime/settlement.py \
  tests/test_nautilus_matching_execution.py \
  tests/test_nautilus_matching_runtime_smoke.py \
  tests/test_nautilus_orchestrator.py \
  tests/test_nautilus_data_ingestor.py \
  tests/test_nautilus_settlement_actor.py
```

- [ ] **Step 3: 清理 `node.py` imports 和 bundle fields**

In `src/polysignal_lab/nautilus_runtime/node.py`, delete these imports:

```python
from polysignal_lab.nautilus_runtime.book_data import NautilusBookDataProvider
from polysignal_lab.nautilus_runtime.data_ingestor import NautilusDataIngestor
```

In `NautilusRuntimeBundle`, replace the class with:

```python
@dataclass(slots=True)
class NautilusRuntimeBundle:
    """Wired Nautilus TradingNode runtime components."""

    scheduler: PolySignalScheduler
    components: dict[str, object]
    bridge_registry: PolymarketMarketRegistry
    sidecar: ExternalDataSidecar
    node: _TradingNodeLike
    observability: ObservabilityActor
    websocket_tasks: list[asyncio.Task[object]]
```

In `_build_nautilus_runtime_bundle()`, replace the return block with:

```python
    return NautilusRuntimeBundle(
        scheduler=scheduler,
        components=components,
        bridge_registry=cast(PolymarketMarketRegistry, components["registry"]),
        sidecar=cast(ExternalDataSidecar, components["sidecar"]),
        node=cast(_TradingNodeLike, components["node"]),
        observability=observability,
        websocket_tasks=[],
    )
```

In `_run_nautilus_housekeeping_once()`, replace the function with:

```python
async def _run_nautilus_housekeeping_once(
    scheduler: PolySignalScheduler,
    last_report_date: date | None,
) -> date | None:
    from polysignal_lab.app.scheduler_runtime import _generate_iteration_report

    return await _generate_iteration_report(scheduler, last_report_date)
```

- [ ] **Step 4: 删除 `paper_execution_metadata` 写入**

In `_build_nautilus_runtime_bundle()`, delete this block:

```python
    paper_execution_metadata = {
        "paper_engine": settings.runtime.nautilus.paper_engine,
        "accuracy_mode": settings.runtime.nautilus.matching_accuracy_mode,
    }
    setattr(scheduler, "nautilus_cache_reader", components.get("cache_reader"))
    setattr(scheduler, "paper_execution_metadata", paper_execution_metadata)
```

Replace it with:

```python
    setattr(scheduler, "nautilus_cache_reader", components.get("cache_reader"))
```

- [ ] **Step 5: 清理 `observability.py` paper model imports 和 methods**

In `src/polysignal_lab/nautilus_runtime/observability.py`, delete these imports:

```python
from polysignal_lab.domain.paper_order import PaperFill, PaperOrder
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import PaperTradeResult
```

Delete `CRITICAL_PAPER_STATE` from `PersistenceClass` and replace the enum with:

```python
class PersistenceClass(Enum):
    BEST_EFFORT_TELEMETRY = "best_effort_telemetry"
    DURABLE_OR_DEGRADED = "durable_or_degraded"
    FATAL_ON_LOSS = "fatal_on_loss"
```

Replace `_CRITICAL_PAPER_STATE_TABLES` with no definition. Replace `persistence_class_for_table()` with:

```python
def persistence_class_for_table(table: str) -> PersistenceClass:
    if table in _BEST_EFFORT_TELEMETRY_TABLES:
        return PersistenceClass.BEST_EFFORT_TELEMETRY
    if table in _DURABLE_OR_DEGRADED_TABLES:
        return PersistenceClass.DURABLE_OR_DEGRADED
    return PersistenceClass.FATAL_ON_LOSS
```

Delete these complete top-level protocols/functions from `observability.py` by removing the full syntactic blocks that begin with these exact signatures:

- `class PaperFillNotifier(Protocol):`
- `class PaperFillMirror(Protocol):`
- `def signal_candidate_from_order(order: PaperOrder) -> SignalCandidate:`
- `def _text_or_fallback(value: object, fallback: object) -> str:`
- `def _metric_float(metrics: Mapping[str, object], key: str, default: float) -> float:`
- `def _metric_int(metrics: Mapping[str, object], key: str) -> int | None:`
- `def _metric_list(metrics: Mapping[str, object], key: str) -> list[str]:`
- `def _order_intent(value: str | None) -> OrderIntent | None:`

Delete these complete `ObservabilityActor` methods by removing the full syntactic blocks that begin with these exact signatures:

- `def record_signal_from_order(self, order: PaperOrder) -> None:`
- `def record_order(self, result: object) -> None:`
- `def record_fill(self, fill: PaperFill) -> None:`
- `def record_position(self, position: PaperPosition) -> None:`
- `def record_settlement(self, result: PaperTradeResult) -> None:`
- `def notify_nautilus_paper_fill(self, payload: dict[str, object]) -> None:`
- `def mirror_nautilus_paper_fill(self, payload: dict[str, object]) -> None:`

In `ObservabilityActor.__init__`, remove parameters `paper_fill_notifier` and `paper_fill_mirror`, and remove assignments to `self.paper_fill_notifier` and `self.paper_fill_mirror`.

- [ ] **Step 6: 修复 `scripts/repair_settlement_results.py`**

In `scripts/repair_settlement_results.py`, delete this import:

```python
from polysignal_lab.nautilus_runtime.scheduler_compat import init_scheduler_paper_components
```

Replace any call to `init_scheduler_paper_components(scheduler)` with this code:

```python
from polysignal_lab.paper.wallet import PaperWallet
from polysignal_lab.paper.exit_engine import PaperExitEngine
from polysignal_lab.paper.settlement import PaperSettlementEngine

scheduler.wallet = PaperWallet(scheduler.settings.paper_trading.starting_balance_usdc)
scheduler.paper = None
scheduler.exits = PaperExitEngine(scheduler.settings.paper_trading.exit_model, scheduler.wallet)
scheduler.settlement = PaperSettlementEngine(scheduler.wallet)
```

This keeps legacy repair script behavior outside `nautilus_runtime`.

- [ ] **Step 7: 运行边界测试确认通过**

Run:

```bash
uv run pytest \
  tests/test_nautilus_platform_boundary.py::test_nautilus_runtime_duplicate_platform_modules_are_deleted \
  tests/test_nautilus_platform_boundary.py::test_nautilus_runtime_source_has_no_platform_truth_source_terms \
  tests/test_default_nautilus_entry_and_report_paths_do_not_reference_legacy_runtime_layers \
  -q
```

Expected: PASS.

- [ ] **Step 8: 运行 import 和 observability focused tests**

Run:

```bash
uv run pytest \
  tests/test_nautilus_dependency_boundary.py \
  tests/test_nautilus_platform_boundary.py \
  tests/test_nautilus_observability.py::test_event_store_upserts_terminal_order_update \
  tests/test_nautilus_observability.py::test_observability_actor_records_projected_nautilus_order_fill_position \
  -q
```

Expected: PASS after removing paper-model observability tests and keeping projected Nautilus telemetry tests.

- [ ] **Step 9: 编译并提交**

```bash
uv run python -m py_compile \
  src/polysignal_lab/nautilus_runtime/node.py \
  src/polysignal_lab/nautilus_runtime/observability.py \
  scripts/repair_settlement_results.py
git add -u \
  src/polysignal_lab/nautilus_runtime \
  tests \
  scripts/repair_settlement_results.py
git commit -m "refactor: delete duplicate nautilus paper runtime layers"
```

---

### Task 4: 用 Nautilus Cache-backed provider 替换本地盘口缓存

**Files:**
- Create: `src/polysignal_lab/nautilus_runtime/cache_market_data.py`
- Remove: `src/polysignal_lab/nautilus_runtime/book_data.py`
- Remove: `tests/test_nautilus_book_data.py`
- Modify: `src/polysignal_lab/nautilus_runtime/node.py:316-323, 357-362`
- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py:499-617`
- Modify: `tests/test_nautilus_full_paper_runtime_smoke.py`
- Test: `tests/test_nautilus_cache_market_data.py`

**Interfaces:**
- Consumes: `PolymarketMarketRegistry.token_meta(token_id) -> InstrumentTokenMeta | None`, Nautilus-like cache methods `order_book(instrument_id)`, `trade_ticks(instrument_id)`.
- Produces: `NautilusCacheMarketDataProvider(cache: object, registry: PolymarketMarketRegistry)` with `book_for_token(token_id: str) -> SideBookView | None` and `trades_for_token(token_id: str) -> Sequence[TradeView]`.

- [ ] **Step 1: 新建失败测试**

Create `tests/test_nautilus_cache_market_data.py` with this complete content:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_bridge.market_registry import (
    InstrumentTokenMeta,
    MarketPairMeta,
    PolymarketMarketRegistry,
)
from polysignal_lab.nautilus_runtime.cache_market_data import (
    NautilusCacheMarketDataProvider,
)


@dataclass(frozen=True)
class FakeLevel:
    price: float
    size: float


class FakeBook:
    def __init__(self) -> None:
        self.bids = [FakeLevel(price=0.48, size=10.0)]
        self.asks = [FakeLevel(price=0.52, size=11.0), FakeLevel(price=0.53, size=12.0)]
        self.last_trade_price = 0.51
        self.last_trade_size = 2.0
        self.last_trade_timestamp = "2026-07-05T00:00:00Z"
        self.received_at = datetime.now(UTC) - timedelta(milliseconds=25)


class FakeTrade:
    price = 0.51
    size = 2.0
    aggressor_side = "BUYER"
    ts_event = datetime(2026, 7, 5, tzinfo=UTC)


class FakeCache:
    def __init__(self, instrument_id: str) -> None:
        self.instrument_id = instrument_id
        self.book = FakeBook()
        self.requested: list[Any] = []

    def order_book(self, instrument_id: object) -> FakeBook | None:
        self.requested.append(instrument_id)
        return self.book if str(instrument_id) == self.instrument_id else None

    def trade_ticks(self, instrument_id: object) -> list[FakeTrade]:
        return [FakeTrade()] if str(instrument_id) == self.instrument_id else []


def _registry() -> PolymarketMarketRegistry:
    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta(
                instrument_id="condition-btc-5m-up.POLYMARKET",
                token_id="up-token",
                side=Side.UP,
            ),
            down=InstrumentTokenMeta(
                instrument_id="condition-btc-5m-down.POLYMARKET",
                token_id="down-token",
                side=Side.DOWN,
            ),
        )
    )
    return registry


def test_cache_market_data_provider_reads_book_without_local_cache() -> None:
    instrument_id = "condition-btc-5m-up.POLYMARKET"
    provider = NautilusCacheMarketDataProvider(
        FakeCache(instrument_id),
        registry=_registry(),
    )

    view = provider.book_for_token("up-token")

    assert view is not None
    assert view.token_id == "up-token"
    assert view.best_bid == 0.48
    assert view.best_ask == 0.52
    assert view.spread == 0.04
    assert view.ask_levels == ((0.52, 11.0), (0.53, 12.0))
    assert view.last_trade_price == 0.51
    assert view.last_trade_size == 2.0
    assert view.last_trade_timestamp == "2026-07-05T00:00:00Z"
    assert view.freshness_ms is not None
    assert view.freshness_ms >= 0


def test_cache_market_data_provider_reads_trades_without_trade_deque() -> None:
    instrument_id = "condition-btc-5m-up.POLYMARKET"
    provider = NautilusCacheMarketDataProvider(
        FakeCache(instrument_id),
        registry=_registry(),
    )

    trades = tuple(provider.trades_for_token("up-token"))

    assert len(trades) == 1
    assert trades[0].price == 0.51
    assert trades[0].size == 2.0
    assert trades[0].side == "BUYER"
    assert trades[0].ts == datetime(2026, 7, 5, tzinfo=UTC)


def test_cache_market_data_provider_returns_none_for_unknown_token() -> None:
    provider = NautilusCacheMarketDataProvider(
        FakeCache("condition-btc-5m-up.POLYMARKET"),
        registry=_registry(),
    )

    assert provider.book_for_token("missing-token") is None
    assert tuple(provider.trades_for_token("missing-token")) == ()
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
uv run pytest tests/test_nautilus_cache_market_data.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'polysignal_lab.nautilus_runtime.cache_market_data'`.

- [ ] **Step 3: 创建 cache-backed provider**

Create `src/polysignal_lab/nautilus_runtime/cache_market_data.py` with this complete content:

```python
from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Callable, cast

from polysignal_lab.alpha.types import SideBookView, TradeView
from polysignal_lab.nautilus_bridge.market_registry import PolymarketMarketRegistry


class NautilusCacheMarketDataProvider:
    """Read current market data from Nautilus Cache without owning book/trade state."""

    def __init__(self, cache: object, *, registry: PolymarketMarketRegistry) -> None:
        self._cache = cache
        self._registry = registry

    def book_for_token(self, token_id: str) -> SideBookView | None:
        meta = self._registry.token_meta(token_id)
        if meta is None:
            return None
        book = self._cache_order_book(meta.instrument_id)
        if book is None:
            return None
        bids = _levels(getattr(book, "bids", ()))
        asks = _levels(getattr(book, "asks", ()))
        best_bid = bids[0][0] if bids else None
        best_ask = asks[0][0] if asks else None
        spread = round(best_ask - best_bid, 10) if best_bid is not None and best_ask is not None else None
        received_at = _datetime_or_none(getattr(book, "received_at", None))
        return SideBookView(
            token_id=token_id,
            best_bid=best_bid,
            best_ask=best_ask,
            spread=spread,
            freshness_ms=_freshness_ms(received_at),
            min_order_size=_maybe_float(getattr(book, "min_order_size", None)),
            tick_size=_maybe_float(getattr(book, "tick_size", None)),
            last_trade_price=_maybe_float(getattr(book, "last_trade_price", None)),
            last_trade_size=_maybe_float(getattr(book, "last_trade_size", None)),
            last_trade_timestamp=_optional_text(getattr(book, "last_trade_timestamp", None)),
            received_at=received_at,
            ask_levels=asks,
        )

    def trades_for_token(self, token_id: str) -> Sequence[TradeView]:
        meta = self._registry.token_meta(token_id)
        if meta is None:
            return ()
        getter = getattr(self._cache, "trade_ticks", None)
        if not callable(getter):
            return ()
        rows = cast(Callable[[object], object], getter)(meta.instrument_id)
        if not isinstance(rows, Iterable) or isinstance(rows, (str, bytes)):
            return ()
        return tuple(
            TradeView(
                price=_float_attr(row, "price"),
                size=_float_attr(row, "size"),
                side=_optional_text(getattr(row, "aggressor_side", getattr(row, "side", None))),
                ts=_datetime_or_none(getattr(row, "ts_event", getattr(row, "timestamp", None))),
            )
            for row in rows
        )

    def _cache_order_book(self, instrument_id: object) -> object | None:
        getter = getattr(self._cache, "order_book", None)
        if not callable(getter):
            return None
        return cast(Callable[[object], object | None], getter)(instrument_id)


def _levels(raw: object) -> Sequence[tuple[float, float]]:
    if callable(raw):
        raw = raw()
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes)):
        return ()
    values = []
    for level in raw:
        price = _maybe_float(getattr(level, "price", None))
        size = _maybe_float(getattr(level, "size", None))
        if price is None or size is None or price <= 0 or size <= 0:
            continue
        values.append((price, size))
    return tuple(values)


def _maybe_float(value: object) -> float | None:
    if value is None:
        return None
    if callable(value):
        value = value()
    try:
        return float(value if isinstance(value, (int, float, str, bytes, bytearray)) else str(value))
    except (TypeError, ValueError):
        return None


def _float_attr(source: object, name: str) -> float:
    value = _maybe_float(getattr(source, name, None))
    return 0.0 if value is None else value


def _datetime_or_none(value: object) -> datetime | None:
    return value if isinstance(value, datetime) else None


def _optional_text(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _freshness_ms(received_at: datetime | None) -> int | None:
    if received_at is None:
        return None
    dt = received_at if received_at.tzinfo is not None else received_at.replace(tzinfo=UTC)
    return max(0, int((datetime.now(UTC) - dt.astimezone(UTC)).total_seconds() * 1000))
```

- [ ] **Step 4: 修改 `node.py` 使用 cache-backed provider**

In `src/polysignal_lab/nautilus_runtime/node.py`, replace:

```python
    book_data_provider = NautilusBookDataProvider()
    assembler = MarketViewAssembler(
        registry=registry,
        books=book_data_provider,
        sidecar=sidecar,
    )
```

with:

```python
    book_data_provider = None
    assembler = MarketViewAssembler(
        registry=registry,
        books=_EmptyBookDataProvider(),
        sidecar=sidecar,
    )
```

After `node.build()` and before creating `NautilusCacheReader`, insert:

```python
    from polysignal_lab.nautilus_runtime.cache_market_data import NautilusCacheMarketDataProvider

    kernel = getattr(node, "kernel", None)
    nautilus_cache = getattr(node, "cache", None) or getattr(kernel, "cache", None)
    assembler.books = NautilusCacheMarketDataProvider(
        nautilus_cache,
        registry=registry,
    )
```

Then keep `cache_reader` construction using the same `kernel` and `nautilus_cache`:

```python
    cache_reader = NautilusCacheReader(
        nautilus_cache,
        portfolio=getattr(node, "portfolio", None) or getattr(kernel, "portfolio", None),
    )
```

- [ ] **Step 5: 修改 native strategy callbacks 不再复制 book/trade state**

In `src/polysignal_lab/nautilus_runtime/native_strategy.py`, replace `_update_book_from_deltas()` with:

```python
    def _update_book_from_deltas(self, deltas: object) -> str | None:
        if self.registry is None:
            return None
        instrument_id = _identifier_text(getattr(deltas, "instrument_id", None))
        if instrument_id is None:
            return None
        condition_id = _condition_id_for_instrument(self.registry, instrument_id)
        if condition_id is None:
            self._note_runtime_progress("dropped_frame")
            return None
        self._market_data_subscription_group.mark_confirmed(instrument_id)
        return condition_id
```

Replace `_update_book_from_quote_tick()` with:

```python
    def _update_book_from_quote_tick(self, tick: object) -> str | None:
        if self.registry is None:
            return None
        instrument_id = _identifier_text(getattr(tick, "instrument_id", None))
        if instrument_id is None:
            return None
        condition_id = _condition_id_for_instrument(self.registry, instrument_id)
        if condition_id is None:
            self._note_runtime_progress("dropped_frame")
            return None
        self._market_data_subscription_group.mark_confirmed(instrument_id)
        return condition_id
```

Replace `_update_book_from_order_book()` with:

```python
    def _update_book_from_order_book(self, book: object) -> str | None:
        if self.registry is None:
            return None
        instrument_id = _identifier_text(getattr(book, "instrument_id", None))
        if instrument_id is None:
            return None
        condition_id = _condition_id_for_instrument(self.registry, instrument_id)
        if condition_id is None:
            self._note_runtime_progress("dropped_frame")
            return None
        self._market_data_subscription_group.mark_confirmed(instrument_id)
        return condition_id
```

Replace `_update_trade_from_tick()` with:

```python
    def _update_trade_from_tick(self, tick: object) -> str | None:
        if self.registry is None:
            return None
        instrument_id = _identifier_text(getattr(tick, "instrument_id", None))
        if instrument_id is None:
            return None
        condition_id = _condition_id_for_instrument(self.registry, instrument_id)
        if condition_id is None:
            self._note_runtime_progress("dropped_frame")
            return None
        self._market_data_subscription_group.mark_confirmed(instrument_id)
        return condition_id
```

Delete helper `_domain_order_book()` and unused import `BookLevel` / `OrderBook` from `native_strategy.py`.

- [ ] **Step 6: 删除旧 provider 文件和 tests**

Run:

```bash
git rm \
  src/polysignal_lab/nautilus_runtime/book_data.py \
  tests/test_nautilus_book_data.py
```

- [ ] **Step 7: 更新 smoke tests**

In `tests/test_nautilus_full_paper_runtime_smoke.py`, replace imports of `NautilusBookDataProvider` with `NautilusCacheMarketDataProvider` and replace assertions:

```python
assert isinstance(runtime["book_data_provider"], NautilusBookDataProvider)
assembler = cast(SimpleNamespace, runtime["assembler"])
assert assembler.books is runtime["book_data_provider"]
```

with:

```python
from polysignal_lab.nautilus_runtime.cache_market_data import NautilusCacheMarketDataProvider

assembler = cast(SimpleNamespace, runtime["assembler"])
assert isinstance(assembler.books, NautilusCacheMarketDataProvider)
assert "book_data_provider" not in runtime
```

- [ ] **Step 8: 运行 focused tests**

Run:

```bash
uv run pytest \
  tests/test_nautilus_cache_market_data.py \
  tests/test_nautilus_platform_boundary.py::test_nautilus_runtime_duplicate_platform_modules_are_deleted \
  tests/test_nautilus_full_paper_runtime_smoke.py::test_build_trading_node_exposes_shared_book_data_provider \
  -q
```

Expected: PASS after renaming the smoke test to `test_build_trading_node_uses_cache_backed_market_data_provider`.

- [ ] **Step 9: 编译并提交**

```bash
uv run python -m py_compile \
  src/polysignal_lab/nautilus_runtime/cache_market_data.py \
  src/polysignal_lab/nautilus_runtime/node.py \
  src/polysignal_lab/nautilus_runtime/native_strategy.py
git add \
  src/polysignal_lab/nautilus_runtime/cache_market_data.py \
  src/polysignal_lab/nautilus_runtime/node.py \
  src/polysignal_lab/nautilus_runtime/native_strategy.py \
  tests/test_nautilus_cache_market_data.py \
  tests/test_nautilus_full_paper_runtime_smoke.py
git add -u src/polysignal_lab/nautilus_runtime tests
git commit -m "refactor: read nautilus market data from cache projections"
```

---

### Task 5: 删除自建 BinaryOption / InstrumentProvider 替代路径

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/instrument_mapping.py:1-128`
- Modify: `src/polysignal_lab/nautilus_runtime/node.py:387-395`
- Modify: `tests/test_nautilus_default_runtime_integration.py:1-243`
- Modify: `tests/test_nautilus_instrument_mapping.py`
- Test: `tests/test_nautilus_platform_boundary.py`

**Interfaces:**
- Consumes: Nautilus Polymarket adapter helper `get_polymarket_instrument_id(condition_id: str, token_id: str) -> object`.
- Produces: `polymarket_instrument_id(condition_id: str, token_id: str) -> str` with no project fallback instrument format and no `BinaryOption` construction.

- [ ] **Step 1: 添加 instrument boundary 测试**

Append this code to `tests/test_nautilus_platform_boundary.py`:

```python


def test_nautilus_runtime_does_not_construct_instruments_locally() -> None:
    forbidden = (
        "class NautilusInstrumentMeta",
        "def instrument_id_for_token",
        "def build_binary_option",
        "BinaryOption(",
        "cache.add_instrument",
        "exchange.add_instrument",
        "DEFAULT_VENUE = \"POLYSIGNAL_PM_PAPER\"",
        "return f\"{condition}-{token}.POLYMARKET\"",
    )
    findings: list[str] = []
    for path in Path("src/polysignal_lab/nautilus_runtime").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
uv run pytest tests/test_nautilus_platform_boundary.py::test_nautilus_runtime_does_not_construct_instruments_locally -q
```

Expected: FAIL with findings in `instrument_mapping.py` and deleted `matching.py` references if Task 3 has not landed in the current branch.

- [ ] **Step 3: 精简 `instrument_mapping.py`**

Replace the entire content of `src/polysignal_lab/nautilus_runtime/instrument_mapping.py` with:

```python
from __future__ import annotations

from importlib import import_module
from typing import Callable, cast


POLYMARKET_VENUE = "POLYMARKET"


def polymarket_instrument_id(condition_id: str, token_id: str) -> str:
    condition = str(condition_id).strip()
    token = str(token_id).strip()
    if not condition:
        raise ValueError("condition_id must not be empty")
    if not token:
        raise ValueError("token_id must not be empty")
    try:
        helper = getattr(
            import_module("nautilus_trader.adapters.polymarket"),
            "get_polymarket_instrument_id",
        )
    except (ModuleNotFoundError, AttributeError) as exc:
        raise RuntimeError(
            "Nautilus Polymarket adapter is required to resolve instrument IDs"
        ) from exc
    return str(cast(Callable[[str, str], object], helper)(condition, token))
```

- [ ] **Step 4: 修改 trading node constants**

In `src/polysignal_lab/nautilus_runtime/trading_node.py`, replace:

```python
from polysignal_lab.nautilus_runtime.instrument_mapping import DEFAULT_VENUE

PAPER_EXEC_CLIENT_ID = DEFAULT_VENUE
```

with:

```python
PAPER_EXEC_CLIENT_ID = "POLYSIGNAL_PM_PAPER"
```

- [ ] **Step 5: 删除依赖项目自建 BinaryOption 的 Nautilus-dependent integration test**

Replace the entire contents of `tests/test_nautilus_default_runtime_integration.py` with this file:

```python
from __future__ import annotations

from polysignal_lab.nautilus_runtime.trading_node import PAPER_EXEC_CLIENT_ID


def test_default_runtime_sandbox_client_id_stays_distinct_from_polymarket_venue() -> None:
    assert PAPER_EXEC_CLIENT_ID != "POLYMARKET"
```

This removes the only integration test that constructed instruments through `build_binary_option()`. The remaining runtime coverage stays in `tests/test_nautilus_node.py`, `tests/test_nautilus_trading_node_runtime.py`, and `tests/test_nautilus_full_paper_runtime_smoke.py`, which use fakes or Nautilus-owned factories instead of project-owned `BinaryOption` construction.

- [ ] **Step 6: 更新 instrument mapping tests**

Replace `tests/test_nautilus_instrument_mapping.py` with tests that monkeypatch the adapter helper instead of asserting fallback construction:

```python
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from polysignal_lab.nautilus_runtime.instrument_mapping import polymarket_instrument_id


def test_polymarket_instrument_id_uses_nautilus_adapter_helper(monkeypatch) -> None:
    helper_calls: list[tuple[str, str]] = []

    def helper(condition_id: str, token_id: str) -> str:
        helper_calls.append((condition_id, token_id))
        return f"{condition_id}:{token_id}.POLYMARKET"

    monkeypatch.setitem(
        sys.modules,
        "nautilus_trader.adapters.polymarket",
        SimpleNamespace(get_polymarket_instrument_id=helper),
    )

    assert polymarket_instrument_id("condition", "token") == "condition:token.POLYMARKET"
    assert helper_calls == [("condition", "token")]


def test_polymarket_instrument_id_rejects_empty_parts() -> None:
    with pytest.raises(ValueError, match="condition_id must not be empty"):
        polymarket_instrument_id("", "token")

    with pytest.raises(ValueError, match="token_id must not be empty"):
        polymarket_instrument_id("condition", "")


def test_polymarket_instrument_id_requires_nautilus_adapter(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "nautilus_trader.adapters.polymarket", SimpleNamespace())

    with pytest.raises(RuntimeError, match="Nautilus Polymarket adapter is required"):
        polymarket_instrument_id("condition", "token")
```

- [ ] **Step 7: 运行测试**

Run:

```bash
uv run pytest \
  tests/test_nautilus_instrument_mapping.py \
  tests/test_nautilus_platform_boundary.py::test_nautilus_runtime_does_not_construct_instruments_locally \
  tests/test_nautilus_default_runtime_integration.py::test_default_runtime_sandbox_client_id_stays_distinct_from_polymarket_venue \
  -q
```

Expected: PASS. The full Nautilus-dependent integration test may skip if Nautilus is unavailable through `require_nautilus()`.

- [ ] **Step 8: 编译并提交**

```bash
uv run python -m py_compile \
  src/polysignal_lab/nautilus_runtime/instrument_mapping.py \
  src/polysignal_lab/nautilus_runtime/trading_node.py
git add \
  src/polysignal_lab/nautilus_runtime/instrument_mapping.py \
  src/polysignal_lab/nautilus_runtime/trading_node.py \
  tests/test_nautilus_instrument_mapping.py \
  tests/test_nautilus_platform_boundary.py \
  tests/test_nautilus_default_runtime_integration.py
git commit -m "refactor: rely on nautilus polymarket instrument provider"
```

---

### Task 6: 删除 installed-source patch 和 Nautilus engine monkeypatch

**Files:**
- Remove: `src/polysignal_lab/nautilus_runtime/patch_nautilus_polymarket_autoload.py`
- Remove: `tests/test_nautilus_wheel_patch.py`
- Modify: `Dockerfile:32-35`
- Modify: `src/polysignal_lab/nautilus_runtime/node.py:1046-1132, 1193-1195, 1294-1296`
- Modify: `tests/test_nautilus_node.py:1645-1830, 2400-2420`
- Test: `tests/test_nautilus_platform_boundary.py`

**Interfaces:**
- Consumes: Task 1 patch boundary test.
- Produces: Nautilus runtime that never rewrites installed package files and never replaces Nautilus engine private methods.

- [ ] **Step 1: 运行 patch boundary 测试确认失败**

Run:

```bash
uv run pytest tests/test_nautilus_platform_boundary.py::test_nautilus_runtime_does_not_patch_nautilus_installed_sources -q
```

Expected: FAIL with `Dockerfile:patch_nautilus_polymarket_autoload` and `node.py:_handle_queue_exception` findings.

- [ ] **Step 2: 删除 patch module 和 tests**

Run:

```bash
git rm \
  src/polysignal_lab/nautilus_runtime/patch_nautilus_polymarket_autoload.py \
  tests/test_nautilus_wheel_patch.py
```

- [ ] **Step 3: 修改 Dockerfile**

Replace lines 33-35 in `Dockerfile`:

```dockerfile
FROM builder AS nautilus-builder
RUN pip install --ignore-installed --no-cache-dir --only-binary=nautilus-trader --prefix=/install-nautilus '.[dev]' 'nautilus_trader[polymarket]==1.229.0' \
    && PYTHONPATH=/install-nautilus/lib/python3.12/site-packages python -m polysignal_lab.nautilus_runtime.patch_nautilus_polymarket_autoload
```

with:

```dockerfile
FROM builder AS nautilus-builder
RUN pip install --ignore-installed --no-cache-dir --only-binary=nautilus-trader --prefix=/install-nautilus '.[dev]' 'nautilus_trader[polymarket]==1.229.0'
```

- [ ] **Step 4: 删除 node.py precision guard functions 和 calls**

In `src/polysignal_lab/nautilus_runtime/node.py`, delete these complete top-level functions by removing the full syntactic blocks that begin with these exact signatures:

- `def _is_polymarket_precision_mismatch(exc: Exception, queue_name: str) -> bool:`
- `def _polymarket_precision_guarded_queue_exception_handler(original: Callable[[object, Exception, str], None]) -> Callable[[object, Exception, str], None]:`
- `def _install_polymarket_precision_engine_guard(module_name: str, class_name: str) -> bool:`
- `def _install_polymarket_precision_data_engine_guard() -> None:`
- `def _install_polymarket_precision_exec_engine_guard() -> None:`
- `def _install_polymarket_precision_runtime_guards() -> None:`

Delete these two calls:

```python
        _install_polymarket_precision_runtime_guards()
```

from `run_nautilus_cli_async()` and `run_nautilus_cli()`.

Remove unused import `time` from `node.py` if no remaining code references it.

- [ ] **Step 5: 删除 precision guard tests**

In `tests/test_nautilus_node.py`, delete every test whose name starts with:

```python
test_polymarket_precision_guard_
test_install_polymarket_precision_exec_engine_guard_
test_run_nautilus_cli_installs_polymarket_precision_guard
```

In remaining tests that monkeypatch `_install_polymarket_precision_runtime_guards`, delete those monkeypatch lines:

```python
monkeypatch.setattr(node_mod, "_install_polymarket_precision_runtime_guards", lambda: None)
```

- [ ] **Step 6: 运行 tests**

Run:

```bash
uv run pytest \
  tests/test_nautilus_platform_boundary.py::test_nautilus_runtime_does_not_patch_nautilus_installed_sources \
  tests/test_nautilus_node.py \
  -q
```

Expected: PASS.

- [ ] **Step 7: 编译并提交**

```bash
uv run python -m py_compile src/polysignal_lab/nautilus_runtime/node.py
git add -u \
  Dockerfile \
  src/polysignal_lab/nautilus_runtime \
  tests/test_nautilus_node.py \
  tests/test_nautilus_platform_boundary.py \
  tests/test_nautilus_wheel_patch.py
git commit -m "refactor: stop patching nautilus internals"
```

---

### Task 7: 收紧 observability 和 report 只读投影边界

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/observability.py:1-760`
- Modify: `src/polysignal_lab/app/scheduler_reporting.py`
- Modify: `tests/test_nautilus_observability.py`
- Modify: `tests/test_nautilus_platform_boundary.py`

**Interfaces:**
- Consumes: `NautilusCacheReader.read_orders()`, `read_fills()`, `read_positions()`, `read_account_projection()`, `snapshot_portfolio_projection()`.
- Produces: Observability actor with no paper model write APIs; reports read from Nautilus cache projections through scheduler `nautilus_cache_reader`.

- [ ] **Step 1: 添加 observability API 边界测试**

Append this code to `tests/test_nautilus_platform_boundary.py`:

```python


def test_nautilus_observability_has_no_paper_model_recording_api() -> None:
    source = Path("src/polysignal_lab/nautilus_runtime/observability.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "from polysignal_lab.domain.paper_order import",
        "from polysignal_lab.domain.paper_position import",
        "from polysignal_lab.domain.paper_result import",
        "def record_order(",
        "def record_fill(",
        "def record_position(",
        "def record_settlement(",
        "def record_signal_from_order(",
        "def signal_candidate_from_order(",
        "PaperFillNotifier",
        "PaperFillMirror",
        "mirror_nautilus_paper_fill",
    )

    assert [token for token in forbidden if token in source] == []
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
uv run pytest tests/test_nautilus_platform_boundary.py::test_nautilus_observability_has_no_paper_model_recording_api -q
```

Expected: FAIL with forbidden paper model APIs in `observability.py`.

- [ ] **Step 3: 删除 paper model observability tests**

In `tests/test_nautilus_observability.py`, delete complete test functions containing any of these exact API call substrings:

- `actor.record_order(`
- `actor.record_fill(`
- `actor.record_position(`
- `actor.record_settlement(`
- `actor.record_signal_from_order(`
- `actor.mirror_nautilus_paper_fill(`
- `actor.notify_nautilus_paper_fill(`

Keep complete test functions containing these Nautilus projection API calls:

- `actor.record_decision(`
- `actor.record_signal(`
- `actor.record_rejected_decision(`
- `actor.record_nautilus_order_event(`
- `actor.record_nautilus_fill_event(`
- `actor.record_nautilus_position(`
- `actor.record_health_snapshot(`

- [ ] **Step 4: 确认 report path 使用 Nautilus cache reader**

In `src/polysignal_lab/app/scheduler_reporting.py`, ensure any Nautilus branch reads from `scheduler.nautilus_cache_reader` and does not import from `polysignal_lab.nautilus_runtime.execution_types`, `matching`, or `orchestrator`. Use this helper if the file lacks one:

```python
def _nautilus_projection_rows(scheduler: object, name: str) -> list[dict[str, object]]:
    reader = getattr(scheduler, "nautilus_cache_reader", None)
    method = getattr(reader, name, None)
    if not callable(method):
        return []
    rows = method()
    return rows if isinstance(rows, list) else []
```

Use it as:

```python
orders = _nautilus_projection_rows(scheduler, "read_orders")
fills = _nautilus_projection_rows(scheduler, "read_fills")
positions = _nautilus_projection_rows(scheduler, "read_positions")
```

- [ ] **Step 5: 运行 tests**

Run:

```bash
uv run pytest \
  tests/test_nautilus_platform_boundary.py::test_nautilus_observability_has_no_paper_model_recording_api \
  tests/test_nautilus_observability.py \
  tests/test_scheduler_reports.py \
  -q
```

Expected: PASS.

- [ ] **Step 6: 编译并提交**

```bash
uv run python -m py_compile \
  src/polysignal_lab/nautilus_runtime/observability.py \
  src/polysignal_lab/app/scheduler_reporting.py
git add \
  src/polysignal_lab/nautilus_runtime/observability.py \
  src/polysignal_lab/app/scheduler_reporting.py \
  tests/test_nautilus_observability.py \
  tests/test_nautilus_platform_boundary.py
git commit -m "refactor: keep nautilus observability projection-only"
```

---

### Task 8: 记录 legacy TradingNode 设计偏差和 LiveNode 迁移门槛

**Files:**
- Modify: `docs/NAUTILUS_BRIDGE_BOUNDARY.md:13-30,90-125`
- Modify: `docs/IMPLEMENTATION_SUMMARY.md:3-20`

**Interfaces:**
- Consumes: current default runtime still enters through `src/polysignal_lab/nautilus_runtime/node.py::build_trading_node()` and imports `nautilus_trader.live.node.TradingNode`.
- Produces: documented non-wheel design-debt boundary: legacy `TradingNode` is not removed in this dedup cleanup, and a future migration must replace it with `LiveNode.builder` without reintroducing custom matching, custom data-engine loops, or external market-data truth stores.

- [ ] **Step 1: 更新 bridge boundary 的 runtime note**

Insert this section immediately after `## Bridge Runtime` in `docs/NAUTILUS_BRIDGE_BOUNDARY.md`:

```markdown
## Node Surface Status

The current default Nautilus bridge enters through `nautilus_trader.live.node.TradingNode`. This is an active default-path design deviation from the newer `LiveNode.builder` surface documented by Nautilus, but it is not a duplicated PolySignal platform implementation.

This cleanup does not delete or rename `TradingNode` wiring. A future `LiveNode` migration is accepted only when all of these conditions are true:

- `build_trading_node()` constructs the Nautilus node through `LiveNode.builder` or the exact supported builder API in the installed Nautilus version.
- Polymarket data remains registered through the Nautilus Polymarket data client factory.
- Paper execution remains registered through the Nautilus sandbox execution client factory.
- Strategy order submission still uses Nautilus `order_factory` and `submit_order`.
- Market views still read from Nautilus cache projections plus PolySignal business custom data.
- No `NautilusMatchingPaperExecutionClient`, `NautilusOrchestrator`, `NautilusDataIngestor`, `PaperWallet` runtime ledger, installed-source patch, or private engine monkeypatch is reintroduced.
```

- [ ] **Step 2: 更新 implementation summary 的 node status row**

In `docs/IMPLEMENTATION_SUMMARY.md`, add this row immediately after the `Paper trading` row:

```markdown
| Node surface | Current default uses legacy Nautilus `TradingNode`; this is tracked as a non-wheel design deviation with a separate `LiveNode.builder` migration gate |
```

- [ ] **Step 3: 提交设计偏差文档**

```bash
git add docs/NAUTILUS_BRIDGE_BOUNDARY.md docs/IMPLEMENTATION_SUMMARY.md
git commit -m "docs: record nautilus livenode migration boundary"
```

---

### Task 9: 更新文档和最终全局验证

**Files:**
- Modify: `docs/NAUTILUS_BRIDGE_BOUNDARY.md:90-125`
- Modify: `docs/IMPLEMENTATION_SUMMARY.md:3-20`
- Test: `tests/test_nautilus_platform_boundary.py`
- Test: `tests/test_nautilus_runtime_config.py`
- Test: `tests/test_nautilus_node.py`
- Test: `tests/test_nautilus_strategy_base.py`
- Test: `tests/test_nautilus_cache_market_data.py`

**Interfaces:**
- Consumes: all previous tasks.
- Produces: documented Nautilus design boundary, explicit `TradingNode` non-wheel deviation, and verified source tree with no duplicate platform layers.

- [ ] **Step 1: 更新 `docs/NAUTILUS_BRIDGE_BOUNDARY.md` implemented components**

Replace the Post-Fix implemented-components list with:

```markdown
- Implemented components after duplicate-platform cleanup:
  * Default runtime: Nautilus node owns lifecycle, data engine, execution engine, cache, portfolio, and sandbox execution.
  * Node surface: current default still uses legacy Nautilus `TradingNode`; this is a non-wheel design deviation tracked behind a separate `LiveNode.builder` migration gate.
  * Data: Polymarket market data uses `PolymarketLiveDataClientFactory`; business spot/PTB/market metadata uses Nautilus custom data.
  * Execution: paper execution uses Nautilus `SandboxLiveExecClientFactory`; no PolySignal-owned matching client, `PaperWallet`, or `PaperExecutionResult` remains under `nautilus_runtime`.
  * Strategy: `PolySignalNativeStrategy` submits orders through Nautilus `order_factory` and `submit_order`.
  * Market views: alpha views are read-only projections from Nautilus cache plus business custom data.
  * Observability: dashboard/report rows are read-only projections from Nautilus events/cache/portfolio; no local paper ledger drives runtime state.
  * Safety: no live Polymarket execution client, no installed Nautilus source patch, no private engine monkeypatch.
```

- [ ] **Step 2: 更新 `docs/IMPLEMENTATION_SUMMARY.md`**

Replace rows 8-16 in the delivered table with:

```markdown
| Polymarket data | Nautilus Polymarket data factory plus business market rotation custom data |
| Sidecar data | Spot, price-to-beat, anchor, and market metadata custom data for Nautilus strategies |
| Snapshots | Market view assembly from Nautilus cache projections and business custom data |
| Strategies | PolySignal alpha cores wrapped by Nautilus strategy callbacks |
| Signal layer | SignalCandidate schema, gate, dedupe, channel rate limiter, consensus engine, formatter |
| Telegram | Dry-run default publisher, retry-capable HTTP sender, publish audit record, real Telegram QA command with redacted evidence |
| Paper trading | Nautilus node, native order submission, Nautilus sandbox execution, cache/portfolio projections |
| Node surface | Current default uses legacy Nautilus `TradingNode`; this is tracked as a non-wheel design deviation with a separate `LiveNode.builder` migration gate |
| Exits/settlement | Prediction-market resolution remains business logic; runtime positions come from Nautilus portfolio projection |
| Reporting | Daily report, PnL, ROI, win rate, drawdown, profit factor, breakdowns over projected Nautilus state |
```

- [ ] **Step 3: 运行所有 Nautilus boundary/config/source tests**

Run:

```bash
uv run pytest \
  tests/test_nautilus_dependency_boundary.py \
  tests/test_nautilus_platform_boundary.py \
  tests/test_nautilus_runtime_config.py \
  tests/test_nautilus_trading_node_runtime.py \
  tests/test_nautilus_node.py \
  tests/test_nautilus_cache_market_data.py \
  -q
```

Expected: PASS.

- [ ] **Step 4: 运行 strategy/order focused tests**

Run:

```bash
uv run pytest \
  tests/test_nautilus_strategy_base.py \
  tests/test_nautilus_order_mapping.py \
  tests/test_nautilus_market_rotation.py \
  tests/test_nautilus_sidecar_actor.py \
  -q
```

Expected: PASS.

- [ ] **Step 5: 运行 import、compile、type check**

Run:

```bash
uv run python -c "import polysignal_lab; import polysignal_lab.nautilus_runtime.node"
uv run python -m py_compile \
  src/polysignal_lab/config.py \
  src/polysignal_lab/nautilus_runtime/node.py \
  src/polysignal_lab/nautilus_runtime/trading_node.py \
  src/polysignal_lab/nautilus_runtime/native_strategy.py \
  src/polysignal_lab/nautilus_runtime/native_order.py \
  src/polysignal_lab/nautilus_runtime/cache_market_data.py \
  src/polysignal_lab/nautilus_runtime/cache_reader.py \
  src/polysignal_lab/nautilus_runtime/projections.py \
  src/polysignal_lab/nautilus_runtime/observability.py \
  src/polysignal_lab/nautilus_runtime/instrument_mapping.py \
  src/polysignal_lab/nautilus_runtime/market_rotation.py \
  src/polysignal_lab/nautilus_runtime/sidecar_data.py
uv run basedpyright \
  src/polysignal_lab/nautilus_runtime \
  src/polysignal_lab/nautilus_bridge \
  tests/test_nautilus_platform_boundary.py \
  tests/test_nautilus_runtime_config.py \
  tests/test_nautilus_cache_market_data.py
```

Expected:

```text
0 errors, 0 warnings, 0 notes
```

If basedpyright prints informational timing lines in addition to `0 errors`, keep the command output in the commit notes.

- [ ] **Step 6: Docker build verification**

Run:

```bash
docker compose build polysignal-lab
```

Expected: build succeeds without running `polysignal_lab.nautilus_runtime.patch_nautilus_polymarket_autoload`.

- [ ] **Step 7: 提交文档和 final verification changes**

```bash
git add \
  docs/NAUTILUS_BRIDGE_BOUNDARY.md \
  docs/IMPLEMENTATION_SUMMARY.md \
  tests/test_nautilus_platform_boundary.py \
  tests/test_nautilus_runtime_config.py \
  tests/test_nautilus_cache_market_data.py
git commit -m "docs: document nautilus-owned runtime boundary"
```

---

## Self-Review

### 1. Spec coverage

- 删除本地 paper matching：Task 3 删除 `matching.py`、matching tests、`PaperExecutionResult`。
- 删除 manual orchestration：Task 3 删除 `orchestrator.py` 和 tests。
- 删除 manual data sync：Task 3 删除 `data_ingestor.py` 和 tests。
- 删除本地盘口缓存：Task 4 删除 `book_data.py`，新增 cache-backed provider。
- 删除 instrument provider 替代实现：Task 5 删除 `build_binary_option()`、`instrument_id_for_token()`、fallback instrument id。
- 删除 PaperWallet runtime ledger：Task 3 删除 `position_policy.py`、`settlement.py`、`scheduler_compat.py`，Task 7 删除 observability paper model APIs。
- 删除 installed-source patch：Task 6 删除 patch module、Docker patch invocation、patch tests。
- 删除 engine monkeypatch：Task 6 删除 precision guard functions/calls/tests。
- 保留 Nautilus 设计：Task 2 保留 the `book_type` constructor argument of `SandboxExecutionClientConfig` 行为，Task 4 使用 Nautilus cache，Task 5 使用 Nautilus Polymarket helper/provider，Task 9 验证。
- 活跃默认路径市场数据状态镜像：Task 1 增加 `NautilusBookDataProvider` / `.update_book(` / `.update_trade(` 边界测试，Task 4 删除外部 book/trade state mirror。
- legacy `TradingNode` 选型：Task 8 作为非 wheel 设计偏差记录 deferred `LiveNode.builder` 迁移门槛，不纳入 duplicate runtime deletion。
- `paper_engine=nautilus_matching` 元数据陈旧：Task 2 删除配置字段和 startup metadata。

### 2. Placeholder scan

No forbidden handoff phrases from the plan-writing skill remain. Task 5 uses an exact file replacement for `tests/test_nautilus_default_runtime_integration.py` and does not ask the implementer to discover a Nautilus fixture name.

### 3. Type consistency

- `sandbox_book_type` is defined once on `NautilusRuntimeConfig` and used by `trading_node.py`, `node.py`, tests, and YAML.
- `NautilusCacheMarketDataProvider.book_for_token()` and `trades_for_token()` satisfy existing `MarketViewAssembler.BookDataProvider` protocol.
- `polymarket_instrument_id(condition_id: str, token_id: str) -> str` remains the only production instrument mapping helper.
- Observability keeps `record_nautilus_order_event`, `record_nautilus_fill_event`, and `record_nautilus_position`; paper model recording APIs are removed consistently.

---

## Final Status (2026-07-06)

Completed and extended by `docs/superpowers/plans/2026-07-06-nautilus-runtime-dedup-final-removal.md`. That follow-up plan removed the local paper execution stack project-wide under `src/polysignal_lab/` (not only `nautilus_runtime/`), updated operator docs to state Nautilus sandbox/cache/portfolio as the only runtime paper truth source, and preserved legacy `TradingNode` only as a non-wheel design deviation behind a separate `LiveNode.builder` migration gate.
