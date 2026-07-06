# 多 Agent 并行重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于 Nautilus 合规审查报告的整改清单，在 git worktree 中用多 agent 并行重构 6 个维度

**Architecture:** 双阶段并行执行：Phase 1 的 5 个 agent 操作零文件冲突的文件集，在各自独立的 git worktree 中真正并行，每个 agent 提交原子化 commit 并运行 pytest 验证；Phase 2 在 Phase 1 合并后的代码上执行，修改 native_strategy.py。

**Tech Stack:** Python 3.11+, pytest, NautilusTrader (optional), git worktree

## Global Constraints

- 每个 agent 在自己的独立 git worktree 中工作，禁止在同一目录并发修改
- 每个 agent 必须 test-first（bugfix）或 test-alongside（refactor），提交前运行 `pytest` 确认通过
- 每个 agent 提交原子化 commit（一个变更一个 commit / 最多按文件组分批 commit）
- 禁止修改 `@refs/` 目录
- 重命名引用时，必须同时更新所有 import 和 test 引用，不得遗漏

---

## Phase 1 — 5 Agent 并行

### Task 1: Agent A — 重命名 PolySignalNautilusStrategy 冲突

**文件清单：**

需要修改的源文件 | 修改内容
---|---
`src/polysignal_lab/nautilus_bridge/strategy_base.py:35` | `PolySignalNautilusStrategy` → `LegacyPolySignalNautilusStrategy`
`src/polysignal_lab/nautilus_bridge/strategies/ptb_diff.py:7,11` | 更新 import 和基类名
`src/polysignal_lab/nautilus_runtime/strategies/base.py:38` | `PolySignalNautilusStrategy` → `CompatPolySignalNautilusStrategy`
`src/polysignal_lab/nautilus_runtime/strategies/__init__.py:1,30` | 更新导出
`src/polysignal_lab/nautilus_runtime/strategies/ptb_diff.py:9,13` | 更新 import 和基类
`src/polysignal_lab/nautilus_runtime/strategies/vwap_momentum.py:9,13` | 同上
`src/polysignal_lab/nautilus_runtime/strategies/fibonacci_bot.py:9,13` | 同上
`src/polysignal_lab/nautilus_runtime/strategies/late_consensus.py:9,13` | 同上
`src/polysignal_lab/nautilus_runtime/strategies/binary_momentum.py:9,13` | 同上
`src/polysignal_lab/nautilus_runtime/strategies/low_side_dual_reversion.py:9,13` | 同上
`src/polysignal_lab/nautilus_runtime/strategies/skew_mean_reversion.py:9,13` | 同上
`src/polysignal_lab/nautilus_runtime/strategies/ninety_nine_cent_sniper.py:9,13` | 同上
`src/polysignal_lab/nautilus_runtime/strategies/dump_hedge.py:9,13` | 同上
`src/polysignal_lab/nautilus_runtime/strategies/pre_order_market.py:9,13` | 同上
`src/polysignal_lab/nautilus_runtime/strategies/mid_price_sizing.py:9,13` | 同上
`src/polysignal_lab/nautilus_runtime/strategies/one_cent_buy.py:9,13` | 同上

测试文件 | 修改内容
---|---
`tests/test_nautilus_strategy_base.py:26,193,205,223,232,277` | 更新两条 import 路径：`nautilus_bridge.strategy_base` → `LegacyPolySignalNautilusStrategy`；`nautilus_runtime.strategies.base` → `CompatPolySignalNautilusStrategy`
`tests/test_nautilus_strategy_wrappers.py:24,369,400,438,465,499,536,575,607,617,639,661,685,722,783,831,873` | 更新 import 和所有实例化引用

> 注意：`test_nautilus_strategy_base.py` 从两个路径都导入了 `PolySignalNautilusStrategy`（第 26 行从 bridge 路径、第 277 行从 runtime 路径）。这些必须重命名为不同的别名。

**接口:**
- 消耗: 无（纯重命名）
- 产出: `LegacyPolySignalNautilusStrategy` (bridge), `CompatPolySignalNautilusStrategy` (runtime compat)

---

- [ ] **Step 1: 确认 worktree 分支和当前文件结构**

进入 worktree 目录，确认所有 13 个 runtime 策略文件 + 1 个 bridge 策略文件 + 测试文件都存在。

```bash
cd /path/to/worktree
ls src/polysignal_lab/nautilus_runtime/strategies/*.py | wc -l
# Expected: 14 (base + 13 strategy wrappers)
ls src/polysignal_lab/nautilus_bridge/strategies/*.py
# Expected: ptb_diff.py (at minimum)
```

- [ ] **Step 2: 重命名 bridge/strategy_base.py 中的类**

```bash
# 将 line 35 的类名和 4+5 行的 imports 更新
# 打开文件编辑
```

修改 `src/polysignal_lab/nautilus_bridge/strategy_base.py:35`:
```python
class LegacyPolySignalNautilusStrategy(_NautilusBase):
```

- [ ] **Step 3: 更新 bridge/ptb_diff.py 的 import 和基类**

```python
# src/polysignal_lab/nautilus_bridge/strategies/ptb_diff.py:7
from polysignal_lab.nautilus_bridge.strategy_base import LegacyPolySignalNautilusStrategy

# line 11
class PTBDiffNautilusStrategy(LegacyPolySignalNautilusStrategy):
```

- [ ] **Step 4: 重命名 runtime/strategies/base.py 中的类和所有引用**

修改 `src/polysignal_lab/nautilus_runtime/strategies/base.py:38`:
```python
class CompatPolySignalNautilusStrategy:
```

修改 `src/polysignal_lab/nautilus_runtime/strategies/__init__.py:1,30`:
```python
# line 1
from polysignal_lab.nautilus_runtime.strategies.base import DEFAULT_DATA_NAMES, CompatPolySignalNautilusStrategy
# line 30
    "CompatPolySignalNautilusStrategy",
```

- [ ] **Step 5: 更新所有 13 个 runtime 策略文件的 import 行**

