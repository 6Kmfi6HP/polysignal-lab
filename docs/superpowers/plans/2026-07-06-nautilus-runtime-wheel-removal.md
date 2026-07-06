# Nautilus Runtime Wheel Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 彻底删除默认 Nautilus runtime 中的 legacy node surface、动态 runtime type factory、共享 sidecar 状态、instrument 反向 registry、裸 `asyncio` actor fallback 和大型订单/数据回调函数，确保 PolySignal 不再重复 Nautilus 已提供的平台能力。

**Architecture:** 默认 runtime 改为 Nautilus `LiveNode.builder(...)` 构建路径，Polymarket market data 继续由 Nautilus Polymarket data client 负责，paper execution 继续由 Nautilus sandbox execution 负责。PolySignal 只保留业务层：alpha core、decision policy、strategy-local custom data 派生状态、read-only cache/portfolio projection、报告/结算。所有 legacy compatibility wrapper、shared mutable sidecar、dynamic `new_class`、runtime truth-source mirror 都删除或收敛为明确的只读/派生接口。

**Tech Stack:** Python 3.11 default import-safe package, NautilusTrader optional bridge runtime on Python 3.12-3.14, pytest, uv, CodeGraph/Fast Context for exploration, Nautilus Polymarket data adapter, Nautilus sandbox execution adapter.

## Global Constraints

- 必须先用 CodeGraph 或 Fast Context 定位相关代码，不能用手工 grep/read loop 代替架构探索。
- 默认 Python 3.11 环境、Docker runtime 和 `polysignal-lab` package import 不能在 package import time 导入 NautilusTrader。
- Nautilus bridge runtime 使用 Python 3.12-3.14；默认 runtime 不读取 `POLYMARKET_PK`、`POLYMARKET_FUNDER`、`POLYMARKET_API_KEY`、`POLYMARKET_API_SECRET`、`POLYMARKET_PASSPHRASE`。
- 默认 runtime 不注册 live Polymarket execution client；只允许 `SandboxLiveExecClientFactory` 作为 paper execution factory。
- Polymarket public market data 必须来自 Nautilus Polymarket data client factory；不能重建本地 data ingestor、book mirror、trade mirror、instrument construction。
- Strategy order submission 必须使用 Nautilus `order_factory.limit(...)` 和 `submit_order(...)`；不能重建 matching engine、wallet ledger、fill model、resting-order store。
- Cache/portfolio/order/fill/position/account 只能通过 read-only projection 读取；不能调用 `cache.add_order`、`exchange.add_instrument`、`MessageBus()`、`SimulatedExchange()`、`BacktestExecClient()`。
- `src/polysignal_lab/nautilus_runtime/strategies/base.py` compatibility wrappers 必须从默认 runtime import path 删除；保留需要显式标注为 compatibility-only，并且默认入口不能引用。
- 每个任务必须按 TDD：先写失败测试，再最小实现，再跑目标测试，再提交。

---

## File Structure

### 删除

- `src/polysignal_lab/nautilus_bridge/external_data.py` — 删除共享 mutable sidecar store；strategy-local 派生状态替代它。
- `src/polysignal_lab/nautilus_runtime/sidecar_data.py` 中的 `runtime_sidecar_actor_type` 和 `PolySignalRuntimeSidecarActor` — 删除独立 sidecar actor；market rotation actor 直接发布 custom data。
- `src/polysignal_lab/nautilus_runtime/native_strategy.py` 中的 `runtime_native_strategy_type` — 删除动态 `new_class` strategy factory。
- `src/polysignal_lab/nautilus_runtime/market_rotation.py` 中的 `runtime_market_rotation_actor_type` — 删除动态 `new_class` actor factory。
- `src/polysignal_lab/nautilus_runtime/strategies/base.py` 默认入口依赖 — 不删除文件本身，删除默认 runtime 的所有引用。

### 新建

- `src/polysignal_lab/nautilus_runtime/live_node.py` — Nautilus `LiveNode.builder(...)` 构建和 factory registration 的唯一入口。
- `src/polysignal_lab/nautilus_runtime/runtime_classes.py` — 仅在 Nautilus runtime lazy import 后加载的静态 Nautilus subclasses：`NautilusPolySignalNativeStrategy`、`NautilusMarketRotationActor`。
- `src/polysignal_lab/nautilus_runtime/custom_data_state.py` — strategy-local custom data 派生状态；不发布、不调度、不持有 Nautilus platform truth。
- `src/polysignal_lab/nautilus_bridge/market_catalog.py` — condition/token business catalog；不存 `_by_instrument`，instrument id 按需用 Nautilus Polymarket helper 派生。
- `src/polysignal_lab/nautilus_runtime/order_plan.py` — 小型纯函数：intent、price、quantity、tags 分离。

### 修改

- `src/polysignal_lab/nautilus_runtime/node.py` — 从 `TradingNode`/`TradingNodeConfig` 改到 `LiveNode.builder(...)`；删除 legacy placeholders；只 attach read-only projections。
- `src/polysignal_lab/nautilus_runtime/trading_node.py` — 保留安全断言和 config 构造小函数；删除 `TradingNodeConfig` 组装职责或迁移到 `live_node.py`。
- `src/polysignal_lab/nautilus_runtime/native_strategy.py` — 使用 strategy-local custom data state 和 `MarketCatalog`；拆分 `on_data`。
- `src/polysignal_lab/nautilus_runtime/market_rotation.py` — 只用 Nautilus actor clock/timer；删除裸 `asyncio.create_task` startup/spot fallback。
- `src/polysignal_lab/nautilus_runtime/cache_market_data.py` — 通过 `MarketCatalog.instrument_id_for_token(token_id)` 读取 Nautilus cache；不反查 instrument。
- `src/polysignal_lab/nautilus_bridge/market_view_assembler.py` — 依赖 `CustomDataSnapshotProvider` protocol；不依赖 shared sidecar class。
- `src/polysignal_lab/nautilus_runtime/sidecar_data.py` — 收敛为 `CustomDataPublisher`，只构造并 publish Nautilus custom data。
- `src/polysignal_lab/nautilus_runtime/order_mapping.py` — 变成 thin wrapper 或删除，由 `order_plan.py` 提供小函数。
- `tests/test_nautilus_platform_boundary.py` — 增加 hard boundary tests。
- `tests/test_nautilus_node.py` — 更新 fake builder tests。
- `tests/test_nautilus_market_registry.py` — 改为 `test_nautilus_market_catalog.py`。
- `tests/test_nautilus_market_view_assembler.py` — 使用 strategy-local custom data state。
- `tests/test_nautilus_sidecar_actor.py` — 改为 custom data publisher tests。
- `tests/test_nautilus_native_order.py` — 覆盖拆分后的 order planning functions。
- `docs/NAUTILUS_BRIDGE_BOUNDARY.md`、`docs/IMPLEMENTATION_SUMMARY.md`、`docs/PROJECT_ARCHITECTURE_VISUAL.md`、`docs/PRD.md` — 更新为 LiveNode + no shared sidecar + no reverse registry。

---

### Task 1: 写硬边界失败测试，锁死所有要删除的情况

**Files:**
- Modify: `tests/test_nautilus_platform_boundary.py`
- Test: `tests/test_nautilus_platform_boundary.py`

**Interfaces:**
- Consumes: 当前 source tree。
- Produces: 以下测试函数，后续任务必须让它们通过：
  - `test_default_runtime_uses_livenode_builder_not_legacy_trading_node() -> None`
  - `test_default_runtime_has_no_dynamic_runtime_class_factories() -> None`
  - `test_default_runtime_has_no_shared_external_sidecar_store() -> None`
  - `test_market_catalog_has_no_reverse_instrument_truth_source() -> None`
  - `test_default_runtime_has_no_asyncio_actor_scheduling_fallbacks() -> None`
  - `test_large_nautilus_runtime_functions_stay_under_limit() -> None`

- [ ] **Step 1: Write failing boundary tests**

Append this exact code to `tests/test_nautilus_platform_boundary.py`:

```python

def test_default_runtime_uses_livenode_builder_not_legacy_trading_node() -> None:
    forbidden = (
        "nautilus_trader.live.node",
        "TradingNodeConfig",
        "TradingNode(",
        "TradingNode =",
    )
    scanned_paths = (
        Path("src/polysignal_lab/nautilus_runtime/node.py"),
        Path("src/polysignal_lab/nautilus_runtime/trading_node.py"),
        Path("src/polysignal_lab/nautilus_runtime/live_node.py"),
    )
    findings: list[str] = []
    for path in scanned_paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []


def test_default_runtime_has_no_dynamic_runtime_class_factories() -> None:
    forbidden = (
        "new_class(",
        "runtime_native_strategy_type",
        "runtime_sidecar_actor_type",
        "runtime_market_rotation_actor_type",
    )
    scanned_paths = (
        Path("src/polysignal_lab/nautilus_runtime/native_strategy.py"),
        Path("src/polysignal_lab/nautilus_runtime/sidecar_data.py"),
        Path("src/polysignal_lab/nautilus_runtime/market_rotation.py"),
        Path("src/polysignal_lab/nautilus_runtime/node.py"),
    )
    findings: list[str] = []
    for path in scanned_paths:
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []


def test_default_runtime_has_no_shared_external_sidecar_store() -> None:
    forbidden_paths = (
        Path("src/polysignal_lab/nautilus_bridge/external_data.py"),
    )
    forbidden_tokens = (
        "ExternalDataSidecar",
        "update_spot(",
        "update_price_to_beat(",
        "self.sidecar",
    )
    scanned_roots = (
        Path("src/polysignal_lab/nautilus_runtime"),
        Path("src/polysignal_lab/nautilus_bridge"),
    )
    path_findings = [str(path) for path in forbidden_paths if path.exists()]
    token_findings: list[str] = []
    for root in scanned_roots:
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            token_findings.extend(f"{path}:{token}" for token in forbidden_tokens if token in text)

    assert path_findings == []
    assert token_findings == []


def test_market_catalog_has_no_reverse_instrument_truth_source() -> None:
    forbidden = (
        "_by_instrument",
        "by_instrument(",
        "condition_id_for_instrument(",
        "token_id_for_instrument(",
    )
    scanned_paths = (
        Path("src/polysignal_lab/nautilus_bridge/market_registry.py"),
        Path("src/polysignal_lab/nautilus_bridge/market_catalog.py"),
    )
    findings: list[str] = []
    for path in scanned_paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []


def test_default_runtime_has_no_asyncio_actor_scheduling_fallbacks() -> None:
    forbidden_by_file = {
        Path("src/polysignal_lab/nautilus_runtime/market_rotation.py"): (
            "asyncio.create_task(",
            "asyncio.sleep(",
            "asyncio.new_event_loop(",
            "asyncio.run(",
            "asyncio.to_thread(",
        ),
        Path("src/polysignal_lab/nautilus_runtime/sidecar_data.py"): (
            "asyncio.create_task(",
            "asyncio.sleep(",
            "asyncio.new_event_loop(",
            "asyncio.run(",
            "asyncio.to_thread(",
        ),
    }
    findings: list[str] = []
    for path, forbidden in forbidden_by_file.items():
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []


def test_large_nautilus_runtime_functions_stay_under_limit() -> None:
    import ast

    roots = (
        Path("src/polysignal_lab/nautilus_runtime"),
        Path("src/polysignal_lab/nautilus_bridge"),
    )
    findings: list[str] = []
    for root in roots:
        for path in root.rglob("*.py"):
            if path.name == "__init__.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.end_lineno is None:
                        continue
                    line_count = node.end_lineno - node.lineno + 1
                    if line_count > 45:
                        findings.append(f"{path}:{node.lineno}-{node.end_lineno}:{node.name}:{line_count}")

    assert findings == []
```

