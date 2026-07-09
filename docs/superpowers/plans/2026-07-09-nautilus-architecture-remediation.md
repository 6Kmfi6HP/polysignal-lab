# NautilusTrader Architecture Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除审查确认的 NautilusTrader 边界、确定性、共享决策所有权、重复 wrapper、死代码和高价值重复代码问题，同时保持 NautilusTrader 对 lifecycle、Cache、Portfolio、orders、fills 和 positions 的唯一所有权。

**Architecture:** 先修复不改变模块边界的确定性与正确性缺陷，再收紧共享 policy 和 runtime assembly 契约，随后统一 cross-market 决策路径并把阻塞市场发现移出 Actor callback。最后按“有测试保护、无生产调用、一次只删一组”的原则清理死代码和重复代码；大型组件仅做职责明确的组合式提取，不引入新的 mixin、通用框架或第二运行时。

**Tech Stack:** Python 3.11 默认运行时、Python 3.12+ NautilusTrader bridge、NautilusTrader `LiveNode`/`Strategy`/`Actor`/CustomData、pytest、Ruff、pyscn、Vulture、Pydantic、SQLite。

## Global Constraints

- 不得修改 `@refs/` 或 `docs/nautilus_reference/`。
- 默认 Python 3.11 安装和 import 必须继续不依赖 NautilusTrader；Nautilus bridge 保持可选依赖。
- 默认执行必须继续是 `Environment.SANDBOX`，不得注册 authenticated Polymarket live execution client。
- NautilusTrader 必须继续拥有 lifecycle、DataEngine、ExecutionEngine、Cache、Portfolio、orders、fills 和 positions。
- SQLite、JSONL、Telegram 和 Dashboard 只能消费只读投影，不得成为实时执行状态源。
- Alpha core 不得 import NautilusTrader；宿主类型转换只发生在 `nautilus_bridge/` 或 `nautilus_runtime/`。
- 消息创建后不可变；回放相关时间必须来自 `ts_event`，不得来自消费时墙钟。
- Bug 修复必须先写失败测试、确认失败，再写最小实现。
- 每个任务单独提交；不得把用户当前工作区中的其他未提交改动混入提交。
- 开始执行时必须使用 `superpowers:using-git-worktrees` 创建隔离 worktree；当前主工作区已有大量未提交改动。
- 每次修改 NautilusTrader 相关代码前重新核对 `docs/nautilus_reference/developer_guide/` 的当前约束。

---

## File Structure and Responsibility Map

### Runtime correctness

- `src/polysignal_lab/nautilus_runtime/custom_data_state.py`：CustomData → 策略局部派生状态；只使用消息事件时间。
- `src/polysignal_lab/nautilus_runtime/group_views.py`：跨市场 view 的绝对 freshness 与相对 skew 校验。
- `src/polysignal_lab/nautilus_bridge/market_catalog.py`：condition/token 业务索引的一致性更新。
- `tests/test_nautilus_market_view_assembler.py`：CustomData 状态和 view 时间语义。
- `tests/test_nautilus_cross_market.py`：跨市场 freshness 行为。
- `tests/test_nautilus_market_catalog.py`：catalog replacement 行为。

### Decision ownership and wrapper unification

- `src/polysignal_lab/nautilus_runtime/native_strategy.py`：要求显式注入共享 policy；不再创建隐式私有 policy。
- `src/polysignal_lab/nautilus_runtime/strategy_builder.py`：构造唯一共享 policy 并注入全部策略。
- `src/polysignal_lab/nautilus_runtime/node_builder.py`：固定三类 runtime extension 契约。
- `src/polysignal_lab/nautilus_runtime/decision_policy_actor.py`：持有并暴露同一 policy 状态；本计划第一阶段不引入新的 MessageBus RPC 框架。
- `src/polysignal_lab/nautilus_runtime/strategies/cross_market_bot.py`：删除独立 policy/mapping/submission pipeline，只保留 group evaluation adapter；如无生产调用则整体删除。
- `tests/test_nautilus_node.py`、`tests/test_nautilus_strategy_base.py`、`tests/test_nautilus_decision_policy.py`、`tests/test_nautilus_cross_market.py`：共享实例和单一 pipeline 证明。

### Actor-safe market discovery

- Create `src/polysignal_lab/nautilus_runtime/market_discovery_worker.py`：唯一职责是在线程中运行阻塞 Gamma discovery，并把不可变结果排回 Actor 可消费队列；不持有交易状态。
- `src/polysignal_lab/nautilus_runtime/market_rotation.py`：timer 只发起非阻塞请求并应用已完成结果，不直接执行 HTTP。
- `src/polysignal_lab/nautilus_runtime/node_builder_components.py`：创建、注入和关闭 worker。
- `tests/test_nautilus_market_rotation.py`：证明 timer callback 不执行 transport、旧结果被拒绝、停止时 worker 关闭。

### Dead code and duplication cleanup

- Delete `src/polysignal_lab/nautilus_runtime/projection_recorder.py`：无生产或测试调用。
- `src/polysignal_lab/nautilus_runtime/strategy/decision_pipeline.py`：删除无调用 helper。
- `src/polysignal_lab/nautilus_runtime/native_strategy.py`：删除无调用转发方法和误导性的本地执行列表。
- `src/polysignal_lab/app/services/persistence_service.py`：删除无调用的 legacy `persist_state()`。
- `src/polysignal_lab/nautilus_runtime/optional_imports.py`：统一 optional Nautilus import gateway。
- `src/polysignal_lab/data/market_discovery_helpers.py`、`src/polysignal_lab/data/polymarket_market_discovery.py`：复用一个纯 helper 实现。
- `src/polysignal_lab/storage/sqlite_store.py`：合并重复 payload insert/query 模板。
- `src/polysignal_lab/nautilus_runtime/strategy/observability_hooks.py`：统一 observability 异常保护。

### Large-component follow-up

- Create `src/polysignal_lab/alpha/vwap_trade_history.py`：VWAP trade history、去重和查询。
- Create `src/polysignal_lab/alpha/vwap_state.py`：版本化状态编码/解码。
- `src/polysignal_lab/alpha/vwap_momentum_core.py`：只保留公式、策略状态机和组合调用。
- Create `src/polysignal_lab/alpha/legacy_snapshot_adapter.py`：legacy `MarketSnapshot → MarketView` 与 `AlphaDecision → SignalCandidate`。
- `src/polysignal_lab/alpha/ptb_diff_core.py`：只保留 PTB core。

---

### Task 1: Make Price-to-Beat CustomData Replay Deterministic

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/custom_data_state.py:15-79`
- Test: `tests/test_nautilus_market_view_assembler.py`
- Test: `tests/test_nautilus_custom_data.py`

**Interfaces:**
- Consumes: `PolySignalPriceToBeatData.ts_event: int`，单位为 Unix nanoseconds。
- Produces: `event_datetime(ts_event: int) -> datetime`；`StrategyCustomDataState.apply()` 生成的 `PriceToBeatView.updated_at` 完全由消息事件时间决定。

- [ ] **Step 1: 写入失败测试，证明墙钟变化不影响状态时间**

在 `tests/test_nautilus_market_view_assembler.py` 增加：

```python
from datetime import UTC, datetime

from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState
from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalPriceToBeatData


def test_price_to_beat_state_uses_event_time() -> None:
    ts_event = 1_788_451_200_123_456_789
    data = PolySignalPriceToBeatData(
        condition_id="condition-1",
        value=99_500.0,
        source="anchor",
        verified=True,
        from_anchor_service=True,
        anchor_source="chainlink",
        anchor_lag_ms=7,
        ts_event=ts_event,
        ts_init=ts_event + 10,
    )

    state = StrategyCustomDataState()
    state.apply(data)

    ptb = state.ptb_for("condition-1")
    assert ptb is not None
    assert ptb.updated_at == datetime.fromtimestamp(ts_event / 1_000_000_000, UTC)
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
uv run pytest tests/test_nautilus_market_view_assembler.py::test_price_to_beat_state_uses_event_time -v
```

Expected: FAIL；`updated_at` 等于测试执行时墙钟，而不是指定的 `ts_event`。

- [ ] **Step 3: 增加严格事件时间转换函数并替换墙钟**

在 `custom_data_state.py` 中实现：

```python
from datetime import UTC, datetime


def event_datetime(ts_event: int) -> datetime:
    if ts_event <= 0:
        raise ValueError("CustomData ts_event must be a positive Unix nanosecond timestamp")
    return datetime.fromtimestamp(ts_event / 1_000_000_000, UTC)
```

将 PTB 分支改为：

```python
if isinstance(data, PolySignalPriceToBeatData):
    self._ptb[data.condition_id] = PriceToBeatView(
        condition_id=data.condition_id,
        value=data.value,
        source=data.source,
        verified=data.verified,
        from_anchor_service=data.from_anchor_service,
        anchor_source=data.anchor_source,
        anchor_lag_ms=data.anchor_lag_ms,
        updated_at=event_datetime(data.ts_event),
    )
    return CustomDataApplyResult(price_to_beat_condition_id=data.condition_id)
```

同时删除不再需要的 `datetime.now` 使用；保留 `UTC` 和 `datetime` 类型。

- [ ] **Step 4: 增加无效时间 fail-closed 测试**

```python
import pytest


def test_price_to_beat_state_rejects_missing_event_time() -> None:
    state = StrategyCustomDataState()
    data = PolySignalPriceToBeatData(
        condition_id="condition-1",
        value=99_500.0,
        source="anchor",
        ts_event=0,
        ts_init=0,
    )

    with pytest.raises(ValueError, match="ts_event"):
        state.apply(data)

    assert state.ptb_for("condition-1") is None
```

- [ ] **Step 5: 运行 CustomData 和 view 测试**

Run:

```bash
uv run pytest tests/test_nautilus_custom_data.py tests/test_nautilus_market_view_assembler.py -v
```

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/polysignal_lab/nautilus_runtime/custom_data_state.py tests/test_nautilus_custom_data.py tests/test_nautilus_market_view_assembler.py
git commit -m "fix: derive custom data freshness from event time"
```

---

### Task 2: Enforce Absolute Freshness for Cross-Market Groups

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/group_views.py:22-69`
- Test: `tests/test_nautilus_cross_market.py:178-213`

**Interfaces:**
- Consumes: each `MarketView.freshness.max_ms: int | None`。
- Produces: `MarketGroupViewAssembler(max_source_skew_ms: int = 5000, max_view_age_ms: int = 5000)`；`assemble(..., max_view_age_ms: int | None = None)`。

- [ ] **Step 1: 写入同样陈旧但相对同步的失败测试**

```python
def test_group_assembler_rejects_equally_stale_views() -> None:
    assembler = MarketGroupViewAssembler(
        max_source_skew_ms=5_000,
        max_view_age_ms=10_000,
    )
    now = datetime.now(timezone.utc)

    group = assembler.assemble(
        relation_id="rel-stale",
        views_by_condition_id={
            "a": _view("a", freshness_ms=120_000),
            "b": _view("b", freshness_ms=121_000),
        },
        created_at=now,
    )

    assert group is None
```

再增加缺失 freshness 测试，使用 `dataclasses.replace` 构造 `FreshnessView(..., max_ms=None)`；期望 `None`。

- [ ] **Step 2: 运行测试确认当前实现错误接受陈旧 group**

```bash
uv run pytest tests/test_nautilus_cross_market.py::test_group_assembler_rejects_equally_stale_views -v
```

Expected: FAIL，当前返回 `MarketGroupView`。

- [ ] **Step 3: 实现绝对 freshness 检查**

将构造器和 `assemble` 签名改为：

```python
class MarketGroupViewAssembler:
    def __init__(
        self,
        max_source_skew_ms: int = 5000,
        max_view_age_ms: int = 5000,
    ) -> None:
        self.max_source_skew_ms = max_source_skew_ms
        self.max_view_age_ms = max_view_age_ms

    def assemble(
        self,
        *,
        relation_id: str,
        views_by_condition_id: Mapping[str, MarketView],
        created_at: datetime,
        max_source_skew_ms: int | None = None,
        max_view_age_ms: int | None = None,
    ) -> MarketGroupView | None:
        skew_limit = (
            max_source_skew_ms
            if max_source_skew_ms is not None
            else self.max_source_skew_ms
        )
        age_limit = (
            max_view_age_ms
            if max_view_age_ms is not None
            else self.max_view_age_ms
        )
        if not views_by_condition_id:
            return None

        freshness_values: list[int] = []
        for view in views_by_condition_id.values():
            freshness = view.freshness.max_ms if view.freshness is not None else None
            if freshness is None or freshness > age_limit:
                return None
            freshness_values.append(freshness)

        if max(freshness_values) - min(freshness_values) > skew_limit:
            return None

        return MarketGroupView(
            group_id=f"group_{relation_id}_{created_at.isoformat()}",
            relation_id=relation_id,
            created_at=created_at,
            views_by_condition_id=dict(views_by_condition_id),
            max_source_skew_ms=skew_limit,
            metrics={"max_view_age_ms": age_limit},
        )
```

- [ ] **Step 4: 更新已有可接受 skew 测试，显式使用不会误拒绝的 age limit**

```python
assembler = MarketGroupViewAssembler(
    max_source_skew_ms=2_000,
    max_view_age_ms=2_000,
)
```

- [ ] **Step 5: 运行 cross-market 测试**

```bash
uv run pytest tests/test_nautilus_cross_market.py -v
```

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/polysignal_lab/nautilus_runtime/group_views.py tests/test_nautilus_cross_market.py
git commit -m "fix: reject globally stale cross-market views"
```

---

### Task 3: Make MarketCatalog Replacement Atomic and Remove Stale Token Indexes

**Files:**
- Modify: `src/polysignal_lab/nautilus_bridge/market_catalog.py:110-145`
- Test: `tests/test_nautilus_market_catalog.py`

**Interfaces:**
- Consumes: `MarketPairMeta`。
- Produces: replacing one `condition_id` removes both previous token mappings before installing the new pair。

- [ ] **Step 1: 写入 replacement 失败测试**

```python
def test_register_replacement_removes_previous_token_indexes() -> None:
    catalog = MarketCatalog(instrument_id_resolver=lambda condition_id, token_id: token_id)
    first = _pair(
        condition_id="condition-1",
        up_token_id="up-old",
        down_token_id="down-old",
    )
    replacement = _pair(
        condition_id="condition-1",
        up_token_id="up-new",
        down_token_id="down-new",
    )

    catalog.register(first)
    catalog.register(replacement)

    assert catalog.by_token("up-old") is None
    assert catalog.by_token("down-old") is None
    assert catalog.by_token("up-new") == replacement
    assert catalog.by_token("down-new") == replacement
```

如果现有测试 helper 名称不同，使用现有 `MarketPairMeta` fixture 直接构造，但断言保持不变。

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_nautilus_market_catalog.py::test_register_replacement_removes_previous_token_indexes -v
```

Expected: FAIL；旧 token 仍返回 replacement condition 对应 pair。

- [ ] **Step 3: 最小修改 `register()`**

```python
def register(self, pair: MarketPairMeta) -> None:
    previous = self._by_condition.get(pair.condition_id)
    if previous is not None:
        self._condition_by_token.pop(previous.up.token_id, None)
        self._condition_by_token.pop(previous.down.token_id, None)

    self._by_condition[pair.condition_id] = pair
    self._condition_by_token[pair.up.token_id] = pair.condition_id
    self._condition_by_token[pair.down.token_id] = pair.condition_id