每个策略文件第 9 行统一替换为:
```python
from polysignal_lab.nautilus_runtime.strategies.base import DEFAULT_DATA_NAMES, CompatPolySignalNautilusStrategy
```

文件列表（确保全部处理）:
- `ptb_diff.py`, `vwap_momentum.py`, `fibonacci_bot.py`, `late_consensus.py`, `binary_momentum.py`
- `low_side_dual_reversion.py`, `skew_mean_reversion.py`, `ninety_nine_cent_sniper.py`, `dump_hedge.py`
- `pre_order_market.py`, `mid_price_sizing.py`, `one_cent_buy.py`

```bash
# 用 sed 批量替换全部 13 个文件
sed -i 's/from polysignal_lab.nautilus_runtime.strategies.base import DEFAULT_DATA_NAMES, PolySignalNautilusStrategy/from polysignal_lab.nautilus_runtime.strategies.base import DEFAULT_DATA_NAMES, CompatPolySignalNautilusStrategy/' \
  src/polysignal_lab/nautilus_runtime/strategies/*.py
```

- [ ] **Step 6: 更新测试文件**

修改 `tests/test_nautilus_strategy_base.py:26`:
```python
from polysignal_lab.nautilus_bridge.strategy_base import (
    LegacyPolySignalNautilusStrategy,
    is_nautilus_available,
)
```

替换 test 文件中所有 `PolySignalNautilusStrategy(` 为 `LegacyPolySignalNautilusStrategy(`（约 7 处）。

修改第 277 行:
```python
    CompatPolySignalNautilusStrategy as RuntimeStrategy,
```

修改 `tests/test_nautilus_strategy_wrappers.py:24`:
```python
from polysignal_lab.nautilus_runtime.strategies.base import DEFAULT_DATA_NAMES, CompatPolySignalNautilusStrategy as PolySignalNautilusStrategy
```

- [ ] **Step 7: 运行 `pytest` 确认通过**

```bash
pytest tests/test_nautilus_strategy_base.py tests/test_nautilus_strategy_wrappers.py -v 2>&1 | tail -30
# Expected: all tests PASS
```

- [ ] **Step 8: 提交原子化 commit**

```bash
git add src/polysignal_lab/nautilus_bridge/strategy_base.py src/polysignal_lab/nautilus_bridge/strategies/ptb_diff.py src/polysignal_lab/nautilus_runtime/strategies/ tests/
git commit -m "fix: rename PolySignalNautilusStrategy to resolve package collision

nautilus_bridge/strategy_base.py → LegacyPolySignalNautilusStrategy
nautilus_runtime/strategies/base.py → CompatPolySignalNautilusStrategy

Resolves P0 finding from compliance review: two identically-named
classes in different packages create import-resolution ambiguity."
```

---

### Task 2: Agent B — exit_policy.py TP/SL → Nautilus Bracket Orders

**文件:**
- Modify: `src/polysignal_lab/nautilus_runtime/exit_policy.py`
- Test: `tests/test_nautilus_exit_policy.py`

**接口:**
- 消耗: 无（不修改 native_strategy.py 的调用方；调用方更新在 Phase 2 Agent D 完成）
- 产出: 重构后的 `ExitPolicyConfig`, `NautilusExitDecision`, `ExitReason`；新增 bracket order helper 函数 `bracket_attachment_for(position, config, book) → list[TaggedBracketOrder]`；移除 `_float()` 辅助函数

**注意：本次重构不修改 native_strategy.py 中的调用方（504-521 行）。Agent B 只修改 `exit_policy.py` 本身。调用方适配在 Phase 2 的 Agent D 中完成。**

---

- [ ] **Step 1: 读取当前所有 exit_policy.py 代码**

```bash
cat -n src/polysignal_lab/nautilus_runtime/exit_policy.py
```

- [ ] **Step 2: 分析 Nautilus bracket order 模式和替换方案**

Nautilus 使用 `order_factory` 中的 bracket order 创建方式：`TakeProfitOrder`, `StopLimitOrder`, `StopMarketOrder`。但由于本项目运行在 sandbox 模式，实际 bracket orders 通过 `order_factory` 接口提交。

本项目不需要直接在 exit_policy 中使用 Nautilus order 类（避免导入 Nautilus），而是暴露一层纯数据接口：

```python
@dataclass(frozen=True, slots=True)
class TaggedBracketOrder:
    """Pure-data description of what bracket to attach. No Nautilus dependency."""
    reason: ExitReason
    position_id: str
    instrument_id: str
    quantity: float
    limit_price: float
    order_type: str  # "TAKE_PROFIT" or "STOP_LIMIT" or "STOP_MARKET"
    time_in_force: str = "GTD"
    expire_secs: int = 86400
```

- [ ] **Step 3: 先写测试（test-first）**

创建 `tests/test_nautilus_exit_policy.py` 中的新测试，验证 bracket 辅助函数：

```python
# 新增测试函数——验证 bracket 辅助函数

def test_bracket_attachment_for_take_profit() -> None:
    """TAKE_PROFIT threshold → produces bracket order spec."""
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    config = _config()  # take_profit_price=0.90
    book = _book(0.91)
    position = _position(now, entry_price=0.50)

    brackets = exit_policy.bracket_attachments_for(position, book, now, config)

    assert len(brackets) == 1
    tp = brackets[0]
    assert tp.order_type == "TAKE_PROFIT"
    assert tp.limit_price == 0.91
    assert tp.reason == ExitReason.TAKE_PROFIT
    assert tp.position_id == "pos-1"


def test_bracket_attachment_for_stop_loss() -> None:
    """STOP_LOSS threshold → produces bracket order spec."""
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    config = _config()  # stop_loss_price=0.35
    book = _book(0.34)
    position = _position(now, entry_price=0.50)

    brackets = exit_policy.bracket_attachments_for(position, book, now, config)

    assert len(brackets) == 1
    sl = brackets[0]
    assert sl.order_type == "STOP_LIMIT"
    assert sl.limit_price == 0.34
    assert sl.reason == ExitReason.STOP_LOSS
```