- [ ] **Step 2: Run boundary tests to verify they fail**

Run:

```bash
uv run python -m pytest tests/test_nautilus_platform_boundary.py -q
```

Expected: FAIL. The failure list must include legacy `TradingNode`, `new_class`, `ExternalDataSidecar`, `_by_instrument`, `asyncio.create_task` or large functions over 45 lines.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_nautilus_platform_boundary.py
git commit -m "test: lock Nautilus runtime wheel removal boundaries"
```

---

### Task 2: Cut over default runtime construction to `LiveNode.builder(...)`

**Files:**
- Create: `src/polysignal_lab/nautilus_runtime/live_node.py`
- Modify: `src/polysignal_lab/nautilus_runtime/node.py:80-290`
- Modify: `src/polysignal_lab/nautilus_runtime/trading_node.py:1-127`
- Modify: `tests/test_nautilus_node.py:38-126`
- Test: `tests/test_nautilus_node.py`

**Interfaces:**
- Consumes: `Settings`, `Market`, `PAPER_EXEC_CLIENT_ID`, `POLYMARKET_CLIENT_ID`, `assert_no_live_polymarket_execution(config: object) -> None`.
- Produces:
  - `build_paper_live_node(settings: Settings | None, *, instrument_config: object) -> object`
  - `build_polymarket_data_client_config(settings: Settings, *, instrument_config: object) -> object`
  - `build_sandbox_exec_client_config(settings: Settings) -> object`
  - `_create_configured_live_node(settings: Settings, configured_markets: Sequence[Market]) -> tuple[_TradingNodeLike, object]`

- [ ] **Step 1: Write failing LiveNode builder tests**

Replace `_patch_nautilus_placeholders` in `tests/test_nautilus_node.py` with this exact helper:

```python
def _patch_nautilus_placeholders(monkeypatch):
    """Monkeypatch LiveNode builder placeholders so tests run without Nautilus."""

    class FakeLiveNode:
        @classmethod
        def builder(cls, trader_id_text, trader_id, environment):
            return FakeBuilder(trader_id_text, trader_id, environment)

    class FakeBuilder:
        def __init__(self, trader_id_text, trader_id, environment):
            self.trader_id_text = trader_id_text
            self.trader_id = trader_id
            self.environment = environment
            self.data_engine_config = None
            self.exec_engine_config = None
            self.cache_config = None
            self.data_clients = []
            self.exec_clients = []

        def with_data_engine_config(self, config):
            self.data_engine_config = config
            return self

        def with_exec_engine_config(self, config):
            self.exec_engine_config = config
            return self

        def with_cache_config(self, config):
            self.cache_config = config
            return self

        def add_data_client(self, name, factory, config):
            self.data_clients.append((name, factory, config))
            return self

        def add_exec_client(self, name, factory, config):
            self.exec_clients.append((name, factory, config))
            return self

        def build(self):
            return FakeBuiltNode(self)

    class FakeBuiltNode:
        def __init__(self, builder):
            self.builder = builder
            self.trader = SimpleNamespace(strategies=[], actors=[])
            self.trader.add_strategy = self.trader.strategies.append
            self.trader.add_actor = self.trader.actors.append
            self.built = False

        def build(self):
            self.built = True

    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node.LiveNode", FakeLiveNode)
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.PolymarketInstrumentProviderConfig",
        lambda *, load_ids: SimpleNamespace(load_ids=load_ids),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.live_node.LiveNode",
        FakeLiveNode,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.live_node.TraderId",
        lambda value: f"TraderId:{value}",
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.live_node.Environment",
        SimpleNamespace(SANDBOX="SANDBOX"),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.live_node.PolymarketLiveDataClientFactory",
        object(),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.live_node.SandboxLiveExecClientFactory",
        object(),
    )
    return FakeLiveNode
```

Add this test near `test_build_trading_node_returns_nautilus_runtime_components`:

```python
def test_build_trading_node_uses_livenode_builder(monkeypatch) -> None:
    _patch_nautilus_placeholders(monkeypatch)

    runtime = build_trading_node(condition_ids=("condition-btc-5m",))
    node = runtime["node"]
    builder = node.builder

    assert builder.trader_id_text == "POLYSIGNAL-001"
    assert builder.environment == "SANDBOX"
    assert builder.data_clients[0][0] == "POLYMARKET"
    assert builder.exec_clients[0][0] == PAPER_EXEC_CLIENT_ID
    assert builder.exec_clients[0][0] != "POLYMARKET"
    assert node.built is True
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run python -m pytest tests/test_nautilus_node.py::test_build_trading_node_uses_livenode_builder -q
```

Expected: FAIL with an attribute or import error showing the current code has no `LiveNode` builder path.

- [ ] **Step 3: Create `src/polysignal_lab/nautilus_runtime/live_node.py`**

Create this file:

```python
from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Protocol, cast

from polysignal_lab.config import Settings, load_settings
from polysignal_lab.nautilus_runtime.trading_node import (
    PAPER_EXEC_CLIENT_ID,
    POLYMARKET_CLIENT_ID,
    assert_no_live_polymarket_execution,
)

LiveNode: object | None = None
TraderId: Callable[[str], object] | None = None
Environment: object | None = None
PolymarketLiveDataClientFactory: object | None = None
SandboxLiveExecClientFactory: object | None = None


class _Builder(Protocol):
    def with_data_engine_config(self, config: object) -> "_Builder": ...
    def with_exec_engine_config(self, config: object) -> "_Builder": ...
    def with_cache_config(self, config: object) -> "_Builder": ...
    def add_data_client(self, name: str | None, factory: object, config: object) -> "_Builder": ...
    def add_exec_client(self, name: str | None, factory: object, config: object) -> "_Builder": ...
    def build(self) -> object: ...


def build_paper_live_node(
    settings: Settings | None = None,
    *,
    instrument_config: object,
) -> object:
    if settings is None:
        settings = load_settings()
    _ensure_live_imports()
    live_node = _required(LiveNode, "LiveNode")
    trader_id_cls = cast(Callable[[str], object], _required(TraderId, "TraderId"))
    environment = _required(Environment, "Environment")
    trader_id = trader_id_cls("POLYSIGNAL-001")
    builder_factory = cast(object, live_node)
    builder = cast(
        _Builder,
        getattr(builder_factory, "builder")(
            "POLYSIGNAL-001",
            trader_id,
            getattr(environment, "SANDBOX"),
        ),
    )
    data_config = build_polymarket_data_client_config(settings, instrument_config=instrument_config)
    exec_config = build_sandbox_exec_client_config(settings)
    assert_no_live_polymarket_execution({"exec_clients": {PAPER_EXEC_CLIENT_ID: exec_config}})
    node = (
        builder.with_cache_config(build_cache_config())
        .with_data_engine_config(build_data_engine_config())
        .with_exec_engine_config(build_exec_engine_config())
        .add_data_client(
            POLYMARKET_CLIENT_ID,
            _required(PolymarketLiveDataClientFactory, "PolymarketLiveDataClientFactory"),
            data_config,
        )
        .add_exec_client(
            PAPER_EXEC_CLIENT_ID,
            _required(SandboxLiveExecClientFactory, "SandboxLiveExecClientFactory"),
            exec_config,
        )
        .build()
    )
    return node


def build_cache_config() -> object:
    cache_config = _import_callable("nautilus_trader.config", "CacheConfig")
    return cache_config(tick_capacity=100, bar_capacity=100)


def build_data_engine_config() -> object:
    live_data_engine_config = _import_callable("nautilus_trader.config", "LiveDataEngineConfig")
    return live_data_engine_config(
        validate_data_sequence=True,
        graceful_shutdown_on_exception=True,
    )


def build_exec_engine_config() -> object:
    live_exec_engine_config = _import_callable("nautilus_trader.config", "LiveExecEngineConfig")
    return live_exec_engine_config(
        reconciliation=False,
        graceful_shutdown_on_exception=True,
    )


def build_polymarket_data_client_config(
    settings: Settings,
    *,
    instrument_config: object,
) -> object:
    polymarket_data_config = _import_callable(
        "nautilus_trader.adapters.polymarket",
        "PolymarketDataClientConfig",
    )
    nautilus_runtime = settings.runtime.nautilus
    return polymarket_data_config(
        instrument_config=instrument_config,
        ws_max_subscriptions_per_connection=nautilus_runtime.polymarket_data.ws_max_subscriptions_per_connection,
        update_instruments_interval_mins=1,
        subscribe_new_markets=nautilus_runtime.market_rotation.allow_adapter_new_market_events,
        auto_load_missing_instruments=True,
        auto_load_debounce_ms=100,
        auto_load_max_retries=12,
    )


def build_sandbox_exec_client_config(settings: Settings) -> object:
    sandbox_exec_config = _import_callable(
        "nautilus_trader.adapters.sandbox.config",
        "SandboxExecutionClientConfig",
    )
    routing_config = _import_callable("nautilus_trader.config", "RoutingConfig")
    return sandbox_exec_config(
        venue=POLYMARKET_CLIENT_ID,
        starting_balances=[f"{float(settings.paper_trading.starting_balance_usdc)} USDC"],
        base_currency="USDC",
        oms_type="NETTING",
        account_type="CASH",
        book_type=settings.runtime.nautilus.sandbox_book_type,
        bar_execution=False,
        trade_execution=True,
        support_gtd_orders=True,
        support_contingent_orders=False,
        use_reduce_only=False,
        routing=routing_config(venues=frozenset({POLYMARKET_CLIENT_ID})),
    )