```

- [ ] **Step 4: 运行 catalog 和 rotation 测试**

```bash
uv run pytest tests/test_nautilus_market_catalog.py tests/test_nautilus_market_rotation.py -v
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/polysignal_lab/nautilus_bridge/market_catalog.py tests/test_nautilus_market_catalog.py
git commit -m "fix: remove stale market catalog token indexes"
```

---

### Task 4: Require One Explicit Shared Decision Policy

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py:110-205`
- Modify: `src/polysignal_lab/nautilus_runtime/strategy_builder.py:156-265`
- Test: `tests/test_nautilus_strategy_base.py`
- Test: `tests/test_nautilus_node.py`

**Interfaces:**
- Consumes: `policy: DecisionPolicyActor`，必填。
- Produces: every strategy created by `_build_native_strategies(...)` has `strategy.policy is policy`；没有隐式 `DecisionPolicyActor()` fallback。

- [ ] **Step 1: 写入构造器拒绝缺失 policy 的测试**

在 `tests/test_nautilus_strategy_base.py` 增加：

```python
def test_native_strategy_requires_shared_policy() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    with pytest.raises(TypeError, match="policy"):
        PolySignalNativeStrategy(
            core=FakeCore([]),
            assembler=_assembler(None),
            condition_ids=(),
            strategy_name="ptb_diff",
            registry=_test_market_catalog(),
        )
```

此测试要求从构造器签名删除默认值，而不是在函数体里静默补对象。

- [ ] **Step 2: 运行测试确认当前构造成功而测试失败**

```bash
uv run pytest tests/test_nautilus_strategy_base.py::test_native_strategy_requires_shared_policy -v
```

Expected: FAIL，因为当前 `policy=None` 会创建私有实例。

- [ ] **Step 3: 修改构造器签名和赋值**

将 `PolySignalNativeStrategy.__init__` 中 policy 参数改成无默认值的 keyword-only 参数：

```python
def __init__(
    self,
    *,
    core: AlphaCore,
    assembler: MarketViewAssembler,
    condition_ids: Sequence[str],
    strategy_name: str,
    policy: DecisionPolicyActor,
    fixed_stake_usdc: float = 10.0,
    # 保留其余现有参数
) -> None:
    super().__init__(config=config or StrategyConfig())
    self.policy = policy
```

删除：

```python
self.policy = policy or DecisionPolicyActor()
```

- [ ] **Step 4: 更新所有直接构造策略的测试，显式注入共享 fake policy**

对仅测试订阅或 lifecycle 的构造点统一加入：

```python
policy=RuntimeFakePolicy(),
```

对于需要真实 policy 的测试使用：

```python
policy=DecisionPolicyActor(),
```

不要在 production 构造器中恢复 fallback 来减少测试改动。

- [ ] **Step 5: 增加 node-level 多策略共享实例测试**

在 `tests/test_nautilus_node.py` 基于现有 `runtime["policy"]` 测试扩展：

```python
def test_all_native_strategies_share_runtime_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _build_runtime_with_two_enabled_strategies(monkeypatch)

    assert len(runtime["strategies"]) == 2
    assert all(
        strategy.policy is runtime["policy"]
        for strategy in runtime["strategies"]
    )
```

复用该文件已有 fake runtime builder；启用两个已存在策略配置，不创建新的测试框架。

- [ ] **Step 6: 运行策略与 node 测试**

```bash
uv run pytest tests/test_nautilus_strategy_base.py tests/test_nautilus_node.py -v
```

Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add src/polysignal_lab/nautilus_runtime/native_strategy.py src/polysignal_lab/nautilus_runtime/strategy_builder.py tests/test_nautilus_strategy_base.py tests/test_nautilus_node.py
git commit -m "refactor: require shared decision policy injection"
```

---

### Task 5: Tighten Runtime Extension Loading to One Fixed Shape

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/node_builder.py:63-163`
- Modify: `src/polysignal_lab/nautilus_runtime/node.py` only if it mirrors the compatibility branch
- Test: `tests/test_nautilus_node.py`
- Test: `tests/test_nautilus_full_paper_runtime_smoke.py:78-194`

**Interfaces:**
- Produces: `_load_runtime_classes() -> tuple[type[object], type[object], type[object]]`，顺序固定为 strategy、market rotation actor、decision policy actor。

- [ ] **Step 1: 更新测试 fake，始终返回三类**

将所有：

```python
lambda: (PolySignalNativeStrategy, MarketRotationActor)
```

改为：

```python
from polysignal_lab.nautilus_runtime.decision_policy_actor import (
    NautilusDecisionPolicyActor,
)

lambda: (
    PolySignalNativeStrategy,
    MarketRotationActor,
    NautilusDecisionPolicyActor,
)
```

- [ ] **Step 2: 写入错误 tuple 长度 fail-fast 测试**

```python
def test_runtime_class_loader_requires_three_classes(monkeypatch: pytest.MonkeyPatch) -> None:
    import polysignal_lab.nautilus_runtime.node_builder as module

    monkeypatch.setattr(
        module,
        "_load_runtime_classes",
        lambda: (object, object),
    )

    with pytest.raises(ValueError, match="three runtime classes"):
        module._runtime_class_triple()
```

- [ ] **Step 3: 运行测试确认当前兼容分支接受两类**

```bash
uv run pytest tests/test_nautilus_node.py::test_runtime_class_loader_requires_three_classes -v
```

Expected: FAIL。

- [ ] **Step 4: 删除两类兼容分支**

```python
def _runtime_class_triple() -> tuple[type[object], type[object], type[object]]:
    classes = _load_runtime_classes()
    if len(classes) != 3:
        raise ValueError("_load_runtime_classes must return three runtime classes")
    strategy_cls, rotation_cls, policy_cls = classes
    return strategy_cls, rotation_cls, policy_cls
```

如果 `_load_runtime_classes()` 已有精确返回类型，直接解包并让 Python 抛出 `ValueError`，但保留清晰错误信息。

- [ ] **Step 5: 运行 node assembly smoke**

```bash
uv run pytest tests/test_nautilus_node.py tests/test_nautilus_full_paper_runtime_smoke.py -v
```

Expected: PASS，且现有断言继续证明只注册 `POLYMARKET` data client 与 sandbox exec client。

- [ ] **Step 6: 提交**

```bash
git add src/polysignal_lab/nautilus_runtime/node.py src/polysignal_lab/nautilus_runtime/node_builder.py tests/test_nautilus_node.py tests/test_nautilus_full_paper_runtime_smoke.py
git commit -m "refactor: require complete Nautilus runtime class set"
```

---

### Task 6: Move Blocking Market Discovery Off the Actor Callback

**Files:**
- Create: `src/polysignal_lab/nautilus_runtime/market_discovery_worker.py`
- Modify: `src/polysignal_lab/nautilus_runtime/market_rotation.py:63-270`
- Modify: `src/polysignal_lab/nautilus_runtime/node_builder_components.py`
- Test: `tests/test_nautilus_market_rotation.py`
- Test: `tests/test_nautilus_full_paper_runtime_smoke.py`

**Interfaces:**
- Consumes: a synchronous callable `refresh: Callable[[], Sequence[Market]]`。
- Produces:
  - `MarketDiscoveryResult(epoch: int, markets: tuple[Market, ...], error: str | None)` immutable dataclass。
  - `MarketDiscoveryWorker.request(epoch: int) -> bool`，非阻塞；已有请求执行中时返回 `False`。
  - `MarketDiscoveryWorker.take_result() -> MarketDiscoveryResult | None`，非阻塞。
  - `MarketDiscoveryWorker.close() -> None`。