- [ ] **Step 4: 运行测试确认失败**

```bash
pytest tests/test_nautilus_exit_policy.py::test_bracket_attachment_for_take_profit -v
# Expected: FAIL (function not defined)
```

- [ ] **Step 5: 重构 exit_policy.py**

```python
# 在 import 区域后添加新的 pure-data 类型

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast

from polysignal_lab.alpha.types import SideBookView
from polysignal_lab.utils import parse_dt


class ExitReason(StrEnum):
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    MAX_HOLD_TIME = "max_hold_time"


@dataclass(frozen=True, slots=True)
class ExitPolicyConfig:
    mode: str
    take_profit_enabled: bool
    stop_loss_enabled: bool
    take_profit_price: float
    stop_loss_price: float
    max_hold_time_sec: int


@dataclass(frozen=True, slots=True)
class NautilusExitDecision:
    reason: ExitReason
    position_id: str
    instrument_id: str
    quantity: float
    limit_price: float
    ts_event: datetime


@dataclass(frozen=True, slots=True)
class TaggedBracketOrder:
    """Pure-data description of a bracket order to attach.

    No Nautilus dependency — consumed by the Nautilus bridge layer
    when creating actual order_factory calls.
    """
    reason: ExitReason
    position_id: str
    instrument_id: str
    quantity: float
    limit_price: float
    order_type: str  # "TAKE_PROFIT" | "STOP_LIMIT" | "STOP_MARKET"
    time_in_force: str = "GTD"
    expire_secs: int = 86400


# ── Evaluate-and-return (kept for backward compat, caller to be migrated in Phase 2) ──

def evaluate_exit_decision(
    position: Mapping[str, object],
    book: SideBookView,
    now: datetime,
    config: ExitPolicyConfig,
) -> NautilusExitDecision | None:
    if bool(position.get("is_closed")):
        return None
    best_bid = book.best_bid
    if best_bid is None or best_bid <= 0:
        return None
    entry_price = _float(position.get("avg_entry_price"))
    quantity = abs(_float(position.get("quantity")))
    instrument_id = str(position.get("instrument_id") or "")
    position_id = str(position.get("position_id") or position.get("paper_position_id") or "")
    if entry_price <= 0 or quantity <= 0 or not instrument_id or not position_id:
        return None
    if config.take_profit_enabled and best_bid >= config.take_profit_price:
        return _decision(ExitReason.TAKE_PROFIT, position_id, instrument_id, quantity, best_bid, now)
    if config.stop_loss_enabled and best_bid <= config.stop_loss_price:
        return _decision(ExitReason.STOP_LOSS, position_id, instrument_id, quantity, best_bid, now)
    opened_at = _opened_at(position)
    if opened_at is not None and (now - opened_at).total_seconds() >= config.max_hold_time_sec:
        return _decision(ExitReason.MAX_HOLD_TIME, position_id, instrument_id, quantity, best_bid, now)
    return None


# ── New: bracket attachment helpers ──

def bracket_attachments_for(
    position: Mapping[str, object],
    book: SideBookView,
    now: datetime,
    config: ExitPolicyConfig,
) -> list[TaggedBracketOrder]:
    """Return bracket order descriptions for a position, if thresholds are met.

    This replaces manual evaluate_exit_decision with Nautilus-native bracket
    semantics. Callers attach bracket orders at submission time instead of
    polling exit conditions per-evaluation-cycle.
    """
    result: list[TaggedBracketOrder] = []
    if bool(position.get("is_closed")):
        return result
    best_bid = book.best_bid
    if best_bid is None or best_bid <= 0:
        return result
    quantity = abs(_float(position.get("quantity")))
    instrument_id = str(position.get("instrument_id") or "")
    position_id = str(position.get("position_id") or position.get("paper_position_id") or "")
    if quantity <= 0 or not instrument_id or not position_id:
        return result
    if config.take_profit_enabled:
        result.append(TaggedBracketOrder(
            reason=ExitReason.TAKE_PROFIT,
            position_id=position_id,
            instrument_id=instrument_id,
            quantity=quantity,
            limit_price=config.take_profit_price,
            order_type="TAKE_PROFIT",
        ))
    if config.stop_loss_enabled:
        result.append(TaggedBracketOrder(
            reason=ExitReason.STOP_LOSS,
            position_id=position_id,
            instrument_id=instrument_id,
            quantity=quantity,
            limit_price=config.stop_loss_price,
            order_type="STOP_LIMIT",
        ))
    return result


def _decision( ... ) -> NautilusExitDecision:
    """(unchanged)"""
    ...


def _opened_at(position: Mapping[str, object]) -> datetime | None:
    """(unchanged)"""
    ...


def _float(value: object) -> float:
    """(unchanged — still used by evaluate_exit_decision; remove when caller migrates)"""
    ...
```

- [ ] **Step 6: 运行测试确认通过**

```bash
pytest tests/test_nautilus_exit_policy.py -v
# Expected: all tests PASS (existing + new)
```

- [ ] **Step 7: 提交原子化 commit**

```bash
git add src/polysignal_lab/nautilus_runtime/exit_policy.py tests/test_nautilus_exit_policy.py
git commit -m "refactor: add bracket_attachments_for to exit_policy.py

Replace inline TP/SL polling logic with bracket-order helper that
exposes TaggedBracketOrder specs for Nautilus order_factory integration.
Retains evaluate_exit_decision for Phase 2 migration.
Part of P1 remediation: exit_policy TP/SL → Nautilus bracket orders."
```

---

### Task 3: Agent C — Dashboard 数据源修复 + 死路由清理

**文件:**
- Modify: `src/polysignal_lab/nautilus_runtime/observability.py:119-132, 133-140`
- Modify: `src/polysignal_lab/dashboard/app.py`
- Test: `tests/test_nautilus_observability.py`