def _ensure_live_imports() -> None:
    global LiveNode, TraderId, Environment, PolymarketLiveDataClientFactory, SandboxLiveExecClientFactory
    if LiveNode is not None:
        return
    live_mod = importlib.import_module("nautilus_trader.live")
    common_mod = importlib.import_module("nautilus_trader.common")
    identifiers_mod = importlib.import_module("nautilus_trader.model.identifiers")
    polymarket_mod = importlib.import_module("nautilus_trader.adapters.polymarket")
    sandbox_factory_mod = importlib.import_module("nautilus_trader.adapters.sandbox.factory")
    LiveNode = getattr(live_mod, "LiveNode")
    Environment = getattr(common_mod, "Environment")
    TraderId = cast(Callable[[str], object], getattr(identifiers_mod, "TraderId"))
    PolymarketLiveDataClientFactory = getattr(polymarket_mod, "PolymarketLiveDataClientFactory")
    SandboxLiveExecClientFactory = getattr(sandbox_factory_mod, "SandboxLiveExecClientFactory")


def _import_callable(module_name: str, attr_name: str) -> Callable[..., object]:
    module = importlib.import_module(module_name)
    return cast(Callable[..., object], getattr(module, attr_name))


def _required(value: object | None, name: str) -> object:
    if value is None:
        raise RuntimeError(f"Nautilus {name} is unavailable")
    return value
```

- [ ] **Step 4: Update `node.py` to call LiveNode builder**

Replace `_create_configured_trading_node` in `src/polysignal_lab/nautilus_runtime/node.py` with:

```python
def _create_configured_live_node(
    settings: Settings,
    configured_markets: Sequence[Market],
) -> tuple[_TradingNodeLike, object]:
    _ensure_nautilus_imports()
    if PolymarketInstrumentProviderConfig is None:
        raise RuntimeError("Nautilus PolymarketInstrumentProviderConfig is unavailable")
    instrument_config = PolymarketInstrumentProviderConfig(
        load_ids=_instrument_load_ids(configured_markets),
    )
    from polysignal_lab.nautilus_runtime.live_node import build_paper_live_node

    node = build_paper_live_node(settings, instrument_config=instrument_config)
    return cast(_TradingNodeLike, node), instrument_config
```

Replace the call in `build_trading_node`:

```python
node, config = _create_configured_live_node(settings, configured_markets)
```

Remove `_FactoryRegistrar`, `_PaperConfigBuilder`, `TradingNode`, `build_paper_trading_node_config`, and `register_paper_factories` placeholders from `node.py`. Keep `PolymarketInstrumentProviderConfig`, `NautilusActor`, `NautilusActorConfig`, `NautilusStrategy`, and `NautilusStrategyConfig` until Task 3 replaces dynamic class factories.

- [ ] **Step 5: Shrink `trading_node.py` to constants and safety assertion**

Replace `src/polysignal_lab/nautilus_runtime/trading_node.py` with:

```python
from __future__ import annotations

from collections.abc import Mapping

PAPER_EXEC_CLIENT_ID = "POLYSIGNAL_PM_PAPER"
POLYMARKET_CLIENT_ID = "POLYMARKET"


def assert_no_live_polymarket_execution(config: object) -> None:
    exec_clients = getattr(config, "exec_clients", None)
    if exec_clients is None and isinstance(config, Mapping):
        exec_clients = config.get("exec_clients", {})
    if isinstance(exec_clients, Mapping) and POLYMARKET_CLIENT_ID in exec_clients:
        raise RuntimeError("default paper runtime refuses live Polymarket execution")
```

- [ ] **Step 6: Run node tests**

Run:

```bash
uv run python -m pytest tests/test_nautilus_node.py -q
```

Expected: PASS for updated tests. If legacy monkeypatch tests fail, update their monkeypatch targets from `TradingNode`/`register_paper_factories` to `LiveNode`/`build_paper_live_node` with the helper from Step 1.

- [ ] **Step 7: Run boundary test for LiveNode**

Run:

```bash
uv run python -m pytest tests/test_nautilus_platform_boundary.py::test_default_runtime_uses_livenode_builder_not_legacy_trading_node -q
```

Expected: PASS.

- [ ] **Step 8: Commit LiveNode cutover**

```bash
git add src/polysignal_lab/nautilus_runtime/live_node.py src/polysignal_lab/nautilus_runtime/node.py src/polysignal_lab/nautilus_runtime/trading_node.py tests/test_nautilus_node.py tests/test_nautilus_platform_boundary.py
git commit -m "refactor: build Nautilus runtime with LiveNode builder"
```

---

### Task 3: Replace dynamic `new_class` factories with static Nautilus runtime classes

**Files:**
- Create: `src/polysignal_lab/nautilus_runtime/runtime_classes.py`
- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py:1-220`
- Modify: `src/polysignal_lab/nautilus_runtime/market_rotation.py:1-437`
- Modify: `src/polysignal_lab/nautilus_runtime/node.py:222-544`
- Test: `tests/test_nautilus_platform_boundary.py`
- Test: `tests/test_nautilus_node.py`

**Interfaces:**
- Consumes: `PolySignalNativeStrategy`, `MarketRotationActor`, Nautilus `Strategy`, Nautilus `Actor`, `StrategyConfig`, `ActorConfig`.
- Produces:
  - `NautilusPolySignalNativeStrategy`
  - `NautilusMarketRotationActor`
  - `_load_runtime_classes() -> tuple[type[object], type[object]]`

- [ ] **Step 1: Write failing runtime class test**

Add this test to `tests/test_nautilus_node.py`:

```python
def test_build_trading_node_uses_static_runtime_classes(monkeypatch) -> None:
    _patch_nautilus_placeholders(monkeypatch)
    captured: dict[str, object] = {}

    class FakeStaticStrategy:
        strategy_name = "vwap_momentum"

        def __init__(self, **kwargs):
            captured["strategy_kwargs"] = kwargs

    class FakeStaticActor:
        def __init__(self, **kwargs):
            captured["actor_kwargs"] = kwargs

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._load_runtime_classes",
        lambda: (FakeStaticStrategy, FakeStaticActor),
    )

    runtime = build_trading_node(condition_ids=("condition-btc-5m",))

    assert runtime["strategies"][0].strategy_name == "vwap_momentum"
    assert runtime["market_rotation_actor"] is runtime["node"].trader.actors[0]
    assert "registry" in captured["strategy_kwargs"]
    assert "registry" in captured["actor_kwargs"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run python -m pytest tests/test_nautilus_node.py::test_build_trading_node_uses_static_runtime_classes -q
```

Expected: FAIL because `_load_runtime_classes` is not defined and current code calls dynamic `runtime_native_strategy_type` / `runtime_market_rotation_actor_type`.

- [ ] **Step 3: Create static runtime classes**

Create `src/polysignal_lab/nautilus_runtime/runtime_classes.py`:

```python
from __future__ import annotations

from typing import Callable, cast

from nautilus_trader.common.actor import Actor
from nautilus_trader.config import ActorConfig, StrategyConfig
from nautilus_trader.trading.strategy import Strategy

from polysignal_lab.config import Settings
from polysignal_lab.data.anchor_price_service import AnchorPriceStore
from polysignal_lab.domain.market import Market
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.market_rotation import MarketRotationActor, _MarketUniverse, _Health
from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy, _Assembler, _Observability
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor
from polysignal_lab.alpha.types import AlphaCore


class NautilusPolySignalNativeStrategy(Strategy, PolySignalNativeStrategy):
    def __init__(
        self,
        *,
        core: AlphaCore,
        assembler: _Assembler | None,
        condition_ids: tuple[str, ...],
        strategy_name: str,
        policy: DecisionPolicyActor | None = None,
        fixed_stake_usdc: float = 10.0,
        data_names: tuple[str, ...] = (),
        book_type: str = "L2_MBP",
        instrument_id_resolver: Callable[[str], object] | None = None,
        catalog: MarketCatalog,
        observability: _Observability | None = None,
        exit_model: object | None = None,
        progress_callback: Callable[[str], None] | None = None,
        unsubscribe_exited: bool = True,
        l1_book_snapshot_interval_ms: int = 250,
    ) -> None:
        Strategy.__init__(self, config=StrategyConfig())
        PolySignalNativeStrategy.__init__(
            self,
            core=core,
            assembler=assembler,
            condition_ids=condition_ids,
            strategy_name=strategy_name,
            policy=policy,
            fixed_stake_usdc=fixed_stake_usdc,
            data_names=data_names,
            book_type=book_type,
            instrument_id_resolver=instrument_id_resolver,
            catalog=catalog,
            observability=observability,
            exit_model=exit_model,
            progress_callback=progress_callback,
            unsubscribe_exited=unsubscribe_exited,
            l1_book_snapshot_interval_ms=l1_book_snapshot_interval_ms,
        )


class NautilusMarketRotationActor(Actor, MarketRotationActor):
    def __init__(
        self,
        *,
        settings: Settings,
        startup_markets: tuple[Market, ...],
        market_universe: _MarketUniverse,
        catalog: MarketCatalog,
        anchor_store: AnchorPriceStore | None = None,
        health: _Health | None = None,
    ) -> None:
        Actor.__init__(self, config=ActorConfig())
        MarketRotationActor.__init__(
            self,
            settings=settings,
            startup_markets=startup_markets,
            market_universe=market_universe,
            catalog=catalog,
            anchor_store=anchor_store,
            health=health,
        )


__all__ = (
    "NautilusMarketRotationActor",
    "NautilusPolySignalNativeStrategy",
)
```

This file imports Nautilus at module import time by design. Only `node._load_runtime_classes()` may import it.

- [ ] **Step 4: Add lazy runtime class loader to `node.py`**

Add this function to `src/polysignal_lab/nautilus_runtime/node.py`:

```python
def _load_runtime_classes() -> tuple[type[object], type[object]]:
    from polysignal_lab.nautilus_runtime.runtime_classes import (
        NautilusMarketRotationActor,
        NautilusPolySignalNativeStrategy,
    )

    return NautilusPolySignalNativeStrategy, NautilusMarketRotationActor
```

Update `_build_market_rotation_actor` to use the loaded actor class:

```python
def _build_market_rotation_actor(
    *,
    settings: Settings,
    startup_markets: Sequence[Market],
    market_universe: object,
    catalog: MarketCatalog,
    store: AnchorPriceStore | None,
    health: object | None,
) -> object:
    _strategy_cls, actor_cls = _load_runtime_classes()
    return actor_cls(
        settings=settings,
        startup_markets=tuple(startup_markets),
        market_universe=cast(_MarketUniverse, market_universe),
        catalog=catalog,
        anchor_store=store,
        health=cast(_Health | None, health),
    )
```

Update `_build_native_strategies` to use the loaded strategy class:

```python
strategy_type, _actor_cls = _load_runtime_classes()
```

Pass `catalog=catalog` instead of `registry=registry` and remove `sidecar=sidecar`.

- [ ] **Step 5: Delete dynamic factory functions**

Remove these definitions entirely:

```python
runtime_native_strategy_type
runtime_market_rotation_actor_type
runtime_sidecar_actor_type
```

Remove these imports where present:

```python
from types import new_class
```