- [ ] **Step 1: 写入 timer 不得直接调用 transport 的失败测试**

```python
def test_market_rotation_timer_does_not_call_discovery_inline() -> None:
    calls: list[str] = []

    class BlockingUniverse:
        def refresh_once_sync(self) -> list[Market]:
            calls.append("transport")
            return []

    class FakeWorker:
        def request(self, epoch: int) -> bool:
            calls.append(f"request:{epoch}")
            return True

        def take_result(self):
            return None

        def close(self) -> None:
            calls.append("close")

    actor = _rotation_actor(
        market_universe=BlockingUniverse(),
        discovery_worker=FakeWorker(),
    )

    actor._on_refresh_timer(None)

    assert calls == ["request:1"]
```

复用 `tests/test_nautilus_market_rotation.py` 现有 `_rotation_actor`/settings fixture；若 helper 参数不同，扩展该 helper 接收 `discovery_worker`。

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_nautilus_market_rotation.py::test_market_rotation_timer_does_not_call_discovery_inline -v
```

Expected: FAIL；当前 timer 下游调用 `refresh_once_sync()`。

- [ ] **Step 3: 创建最小单线程 worker**

`market_discovery_worker.py`：

```python
from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock

from polysignal_lab.domain.market import Market


@dataclass(frozen=True, slots=True)
class MarketDiscoveryResult:
    epoch: int
    markets: tuple[Market, ...]
    error: str | None = None


class MarketDiscoveryWorker:
    def __init__(self, refresh: Callable[[], Sequence[Market]]) -> None:
        self._refresh = refresh
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="polysignal-market-discovery",
        )
        self._future: Future[MarketDiscoveryResult] | None = None
        self._lock = Lock()

    def request(self, epoch: int) -> bool:
        with self._lock:
            if self._future is not None and not self._future.done():
                return False
            self._future = self._executor.submit(self._run, epoch)
            return True

    def take_result(self) -> MarketDiscoveryResult | None:
        with self._lock:
            future = self._future
            if future is None or not future.done():
                return None
            self._future = None
        return future.result()

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run(self, epoch: int) -> MarketDiscoveryResult:
        try:
            return MarketDiscoveryResult(
                epoch=epoch,
                markets=tuple(self._refresh()),
            )
        except Exception as exc:
            return MarketDiscoveryResult(
                epoch=epoch,
                markets=(),
                error=f"{type(exc).__name__}: {exc}",
            )
```

这里的 worker 只承载 transport，不持有 Cache、Portfolio、策略或共享行情状态。

- [ ] **Step 4: 将 Actor timer 改成 request/poll 两阶段**

在 `MarketRotationActor.__init__` 增加必填或由 builder 注入的：

```python
discovery_worker: MarketDiscoveryWorker
```

保存为：

```python
self._discovery_worker = discovery_worker
self._requested_epoch = self._epoch
```

将 timer callback 改为：

```python
def _on_refresh_timer(self, _event: object) -> None:
    result = self._discovery_worker.take_result()
    if result is not None:
        self._apply_discovery_result(result)

    next_epoch = max(self._epoch, self._requested_epoch) + 1
    if self._discovery_worker.request(next_epoch):
        self._requested_epoch = next_epoch
```

增加：

```python
def _apply_discovery_result(self, result: MarketDiscoveryResult) -> None:
    if result.epoch <= self._epoch:
        return
    if result.error is not None:
        self._mark_degraded(
            phase="market_discovery",
            error=result.error,
        )
        return
    self._apply_refreshed_markets(result.markets, epoch=result.epoch)
```

把现有 refresh 后的 diff/publish 逻辑移动到 `_apply_refreshed_markets(...)`，不改变业务行为。

`on_stop()` 增加：

```python
self._discovery_worker.close()
```

- [ ] **Step 5: 在 builder 中创建 worker 并注入**

在 `node_builder_components.py` 使用现有 `market_universe.refresh_once_sync`：

```python
worker = MarketDiscoveryWorker(market_universe.refresh_once_sync)
rotation_actor = rotation_actor_type(
    settings=settings,
    startup_markets=markets,
    market_universe=market_universe,
    discovery_worker=worker,
    catalog=catalog,
    anchor_store=anchor_store,
)
```

不得在线程 worker 中发布 CustomData；发布仍由 Actor `_apply_discovery_result()` 完成。

- [ ] **Step 6: 增加完成结果、陈旧 epoch 和错误结果测试**

```python
def test_market_rotation_applies_completed_worker_result() -> None:
    worker = StubWorker(
        result=MarketDiscoveryResult(epoch=2, markets=(market_b,)),
    )
    actor = _rotation_actor(discovery_worker=worker, startup_markets=(market_a,))

    actor._on_refresh_timer(None)

    assert actor.active_markets() == (market_b,)


def test_market_rotation_ignores_stale_worker_result() -> None:
    worker = StubWorker(
        result=MarketDiscoveryResult(epoch=1, markets=(market_b,)),
    )
    actor = _rotation_actor(discovery_worker=worker, startup_markets=(market_a,))
    actor._epoch = 2

    actor._on_refresh_timer(None)

    assert actor.active_markets() == (market_a,)
```

错误结果测试断言 active markets 不变且 health 被标记 degraded。

- [ ] **Step 7: 运行 rotation 与 full paper smoke**

```bash
uv run pytest tests/test_nautilus_market_rotation.py tests/test_nautilus_sidecar_actor.py tests/test_nautilus_full_paper_runtime_smoke.py -v
```

Expected: PASS；测试中不再需要通过 timer callback 直接调用阻塞 transport。

- [ ] **Step 8: 提交**

```bash
git add src/polysignal_lab/nautilus_runtime/market_discovery_worker.py src/polysignal_lab/nautilus_runtime/market_rotation.py src/polysignal_lab/nautilus_runtime/node_builder_components.py tests/test_nautilus_market_rotation.py tests/test_nautilus_full_paper_runtime_smoke.py
git commit -m "refactor: move market discovery off actor callbacks"
```

---

### Task 7: Eliminate the Duplicate Cross-Market Submission Pipeline

**Files:**
- Modify or Delete: `src/polysignal_lab/nautilus_runtime/strategies/cross_market_bot.py`
- Modify: `src/polysignal_lab/nautilus_runtime/strategies/__init__.py`
- Modify: `src/polysignal_lab/nautilus_runtime/strategy/decision_pipeline.py`
- Test: `tests/test_nautilus_cross_market.py`

**Interfaces:**
- Consumes: `Iterable[AlphaDecision]` from `CrossMarketAlphaCore.evaluate_group()`。
- Produces: all decisions pass through the existing `DecisionPipeline.handle_decision(...)` and `NativeDecisionSink` contract；cross-market adapter no longer owns `submitted_specs` or its own rejection list。

- [ ] **Step 1: 先证明该 wrapper 没有生产调用者**

Run:

```bash
rg -n "CrossMarketNautilusStrategy" src tests --glob '*.py'
```

Expected: only definition/export and `tests/test_nautilus_cross_market.py`。如果出现 production builder caller，保留类但按后续步骤改成 adapter；如果没有，选择删除类并把测试改成主 pipeline parity 测试。

- [ ] **Step 2: 写入 pipeline parity 失败测试**

在 `tests/test_nautilus_cross_market.py` 增加一个 sink probe：

```python
def test_cross_market_decisions_use_native_decision_pipeline() -> None:
    decisions = tuple(_core().evaluate_group(_group()))
    submitted: list[ApprovedDecision] = []
    state = DecisionPipelineState()
    pipeline = DecisionPipeline(
        RuntimeFakePolicy(),
        is_active_condition=lambda _condition_id: True,
    )
    sink = _RecordingSink(submitted)

    for decision in decisions:
        view = _group().views_by_condition_id[decision.condition_id]
        pipeline.handle_decision(decision, view, state=state, sink=sink)

    assert len(submitted) == len(decisions)
    assert len(state.submitted_orders) == len(decisions)