**接口:**
- 消耗: 无
- 产出: 清理后的 `NautilusEventStoreAdapter._routes`（移除 "orders"/"fills"/"positions" 路由）；Dashboard 端点指向 `nautilus_*` 表或 Nautilus cache

---

- [ ] **Step 1: 读取 observability.py 的 _routes 定义和 dashboard app.py 的端点**

```bash
cat -n src/polysignal_lab/nautilus_runtime/observability.py | head -145
grep -n "def \|@router\|@app\|paper_orders\|paper_fills\|paper_positions\|nautilus_order\|nautilus_fill\|nautilus_position" src/polysignal_lab/dashboard/app.py
```

- [ ] **Step 2: 先写测试验证当前路由行为**

```python
# 在 tests/test_nautilus_observability.py 中新增

def test_nautilus_event_store_adapter_routes_exclude_paper_tables() -> None:
    """NautilusEventStoreAdapter._routes must not contain paper_* mappings."""
    from polysignal_lab.nautilus_runtime.observability import NautilusEventStoreAdapter
    
    class _FakePersistence:
        def insert_signal(self, signal): pass
        def insert_rejected_signal(self, rejected): pass
        def upsert_paper_order(self, order): pass
        def insert_paper_fill(self, fill): pass
        def upsert_paper_position(self, position): pass
        def insert_paper_trade_result(self, result): pass
        def insert_system_event(self, event): pass
        def append_log(self, stream, payload): pass
    
    adapter = NautilusEventStoreAdapter(_FakePersistence())
    routes = adapter._routes
    
    assert "orders" not in routes, "orders→upsert_paper_order route must be removed"
    assert "fills" not in routes, "fills→insert_paper_fill route must be removed"
    assert "positions" not in routes, "positions→upsert_paper_position route must be removed"
    # Keep signals, rejected_signals, settlements, health, nautilus_*
    assert "signals" in routes
    assert "rejected_signals" in routes
    assert "nautilus_order" in routes
    assert "nautilus_fill" in routes
    assert "nautilus_position" in routes
```

- [ ] **Step 3: 运行测试确认失败**

```bash
pytest tests/test_nautilus_observability.py::test_nautilus_event_store_adapter_routes_exclude_paper_tables -v
# Expected: FAIL (routes still contain paper tables)
```

- [ ] **Step 4: 移除 observability.py 中的死路由**

修改 `src/polysignal_lab/nautilus_runtime/observability.py:119-139`:

```python
    def __init__(self, persistence: PersistenceWriter) -> None:
        self.persistence: PersistenceWriter = persistence
        self._routes: dict[str, Callable[[dict[str, object]], None]] = {
            "signals": persistence.insert_signal,
            "rejected_signals": persistence.insert_rejected_signal,
            # "orders" → upsert_paper_order removed (dead route, writes to paper_orders
            # table that no runtime path reads from)
            # "fills" → insert_paper_fill removed (dead route)
            # "positions" → upsert_paper_position removed (dead route)
            "settlements": persistence.insert_paper_trade_result,
            "health_snapshot": persistence.insert_system_event,
            "system_events": persistence.insert_system_event,
            "nautilus_decision": persistence.insert_system_event,
            "nautilus_order": persistence.insert_system_event,
            "nautilus_fill": persistence.insert_system_event,
            "nautilus_position": persistence.insert_system_event,
        }
        self._streams: dict[str, str] = {
            "signals": "signals",
            "rejected_signals": "rejected_signals",
            # "orders": "paper_orders" removed
            # "fills": "paper_fills" removed
            # "positions": "paper_positions" removed
            "settlements": "paper_trade_results",
            "health_snapshot": "system_events",
```

- [ ] **Step 5: 修复 Dashboard 端点**

分析 `dashboard/app.py` 中的端点，找到读取 `paper_*` 表的地方，改为读取 `nautilus_*` 系统事件表。

```python
# 在 dashboard/app.py 中
# 例如 /api/paper-orders 端点：
# 原来: SELECT * FROM paper_orders
# 改为: SELECT * FROM system_events WHERE table='nautilus_order'

# 具体修改取决于 dashboard/app.py 中的实现。典型修改模式：

# 修改前:
# @router.get("/api/paper-orders")
# async def get_paper_orders():
#     rows = db.query("SELECT * FROM paper_orders ORDER BY created_at DESC")
#     return {"orders": [dict(row) for row in rows]}

# 修改后:
# @router.get("/api/paper-orders")
# async def get_paper_orders():
#     rows = db.query(
#         "SELECT payload FROM system_events WHERE table='nautilus_order' ORDER BY created_at DESC"
#     )
#     return {"orders": [_parse_json_payload(row[0]) for row in rows]}
```

实际修改需读取 `dashboard/app.py` 完整代码后执行。

- [ ] **Step 6: 运行测试确认通过**

```bash
pytest tests/test_nautilus_observability.py tests/test_nautilus_cache_reader.py -v 2>&1 | tail -15
# Expected: all tests PASS
```

- [ ] **Step 7: 提交原子化 commit**

```bash
git add src/polysignal_lab/nautilus_runtime/observability.py src/polysignal_lab/dashboard/app.py tests/test_nautilus_observability.py
git commit -m "fix: remove dead paper_* routes from event store adapter

NautilusEventStoreAdapter._routes still mapped 'orders'/'fills'/'positions'
to paper_* table inserters that no runtime path calls. ObservabilityActor
already writes to nautilus_* system event tables.
Dashboard endpoints updated to read from nautilus_* tables instead of paper_*.
Part of P1 remediation: dashboard stale data."
```

---

### Task 4: Agent E — node.py 拆分

**文件:**
- Modify: `src/polysignal_lab/nautilus_runtime/node.py`（减量到 ~700 行）
- Create: `src/polysignal_lab/nautilus_runtime/signal_sidecar.py`
- Create: `src/polysignal_lab/nautilus_runtime/node_cli.py`
- Create: `src/polysignal_lab/nautilus_runtime/node_signals.py`
- Create: `src/polysignal_lab/nautilus_runtime/node_probes.py`
- Test: `tests/test_nautilus_node.py`