- [ ] **Step 6: Run runtime class tests**

Run:

```bash
uv run python -m pytest tests/test_nautilus_node.py::test_build_trading_node_uses_static_runtime_classes tests/test_nautilus_platform_boundary.py::test_default_runtime_has_no_dynamic_runtime_class_factories -q
```

Expected: PASS.

- [ ] **Step 7: Commit static runtime classes**

```bash
git add src/polysignal_lab/nautilus_runtime/runtime_classes.py src/polysignal_lab/nautilus_runtime/native_strategy.py src/polysignal_lab/nautilus_runtime/market_rotation.py src/polysignal_lab/nautilus_runtime/node.py tests/test_nautilus_node.py tests/test_nautilus_platform_boundary.py
git commit -m "refactor: replace dynamic Nautilus runtime class factories"
```

---

### Task 4: Delete shared `ExternalDataSidecar`; use strategy-local custom data state

**Files:**
- Create: `src/polysignal_lab/nautilus_runtime/custom_data_state.py`
- Remove: `src/polysignal_lab/nautilus_bridge/external_data.py`
- Modify: `src/polysignal_lab/nautilus_runtime/sidecar_data.py:1-131`
- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py:226-419`
- Modify: `src/polysignal_lab/nautilus_bridge/market_view_assembler.py:1-93`
- Modify: `tests/test_nautilus_sidecar_actor.py`
- Modify: `tests/test_nautilus_market_view_assembler.py`
- Test: `tests/test_nautilus_sidecar_actor.py`
- Test: `tests/test_nautilus_market_view_assembler.py`

**Interfaces:**
- Consumes: `PolySignalSpotData`, `PolySignalPriceToBeatData`, `PolySignalMarketMetaData`, `PolySignalMarketUniverseData`.
- Produces:
  - `CustomDataSnapshotProvider` protocol with `spot_for(asset: str) -> SpotView | None` and `ptb_for(condition_id: str) -> PriceToBeatView | None`.
  - `StrategyCustomDataState.apply(data: object) -> CustomDataApplyResult`.
  - `CustomDataPublisher.publish_spot(*, asset: str, symbol: str, price: float, source: str, freshness_ms: int | None, ts_event: int, ts_init: int) -> None`.
  - `CustomDataPublisher.publish_price_to_beat(*, condition_id: str, value: float, source: str, verified: bool, from_anchor_service: bool, anchor_source: str | None, anchor_lag_ms: int | None, ts_event: int, ts_init: int) -> None`.
  - `CustomDataPublisher.publish_market_metadata(meta: PolySignalMarketMetaData) -> None`.
  - `CustomDataPublisher.publish_market_universe(data: PolySignalMarketUniverseData) -> None`.

- [ ] **Step 1: Rewrite sidecar tests to prove publisher has no local state**

Replace `tests/test_nautilus_sidecar_actor.py` imports and first two tests with:

```python
from __future__ import annotations

from types import SimpleNamespace

from polysignal_lab.nautilus_runtime.market_data import (
    PolySignalMarketMetaData,
    PolySignalPriceToBeatData,
    PolySignalSpotData,
)
from polysignal_lab.nautilus_runtime.sidecar_data import CustomDataPublisher


class FakePublisher:
    def __init__(self) -> None:
        self.published: list[object] = []

    def publish_data(self, data_type: object, data: object) -> None:
        self.published.append(data)


def test_custom_data_publisher_publishes_spot_without_local_store() -> None:
    publisher = FakePublisher()
    actor = CustomDataPublisher(publisher=publisher)

    actor.publish_spot(
        asset="BTC",
        symbol="BTCUSD",
        price=100001.0,
        source="polymarket_rtds",
        freshness_ms=9,
        ts_event=1,
        ts_init=2,
    )

    assert isinstance(publisher.published[-1], PolySignalSpotData)
    assert not hasattr(actor, "sidecar")
    assert not hasattr(actor, "registry")


def test_custom_data_publisher_publishes_price_to_beat_without_local_store() -> None:
    publisher = FakePublisher()
    actor = CustomDataPublisher(publisher=publisher)

    actor.publish_price_to_beat(
        condition_id="condition-1",
        value=100000.0,
        source="anchor",
        verified=True,
        from_anchor_service=True,
        anchor_source="chainlink",
        anchor_lag_ms=15,
        ts_event=1,
        ts_init=2,
    )

    assert isinstance(publisher.published[-1], PolySignalPriceToBeatData)
    assert not hasattr(actor, "sidecar")
    assert not hasattr(actor, "registry")
```

Replace metadata test with:

```python
def test_custom_data_publisher_publishes_market_metadata_without_registering_state() -> None:
    publisher = FakePublisher()
    actor = CustomDataPublisher(publisher=publisher)

    actor.publish_market_metadata(
        PolySignalMarketMetaData(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts_ns=0,
            end_ts_ns=0,
            up_token_id="up-token",
            down_token_id="down-token",
            ts_event=1,
            ts_init=2,
        )
    )

    assert isinstance(publisher.published[-1], PolySignalMarketMetaData)
    assert not hasattr(actor, "registry")
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run python -m pytest tests/test_nautilus_sidecar_actor.py -q
```

Expected: FAIL because `CustomDataPublisher` does not exist and `SidecarDataActor` still owns sidecar/registry state.

- [ ] **Step 3: Create strategy-local custom data state**

Create `src/polysignal_lab/nautilus_runtime/custom_data_state.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from polysignal_lab.alpha.types import SpotView
from polysignal_lab.nautilus_runtime.market_data import PolySignalPriceToBeatData, PolySignalSpotData


@dataclass(frozen=True, slots=True)
class PriceToBeatView:
    condition_id: str
    value: float
    source: str
    verified: bool
    from_anchor_service: bool
    anchor_source: str | None
    anchor_lag_ms: int | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CustomDataApplyResult:
    spot_asset: str | None = None
    price_to_beat_condition_id: str | None = None


class CustomDataSnapshotProvider(Protocol):
    def spot_for(self, asset: str) -> SpotView | None: ...
    def ptb_for(self, condition_id: str) -> PriceToBeatView | None: ...


class StrategyCustomDataState:
    """Strategy-local derived state from Nautilus CustomData messages."""

    def __init__(self) -> None:
        self._spots: dict[str, SpotView] = {}
        self._ptb: dict[str, PriceToBeatView] = {}

    def apply(self, data: object) -> CustomDataApplyResult:
        if isinstance(data, PolySignalSpotData):
            spot = SpotView(
                asset=data.asset,
                symbol=data.symbol,
                price=data.price,
                source=data.source,
                freshness_ms=data.freshness_ms,
            )
            self._spots[spot.asset.upper()] = spot
            return CustomDataApplyResult(spot_asset=spot.asset.upper())
        if isinstance(data, PolySignalPriceToBeatData):
            self._ptb[data.condition_id] = PriceToBeatView(
                condition_id=data.condition_id,
                value=data.value,
                source=data.source,
                verified=data.verified,
                from_anchor_service=data.from_anchor_service,
                anchor_source=data.anchor_source,
                anchor_lag_ms=data.anchor_lag_ms,
                updated_at=datetime.now(UTC),
            )
            return CustomDataApplyResult(price_to_beat_condition_id=data.condition_id)
        return CustomDataApplyResult()

    def spot_for(self, asset: str) -> SpotView | None:
        return self._spots.get(asset.upper())

    def ptb_for(self, condition_id: str) -> PriceToBeatView | None:
        return self._ptb.get(condition_id)
```

- [ ] **Step 4: Replace `SidecarDataActor` with stateless `CustomDataPublisher`**

In `src/polysignal_lab/nautilus_runtime/sidecar_data.py`, replace `SidecarDataActor` with:

```python
class CustomDataPublisher:
    def __init__(self, *, publisher: _Publisher) -> None:
        self.publisher: _Publisher = publisher

    def publish_spot(
        self,
        *,
        asset: str,
        symbol: str,
        price: float,
        source: str,
        freshness_ms: int | None,
        ts_event: int,
        ts_init: int,
    ) -> None:
        data = PolySignalSpotData(
            asset=asset,
            symbol=symbol,
            price=price,
            source=source,
            freshness_ms=freshness_ms,
            ts_event=ts_event,
            ts_init=ts_init,
        )
        self.publisher.publish_data(_data_type(PolySignalSpotData), data)

    def publish_price_to_beat(
        self,
        *,
        condition_id: str,
        value: float,
        source: str,
        verified: bool,
        from_anchor_service: bool,
        anchor_source: str | None,
        anchor_lag_ms: int | None,
        ts_event: int,
        ts_init: int,
    ) -> None:
        data = PolySignalPriceToBeatData(
            condition_id=condition_id,
            value=value,
            source=source,
            verified=verified,
            from_anchor_service=from_anchor_service,
            anchor_source=anchor_source,
            anchor_lag_ms=anchor_lag_ms,
            ts_event=ts_event,
            ts_init=ts_init,
        )
        self.publisher.publish_data(_data_type(PolySignalPriceToBeatData), data)

    def publish_market_metadata(self, meta: PolySignalMarketMetaData) -> None:
        self.publisher.publish_data(_data_type(PolySignalMarketMetaData), meta)

    def publish_market_universe(self, data: PolySignalMarketUniverseData) -> None:
        self.publisher.publish_data(_data_type(PolySignalMarketUniverseData), data)
```

Remove `PolySignalRuntimeSidecarActor`, `runtime_sidecar_actor_type`, `_pair_from_metadata`, and every import of `ExternalDataSidecar` from this file.

- [ ] **Step 5: Update `MarketViewAssembler` dependency**

Replace imports and constructor in `src/polysignal_lab/nautilus_bridge/market_view_assembler.py`:

```python
from polysignal_lab.nautilus_runtime.custom_data_state import CustomDataSnapshotProvider


@final
class MarketViewAssembler:
    def __init__(
        self,
        *,
        catalog: MarketCatalog,
        books: BookDataProvider,
        custom_data: CustomDataSnapshotProvider,
    ):
        self.catalog: MarketCatalog = catalog
        self.books: BookDataProvider = books
        self.custom_data: CustomDataSnapshotProvider = custom_data
```

Inside `build`, replace:

```python
pair = self.registry.by_condition(condition_id)
spot = self.sidecar.spot_for(pair.asset)
ptb = self.sidecar.ptb_for(pair.condition_id)
```

with:

```python
pair = self.catalog.by_condition(condition_id)
spot = self.custom_data.spot_for(pair.asset)
ptb = self.custom_data.ptb_for(pair.condition_id)
```

- [ ] **Step 6: Update `PolySignalNativeStrategy` to own custom data state**

In `src/polysignal_lab/nautilus_runtime/native_strategy.py`, add:

```python
from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState
```

In `__init__`, remove `sidecar` parameter and add:

```python
self.custom_data: StrategyCustomDataState = StrategyCustomDataState()
```

In `on_data`, replace the `PolySignalSpotData` and `PolySignalPriceToBeatData` branches with:

```python
if isinstance(data, (PolySignalSpotData, PolySignalPriceToBeatData)):
    result = self.custom_data.apply(data)
    if result.spot_asset is not None:
        for candidate in self._asset_condition_ids.get(result.spot_asset, ()): 
            self.evaluate_condition(candidate)
        return
    if result.price_to_beat_condition_id is not None:
        self._retry_market_instrument_requests(
            (result.price_to_beat_condition_id,), retry_after=timedelta(seconds=10)
        )
        self.evaluate_condition(result.price_to_beat_condition_id)
        return