```

`_RecordingSink` 必须实现现有 `NativeDecisionSink` 的七个方法；`submit_order()` 记录 approved 并返回一个简单 object。

- [ ] **Step 3: 删除测试中的 callback submitter 专用断言**

删除依赖以下专用行为的测试：

```python
CrossMarketNautilusStrategy(..., submitter=fake_submitter)
strategy.submitted_specs
strategy.rejected_decisions
```

将 basket tag 测试改为直接验证统一 mapping helper：

```python
spec = map_approved_to_order_spec(
    approved,
    view=view,
    fixed_stake_usdc=10.0,
)
assert spec.pair_id == "btc-eth-rel"
assert spec.tags["pair_id"] == "btc-eth-rel"
```

若 pair-id transform 仍在 wrapper 内，将其移动为 `decision_order_spec_transform(...)` 纯函数并由主 pipeline 调用。

- [ ] **Step 4: 删除无生产调用的 wrapper**

如果 Step 1 确认无生产 caller：

```bash
git rm src/polysignal_lab/nautilus_runtime/strategies/cross_market_bot.py
```

并从 `strategies/__init__.py` 删除 import 和 `__all__` 项。

如果存在 caller，则把类缩减为：

```python
class CrossMarketDecisionAdapter:
    def __init__(self, core: CrossMarketAlphaCore) -> None:
        self.core = core

    def evaluate_group(self, group: MarketGroupView) -> tuple[AlphaDecision, ...]:
        return tuple(self.core.evaluate_group(group))
```

该类不得继承 `Strategy`、不得拥有 policy、submitter、state persistence 或 audit collections。

- [ ] **Step 5: 运行 cross-market 与 native pipeline 测试**

```bash
uv run pytest tests/test_nautilus_cross_market.py tests/test_nautilus_strategy_base.py -v
```

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add -A src/polysignal_lab/nautilus_runtime/strategies src/polysignal_lab/nautilus_runtime/strategy/decision_pipeline.py tests/test_nautilus_cross_market.py
git commit -m "refactor: unify cross-market decision submission"
```

---

### Task 8: Remove Verified Dead Runtime and Legacy Persistence Code

**Files:**
- Delete: `src/polysignal_lab/nautilus_runtime/projection_recorder.py`
- Modify: `src/polysignal_lab/nautilus_runtime/strategy/decision_pipeline.py:28-52,230-254`
- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py:450-539`
- Modify: `src/polysignal_lab/app/services/persistence_service.py:126-139`
- Modify: affected `FOLDER_INDEX.md` files
- Test: existing Nautilus, storage, reporting and repair tests

**Interfaces:**
- Removes only symbols with no production or test callers after Task 7。
- No replacement interface is introduced。

- [ ] **Step 1: 对每个候选重新运行引用检查**

```bash
rg -n "NautilusProjectionRecorder|should_notify_core_fill|submit_approved_for_view|try_map_approved_spec|_token_id_from_view_instrument|_retry_market_instrument_requests|_call_subscription|persist_state\(" src tests scripts --glob '*.py'
```

Expected references before deletion:

- `NautilusProjectionRecorder`：definition/header only。
- `should_notify_core_fill`：definition/export only。
- `submit_approved_for_view`：definition/export only。
- `try_map_approved_spec`：definition only after Task 7。
- three private native strategy methods：definition and imported helper alias only。
- `PersistenceService.persist_state`：definition only。

如果任何符号出现真实 caller，将该符号从本任务删除列表中移除并记录 caller；不得机械删除。

- [ ] **Step 2: 删除 projection recorder 文件和 exports/index**

```bash
git rm src/polysignal_lab/nautilus_runtime/projection_recorder.py
```

从对应 `FOLDER_INDEX.md` 删除该文件条目。

- [ ] **Step 3: 删除无调用函数和相关 imports**

从 `decision_pipeline.py` 删除：

```python
should_notify_core_fill
submit_approved_for_view
DecisionPipeline.try_map_approved_spec
```

随后删除只为它们存在的 imports，例如 `AlphaFillEvent`、`OrderSubmittingStrategy`、`submit_approved_decision`；保留仍被 `map_approved_to_order_spec` 使用的类型和函数。

从 `native_strategy.py` 删除：

```python
_token_id_from_view_instrument
_retry_market_instrument_requests
_call_subscription
```

并删除对应 alias import，前提是没有其他方法使用同一 alias。

- [ ] **Step 4: 删除 legacy `persist_state()`**

从 `PersistenceService` 删除：

```python
def persist_state(
    self,
    *,
    wallet_snapshot: Any,
    open_positions: list[dict[str, Any]],
    market_cache: list[dict[str, Any]],
    signal_dedupe: Any,
) -> None:
    ...
```

保留只读 restore API，因为 Telegram、repair 和 reporting 仍有调用者。

- [ ] **Step 5: 运行 lint 与相关测试**

```bash
uv run ruff check src/polysignal_lab/nautilus_runtime src/polysignal_lab/app/services/persistence_service.py --select F401,F841
uv run pytest tests/test_nautilus_strategy_base.py tests/test_nautilus_node.py tests/test_storage_restore.py tests/test_storage_reporting_publish.py tests/test_repair_settlement_results.py -v
```

Expected: Ruff 在修改文件范围内无 F401/F841；tests PASS。

- [ ] **Step 6: 提交**

```bash
git add -A src/polysignal_lab/nautilus_runtime src/polysignal_lab/app/services/persistence_service.py
git commit -m "refactor: remove obsolete runtime compatibility code"
```

---

### Task 9: Consolidate Optional Nautilus Imports Without Breaking Python 3.11

**Files:**
- Create: `src/polysignal_lab/nautilus_runtime/optional_imports.py`
- Modify: `src/polysignal_lab/nautilus_runtime/live_node.py:36-214`
- Modify: `src/polysignal_lab/nautilus_runtime/node_builder.py:76-140`
- Test: `tests/test_nautilus_dependency_boundary.py`
- Test: `tests/test_nautilus_full_paper_runtime_smoke.py`

**Interfaces:**
- Produces: `LiveRuntimeSymbols` immutable dataclass and `load_live_runtime_symbols() -> LiveRuntimeSymbols`。
- Preserves module-level monkeypatch surfaces in `live_node.py` and `node_builder.py` until tests migrate。

- [ ] **Step 1: 写入默认 import 不加载 Nautilus 的保护测试**

在 `tests/test_nautilus_dependency_boundary.py` 增加：

```python
def test_optional_import_gateway_does_not_import_nautilus_at_module_import() -> None:
    sys.modules.pop("nautilus_trader", None)

    module = importlib.import_module(
        "polysignal_lab.nautilus_runtime.optional_imports"
    )

    assert module is not None
    assert "nautilus_trader" not in sys.modules
```

- [ ] **Step 2: 创建集中 gateway**

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module


@dataclass(frozen=True, slots=True)
class LiveRuntimeSymbols:
    live_node: object
    trader_id: Callable[[str], object]
    environment: object
    polymarket_data_factory: object
    sandbox_exec_factory: object


def load_live_runtime_symbols() -> LiveRuntimeSymbols:
    live_mod = import_module("nautilus_trader.live")
    common_mod = import_module("nautilus_trader.common")
    identifiers_mod = import_module("nautilus_trader.model.identifiers")
    polymarket_mod = import_module("nautilus_trader.adapters.polymarket")
    sandbox_mod = import_module("nautilus_trader.adapters.sandbox.factory")
    return LiveRuntimeSymbols(
        live_node=live_mod.LiveNode,
        trader_id=identifiers_mod.TraderId,
        environment=common_mod.Environment,
        polymarket_data_factory=polymarket_mod.PolymarketLiveDataClientFactory,
        sandbox_exec_factory=sandbox_mod.SandboxLiveExecClientFactory,
    )
```