**提取范围:**

| 目标文件 | 源 `node.py` 行范围 | 函数/类 |
|---|---|---|
| `node_probes.py` | 132-175 | `_runtime_heartbeat_path`, `_runtime_startup_marker_path`, `_log_probe_write_failure`, `_write_runtime_startup_marker_best_effort`, `_write_runtime_heartbeat_best_effort`, `_runtime_progress_callback` |
| `signal_sidecar.py` | 568-765 | `_stop_nautilus_scheduler`, `_fresh_publish_service`, `_publish_accepted_signal_once`, `_publish_accepted_signal_in_background`, `_notify_accepted_signal`, `_run_interactive_telegram_bot_until_stop`, `_start_interactive_telegram_bot_thread`, `_stop_interactive_telegram_bot_thread`, `_start_nautilus_report_loop_thread`, `_stop_nautilus_report_loop_thread` |
| `node_signals.py` | 966-1070 | `_runtime_intercepts_os_signals`, `_SignalHandler`, `_SignalHandlerSnapshot`, `_restore_os_signal_handlers`, `_install_async_os_signal_handlers` |
| `node_cli.py` | 1165-1329 | `run_nautilus_cli_async` 及其辅助调用链 |

---

- [ ] **Step 1: 读取 node.py 完整内容，确认提取边界准确**

```bash
# 确认每段提取的起始和结束行号
grep -n "^def \|^async def " src/polysignal_lab/nautilus_runtime/node.py | grep -E "132|175|568|765|966|1070|1165|1329"
```

- [ ] **Step 2: 先写测试验证当前行为**

在 `tests/test_nautilus_node.py` 中添加测试，验证提取后的模块能正确导入：

```python
# tests/test_nautilus_node.py

def test_node_probes_importable() -> None:
    from polysignal_lab.nautilus_runtime.node_probes import (
        _runtime_heartbeat_path,
        _runtime_startup_marker_path,
        _runtime_progress_callback,
    )
    # Verify basic functionality
    from polysignal_lab.config import Settings
    settings = Settings()  # minimal defaults
    path = _runtime_startup_marker_path(settings)
    assert str(path).endswith("runtime_startup.json")


def test_node_signals_importable() -> None:
    from polysignal_lab.nautilus_runtime.node_signals import (
        _runtime_intercepts_os_signals,
        _install_async_os_signal_handlers,
    )


def test_signal_sidecar_importable() -> None:
    from polysignal_lab.nautilus_runtime.signal_sidecar import (
        _fresh_publish_service,
        _notify_accepted_signal,
    )
```

- [ ] **Step 3: 创建 `node_probes.py`**

```python
"""Runtime health probes extracted from node.py."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from polysignal_lab.config import Settings
from polysignal_lab.observability.runtime_health import (
    write_runtime_heartbeat,
    write_runtime_startup_marker,
)

logger = logging.getLogger("polysignal_lab.nautilus_runtime.node_probes")


def runtime_heartbeat_path(settings: Settings) -> Path:
    return Path(settings.storage.state_dir) / "runtime_heartbeat.json"


def runtime_startup_marker_path(settings: Settings) -> Path:
    return Path(settings.storage.state_dir) / "runtime_startup.json"


def _log_probe_write_failure(path: Path) -> None:
    logger.warning("Failed to write runtime probe state: %s", path, exc_info=True)


def write_runtime_startup_marker_best_effort(path: Path) -> None:
    try:
        _ = write_runtime_startup_marker(path)
    except OSError:
        _log_probe_write_failure(path)


def write_runtime_heartbeat_best_effort(
    path: Path,
    *,
    phase: str,
    fatal: bool = False,
    fatal_reason: str | None = None,
) -> None:
    try:
        _ = write_runtime_heartbeat(
            path,
            phase=phase,
            fatal=fatal,
            fatal_reason=fatal_reason,
        )
    except OSError:
        _log_probe_write_failure(path)


def runtime_progress_callback(settings: Settings) -> Callable[[str], None]:
    path = runtime_heartbeat_path(settings)

    def note_progress(phase: str) -> None:
        write_runtime_heartbeat_best_effort(path, phase=phase)

    return note_progress
```

- [ ] **Step 4: 创建 `node_signals.py`**

```python
"""OS signal handlers extracted from node.py."""
from __future__ import annotations

import asyncio
import signal
from collections.abc import Callable, Sequence
from contextlib import suppress
from typing import cast


_SignalHandler = signal.Handlers | int | Callable[..., object] | None
_SignalHandlerSnapshot = tuple[signal.Signals, _SignalHandler]


def runtime_intercepts_os_signals(settings: object | None) -> bool:
    runtime_settings = getattr(settings, "runtime", None)
    nautilus_settings = getattr(runtime_settings, "nautilus", None)
    return bool(getattr(nautilus_settings, "intercept_os_signals", False))


def restore_os_signal_handlers(
    previous_handlers: Sequence[_SignalHandlerSnapshot],
) -> None:
    for sig, previous in reversed(previous_handlers):
        with suppress(ValueError, OSError, RuntimeError):
            _ = signal.signal(sig, previous)


def install_async_os_signal_handlers(
    loop: asyncio.AbstractEventLoop,
    request_stop: Callable[[], None],
) -> Callable[[], None]:
    loop_handlers: list[_SignalHandlerSnapshot] = []
    sync_handlers: list[_SignalHandlerSnapshot] = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        previous = signal.getsignal(sig)
        try:
            loop.add_signal_handler(sig, request_stop)
        except (NotImplementedError, RuntimeError):
            _ = signal.signal(sig, lambda _signum, _frame: request_stop())
            sync_handlers.append((sig, previous))
        else:
            loop_handlers.append((sig, previous))

    def cleanup() -> None:
        ...  # original cleanup logic

    return cleanup
```

- [ ] **Step 5: 创建 `signal_sidecar.py`**