```

- [ ] **Step 7: Delete external sidecar file**

Remove:

```bash
git rm src/polysignal_lab/nautilus_bridge/external_data.py
```

- [ ] **Step 8: Run sidecar and assembler tests**

Run:

```bash
uv run python -m pytest tests/test_nautilus_sidecar_actor.py tests/test_nautilus_market_view_assembler.py -q
```

Expected: PASS after tests use `StrategyCustomDataState` and `CustomDataPublisher`.

- [ ] **Step 9: Run sidecar boundary test**

Run:

```bash
uv run python -m pytest tests/test_nautilus_platform_boundary.py::test_default_runtime_has_no_shared_external_sidecar_store -q
```

Expected: PASS.

- [ ] **Step 10: Commit sidecar deletion**

```bash
git add src/polysignal_lab/nautilus_runtime/custom_data_state.py src/polysignal_lab/nautilus_runtime/sidecar_data.py src/polysignal_lab/nautilus_runtime/native_strategy.py src/polysignal_lab/nautilus_bridge/market_view_assembler.py tests/test_nautilus_sidecar_actor.py tests/test_nautilus_market_view_assembler.py tests/test_nautilus_platform_boundary.py
git rm src/polysignal_lab/nautilus_bridge/external_data.py
git commit -m "refactor: remove shared Nautilus sidecar state"
```

---

### Task 5: Replace reverse instrument registry with business-only market catalog

**Files:**
- Create: `src/polysignal_lab/nautilus_bridge/market_catalog.py`
- Remove: `src/polysignal_lab/nautilus_bridge/market_registry.py`
- Modify: `src/polysignal_lab/nautilus_runtime/cache_market_data.py:1-70`
- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py:565-616,953-990`
- Modify: `src/polysignal_lab/nautilus_runtime/node.py:293-328,469-491`
- Rename Test: `tests/test_nautilus_market_registry.py` -> `tests/test_nautilus_market_catalog.py`

**Interfaces:**
- Consumes: `polymarket_instrument_id(condition_id: str, token_id: str) -> str`.
- Produces:
  - `MarketCatalog.register(pair: MarketPairMeta) -> None`
  - `MarketCatalog.by_condition(condition_id: str) -> MarketPairMeta | None`
  - `MarketCatalog.by_token(token_id: str) -> MarketPairMeta | None`
  - `MarketCatalog.token_meta(token_id: str) -> InstrumentTokenMeta | None`
  - `MarketCatalog.instrument_id_for_token(token_id: str) -> str | None`

- [ ] **Step 1: Rewrite registry tests as catalog tests**

Rename:

```bash
git mv tests/test_nautilus_market_registry.py tests/test_nautilus_market_catalog.py
```

Replace imports in the renamed file:

```python
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog, MarketPairMeta
```

Replace every `PolymarketMarketRegistry()` with:

```python
MarketCatalog()
```

Delete tests for `by_instrument` and `token_id_for_instrument`. Add this test:

```python
def test_market_catalog_derives_instrument_id_from_condition_and_token(monkeypatch) -> None:
    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m"))
    pair = MarketPairMeta.from_market(market)
    catalog = MarketCatalog()
    catalog.register(pair)

    monkeypatch.setattr(
        "polysignal_lab.nautilus_bridge.market_catalog.polymarket_instrument_id",
        lambda condition_id, token_id: f"{condition_id}-{token_id}.POLYMARKET",
    )

    assert catalog.instrument_id_for_token(pair.up.token_id) == f"{pair.condition_id}-{pair.up.token_id}.POLYMARKET"
    assert catalog.instrument_id_for_token("missing") is None
```

- [ ] **Step 2: Run catalog tests to verify failure**

Run:

```bash
uv run python -m pytest tests/test_nautilus_market_catalog.py -q
```

Expected: FAIL because `market_catalog.py` does not exist.

- [ ] **Step 3: Create `market_catalog.py`**

Create `src/polysignal_lab/nautilus_bridge/market_catalog.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market
from polysignal_lab.nautilus_runtime.instrument_mapping import polymarket_instrument_id


@dataclass(frozen=True, slots=True)
class InstrumentTokenMeta:
    token_id: str
    side: Side


@dataclass(frozen=True, slots=True)
class MarketPairMeta:
    market_id: str
    market_slug: str
    condition_id: str
    asset: str
    timeframe: str
    start_ts: datetime | None
    end_ts: datetime | None
    up: InstrumentTokenMeta
    down: InstrumentTokenMeta

    @classmethod
    def from_market(cls, market: Market) -> "MarketPairMeta":
        if len(market.outcome_tokens) != 2:
            raise ValueError("Only binary YES/NO markets are supported by the Nautilus bridge")
        up_token = market.token_for(Side.UP)
        down_token = market.token_for(Side.DOWN)
        return cls(
            market_id=market.market_id,
            market_slug=market.market_slug,
            condition_id=market.condition_id,
            asset=market.asset.upper(),
            timeframe=market.timeframe,
            start_ts=market.start_ts,
            end_ts=market.end_ts,
            up=InstrumentTokenMeta(token_id=up_token.token_id, side=Side.UP),
            down=InstrumentTokenMeta(token_id=down_token.token_id, side=Side.DOWN),
        )

    @classmethod
    def from_metadata(cls, meta: object) -> "MarketPairMeta":
        start_ts_ns = cast(int | float | None, getattr(meta, "start_ts_ns", None))
        end_ts_ns = cast(int | float | None, getattr(meta, "end_ts_ns", None))
        start_ts = datetime.fromtimestamp(start_ts_ns / 1e9, tz=UTC) if start_ts_ns is not None else None
        end_ts = datetime.fromtimestamp(end_ts_ns / 1e9, tz=UTC) if end_ts_ns is not None else None
        asset = cast(str, getattr(meta, "asset"))
        return cls(
            market_id=cast(str, getattr(meta, "market_id")),
            market_slug=cast(str, getattr(meta, "market_slug")),
            condition_id=cast(str, getattr(meta, "condition_id")),
            asset=asset.upper(),
            timeframe=cast(str, getattr(meta, "timeframe")),
            start_ts=start_ts,
            end_ts=end_ts,
            up=InstrumentTokenMeta(token_id=cast(str, getattr(meta, "up_token_id")), side=Side.UP),
            down=InstrumentTokenMeta(token_id=cast(str, getattr(meta, "down_token_id")), side=Side.DOWN),
        )


class MarketCatalog:
    def __init__(self) -> None:
        self._by_condition: dict[str, MarketPairMeta] = {}
        self._condition_by_token: dict[str, str] = {}

    def register(self, pair: MarketPairMeta) -> None:
        self._by_condition[pair.condition_id] = pair
        self._condition_by_token[pair.up.token_id] = pair.condition_id
        self._condition_by_token[pair.down.token_id] = pair.condition_id

    def by_condition(self, condition_id: str) -> MarketPairMeta | None:
        return self._by_condition.get(condition_id)

    def by_token(self, token_id: str) -> MarketPairMeta | None:
        condition_id = self._condition_by_token.get(token_id)
        if condition_id is None:
            return None
        return self._by_condition.get(condition_id)

    def token_meta(self, token_id: str) -> InstrumentTokenMeta | None:
        pair = self.by_token(token_id)
        if pair is None:
            return None
        if pair.up.token_id == token_id:
            return pair.up
        if pair.down.token_id == token_id:
            return pair.down
        return None

    def instrument_id_for_token(self, token_id: str) -> str | None:
        pair = self.by_token(token_id)
        if pair is None:
            return None
        return polymarket_instrument_id(pair.condition_id, token_id)
```

- [ ] **Step 4: Update cache market data provider**

In `src/polysignal_lab/nautilus_runtime/cache_market_data.py`, replace constructor and token lookup:

```python
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog


class NautilusCacheMarketDataProvider:
    """Read current market data from Nautilus Cache without owning book/trade state."""

    def __init__(self, cache: object, *, catalog: MarketCatalog) -> None:
        self._cache: object = cache
        self._catalog: MarketCatalog = catalog

    def book_for_token(self, token_id: str) -> SideBookView | None:
        instrument_id = self._catalog.instrument_id_for_token(token_id)
        if instrument_id is None:
            return None
        book = self._cache_order_book(instrument_id)
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
        instrument_id = self._catalog.instrument_id_for_token(token_id)
        if instrument_id is None:
            return ()
        getter = getattr(self._cache, "trade_ticks", None)
        if not callable(getter):
            return ()
        rows = cast(Callable[[object], object], getter)(instrument_id)
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
```

- [ ] **Step 5: Update node catalog wiring**

In `src/polysignal_lab/nautilus_runtime/node.py`, replace registry creation with catalog:

```python
def _create_market_projection_components(
    markets: Sequence[Market],
) -> tuple[MarketCatalog, MarketViewAssembler]:
    catalog = MarketCatalog()
    _register_markets(catalog, markets)
    custom_data = StrategyCustomDataState()
    assembler = MarketViewAssembler(
        catalog=catalog,
        books=_EmptyBookDataProvider(),
        custom_data=custom_data,
    )
    return catalog, assembler
```

For strategy construction, pass the same `custom_data` object owned by each strategy into its assembler. If one assembler is shared across strategies, it must use a provider owned by the strategy before evaluation:

```python
strategy.custom_data = StrategyCustomDataState()
strategy.assembler.custom_data = strategy.custom_data
```

- [ ] **Step 6: Update native strategy exit lookup without reverse instrument registry**

In `evaluate_exit_positions`, replace registry reverse lookup with view token comparison:

```python
def _token_id_from_view_instrument(self, view: MarketView, instrument_id: str) -> str | None:
    up_instrument = str(self._resolved_instrument(view.up.token_id))
    if instrument_id == up_instrument:
        return view.up.token_id
    down_instrument = str(self._resolved_instrument(view.down.token_id))
    if instrument_id == down_instrument:
        return view.down.token_id
    return None
```

Use it inside the loop:

```python
token_id = str(position.get("token_id") or "")
if not token_id and instrument_id:
    token_id = self._token_id_from_view_instrument(view, instrument_id) or ""
```

Delete calls to `condition_id_for_instrument` and `token_id_for_instrument`.