- [ ] **Step 3: 让 `live_node._ensure_live_imports()` 委托 gateway**

保留现有 monkeypatch-first 分支；仅替换真实 import 分支：

```python
symbols = load_live_runtime_symbols()
LiveNode = symbols.live_node
TraderId = symbols.trader_id
Environment = symbols.environment
PolymarketLiveDataClientFactory = symbols.polymarket_data_factory
SandboxLiveExecClientFactory = symbols.sandbox_exec_factory
```

`node_builder.py` 不再复制相同 import 逻辑；它从 `live_node` 的已解析符号或 gateway 获取依赖。

- [ ] **Step 4: 更新 full runtime smoke monkeypatch**

测试继续 patch module globals，证明 gateway 不强迫真实 Nautilus import。不要在测试中 patch `importlib.import_module` 全局函数。

- [ ] **Step 5: 运行 dependency boundary 和 runtime assembly 测试**

```bash
uv run pytest tests/test_nautilus_dependency_boundary.py tests/test_nautilus_full_paper_runtime_smoke.py tests/test_nautilus_node.py -v
```

Expected: PASS；默认 Python 环境不需要安装 Nautilus。

- [ ] **Step 6: 提交**

```bash
git add src/polysignal_lab/nautilus_runtime/optional_imports.py src/polysignal_lab/nautilus_runtime/live_node.py src/polysignal_lab/nautilus_runtime/node_builder.py tests/test_nautilus_dependency_boundary.py tests/test_nautilus_full_paper_runtime_smoke.py
git commit -m "refactor: centralize optional Nautilus imports"
```

---

### Task 10: Remove High-Value Duplicate Code Without New Frameworks

**Files:**
- Modify: `src/polysignal_lab/data/market_discovery_helpers.py`
- Modify: `src/polysignal_lab/data/polymarket_market_discovery.py`
- Modify: `src/polysignal_lab/storage/sqlite_store.py`
- Modify: `src/polysignal_lab/nautilus_runtime/strategy/observability_hooks.py`
- Modify: `src/polysignal_lab/nautilus_runtime/observability.py`
- Test: `tests/test_market_data.py`
- Test: `tests/test_market_discovery_and_feeds.py`
- Test: `tests/test_storage_restore.py`
- Test: `tests/test_nautilus_observability.py`

**Interfaces:**
- Reuse existing pure discovery helpers rather than defining second copies。
- Produces one private SQLite payload write helper; public SQLiteStore API unchanged。
- Produces one `record_observability(...)` exception boundary; public observability API unchanged。

- [ ] **Step 1: 为重复 discovery 路径写等价性测试**

```python
def test_market_discovery_current_slot_slugs_uses_shared_helper() -> None:
    now = datetime(2026, 7, 9, 12, 3, tzinfo=UTC)

    direct = build_current_slot_slugs(
        assets=("BTC",),
        timeframes=("5m",),
        now=now,
    )
    discovery = MarketDiscovery(...)._current_slot_slugs(now)

    assert discovery == direct
```

使用现有 `MarketDiscovery` fixture 和 helper 的真实签名；断言必须是完整 tuple/list 等价。

- [ ] **Step 2: 删除 `MarketDiscovery` 内部复制实现并委托 helper**

```python
def _current_slot_slugs(self, now: datetime) -> list[str]:
    return build_current_slot_slugs(
        assets=tuple(self.config.assets),
        timeframes=tuple(self.config.timeframes),
        now=now,
    )
```

对 `gamma_events_from_json`、pagination、flatten helper 采用相同原则：只有在签名和语义完全一致时委托；每次只合并一个 clone group并运行测试。

- [ ] **Step 3: 为 SQLite 重复写入模板增加行为测试**

```python
def test_payload_insert_preserves_duplicate_detection(sqlite_store: SQLiteStore) -> None:
    payload = _sample_signal_payload()

    sqlite_store.insert_signal(payload)
    sqlite_store.insert_signal(payload)

    assert sqlite_store.counts()["signals"] == 1
```

同时保留已有“相同 key 不同 payload 抛 `DuplicateRecordError`”测试。

- [ ] **Step 4: 提取一个私有 `_insert_payload_row`**

```python
def _insert_payload_row(
    self,
    *,
    table: str,
    key_column: str,
    key_value: str,
    created_at: str,
    payload: object,
) -> None:
    payload_json = _json_dumps(payload)
    with self._lock, self._conn:
        existing = self._conn.execute(
            f"SELECT payload_json FROM {table} WHERE {key_column} = ?",
            (key_value,),
        ).fetchone()
        if existing is not None:
            if str(existing["payload_json"]) != payload_json:
                raise DuplicateRecordError(table, key_column, key_value)
            return
        self._conn.execute(
            f"INSERT INTO {table} ({key_column}, created_at, payload_json) VALUES (?, ?, ?)",
            (key_value, created_at, payload_json),
        )
```

只让 schema 形状相同的 insert 方法调用它；不要把不同列或 upsert 语义强塞进同一 helper。

- [ ] **Step 5: 合并 observability exception boundary**

`strategy/observability_hooks.py` 中所有可能发生 SQLite/OSError 的写入都改成：

```python
record_observability(
    strategy,
    lambda obs: obs.record_decision(decision, accepted),
)
```

`record_rejected()` 也进入同一边界，避免它与其他 recorder 异常策略不一致。

- [ ] **Step 6: 分组运行测试**

```bash
uv run pytest tests/test_market_data.py tests/test_market_discovery_and_feeds.py -v
uv run pytest tests/test_storage_restore.py tests/test_storage_reporting_publish.py -v
uv run pytest tests/test_nautilus_observability.py tests/test_nautilus_strategy_base.py -v
```

Expected: 全部 PASS。

- [ ] **Step 7: 重跑 clone 报告记录改善**

```bash
uvx pyscn@latest analyze --select clones --clone-threshold 0.65 --json src/polysignal_lab tests
```

Expected: clone groups 少于基线 40，duplication percentage 低于 13.2%；如果某组仍存在，记录原因，不为了指标进行错误抽象。

- [ ] **Step 8: 提交**

```bash
git add src/polysignal_lab/data/market_discovery_helpers.py src/polysignal_lab/data/polymarket_market_discovery.py src/polysignal_lab/storage/sqlite_store.py src/polysignal_lab/nautilus_runtime/strategy/observability_hooks.py src/polysignal_lab/nautilus_runtime/observability.py tests
git commit -m "refactor: consolidate repeated discovery and persistence paths"
```

---

### Task 11: Separate Legacy Snapshot Adapters from PTB Alpha Core

**Files:**
- Create: `src/polysignal_lab/alpha/legacy_snapshot_adapter.py`
- Modify: `src/polysignal_lab/alpha/ptb_diff_core.py:279-365`
- Modify: `src/polysignal_lab/alpha/helpers.py`
- Modify: `src/polysignal_lab/alpha/__init__.py` only if public exports currently expose these functions
- Test: existing PTB and Alpha equivalence tests

**Interfaces:**
- Produces:
  - `market_view_from_snapshot(snapshot: MarketSnapshot) -> MarketView`
  - `decision_to_signal_candidate(decision: AlphaDecision) -> SignalCandidate`
- `PTBDiffAlphaCore` retains only config、evaluate and strategy-local state。

- [ ] **Step 1: 写入 import boundary 测试**