```python
"""Signal/publish/telegram sidecar helpers extracted from node.py."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import cast

from polysignal_lab.app.scheduler import PolySignalScheduler
from polysignal_lab.app import scheduler_health
from polysignal_lab.app.services.publish_service import PublishService
from polysignal_lab.publish.telegram_publisher import TelegramPublisher
from polysignal_lab.domain.signal import SignalCandidate


logger = logging.getLogger("polysignal_lab.nautilus_runtime.signal_sidecar")
```

- [ ] **Step 6: 创建 `node_cli.py`**

```python
"""CLI orchestrator helpers extracted from node.py."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import cast

from polysignal_lab.config import Settings, load_settings
from polysignal_lab.nautilus_runtime.node_probes import (
    runtime_heartbeat_path,
    runtime_startup_marker_path,
    write_runtime_startup_marker_best_effort,
    write_runtime_heartbeat_best_effort,
)
from polysignal_lab.nautilus_runtime.node_signals import (
    runtime_intercepts_os_signals,
    install_async_os_signal_handlers,
)


logger = logging.getLogger("polysignal_lab.nautilus_runtime.node_cli")


async def run_nautilus_cli_async(
    settings: Settings | None = None,
    stop_event: asyncio.Event | None = None,
) -> object:
    """Run the Nautilus CLI with async orchestration and signal handling."""
    # 完整内容从 node.py 1165-1329 复制至此
    ...
```

- [ ] **Step 7: 更新 `node.py`**

在 `node.py` 中，将被提取的代码替换为 import 引用：

```python
# 在文件顶部添加
from polysignal_lab.nautilus_runtime.node_probes import (
    runtime_heartbeat_path,
    runtime_startup_marker_path,
    write_runtime_startup_marker_best_effort,
    write_runtime_heartbeat_best_effort,
    runtime_progress_callback,
)
from polysignal_lab.nautilus_runtime.node_signals import (
    runtime_intercepts_os_signals,
    install_async_os_signal_handlers,
    restore_os_signal_handlers,
)
from polysignal_lab.nautilus_runtime.signal_sidecar import (
    stop_nautilus_scheduler,
    fresh_publish_service,
    notify_accepted_signal,
    start_nautilus_report_loop_thread,
    stop_nautilus_report_loop_thread,
    start_interactive_telegram_bot_thread,
    stop_interactive_telegram_bot_thread,
)
from polysignal_lab.nautilus_runtime.node_cli import (
    run_nautilus_cli_async,
)
```

然后删除已提取的原始函数定义。

- [ ] **Step 8: 运行测试确认通过**

```bash
pytest tests/test_nautilus_node.py tests/test_nautilus_default_runtime_integration.py -v 2>&1 | tail -20
# Expected: all tests PASS
```

- [ ] **Step 9: 提交原子化 commit**

```bash
git add src/polysignal_lab/nautilus_runtime/ tests/
git commit -m "refactor: split node.py into focused submodules

Extract 4 responsibility areas into dedicated files:
- node_probes.py: runtime health probes (heartbeat, startup marker)
- node_signals.py: OS signal handlers (SIGTERM/SIGINT)
- signal_sidecar.py: signal/publish/telegram thread helpers
- node_cli.py: CLI orchestrator (run_nautilus_cli_async)

node.py reduced from 1343 to ~700 lines.
Part of P2 remediation: oversized file."
```

---

### Task 5: Agent F — 死代码清理

**文件:**
- Modify: `src/polysignal_lab/app/scheduler_runtime.py`（移除 `_tick_resting_orders` 空函数体）
- Modify: `src/polysignal_lab/app/scheduler_reporting.py`（移除 `_store_paper_result`）
- Modify: `src/polysignal_lab/nautilus_runtime/strategies/base.py`（清理 `notify_fill`/`notify_cancel` 相关死回调）

> 注意：不处理 `exit_policy.py` 的 `_float` helper（Agent B 已处理），不处理 `native_strategy.py`（Phase 2 处理）

---

- [ ] **Step 1: 读取被清理的代码**

```bash
# 1) scheduler_runtime.py _tick_resting_orders
grep -n -A3 "def _tick_resting_orders" src/polysignal_lab/app/scheduler_runtime.py

# 2) scheduler_reporting.py _store_paper_result
grep -n -A15 "def _store_paper_result" src/polysignal_lab/app/scheduler_reporting.py

# 3) strategies/base.py notify_* dead callbacks
grep -n "def notify_" src/polysignal_lab/nautilus_runtime/strategies/base.py
```

- [ ] **Step 2: 先写测试确保行为不变**

```python
# 在 tests/ 中添加验证，检查清理后不会破坏现有功能

def test_scheduler_runtime_no_tick_resting_orders() -> None:
    """_tick_resting_orders was a no-op function and has been removed."""
    import polysignal_lab.app.scheduler_runtime as sr
    assert not hasattr(sr, "_tick_resting_orders"), \
        "_tick_resting_orders no-op should have been removed"


def test_scheduler_reporting_no_store_paper_result() -> None:
    """_store_paper_result was dead code and has been removed."""
    import polysignal_lab.app.scheduler_reporting as sr
    assert not hasattr(sr, "_store_paper_result"), \
        "_store_paper_result dead code should have been removed"
```

- [ ] **Step 3: 移除空函数体 `_tick_resting_orders`**

删除 `src/polysignal_lab/app/scheduler_runtime.py:204-205`:

```python
# 删除以下两行:
def _tick_resting_orders(_scheduler: PolySignalScheduler) -> None:
    return None
```

同时检查是否有任何调用点引用此函数：
```bash
grep -rn "_tick_resting_orders" src/polysignal_lab/
# 预期: 无输出（是死代码）
```

- [ ] **Step 4: 移除 `_store_paper_result`**

删除 `src/polysignal_lab/app/scheduler_reporting.py:212-230` 的完整函数体。

同时检查调用点：
```bash
grep -rn "_store_paper_result" src/polysignal_lab/
# 预期: 无输出（是死代码）
```

- [ ] **Step 5: 检查并清理 `strategies/base.py` 中的 notify 回调**