- [ ] **Step 7: Remove old registry file**

```bash
git rm src/polysignal_lab/nautilus_bridge/market_registry.py
```

Update these exact imports project-wide:

```python
from polysignal_lab.nautilus_bridge.market_registry import MarketPairMeta, PolymarketMarketRegistry
from polysignal_lab.nautilus_bridge.market_registry import PolymarketMarketRegistry
from polysignal_lab.nautilus_bridge.market_registry import (
    InstrumentTokenMeta,
    MarketPairMeta,
    PolymarketMarketRegistry,
)
```

to these exact imports:

```python
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog, MarketPairMeta
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
from polysignal_lab.nautilus_bridge.market_catalog import (
    InstrumentTokenMeta,
    MarketCatalog,
    MarketPairMeta,
)
```

Then replace every constructor call:

```python
PolymarketMarketRegistry()
```

with:

```python
MarketCatalog()
```

- [ ] **Step 8: Run catalog and cache tests**

Run:

```bash
uv run python -m pytest tests/test_nautilus_market_catalog.py tests/test_nautilus_cache_market_data.py tests/test_nautilus_market_view_assembler.py -q
```

Expected: PASS.

- [ ] **Step 9: Run reverse registry boundary test**

Run:

```bash
uv run python -m pytest tests/test_nautilus_platform_boundary.py::test_market_catalog_has_no_reverse_instrument_truth_source -q
```

Expected: PASS.

- [ ] **Step 10: Commit market catalog cutover**

```bash
git add src/polysignal_lab/nautilus_bridge/market_catalog.py src/polysignal_lab/nautilus_runtime/cache_market_data.py src/polysignal_lab/nautilus_runtime/native_strategy.py src/polysignal_lab/nautilus_runtime/node.py tests/test_nautilus_market_catalog.py tests/test_nautilus_cache_market_data.py tests/test_nautilus_market_view_assembler.py tests/test_nautilus_platform_boundary.py
git rm src/polysignal_lab/nautilus_bridge/market_registry.py
git commit -m "refactor: replace instrument registry with market catalog"
```

---

### Task 6: Remove bare `asyncio` actor scheduling fallbacks

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/market_rotation.py:1-348`
- Modify: `src/polysignal_lab/nautilus_runtime/sidecar_data.py:1-131`
- Modify: `tests/test_nautilus_sidecar_actor.py:116-176`
- Test: `tests/test_nautilus_platform_boundary.py`
- Test: `tests/test_nautilus_sidecar_actor.py`

**Interfaces:**
- Consumes: Nautilus actor `clock.set_timer(name, interval, callback)` and `clock.cancel_timer(name)`.
- Produces:
  - `MarketRotationActor.on_start() -> None` with mandatory actor clock timer path.
  - `MarketRotationActor._on_refresh_timer(_event: object = None) -> None` sync refresh path without `asyncio` module calls.
  - `MarketRotationActor._publish_price_to_beat_sync(market: Market) -> None`.

- [ ] **Step 1: Replace sidecar actor async test with timer test**

Remove tests that monkeypatch `asyncio.create_task`. Add this test to `tests/test_nautilus_sidecar_actor.py`:

```python
def test_market_rotation_actor_uses_clock_timer_for_startup(monkeypatch) -> None:
    from datetime import timedelta

    from polysignal_lab.config import Settings
    from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
    from polysignal_lab.nautilus_runtime.market_rotation import MarketRotationActor, REFRESH_TIMER_NAME

    timers: list[tuple[str, timedelta, object]] = []

    class FakeClock:
        def set_timer(self, name, interval, callback):
            timers.append((name, interval, callback))

        def cancel_timer(self, name):
            timers.append((f"cancel:{name}", timedelta(seconds=0), None))

    class FakeUniverse:
        async def refresh_once(self):
            return []

    settings = Settings()
    settings.runtime.nautilus.market_rotation.enabled = True
    actor = MarketRotationActor(
        settings=settings,
        startup_markets=(),
        market_universe=FakeUniverse(),
        catalog=MarketCatalog(),
    )
    actor.clock = FakeClock()
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.market_rotation.register_polysignal_data_types",
        lambda: None,
    )

    actor.on_start()

    assert timers[0][0] == REFRESH_TIMER_NAME
    assert callable(timers[0][2])
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run python -m pytest tests/test_nautilus_sidecar_actor.py::test_market_rotation_actor_uses_clock_timer_for_startup -q
```

Expected: FAIL while `MarketRotationActor` still requires old constructor parameters or uses sidecar actor patterns.

- [ ] **Step 3: Update `MarketRotationActor` constructor and publisher**

Replace constructor fields:

```python
self.catalog: MarketCatalog = catalog
self.publisher: CustomDataPublisher = CustomDataPublisher(publisher=self)
```

Remove:

```python
self.sidecar
self._refresh_task
self._rtds_task
```

- [ ] **Step 4: Make actor clock mandatory**

Replace timer setup in `on_start` with:

```python
if self.settings.runtime.nautilus.market_rotation.enabled:
    interval = max(int(self.settings.runtime.nautilus.market_rotation.interval_sec), 1)
    clock = getattr(self, "clock", None)
    set_timer = getattr(clock, "set_timer", None)
    if not callable(set_timer):
        raise RuntimeError("Nautilus actor clock is required for market rotation")
    _ = set_timer(
        REFRESH_TIMER_NAME,
        timedelta(seconds=interval),
        callback=self._on_refresh_timer,
    )
```

Replace `on_stop` with:

```python
def on_stop(self) -> None:
    self.rtds_feed.stop()
    clock = getattr(self, "clock", None)
    cancel_timer = getattr(clock, "cancel_timer", None)
    if callable(cancel_timer):
        _ = cancel_timer(REFRESH_TIMER_NAME)
```

- [ ] **Step 5: Remove async helper methods**

Delete these methods from `market_rotation.py`:

```python
_run_loop
_refresh_market_universe_async
_refresh_market_universe_sync
_run_refresh_price_to_beat_batch_sync
_refresh_once_via_thread
_refresh_once_via_thread_guarded
_refresh_price_to_beat_batch
_publish_price_to_beat
```

Add sync PTB methods:

```python
def _publish_price_to_beat_sync(self, market: Market) -> None:
    result = self.ptb_provider.get_sync(market)
    if result.value is None:
        return
    signature: _PriceToBeatSignature = (
        result.value,
        result.source,
        result.verified,
        result.from_anchor_service,
        result.anchor_source,
    )
    if self._last_published_ptb.get(market.condition_id) == signature:
        return
    now = datetime.now(UTC)
    self.publisher.publish_price_to_beat(
        condition_id=market.condition_id,
        value=result.value,
        source=result.source,
        verified=result.verified,
        from_anchor_service=result.from_anchor_service,
        anchor_source=result.anchor_source,
        anchor_lag_ms=result.anchor_lag_ms,
        ts_event=_timestamp_ns(now),
        ts_init=_timestamp_ns(now),
    )
    self._last_published_ptb[market.condition_id] = signature


def _publish_price_to_beat_batch_sync(self, markets: tuple[Market, ...]) -> None:
    for market in markets:
        try:
            self._publish_price_to_beat_sync(market)
        except Exception:
            logger.exception(
                "market_rotation phase=refresh_ptb failed epoch=%s condition_id=%s",
                self._epoch,
                market.condition_id,
            )
```

Add `PriceToBeatProvider.get_sync(market: Market) -> PriceToBeatResult` in `src/polysignal_lab/data/price_to_beat_provider.py` using the existing synchronous internals. If no synchronous internals exist, implement it as a direct call to the already synchronous anchor/crypto price providers used by `get`.

- [ ] **Step 6: Update `_on_refresh_timer`**

Use only sync methods:

```python
def _on_refresh_timer(self, _event: object = None) -> None:
    if self._refresh_in_flight:
        return
    self._refresh_in_flight = True
    try:
        refreshed_markets = tuple(self.market_universe.refresh_once_sync())
        markets = self._apply_refreshed_markets(refreshed_markets)
        self._publish_price_to_beat_batch_sync(markets)
    except Exception as exc:
        logger.exception("market_rotation phase=refresh failed epoch=%s", self._epoch)
        self._mark_down(exc, phase="refresh")
    finally:
        self._refresh_in_flight = False
```

Add `refresh_once_sync() -> list[Market]` to the concrete market universe class used by node startup. It must call the existing Polymarket discovery client synchronously and must close the client in the same call.

- [ ] **Step 7: Run scheduling boundary tests**

Run:

```bash
uv run python -m pytest tests/test_nautilus_sidecar_actor.py::test_market_rotation_actor_uses_clock_timer_for_startup tests/test_nautilus_platform_boundary.py::test_default_runtime_has_no_asyncio_actor_scheduling_fallbacks -q
```

Expected: PASS.

- [ ] **Step 8: Commit scheduling cleanup**

```bash
git add src/polysignal_lab/nautilus_runtime/market_rotation.py src/polysignal_lab/nautilus_runtime/sidecar_data.py src/polysignal_lab/data/price_to_beat_provider.py tests/test_nautilus_sidecar_actor.py tests/test_nautilus_platform_boundary.py
git commit -m "refactor: remove asyncio scheduling from Nautilus actors"
```

---

### Task 7: Split large order mapping and native strategy data callback functions

**Files:**
- Create: `src/polysignal_lab/nautilus_runtime/order_plan.py`
- Modify: `src/polysignal_lab/nautilus_runtime/order_mapping.py:1-153`
- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py:344-419,565-616,618-659`
- Modify: `tests/test_nautilus_native_order.py`
- Modify: `tests/test_nautilus_strategy_base.py`
- Test: `tests/test_nautilus_native_order.py`
- Test: `tests/test_nautilus_strategy_base.py`

**Interfaces:**
- Consumes: `ApprovedDecision | AlphaDecision | SignalCandidate`, `OrderIntent`, `NautilusOrderSpec`.
- Produces:
  - `resolve_order_intent(source: AlphaDecision | SignalCandidate) -> OrderIntent`
  - `resolve_order_price(source: AlphaDecision | SignalCandidate, intent: OrderIntent, best_ask: float | None) -> float`
  - `resolve_order_quantity(metrics: Mapping[str, object], fixed_stake_usdc: float, price: float) -> float`
  - `build_order_tags(source: AlphaDecision | SignalCandidate, intent: OrderIntent, expiry_seconds: int | None) -> dict[str, str]`
  - `build_order_spec(source: AlphaDecision | SignalCandidate, fixed_stake_usdc: float, best_ask: float | None) -> NautilusOrderSpec`
  - `PolySignalNativeStrategy._handle_custom_data(data: object) -> bool`
  - `PolySignalNativeStrategy._handle_market_metadata(data: PolySignalMarketMetaData) -> bool`
  - `PolySignalNativeStrategy._handle_market_universe(data: PolySignalMarketUniverseData) -> bool`
  - `PolySignalNativeStrategy._handle_generic_data(data: object) -> None`