```python
def test_legacy_snapshot_adapter_owns_snapshot_conversion() -> None:
    from polysignal_lab.alpha.legacy_snapshot_adapter import (
        market_view_from_snapshot,
    )
    from polysignal_lab.alpha.ptb_diff_core import PTBDiffAlphaCore

    assert callable(market_view_from_snapshot)
    assert not hasattr(PTBDiffAlphaCore, "market_view_from_snapshot")
```

如果函数当前是 module-level，不断言 class attribute；改为检查 `ptb_diff_core.__all__` 或 imports 不再从该模块取得转换函数。

- [ ] **Step 2: 移动函数，代码保持逐字等价**

将 `ptb_diff_core.py:279-365` 的两个转换函数及其专用 imports 移到新文件。新文件头部仅 import：

```python
from polysignal_lab.alpha.types import AlphaDecision, MarketView
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot
```

保留原函数签名和函数体，第一提交不改变转换行为。

- [ ] **Step 3: 更新所有 callers**

将：

```python
from polysignal_lab.alpha.ptb_diff_core import market_view_from_snapshot
```

改为：

```python
from polysignal_lab.alpha.legacy_snapshot_adapter import market_view_from_snapshot
```

`alpha/helpers.py` 不再依赖 PTB-specific module。

- [ ] **Step 4: 运行 Alpha 与等价性测试**

```bash
uv run pytest tests/test_alpha_ptb_diff.py tests/test_alpha_types.py tests/test_alpha_equivalence.py -v
```

如果仓库中的实际文件名不同，先用 `rg -l "market_view_from_snapshot" tests` 获取精确测试文件并运行全部命中测试。

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/polysignal_lab/alpha/legacy_snapshot_adapter.py src/polysignal_lab/alpha/ptb_diff_core.py src/polysignal_lab/alpha/helpers.py src/polysignal_lab/alpha/__init__.py tests
git commit -m "refactor: move legacy snapshot adapters out of PTB core"
```

---

### Task 12: Split VWAP Trade History and State Serialization from the Core

**Files:**
- Create: `src/polysignal_lab/alpha/vwap_trade_history.py`
- Create: `src/polysignal_lab/alpha/vwap_state.py`
- Modify: `src/polysignal_lab/alpha/vwap_momentum_core.py`
- Test: `tests/test_alpha_vwap_momentum.py`
- Test: any state restore/equivalence tests returned by `rg -l "VWAPMomentumAlphaCore|vwap_momentum" tests`

**Interfaces:**
- Produces:
  - `TradeHistory.append(trade: TradeView) -> bool`，重复 trade 返回 `False`。
  - `TradeHistory.recent(*, now: datetime, window: timedelta) -> tuple[TradeView, ...]`。
  - `encode_vwap_state(state: Mapping[str, object]) -> dict[str, object]`。
  - `decode_vwap_state(payload: Mapping[str, object]) -> dict[str, object]`，未知 schema version 抛 `ValueError`。
- Core formulas and public `VWAPMomentumAlphaCore` behavior remain unchanged。

- [ ] **Step 1: 先为现有 trade dedupe 和 state round-trip 写 characterization tests**

```python
def test_vwap_duplicate_trade_does_not_change_signal_inputs() -> None:
    core = _core()
    view = _view_with_trades((_trade("trade-1"),))

    first = core.evaluate(view)
    second = core.evaluate(view)

    assert second == first


def test_vwap_state_round_trip_preserves_pending_hedge() -> None:
    core = _core_with_pending_hedge()
    restored = _core()

    restored.load_state(core.save_state())

    assert restored.save_state() == core.save_state()
```

这些测试必须在移动代码前通过，作为行为基线。

- [ ] **Step 2: 创建 `TradeHistory` 并写直接单元测试**

```python
@dataclass(slots=True)
class TradeHistory:
    maxlen: int
    _trades: deque[TradeView] = field(init=False)
    _keys: set[tuple[object, ...]] = field(default_factory=set)

    def __post_init__(self) -> None:
        self._trades = deque(maxlen=self.maxlen)

    def append(self, trade: TradeView) -> bool:
        key = (trade.ts, trade.price, trade.size, trade.side)
        if key in self._keys:
            return False
        if len(self._trades) == self.maxlen:
            removed = self._trades[0]
            self._keys.discard((removed.ts, removed.price, removed.size, removed.side))
        self._trades.append(trade)
        self._keys.add(key)
        return True

    def recent(self, *, now: datetime, window: timedelta) -> tuple[TradeView, ...]:
        cutoff = now - window
        return tuple(
            trade
            for trade in self._trades
            if trade.ts is not None and trade.ts >= cutoff
        )
```

测试 append、duplicate、maxlen eviction、window filtering。

- [ ] **Step 3: 让 core 委托 `TradeHistory`，不同时改公式**

用 `self._trade_history` 替换现有 deque/set 字段；所有 VWAP/momentum 计算继续接收 tuple trades。删除只为旧容器存在的 helper。

- [ ] **Step 4: 创建显式 state codec**

```python
VWAP_STATE_VERSION = 1


def encode_vwap_state(state: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema_version": VWAP_STATE_VERSION,
        "payload": dict(state),
    }


def decode_vwap_state(payload: Mapping[str, object]) -> dict[str, object]:
    version = payload.get("schema_version")
    if version != VWAP_STATE_VERSION:
        raise ValueError(f"unsupported VWAP state schema_version: {version!r}")
    raw = payload.get("payload")
    if not isinstance(raw, Mapping):
        raise ValueError("VWAP state payload must be a mapping")
    return dict(raw)
```

如果当前 bridge 已提供外层 schema envelope，此 codec 只编码 core 内部 payload，避免重复外层版本。

- [ ] **Step 5: 将 `save_state/load_state` 解析委托 codec**

Core 保留字段赋值和策略不变量校验；JSON shape/version 解析移出。未知 version、错误字段类型继续 fail closed。

- [ ] **Step 6: 运行全部 VWAP 测试**

```bash
uv run pytest $(rg -l "VWAPMomentumAlphaCore|vwap_momentum" tests --glob '*.py') -v
```

Expected: PASS；公式输出、hedge 状态和 event callbacks 不变。

- [ ] **Step 7: 重跑复杂度报告**

```bash
uvx pyscn@latest analyze --select complexity --min-complexity 5 --json src/polysignal_lab/alpha
```

Expected: `vwap_momentum_core.py` 文件行数和职责减少；不得以增加更多高复杂函数换取文件缩短。

- [ ] **Step 8: 提交**

```bash
git add src/polysignal_lab/alpha/vwap_trade_history.py src/polysignal_lab/alpha/vwap_state.py src/polysignal_lab/alpha/vwap_momentum_core.py tests
git commit -m "refactor: separate VWAP history and state codecs"
```

---

### Task 13: Clean Current Ruff Dead Imports and Local Variables

**Files:**
- Modify only files reported by the fresh Ruff command
- Test: targeted tests for each modified package

**Interfaces:**
- No public interface changes。

- [ ] **Step 1: 生成最新清单，不使用审查时的旧输出直接修改**

```bash
uv run ruff check src/polysignal_lab --select F401,F841 --output-format=concise
```

Expected baseline: current review found 36 issues, but implementation必须以当前 worktree 输出为准。

- [ ] **Step 2: 使用 Ruff safe fixes 处理纯 import 项**

```bash
uv run ruff check src/polysignal_lab --select F401 --fix
```

检查 diff，确认没有删除 `TYPE_CHECKING` 下实际用于字符串 annotation 或动态 export 的 import；若 Ruff 误判，恢复该行并添加精确 `# noqa: F401` 及原因。

- [ ] **Step 3: 手工删除 F841 局部变量**

已知候选：

```python
# src/polysignal_lab/paper/report.py
wins = row["win_count"]
row["win_rate"] = wins / count if count else 0.0
```