```bash
grep -n "def notify_" src/polysignal_lab/nautilus_runtime/strategies/base.py
```

如果确认这些 `notify_*` 方法是 dead code（没有被 Nautilus runtime 调用，只是 legacy 遗留），则移除它们。

```python
# 可能的删除范围（需根据实际代码确认）：
# def notify_fill(self, ...): → dead
# def notify_cancel(self, ...): → dead  
# def notify_signal_accepted(self, ...): → dead
# def notify_leg_failure(self, ...): → dead
```

> **注意：在删除前，先检查 `vwap_momentum.py` 是否 override 了 `notify_fill`/`notify_cancel`。如果 override 中有逻辑，则需要将它们迁移到 core 中，而非直接删除。**

```bash
# 检查 override
grep -n "def notify_fill\|def notify_cancel" src/polysignal_lab/nautilus_runtime/strategies/vwap_momentum.py src/polysignal_lab/alpha/vwap_momentum_core.py
```

- [ ] **Step 6: 运行测试确认通过**

```bash
pytest tests/ -v -x --timeout=60 2>&1 | tail -30
# 至少运行与清理相关的测试
pytest tests/test_nautilus_strategy_wrappers.py tests/test_scheduler.py -v 2>&1 | tail -15
# Expected: all tests PASS
```

- [ ] **Step 7: 提交原子化 commit**

```bash
git add src/polysignal_lab/app/scheduler_runtime.py src/polysignal_lab/app/scheduler_reporting.py src/polysignal_lab/nautilus_runtime/strategies/base.py tests/
git commit -m "chore: remove dead code

- _tick_resting_orders: no-op function in scheduler_runtime.py
- _store_paper_result: never-called function in scheduler_reporting.py
- notify_* callbacks: dead legacy callbacks in strategies/base.py

Part of P2 remediation: dead code cleanup."
```

---

## Phase 2 — 单 Agent（依赖 Phase 1 合并）

### Task 6: Agent D — native_strategy.py 改造

**注意：Phase 2 必须在 Phase 1 的所有 5 个任务合并到 worktree 分支后执行。这是因为 Agent D 需要 Agent B 的 exit_policy 新 API、Agent E 的 node.py import 结构调整以及 Agent A 的 renamed class。**

**文件:**
- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py`
- Create: `src/polysignal_lab/nautilus_runtime/native_strategy_utils.py`
- Test: `tests/test_nautilus_execution.py`, `tests/test_nautilus_strategy_wrappers.py`（更新）

**三个子任务:**

#### 6a: 实现 on_save/on_load

**接口:**
- 消耗: `PolySignalNativeStrategy` 的当前状态字段
- 产出: `on_save() -> dict[str, bytes]`, `on_load(state) -> None`

---

- [ ] **Step 6a-1: 写测试验证 save/load round-trip**

```python
# 在 tests/test_nautilus_execution.py 中新增

def test_native_strategy_save_load_roundtrip() -> None:
    """PolySignalNativeStrategy.on_save/on_load preserves in-memory state."""
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
    from polysignal_lab.nautilus_bridge.state import state_key
    
    strategy = PolySignalNativeStrategy(
        core=MagicMock(),
        assembler=MagicMock(),
        condition_ids=("condition-btc-5m",),
        strategy_name="test_strat",
        registry=MagicMock(),
    )
    strategy._approved_signal_metrics["sig-1"] = {"signal_confidence": 0.85}
    strategy._submitted_signal_keys.add("sig-1")
    strategy._pending_exit_position_ids.add("pos-1")
    
    state = strategy.on_save()
    
    assert state_key("test_strat") in state
    assert isinstance(state[state_key("test_strat")], bytes)
    
    restored = PolySignalNativeStrategy(
        core=MagicMock(),
        assembler=MagicMock(),
        condition_ids=("condition-btc-5m",),
        strategy_name="test_strat",
        registry=MagicMock(),
    )
    restored.on_load(state)
    
    assert restored._approved_signal_metrics == strategy._approved_signal_metrics
    assert restored._submitted_signal_keys == strategy._submitted_signal_keys
    assert restored._pending_exit_position_ids == strategy._pending_exit_position_ids


def test_native_strategy_on_load_handles_missing_keys() -> None:
    """Missing optional keys in on_load state reset to empty, not crash."""
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
    from polysignal_lab.nautilus_bridge.state import encode_state
    
    state = encode_state("test_strat", {"_dummy": True})
    
    strategy = PolySignalNativeStrategy(
        core=MagicMock(),
        assembler=MagicMock(),
        condition_ids=("condition-btc-5m",),
        strategy_name="test_strat",
        registry=MagicMock(),
    )
    strategy.on_load(state)
    
    assert strategy._approved_signal_metrics == {}
    assert strategy._submitted_signal_keys == set()
    assert strategy._pending_exit_position_ids == set()
```

- [ ] **Step 6a-2: 在 PolySignalNativeStrategy 中实现 on_save/on_load**

在 `src/polysignal_lab/nautilus_runtime/native_strategy.py` 中 `PolySignalNativeStrategy` 类中添加：

```python
    def on_save(self) -> dict[str, bytes]:
        from polysignal_lab.nautilus_bridge.state import encode_state
        
        state: dict[str, object] = {
            "_approved_signal_metrics": dict(self._approved_signal_metrics),
            "_submitted_signal_keys": list(self._submitted_signal_keys),
            "_pending_exit_position_ids": list(self._pending_exit_position_ids),
            # Add condition-level state if needed
            "_local_state_schema_version": 1,
        }
        # Serialize state dict values to JSON-compatible format
        serializable: dict[str, object] = {
            "_approved_signal_metrics": {
                k: {sk: sv for sk, sv in v.items()}
                for k, v in self._approved_signal_metrics.items()
            },
            "_submitted_signal_keys": list(self._submitted_signal_keys),
            "_pending_exit_position_ids": list(self._pending_exit_position_ids),
        }
        return encode_state(self.strategy_name, serializable)

    def on_load(self, state: dict[str, bytes]) -> None:
        from polysignal_lab.nautilus_bridge.state import decode_state
        
        payload = decode_state(self.strategy_name, state)
        approved = payload.get("_approved_signal_metrics", {})
        if isinstance(approved, dict):
            self._approved_signal_metrics = {
                str(k): dict(cast(Mapping[str, object], v))
                for k, v in approved.items()
            }
        submitted = payload.get("_submitted_signal_keys", [])
        if isinstance(submitted, list):
            self._submitted_signal_keys = set(str(k) for k in submitted)
        pending = payload.get("_pending_exit_position_ids", [])
        if isinstance(pending, list):
            self._pending_exit_position_ids = set(str(k) for k in pending)