- [ ] **Step 1: Add order plan unit tests**

Append to `tests/test_nautilus_native_order.py`:

```python
def test_order_plan_resolves_taker_price_from_best_ask() -> None:
    from polysignal_lab.nautilus_runtime.order_plan import build_order_spec

    spec = build_order_spec(
        _approved(OrderIntent.TAKER_IOC).signal,
        fixed_stake_usdc=10.0,
        best_ask=0.50,
    )

    assert spec.price == 0.50
    assert spec.quantity == 20.0
    assert spec.tags["time_in_force"] == "IOC"


def test_order_plan_rejects_taker_without_best_ask() -> None:
    from polysignal_lab.nautilus_runtime.order_plan import build_order_spec

    approved = _approved(OrderIntent.TAKER_FOK)

    try:
        build_order_spec(approved.signal, fixed_stake_usdc=10.0, best_ask=None)
    except ValueError as exc:
        assert "taker_fok requires best ask depth" in str(exc)
    else:
        raise AssertionError("expected ValueError")
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run python -m pytest tests/test_nautilus_native_order.py::test_order_plan_resolves_taker_price_from_best_ask tests/test_nautilus_native_order.py::test_order_plan_rejects_taker_without_best_ask -q
```

Expected: FAIL because `order_plan.py` does not exist.

- [ ] **Step 3: Create `order_plan.py`**

Create `src/polysignal_lab/nautilus_runtime/order_plan.py`:

```python
from __future__ import annotations

from collections.abc import Mapping
from typing import SupportsFloat, cast

from polysignal_lab.alpha.types import AlphaDecision, NautilusOrderSpec, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent
from polysignal_lab.domain.signal import SignalCandidate


def build_order_spec(
    source: AlphaDecision | SignalCandidate,
    *,
    fixed_stake_usdc: float,
    best_ask: float | None,
) -> NautilusOrderSpec:
    intent = resolve_order_intent(source)
    expiry_seconds = expiry_seconds_for(source)
    pair_id = pair_id_for(source)
    metrics = dict(cast(Mapping[str, object], source.metrics))
    price = resolve_order_price(source, intent=intent, best_ask=best_ask)
    quantity = resolve_order_quantity(metrics, fixed_stake_usdc=fixed_stake_usdc, price=price)
    return NautilusOrderSpec(
        instrument_id=str(source.token_id),
        side=source.side,
        price=price,
        quantity=quantity,
        intent=intent,
        expiry_seconds=expiry_seconds,
        pair_id=pair_id,
        reduce_only=False,
        hedge_leg=source.hedge_leg,
        tags=build_order_tags(source, intent=intent, expiry_seconds=expiry_seconds),
    )


def resolve_order_intent(source: AlphaDecision | SignalCandidate) -> OrderIntent:
    raw = source.order_intent
    if raw is None:
        return OrderIntent.TAKER_IOC
    if isinstance(raw, OrderIntent):
        return raw
    return raw.intent


def explicit_order_intent(source: AlphaDecision | SignalCandidate) -> OrderIntent | None:
    raw = source.order_intent
    if raw is None:
        return None
    if isinstance(raw, OrderIntent):
        return raw
    return raw.intent


def resolve_order_price(
    source: AlphaDecision | SignalCandidate,
    *,
    intent: OrderIntent,
    best_ask: float | None,
) -> float:
    max_price = positive_float(source.max_entry_price, "max_entry_price")
    explicit_intent = explicit_order_intent(source)
    if explicit_intent is None and best_ask is None:
        return max_price
    if explicit_intent is not None and intent not in {OrderIntent.TAKER_FAK, OrderIntent.TAKER_FOK, OrderIntent.TAKER_IOC}:
        return max_price
    if best_ask is None:
        raise ValueError(f"{intent.value} requires best ask depth")
    price = positive_float(best_ask, "best_ask")
    if price > max_price:
        raise ValueError(f"best ask {price} exceeds max entry price {max_price}")
    return price


def resolve_order_quantity(
    metrics: Mapping[str, object],
    *,
    fixed_stake_usdc: float,
    price: float,
) -> float:
    contracts = metric_float(metrics, "contracts")
    quantity = (
        positive_float(contracts, "contracts")
        if contracts is not None
        else positive_float(fixed_stake_usdc, "fixed_stake_usdc") / price
    )
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    return quantity


def build_order_tags(
    source: AlphaDecision | SignalCandidate,
    *,
    intent: OrderIntent,
    expiry_seconds: int | None,
) -> dict[str, str]:
    tags: dict[str, str] = {
        "strategy": str(source.strategy),
        "asset": str(source.asset),
        "timeframe": str(source.timeframe),
        "market_id": str(source.market_id),
        "market_slug": str(source.market_slug),
        "condition_id": str(source.condition_id),
        "confidence": str(source.confidence),
        "entry_reference_price": str(source.entry_reference_price),
        "max_entry_price": str(source.max_entry_price),
        "order_intent": intent.value,
    }
    add_optional_source_tags(tags, source)
    add_time_in_force_tags(tags, source=source, intent=intent, expiry_seconds=expiry_seconds)
    return tags


def add_optional_source_tags(tags: dict[str, str], source: AlphaDecision | SignalCandidate) -> None:
    signal_id = source.signal_id if isinstance(source, SignalCandidate) else None
    if signal_id is not None:
        tags["signal_id"] = str(signal_id)
    if source.seconds_to_close is not None:
        tags["seconds_to_close"] = str(source.seconds_to_close)
    if source.data_freshness_ms is not None:
        tags["data_freshness_ms"] = str(source.data_freshness_ms)
    if source.reason_codes:
        tags["reason_codes"] = "|".join(str(code) for code in source.reason_codes)
    if source.hedge_leg:
        tags["hedge_leg"] = "true"


def add_time_in_force_tags(
    tags: dict[str, str],
    *,
    source: AlphaDecision | SignalCandidate,
    intent: OrderIntent,
    expiry_seconds: int | None,
) -> None:
    if intent == OrderIntent.PASSIVE_GTD:
        tags["time_in_force"] = "GTD"
        if expiry_seconds is not None:
            tags["expire_seconds"] = str(expiry_seconds)
        return
    if intent == OrderIntent.TAKER_FOK:
        tags["time_in_force"] = "FOK"
        return
    tags["time_in_force"] = "IOC"
    tags["fill_policy"] = "FAK" if intent == OrderIntent.TAKER_FAK else "IOC"
    if explicit_order_intent(source) is None:
        tags["paper_safe_default"] = "true"


def expiry_seconds_for(source: AlphaDecision | SignalCandidate) -> int | None:
    raw = source.order_intent
    if isinstance(raw, OrderIntentSpec):
        return raw.expiry_seconds
    if isinstance(source, SignalCandidate):
        return source.expiry_seconds
    return None


def pair_id_for(source: AlphaDecision | SignalCandidate) -> str | None:
    raw = source.order_intent
    if isinstance(raw, OrderIntentSpec):
        return raw.pair_id
    if isinstance(source, SignalCandidate):
        return source.pair_id
    return None


def positive_float(value: float, name: str) -> float:
    number = float(value)
    if number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def metric_float(metrics: Mapping[str, object], *names: str) -> float | None:
    for name in names:
        value = metrics.get(name)
        if value is not None:
            return float(cast(SupportsFloat | str | bytes | bytearray, value))
    return None
```

- [ ] **Step 4: Thin out `order_mapping.py`**

Replace `order_spec_from_decision` with:

```python
def order_spec_from_decision(
    decision: ApprovedDecision | AlphaDecision | SignalCandidate,
    fixed_stake_usdc: float,
    best_ask: float | None = None,
) -> NautilusOrderSpec:
    return build_order_spec(
        _decision_source(decision),
        fixed_stake_usdc=fixed_stake_usdc,
        best_ask=best_ask,
    )
```

Import:

```python
from polysignal_lab.nautilus_runtime.order_plan import build_order_spec
```

Delete helper functions now moved to `order_plan.py`.

- [ ] **Step 5: Split `PolySignalNativeStrategy.on_data`**

Replace `on_data` body with:

```python
def on_data(self, data: object) -> None:
    if classify_project_owned_data(data) is DataBoundaryClassification.DROPPED_FRAME:
        self._note_runtime_progress("dropped_frame")
        return
    if self._handle_custom_data(data):
        return
    if isinstance(data, PolySignalMarketMetaData):
        if self._handle_market_metadata(data):
            return
    if isinstance(data, PolySignalMarketUniverseData):
        if self._handle_market_universe(data):
            return
    self._handle_generic_data(data)
```

Add methods:

```python
def _handle_custom_data(self, data: object) -> bool:
    if not isinstance(data, (PolySignalSpotData, PolySignalPriceToBeatData)):
        return False
    result = self.custom_data.apply(data)
    if result.spot_asset is not None:
        for candidate in self._asset_condition_ids.get(result.spot_asset, ()): 
            self.evaluate_condition(candidate)
        return True
    if result.price_to_beat_condition_id is not None:
        self._retry_market_instrument_requests(
            (result.price_to_beat_condition_id,), retry_after=timedelta(seconds=10)
        )
        self.evaluate_condition(result.price_to_beat_condition_id)
        return True
    return True


def _handle_market_metadata(self, data: PolySignalMarketMetaData) -> bool:
    catalog = self._require_catalog()
    catalog.register(MarketPairMeta.from_metadata(data))
    self._refresh_asset_conditions()
    if data.condition_id in self._active_condition_ids:
        self._subscribe_market_conditions((data.condition_id,))
    return True


def _handle_market_universe(self, data: PolySignalMarketUniverseData) -> bool:
    if self._market_epoch is not None and data.epoch <= self._market_epoch:
        return True
    self._market_epoch = data.epoch
    self._active_condition_ids = set(data.active_condition_ids)
    self._refresh_asset_conditions()
    for condition_id in data.exited_condition_ids:
        self._subscription_state.pending_metadata_condition_ids.discard(condition_id)
        self._subscription_state.pending_subscribe_condition_ids.discard(condition_id)
    if self.unsubscribe_exited:
        self._unsubscribe_market_conditions(data.exited_condition_ids)
    self._subscribe_market_conditions(tuple(self._active_condition_ids))
    return True


def _handle_generic_data(self, data: object) -> None:
    assembler = self._require_assembler()
    updater = getattr(assembler, "on_data", None) or getattr(assembler, "update", None)
    if callable(updater):
        _ = updater(data)
    condition_id = cast(object, getattr(data, "condition_id", None))
    if condition_id is not None:
        self.evaluate_condition(str(condition_id))
        return
    for candidate in self._active_condition_ids:
        self.evaluate_condition(candidate)
```

- [ ] **Step 6: Run order and strategy tests**