删除未使用的：

```python
losses = row["loss_count"]
```

- [ ] **Step 4: 运行 Ruff 和受影响测试**

```bash
uv run ruff check src/polysignal_lab --select F401,F841
uv run pytest tests/test_reporting.py tests/test_storage_reporting_publish.py tests/test_nautilus_node.py tests/test_nautilus_strategy_base.py -v
```

Expected: Ruff PASS；tests PASS。

- [ ] **Step 5: 提交**

```bash
git add src/polysignal_lab
git commit -m "chore: remove stale imports and local variables"
```

---

### Task 14: Final Architecture Verification and Documentation Refresh

**Files:**
- Modify: `docs/architecture-review-2026-07-09.md`
- Modify: relevant `FOLDER_INDEX.md` files
- Create: `docs/architecture-remediation-results-2026-07-09.md`

**Interfaces:**
- Produces a durable before/after report with commands, measured metrics, remaining accepted debt and deferred tasks。

- [ ] **Step 1: 运行完整静态分析**

```bash
uvx pyscn@latest analyze --select communities --json src/polysignal_lab
uvx pyscn@latest analyze --select deps,cbo,lcom --json src/polysignal_lab
uvx pyscn@latest analyze --select complexity,deadcode,clones --min-complexity 5 --min-severity info --clone-threshold 0.65 --json src/polysignal_lab tests
uvx vulture@latest src/polysignal_lab --min-confidence 80 --sort-by-size
uv run ruff check src/polysignal_lab --select F401,F841
```

Expected gates:

- dependency cycles：0。
- high-coupling classes：不高于基线 8。
- clone groups：低于基线 40。
- cloned fragment percentage：低于基线 13.2%。
- high-risk complexity functions：不高于基线 9。
- Vulture 80%：无确认的 production unused import/class/function。
- Ruff F401/F841：0。

- [ ] **Step 2: 运行核心 Python 测试集合**

```bash
uv run pytest \
  tests/test_nautilus_custom_data.py \
  tests/test_nautilus_market_view_assembler.py \
  tests/test_nautilus_cross_market.py \
  tests/test_nautilus_market_catalog.py \
  tests/test_nautilus_market_rotation.py \
  tests/test_nautilus_decision_policy.py \
  tests/test_nautilus_strategy_base.py \
  tests/test_nautilus_node.py \
  tests/test_nautilus_full_paper_runtime_smoke.py \
  tests/test_nautilus_dependency_boundary.py \
  tests/test_nautilus_observability.py \
  tests/test_storage_restore.py \
  tests/test_storage_reporting_publish.py \
  -v
```

Expected: PASS。

- [ ] **Step 3: 运行全套测试**

```bash
uv run pytest -q
```

Expected: PASS；若有环境依赖 skip，结果文档记录精确 skip 数量和原因。若存在预先失败，必须在执行任何任务前保存 baseline 输出，最终报告区分 pre-existing 与新增失败。

- [ ] **Step 4: 在支持的 Python/Nautilus 环境执行真实 bridge 验证**

运行项目现有 Nautilus optional/integration 命令；若仓库没有统一命令，至少执行：

```bash
uv run --python 3.12 pytest \
  tests/test_nautilus_full_paper_runtime_smoke.py \
  tests/test_nautilus_cache_market_data.py \
  tests/test_nautilus_dependency_boundary.py \
  -v
```

验证并记录：

- node 只含 `POLYMARKET` data client。
- exec client 是 sandbox，而不是 authenticated Polymarket client。
- Cache book/trade API 与 projection 兼容。
- account/portfolio 在首个策略订单前可用。
- `reconciliation=False` 的实际启动行为符合 sandbox 预期。

- [ ] **Step 5: 更新架构审查文档中的过期数字和结论**

`docs/architecture-review-2026-07-09.md` 必须更新：

- 当前 `PolySignalNativeStrategy` 行数、CBO、LCOM。
- lazy import 是 optional-dependency boundary，不再笼统标记为必须改成 static import。
- `OrderBookRegistry` 是兼容/只读重复路径，而不是当前生产执行 truth。
- `scheduler` alias 已映射到 Nautilus 或 bounded smoke。
- 列出尚未完成的 deferred debt，而不是把已删除文件继续列为当前问题。

- [ ] **Step 6: 写入 before/after 结果文档**

`docs/architecture-remediation-results-2026-07-09.md` 使用以下固定结构：

```markdown
# NautilusTrader Architecture Remediation Results

## Scope
## Commits
## Verification Commands
## Before/After Metrics
## Fixed Findings
## Accepted Boundaries
## Remaining Debt
## Test Results
## Known Environment Limitations
```

必须填入实际命令输出和实际 commit hash，不得写预测值。

- [ ] **Step 7: 更新 folder indexes**

对新增/删除文件更新：

- `src/polysignal_lab/alpha/FOLDER_INDEX.md`
- `src/polysignal_lab/nautilus_runtime/FOLDER_INDEX.md`
- `src/polysignal_lab/nautilus_runtime/strategy/FOLDER_INDEX.md`
- 其他受影响目录的 `FOLDER_INDEX.md`

- [ ] **Step 8: 最终提交**

```bash
git add docs src/polysignal_lab/**/FOLDER_INDEX.md
git commit -m "docs: record Nautilus architecture remediation results"
```

---

## Execution Order and Review Gates

按以下顺序执行，不得把所有任务合并成一次大改：

1. Tasks 1–3：确定性和数据正确性。
2. Tasks 4–5：共享 policy 与 assembly 契约。
3. Task 6：Actor-safe discovery；单独审查线程生命周期和 shutdown。
4. Task 7：Cross-market pipeline 统一。
5. Tasks 8–10：死代码和重复代码。
6. Tasks 11–12：大型 Alpha 模块拆分。
7. Task 13：机械清理。
8. Task 14：全量验证和文档刷新。

每个 task 完成后执行：

```bash
git diff --check
git status --short
```

确认提交只包含该 task 的文件；然后请求 code review，再进入下一 task。

## Explicitly Deferred

以下项目不在本计划中直接实施，除非执行过程中出现生产 correctness 证据：

- 将 shared policy 完整改造成 Nautilus MessageBus request/outcome RPC。Task 4 先建立唯一实例和强制注入；MessageBus 化应另写设计规格。
- 把 SQLite 全部替换为 Nautilus database。当前 SQLite 是审计和报告存储，不是执行 truth。
- 删除所有 `paper_*` schema 字段。需要单独版本化 API/数据库迁移计划。
- 把 Binance spot feed 改写为 Nautilus adapter。只有当它重新进入生产策略输入时才实施。
- 拆分 `TelegramBotService` 和 Dashboard。它们是维护债务，但不阻塞 Nautilus 边界正确性。
- 为降低指标而抽象所有 clone groups。仅处理跨文件、高相似度且行为应保持一致的组。

## Self-Review Results

- **Spec coverage:** 已覆盖审查中的确定性时间、绝对 freshness、catalog replacement、共享 policy、runtime class 契约、Actor 阻塞 I/O、cross-market 重复 wrapper、确认死代码、optional import 重复、主要 clone groups、PTB adapter 泄漏、VWAP 大型模块、Ruff 残留和最终验证。SQLite schema 命名迁移、完整 MessageBus 化和 Telegram/Dashboard 拆分被明确延期。
- **Placeholder scan:** 文档没有未决占位符，也没有缺少具体测试内容的步骤。所有实现任务包含精确接口、代码形状、命令和预期结果。
- **Type consistency:** `MarketDiscoveryResult`、`MarketDiscoveryWorker`、`MarketGroupViewAssembler`、shared `DecisionPolicyActor`、`TradeHistory` 和 state codec 的签名在定义与后续使用中保持一致。