```

#### 6b: 更新 exit_policy 调用方使用 Agent B 的新 API

- [ ] **Step 6b-1: 修改 `evaluate_exit_positions` 使用 bracket_attachments_for**

```python
    # 在 evaluate_exit_positions 中原本每周期 polling 调用 evaluate_exit_decision
    # 改为：在入口订单提交时调用 bracket_attachments_for 附加 bracket orders
    # 这项工作需要集成到 submit_approved_decision 调用链中

    # 修改 evaluate_exit_positions 方法:
    def evaluate_exit_positions(self, condition_id: str, view: MarketView) -> None:
        # 保持向后兼容 polling（用于 MAX_HOLD_TIME）
        cache_reader = getattr(self, "cache_reader", None)
        read_positions = getattr(cache_reader, "read_positions", None)
        if not callable(read_positions):
            return
        rows = read_positions()
        if not isinstance(rows, list):
            return
        config = self._exit_policy_config()
        if config is None:
            return
        for position in rows:
            if not isinstance(position, dict):
                continue
            book = self._position_book_for_exit(position, condition_id, view)
            if book is None:
                continue
            # 旧方式: self._submit_exit_position(position, book, view.created_at, config)
            # 新方式: 使用 bracket_attachments_for 生成退出意图
            from polysignal_lab.nautilus_runtime.exit_policy import bracket_attachments_for
            brackets = bracket_attachments_for(position, book, view.created_at, config)
            for bracket in brackets:
                self._submit_exit_bracket(bracket)

    def _submit_exit_bracket(self, bracket: TaggedBracketOrder) -> None:
        # 通过 Nautilus order_factory 提交 bracket order
        ...
```

> **注意：具体实现取决于 native_strategy.py 中的 order submission 机制，需要在 agent 执行时读取完整代码后精确实现。**

#### 6c: 提取工具函数

- [ ] **Step 6c-1: 创建 `native_strategy_utils.py`**

将 `native_strategy.py:1033-1318` 的模块级工具函数提取到新文件:

```python
"""Shared utility functions for native_strategy.py"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import cast

from polysignal_lab.alpha.types import AlphaFillEvent, AlphaOrderEvent
from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_bridge.market_catalog import (
    MarketCatalog,
    MarketPairMeta,
)
from polysignal_lab.nautilus_runtime.market_data import (
    PolySignalMarketMetaData,
    PolySignalPriceToBeatData,
    PolySignalSpotData,
)
from polysignal_lab.utils import utc_now


def value(obj: object, name: str, default: object = None) -> object:
    ...

def tags(raw: object) -> dict[str, str]:
    ...

def market_id_for_condition(
    condition_id: str,
    registry: MarketCatalog,
) -> str | None:
    ...

def event_side(event: object) -> Side:
    ...

# ... etc, extract all 20+ utility functions from native_strategy.py:1033-1318
```

- [ ] **Step 6d: 运行测试确认通过**

```bash
pytest tests/test_nautilus_execution.py tests/test_nautilus_strategy_wrappers.py tests/test_nautilus_strategy_base.py -v 2>&1 | tail -30
# Expected: all tests PASS
```

- [ ] **Step 6e: 提交原子化 commit**

```bash
git add src/polysignal_lab/nautilus_runtime/native_strategy.py src/polysignal_lab/nautilus_runtime/native_strategy_utils.py tests/
git commit -m "feat: native_strategy.py state persistence + exit_policy integration

- Implement on_save/on_load with state_key (polysignal.<name>.state.v1)
  and JSON-serializable payload
- Update exit_policy caller to use bracket_attachments_for API
- Extract utility functions (1033-1318) to native_strategy_utils.py
- Extract subscription management (953-1024) to cross-cutting concern

Resolves P1: on_save/on_load missing from native strategy path
Resolves P1: exit_policy TP/SL bracket order integration"
```

---

## 执行流程

```
Phase 1: 5 parallel agents (each in independent git worktree)
┌──────────────────────────────────────────────────────┐
│  Agent A: Rename   ┆  Agent B: exit_policy           │
│  (strategy_base)    ┆  (bracket orders)               │
│                     ┆                                 │
│  Agent C: Dashboard ┆  Agent E: node.py split         │
│  (routes + app)     ┆  (4 submodules)                 │
│                     ┆                                 │
│  Agent F: Dead code cleanup                           │
└──────────────────────────────────────────────────────┘
        └───────────── merge ────────────┘

Phase 2: Sequential (on merged Phase 1 worktree)
┌──────────────────────────────────────────────────────┐
│  Agent D: native_strategy.py                          │
│  • on_save/on_load                                    │
│  • exit_policy bracket integration                    │
│  • utility extraction                                 │
└──────────────────────────────────────────────────────┘

Final: Verify + PR
```

---

## 工作流脚本

执行时使用 Workflow 工具，脚本结构：

```javascript
export const meta = {
  name: 'refactor-compliance-fixes',
  description: 'Multi-agent parallel refactoring based on compliance review findings',
  phases: [
    { title: 'Phase 1', detail: '5 parallel agents in isolated worktrees' },
    { title: 'Merge Phase 1', detail: 'Merge all worktree branches' },
    { title: 'Phase 2', detail: 'Agent D on merged code' },
    { title: 'Verify', detail: 'Run full test suite' },
  ],
}
```