Run:

```bash
uv run python -m pytest tests/test_nautilus_native_order.py tests/test_nautilus_strategy_base.py -q
```

Expected: PASS.

- [ ] **Step 7: Run large function boundary test**

Run:

```bash
uv run python -m pytest tests/test_nautilus_platform_boundary.py::test_large_nautilus_runtime_functions_stay_under_limit -q
```

Expected: PASS. If any function still exceeds 45 lines, split only that function into named helpers with tests around the helper behavior.

- [ ] **Step 8: Commit large function split**

```bash
git add src/polysignal_lab/nautilus_runtime/order_plan.py src/polysignal_lab/nautilus_runtime/order_mapping.py src/polysignal_lab/nautilus_runtime/native_strategy.py tests/test_nautilus_native_order.py tests/test_nautilus_strategy_base.py tests/test_nautilus_platform_boundary.py
git commit -m "refactor: split Nautilus order and data callback planning"
```

---

### Task 8: Update safety scan and docs to enforce the final boundary

**Files:**
- Modify: `src/polysignal_lab/observability/safety.py:33-48`
- Modify: `docs/NAUTILUS_BRIDGE_BOUNDARY.md:15-27,111-119`
- Modify: `docs/IMPLEMENTATION_SUMMARY.md:7-20`
- Modify: `docs/PROJECT_ARCHITECTURE_VISUAL.md:7-37,150-165,197-222`
- Modify: `docs/PRD.md:145-180,476-485,1059-1063`
- Test: `tests/test_nautilus_platform_boundary.py`

**Interfaces:**
- Consumes: final source tree.
- Produces: docs and scanner language aligned with final architecture.

- [ ] **Step 1: Extend safety scan forbidden symbols**

In `src/polysignal_lab/observability/safety.py`, extend `LOCAL_PAPER_ISOLATION_SYMBOLS` with:

```python
    "nautilus_trader.live.node",
    "TradingNodeConfig",
    "new_class(",
    "ExternalDataSidecar",
    "runtime_native_strategy_type",
    "runtime_sidecar_actor_type",
    "runtime_market_rotation_actor_type",
    "_by_instrument",
    "condition_id_for_instrument",
    "token_id_for_instrument",
    "asyncio.create_task(",
```

Keep the `submit_order` allow-list for Nautilus strategy paths.

- [ ] **Step 2: Run safety scan to verify docs still fail if stale source remains**

Run:

```bash
uv run polysignal-safety-scan .
```

Expected: PASS after Tasks 2-7. If it fails, remove the listed forbidden source token or narrow the scanner skip only for generated docs containing historical evidence.

- [ ] **Step 3: Update `docs/NAUTILUS_BRIDGE_BOUNDARY.md`**

Replace the Node Surface section with:

```markdown
## Node Surface Status

The default Nautilus bridge enters through `nautilus_trader.live.LiveNode.builder(...)`.
Legacy `nautilus_trader.live.node.TradingNode` and `TradingNodeConfig` are not used by the default runtime.

The default runtime boundary is:

- Polymarket data is registered through the Nautilus Polymarket data client factory.
- Paper execution is registered through the Nautilus sandbox execution client factory.
- Strategy order submission uses Nautilus `order_factory` and `submit_order`.
- Market views read from Nautilus cache projections plus strategy-local custom data derived from Nautilus `CustomData` callbacks.
- No `NautilusMatchingPaperExecutionClient`, `NautilusOrchestrator`, `NautilusDataIngestor`, `PaperWallet` runtime ledger, installed-source patch, private engine monkeypatch, shared external sidecar store, dynamic runtime class factory, or reverse instrument registry is allowed.
```

Replace the post-task bullets with:

```markdown
- Default runtime: Nautilus `LiveNode` owns lifecycle, data engine, execution engine, cache, portfolio, and sandbox execution.
- Node surface: default path uses `LiveNode.builder(...)`; legacy `TradingNode` is absent from runtime source.
- Data: Polymarket market data uses `PolymarketLiveDataClientFactory`; spot/PTB/market metadata uses Nautilus `CustomData` and strategy-local derived state.
- Execution: paper execution uses `SandboxLiveExecClientFactory`; no PolySignal-owned simulator, wallet, FAK/FOK/GTD executor, fill model, exit engine, or local resting-order store remains.
- Strategy: `PolySignalNativeStrategy` submits orders through Nautilus `order_factory` and `submit_order`; fillability and order lifecycle are delegated to Nautilus sandbox/cache/portfolio.
- Market views: alpha views are read-only projections from Nautilus cache plus strategy-local custom data state.
- Observability: dashboard/report rows are read-only projections from Nautilus events/cache/portfolio; no local paper ledger drives runtime state.
- Safety: project-wide source scan blocks live Polymarket execution symbols, legacy paper wheel symbols, legacy TradingNode surface, dynamic runtime class factories, shared external sidecar store, reverse instrument registry, and bare asyncio actor scheduling fallbacks.
```

- [ ] **Step 4: Update summary docs**

In `docs/IMPLEMENTATION_SUMMARY.md`, replace rows 8-16 with:

```markdown
| Polymarket data | Nautilus Polymarket data factory plus Nautilus `CustomData` business market rotation payloads |
| Custom data | Spot, price-to-beat, anchor, and market metadata flow through Nautilus custom data; latest values are strategy-local derived state only |
| Snapshots | Market view assembly from Nautilus cache projections and strategy-local custom data |
| Strategies | PolySignal alpha cores wrapped by static Nautilus strategy subclasses |
| Signal layer | SignalCandidate schema, gate, dedupe, channel rate limiter, consensus engine, formatter |
| Telegram | Dry-run default publisher, retry-capable HTTP sender, publish audit record, real Telegram QA command with redacted evidence |
| Paper trading | Nautilus LiveNode, native order submission, Nautilus sandbox execution, cache/portfolio projections |
| Node surface | Default runtime uses `LiveNode.builder(...)`; legacy `TradingNode` is absent from runtime source |
| Exits/settlement | Prediction-market resolution remains business logic; runtime positions and account state come from Nautilus portfolio/cache projection |
```

In `docs/PROJECT_ARCHITECTURE_VISUAL.md`, replace `Nautilus TradingNode` with `Nautilus LiveNode`, replace `Sidecar` wording with `Nautilus CustomData`, and remove the old risk item about `README` if it no longer reflects current source.

In `docs/PRD.md`, replace startup step 4 with:

```markdown
4. 初始化 Nautilus `LiveNode.builder(...)` paper runtime。
```

Replace paper flow steps 1-6 with:

```markdown
1. 通过 gate 的信号由 Nautilus strategy wrapper 映射为 Nautilus native order 参数。
2. Strategy wrapper 调用 Nautilus `order_factory.limit(...)` 和 `submit_order(...)`。
3. Nautilus sandbox 根据当前 instrument、book、trade 数据处理 paper order。
4. 订单状态、成交、持仓、账户状态来自 Nautilus cache/portfolio。
5. PolySignal 将 Nautilus events/projected cache rows 写入 SQLite/JSONL、Telegram、日报和 dashboard。
6. 市场结束后的 win/loss 计算只读取 Nautilus position projection 和 Polymarket outcome resolution，不维护本地 PaperWallet。
```

- [ ] **Step 5: Run docs and platform verification**

Run:

```bash
uv run polysignal-safety-scan .
uv run python -m pytest tests/test_nautilus_platform_boundary.py -q
```

Expected:

```text
Safety scan passed
```

and:

```text
[100%]
```

- [ ] **Step 6: Commit safety and docs**

```bash
git add src/polysignal_lab/observability/safety.py docs/NAUTILUS_BRIDGE_BOUNDARY.md docs/IMPLEMENTATION_SUMMARY.md docs/PROJECT_ARCHITECTURE_VISUAL.md docs/PRD.md tests/test_nautilus_platform_boundary.py
git commit -m "docs: document final Nautilus runtime boundary"
```

---

### Task 9: Final integration verification

**Files:**
- Test only: no source edits unless a verification command reports a concrete failure.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: verified final state with no duplicate Nautilus platform wheels.

- [ ] **Step 1: Run focused Nautilus tests**

Run:

```bash
uv run python -m pytest \
  tests/test_nautilus_platform_boundary.py \
  tests/test_nautilus_node.py \
  tests/test_nautilus_market_catalog.py \
  tests/test_nautilus_cache_market_data.py \
  tests/test_nautilus_market_view_assembler.py \
  tests/test_nautilus_sidecar_actor.py \
  tests/test_nautilus_native_order.py \
  tests/test_nautilus_strategy_base.py \
  -q
```

Expected: PASS, no failures.

- [ ] **Step 2: Run safety scan**

Run:

```bash
uv run polysignal-safety-scan .
```

Expected:

```text
Safety scan passed
```

- [ ] **Step 3: Run default import boundary**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -c "import polysignal_lab"
```

Expected: exit 0 with no output. If `/home/gyue/.local/bin/python3.11` is unavailable on the execution host, run:

```bash
uv run python -c "import polysignal_lab"
```

Expected: exit 0 with no output.

- [ ] **Step 4: Run function-size audit**

Run:

```bash
uv run python -m pytest tests/test_nautilus_platform_boundary.py::test_large_nautilus_runtime_functions_stay_under_limit -q
```

Expected: PASS.

- [ ] **Step 5: Commit verification note only if source changed during fixes**

If Step 1-4 required fixes, commit those source/test changes:

```bash
git add src tests docs
git commit -m "fix: satisfy final Nautilus boundary verification"
```

If Step 1-4 required no fixes, do not create an empty commit.

---

## Self-Review

### Spec coverage

- Legacy `TradingNode` surface removal: Task 1, Task 2, Task 8, Task 9.
- Dynamic runtime type factory removal: Task 1, Task 3, Task 9.
- Shared sidecar store deletion: Task 1, Task 4, Task 8, Task 9.
- Reverse instrument registry deletion: Task 1, Task 5, Task 9.
- Bare `asyncio` actor fallback removal: Task 1, Task 6, Task 9.
- Large function remediation: Task 1, Task 7, Task 9.
- No local paper execution/matching/wallet regression: existing platform boundary tests plus Task 8 safety scan.
- Docs alignment: Task 8.

### Placeholder scan

No placeholder markers, no unspecified test step, no unnamed file path, no undefined interface in later tasks.

### Type consistency

- `MarketCatalog` replaces `PolymarketMarketRegistry` everywhere.
- `CustomDataPublisher` replaces `SidecarDataActor` as publisher-only class.
- `StrategyCustomDataState` is the only state object used by `MarketViewAssembler` through `CustomDataSnapshotProvider`.
- `build_paper_live_node` is the only default runtime node construction function.
- `NautilusPolySignalNativeStrategy` and `NautilusMarketRotationActor` are static runtime classes loaded lazily by `node._load_runtime_classes()`.
