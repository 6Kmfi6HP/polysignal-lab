# Nautilus Runtime Dedup Final Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 彻底删除 PolySignal 中与 NautilusTrader 已有职责重复的本地 paper execution、wallet、subscription registry、execution precheck 和大型混合函数，让默认与显式运行路径都只依赖 Nautilus sandbox/cache/portfolio 作为 paper truth。

**Architecture:** 默认 runtime 已由 `config/signal_bot.yaml` 的 `runtime.engine: nautilus` 和 `main.py` 的 config-default resolution 进入 Nautilus。本计划保留 Nautilus `TradingNode` 作为已记录的非 wheel 设计偏差，删除本地 paper simulator/wallet/executor，改为 Nautilus-only projection/reporting，并把自建 subscription owner 状态改为薄的 Nautilus strategy subscription calls。所有业务特有逻辑仅保留为只读 projection、Telegram/report formatting、Polymarket outcome resolution。

**Tech Stack:** Python 3.11 default package, Python 3.12 Nautilus optional runtime, `nautilus_trader[polymarket]==1.229.0`, pytest, basedpyright, Docker target `nautilus-runtime`, existing `uv run` workflow.

## Global Constraints

- 默认配置必须保持 `config/signal_bot.yaml` 中 `runtime.engine: nautilus`。
- 默认 runtime 不得注册 live Polymarket execution client，不得读取 `POLYMARKET_PK`、`POLYMARKET_FUNDER`、`POLYMARKET_API_KEY`、`POLYMARKET_API_SECRET`、`POLYMARKET_PASSPHRASE`。
- `TradingNode` wiring 保留为 `docs/NAUTILUS_BRIDGE_BOUNDARY.md` 已记录的设计偏差；本计划不得把它当作重复造轮子删除。
- Paper execution truth 只能来自 Nautilus `SandboxLiveExecClientFactory`、Nautilus cache、Nautilus portfolio。
- 项目业务 projection 可以写 SQLite/JSONL，但不得自建撮合、wallet ledger、resting order store、paper fill model、paper position lifecycle。
- 不新增 dependency。
- 不保留 deprecated alias、compat shim、dual backend、rollback config。
- 每个任务先写失败测试，再改代码，再运行该任务指定测试。
- 每个任务独立 commit。

---

## Scope Check

该清理横跨 runtime boundary、scheduler compatibility、paper package deletion、reporting projection、native strategy subscription、order mapping 和文档。它们不是独立可发布子系统，因为任一旧路径残留都会继续允许重复平台职责。任务按 reviewer 可拒绝的边界拆分：先加硬边界测试，再删除 legacy paper execution wiring，再删除模块，再修 reporting/projection，再删除 subscription wheel，再拆大型函数。

## File Structure

### 删除的文件

- `src/polysignal_lab/paper/fill_model.py` — 本地 best-ask paper fill model，重复 Nautilus sandbox execution。
- `src/polysignal_lab/paper/order_intent_executor.py` — 本地 FAK/FOK/GTD/resting order executor，重复 Nautilus order matching / TIF handling。
- `src/polysignal_lab/paper/simulator.py` — 本地 PaperSimulator，重复 Nautilus sandbox execution。
- `src/polysignal_lab/paper/wallet.py` — 本地 PaperWallet，重复 Nautilus portfolio/account state。
- `src/polysignal_lab/paper/exit_engine.py` — 本地 take-profit/stop-loss/max-hold exit over PaperWallet，重复本地 paper lifecycle。
- `src/polysignal_lab/paper/preflight.py` — 本地 execution reject/preflight，重复 sandbox/order validation。
- `tests/test_paper_simulation.py` — 删除本地 simulator 测试。
- `tests/test_paper_execution_preflight.py` — 删除本地 execution preflight 测试。
- `tests/test_exit_engine.py` — 删除本地 wallet exit 测试。

### 保留但改名/收敛职责的文件

- `src/polysignal_lab/paper/report.py` — 保留为 report aggregation，改为不依赖 local paper execution types；只接收 dict projection rows 和 `PaperTradeResult`。
- `src/polysignal_lab/paper/settlement_resolver.py`、`src/polysignal_lab/paper/settlement_sources.py` — 保留；这是 Polymarket outcome business resolution，不是 Nautilus 平台职责。
- `src/polysignal_lab/domain/paper_result.py` — 保留；这是报告/结算 projection schema。
- `src/polysignal_lab/domain/paper_order.py`、`src/polysignal_lab/domain/paper_position.py` — 先保留为 SQLite/JSONL storage projection schema；运行时代码不得构造本地 paper order/fill/position。

### 修改的文件

- `src/polysignal_lab/observability/safety.py` — 扩大本地 paper wheel 禁止范围到 `src/polysignal_lab`，允许已删除文件不存在。
- `tests/test_nautilus_safety_boundary.py` — 增加 app/paper 全源边界测试。
- `tests/test_nautilus_execution.py` — 删除只检查 `nautilus_runtime.execution` 的窄边界，改成全源禁止。
- `src/polysignal_lab/app/main.py` — 显式 `scheduler` mode 改为 Nautilus alias 或只读 smoke；不再启动 legacy paper scheduler。
- `src/polysignal_lab/app/scheduler.py` — 删除 `PaperWallet`、`PaperSimulator`、`PaperExitEngine`、`PaperSettlementEngine` wiring；`_initialize_trading_components()` 改为 signal-only setup 或删除。
- `src/polysignal_lab/app/services/paper_portfolio_service.py` — 改为 `NautilusProjectionPortfolioService` 或删除；不再调用 simulator。
- `src/polysignal_lab/app/scheduler_processing.py` — 删除 `_store_simulation_result()` 和 `tick_resting_orders()`；`process_signal()` 只持久化/publish signal。
- `src/polysignal_lab/app/scheduler_runtime.py` — 删除 `_tick_resting_orders()`，不再调用 paper portfolio tick。
- `src/polysignal_lab/app/scheduler_state.py` — 删除 paper wallet/open positions restore/persist；只保留 market cache / signal dedupe state。
- `src/polysignal_lab/app/scheduler_reporting.py` — 删除 wallet fallback，reporting 只读 Nautilus cache/SQLite projection rows。
- `src/polysignal_lab/nautilus_runtime/native_strategy.py` — 删除 `_MarketDataSubscriptionGroup`；使用 Nautilus strategy/actor subscription state。
- `src/polysignal_lab/nautilus_runtime/order_mapping.py` — 删除 FOK/FAK/available_shares execution-like precheck；只做 order spec mapping。
- `src/polysignal_lab/nautilus_runtime/native_order.py` — 删除 `available_shares` 入参透传；保持 `order_factory.limit()` + `submit_order()`。
- `src/polysignal_lab/nautilus_runtime/node.py` — 拆分 `build_trading_node()`、`run_nautilus_cli()`、`run_nautilus_cli_async()` 的混合职责；删除 scheduler paper metadata。
- `docs/NAUTILUS_BRIDGE_BOUNDARY.md` — 更新最终边界，明确 no local paper execution stack anywhere under runtime-started source。
- `docs/PRD.md`、`docs/PROJECT_ARCHITECTURE_VISUAL.md`、`docs/IMPLEMENTATION_SUMMARY.md` — 删除 legacy paper stack 描述，保留 Nautilus sandbox/cache/portfolio projection。

---

### Task 1: 加全源 Nautilus 平台边界测试

**Files:**
- Modify: `tests/test_nautilus_safety_boundary.py:1-91`
- Modify: `tests/test_nautilus_execution.py:10-50`
- Modify: `src/polysignal_lab/observability/safety.py:29-77`

**Interfaces:**
- Consumes: `polysignal_lab.observability.safety.scan(root: str | Path) -> list[tuple[str, str]]`
- Produces: `scan()` 对 `src/polysignal_lab` 全源禁止本地 paper wheel symbols；允许 `submit_order` 只在 Nautilus strategy/runtime 测试中出现。

- [ ] **Step 1: Write failing boundary tests**

Replace `tests/test_nautilus_safety_boundary.py` local paper tests with this exact test block after `test_default_nautilus_source_avoids_live_execution_symbols()`:

```python
def test_project_source_avoids_local_paper_execution_wheels() -> None:
    findings: list[str] = []
    source_root = Path("src/polysignal_lab")
    forbidden = (
        "from polysignal_lab.paper.order_intent_executor import",
        "BestAskTakerExecutor",
        "PassiveGtdExecutor",
        "PaperSimulator",
        "from polysignal_lab.paper.wallet import",
        "PaperWallet(",
        "BestAskTakerFillModel",
        "PaperExecutionPreflight",
        "PaperExitEngine",
        "PaperSettlementEngine(self.wallet)",
        "scheduler.wallet",
        "scheduler.paper",
        "paper_portfolio.process_signal",
        "paper_portfolio.tick_resting_orders",
    )
    for path in source_root.rglob("*.py"):
        if path.name == "safety.py":
            continue
        text = path.read_text(encoding="utf-8")
        findings.extend(
            f"{path}:{symbol}"
            for symbol in forbidden
            if symbol in text
        )

    assert findings == []


def test_safety_scan_enforces_project_wide_local_paper_isolation(tmp_path: Path) -> None:
    source_root = tmp_path / "src" / "polysignal_lab" / "app"
    source_root.mkdir(parents=True)
    (source_root / "scheduler.py").write_text(
        "from polysignal_lab.paper.simulator import PaperSimulator\n"
        "def f(scheduler):\n"
        "    scheduler.wallet = object()\n",
        encoding="utf-8",
    )

    assert sorted(scan(tmp_path)) == [
        (
            "src/polysignal_lab/app/scheduler.py",
            "PaperSimulator",
        ),
        (
            "src/polysignal_lab/app/scheduler.py",
            "scheduler.wallet",
        ),
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_nautilus_safety_boundary.py::test_project_source_avoids_local_paper_execution_wheels tests/test_nautilus_safety_boundary.py::test_safety_scan_enforces_project_wide_local_paper_isolation -v
```

Expected: FAIL. The first test reports current offenders in `app/scheduler.py`, `app/scheduler_processing.py`, `app/scheduler_reporting.py`, `app/scheduler_state.py`, and `paper/*`. The second test fails because `scan()` only applies local paper isolation to `nautilus_runtime` paths.

- [ ] **Step 3: Expand safety scan scope**

In `src/polysignal_lab/observability/safety.py`, replace lines 29-40 with:

```python
NAUTILUS_RUNTIME_ALLOWED_SYMBOLS: Final = {"submit_order"}

SKIP_TOP_LEVEL_DIRS: Final = {"data", "logs", "refs", "state"}

LOCAL_PAPER_ISOLATION_SYMBOLS: Final = (
    "from polysignal_lab.paper.order_intent_executor import",
    "BestAskTakerExecutor",
    "PassiveGtdExecutor",
    "PaperSimulator",
    "from polysignal_lab.paper.wallet import",
    "PaperWallet(",
    "BestAskTakerFillModel",
    "PaperExecutionPreflight",
    "PaperExitEngine",
    "PaperSettlementEngine(self.wallet)",
    "scheduler.wallet",
    "scheduler.paper",
    "paper_portfolio.process_signal",
    "paper_portfolio.tick_resting_orders",
)
```

Replace `scan()` lines 57-77 with:

```python
def scan(root: str | Path) -> list[tuple[str, str]]:
    base = Path(root)
    base_is_file = base.is_file()
    paths = (base,) if base_is_file else base.rglob("*")
    findings: list[tuple[str, str]] = []
    for path in paths:
        if path.is_dir() or skip_path(base, path):
            continue
        if path.suffix not in SCANNED_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        report_path = path.name if base_is_file else str(path.relative_to(base))
        symbols = list(blocked_symbols())
        if _is_project_source(path):
            symbols.extend(LOCAL_PAPER_ISOLATION_SYMBOLS)
        for symbol in symbols:
            if symbol in text:
                if _is_submit_order_allowed_for_nautilus_strategy(path) and symbol == "submit_order":
                    continue
                findings.append((report_path, symbol))
    return findings
```

Replace `_is_default_nautilus_runtime_source()` lines 93-102 with:

```python
def _is_project_source(path: Path) -> bool:
    if path.suffix != ".py":
        return False
    parts = path.parts
    for idx, part in enumerate(parts[:-1]):
        if part == "polysignal_lab" and "tests" not in parts[:idx]:
            return True
    return False
```

- [ ] **Step 4: Run tests to verify scan fixture passes and source boundary still fails**

Run:

```bash
uv run pytest tests/test_nautilus_safety_boundary.py::test_safety_scan_enforces_project_wide_local_paper_isolation tests/test_nautilus_safety_boundary.py::test_project_source_avoids_local_paper_execution_wheels -v
```

Expected: first test PASS, second test FAIL with real source offenders.

- [ ] **Step 5: Commit boundary tests**

```bash
git add tests/test_nautilus_safety_boundary.py tests/test_nautilus_execution.py src/polysignal_lab/observability/safety.py
git commit -m "test: enforce project-wide Nautilus paper boundary"
```

---

### Task 2: 删除 legacy scheduler paper wiring

**Files:**
- Modify: `src/polysignal_lab/app/main.py:23-177`
- Modify: `src/polysignal_lab/app/scheduler.py:1-379`
- Modify: `src/polysignal_lab/app/services/paper_portfolio_service.py:1-105`
- Modify: `src/polysignal_lab/app/scheduler_processing.py:1-799`
- Modify: `src/polysignal_lab/app/scheduler_runtime.py:187-224`
- Test: `tests/test_scheduler_paper.py`
- Test: `tests/test_scheduler_services.py`

**Interfaces:**
- Consumes: `PolySignalScheduler.process_signal(signal: SignalCandidate) -> ProcessSignalResult`
- Produces: `process_signal()` stores/publishes signals only; no local order/fill/position/wallet result fields.
- Produces: `RuntimeMode.SCHEDULER` no longer starts local paper execution; explicit scheduler mode aliases to Nautilus unless `--once` smoke is used.

- [ ] **Step 1: Replace paper scheduler tests with signal-only tests**

Replace `tests/test_scheduler_paper.py` with:

```python
from __future__ import annotations

from pathlib import Path

from polysignal_lab.app.scheduler import PolySignalScheduler
from polysignal_lab.strategies.ptb_diff import PTBDiffStrategy


async def _signal(snapshot, settings):
    return PTBDiffStrategy(settings.strategies.ptb_diff).evaluate(snapshot)[0]


def _signal_scheduler(tmp_path: Path, settings) -> PolySignalScheduler:
    settings.telegram.enabled = False
    settings.telegram.send_signals = False
    settings.telegram.send_paper_results = False
    settings.telegram.send_daily_report = False
    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)
    scheduler._initialize_trading_components()
    return scheduler


async def test_process_signal_stores_signal_without_local_paper_execution(
    tmp_path: Path, snapshot, settings
) -> None:
    sig = await _signal(snapshot, settings)
    scheduler = _signal_scheduler(tmp_path, settings)

    result = await scheduler.process_signal(sig)

    counts = scheduler.sqlite.counts()
    assert result == {
        "signal_id": sig.signal_id,
        "stored": True,
        "published": False,
        "publish_status": None,
    }
    assert counts["signals"] == 1
    assert counts["paper_orders"] == 0
    assert counts["paper_fills"] == 0
    assert counts["paper_positions"] == 0
    assert not hasattr(scheduler, "wallet")
    assert not hasattr(scheduler, "paper")


async def test_process_signal_writes_prd_named_telegram_jsonl_stream(
    tmp_path: Path, snapshot, settings
) -> None:
    sig = await _signal(snapshot, settings)
    settings.telegram.enabled = True
    settings.telegram.dry_run = True
    settings.telegram.send_signals = True
    settings.telegram.send_paper_results = False
    settings.telegram.send_daily_report = False
    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)
    scheduler._initialize_trading_components()

    result = await scheduler.process_signal(sig)

    publish_rows = scheduler.logs.read_all("telegram_publishes")
    assert result["published"] is True
    assert [(row["message_type"], row["status"]) for row in publish_rows] == [
        ("signal", "DRY_RUN")
    ]
    assert not (scheduler.logs.base_dir / "telegram_publish.jsonl").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_scheduler_paper.py -v
```

Expected: FAIL because current result includes `paper_order`, `paper_fill`, `paper_position` and scheduler creates `wallet` / `paper`.

- [ ] **Step 3: Change `ProcessSignalResult` to signal-only**

In `src/polysignal_lab/app/scheduler_processing.py`, replace the `ProcessSignalResult` TypedDict with:

```python
class ProcessSignalResult(TypedDict):
    signal_id: str
    stored: bool
    published: bool
    publish_status: str | None
```

Replace `process_signal()` lines 614-666 with:

```python
async def process_signal(
    scheduler: PolySignalScheduler, signal: SignalCandidate
) -> ProcessSignalResult:
    result = ProcessSignalResult(
        signal_id=signal.signal_id,
        stored=False,
        published=False,
        publish_status=None,
    )

    try:
        _append_persistence_log(scheduler, "signals", signal)
        _write_persistence_sqlite(scheduler, scheduler.persistence.insert_signal, signal)
        result["stored"] = True
    except Exception as exc:
        scheduler.logger.error("Failed to store signal %s: %s", signal.signal_id, exc)

    if scheduler.settings.telegram.send_signals:
        try:
            publish = await scheduler.publish_service.publish_signal(
                signal, scheduler.settings.paper_trading.fixed_stake_usdc
            )
            scheduler_health.note_publish_result(scheduler, publish.as_dict())
            result["published"] = True
            result["publish_status"] = publish.status
        except Exception as exc:
            scheduler.health.inc_metric("telegram", "failed")
            scheduler.health.mark_degraded("telegram", str(exc))
            scheduler.logger.error(
                "Failed to publish signal %s: %s: %s",
                signal.signal_id,
                type(exc).__name__,
                exc,
            )

    return result
```

Delete `_store_simulation_result()` lines 669-716 and `tick_resting_orders()` lines 734-799 completely.

- [ ] **Step 4: Remove scheduler paper component construction**

In `src/polysignal_lab/app/scheduler.py`, delete these imports:

```python
from polysignal_lab.paper.settlement import PaperSettlementEngine
from polysignal_lab.paper.simulator import PaperSimulator
from polysignal_lab.paper.wallet import PaperWallet
from polysignal_lab.paper.exit_engine import PaperExitEngine
from polysignal_lab.domain.paper_order import PaperFill, PaperOrder
```

Replace `_make_fill_notifier()` lines 67-94 with:

```python
def _make_fill_notifier(_scheduler: object, _strategies: object) -> None:
    raise RuntimeError("Local paper fill notifier was removed; Nautilus emits order/fill callbacks")
```

Replace `_initialize_trading_components()` lines 245-279 with:

```python
    def _initialize_trading_components(self) -> None:
        if self._trading_components_initialized:
            return
        self.strategy_schedule = build_strategy_schedule(self.settings.strategies)
        self.strategies = [entry.strategy for entry in self.strategy_schedule]
        self.signal_pipeline.strategies = self.strategies
        self.signal_pipeline.set_strategy_dependencies(
            {entry.name: tuple(entry.depends_on) for entry in self.strategy_schedule}
        )
        known_strategy_names = {entry.name for entry in self.strategy_schedule}
        disabled = self.persistence.read_state("telegram_disabled_strategies", default=[])
        for name in disabled if isinstance(disabled, list) else []:
            if name in known_strategy_names:
                self.signal_pipeline.set_strategy_enabled(str(name), False)
        self.arbiter = SignalArbiter()
        self._trading_components_initialized = True
```

- [ ] **Step 5: Remove paper portfolio service from scheduler service list**

In `src/polysignal_lab/app/scheduler.py`, delete the `PaperPortfolioService` import and delete the `self.paper_portfolio = PaperPortfolioService(...)` block lines 193-200.

Replace `core_services` lines 201-210 with:

```python
        core_services = [
            self.persistence,
            self.market_universe,
            self.book_feed,
            self.spot_feed,
            self.snapshot_service,
            self.signal_pipeline,
            self.publish_service,
        ]
```

Replace methods lines 357-361 with:

```python
    async def check_settlements(self) -> list[PaperTradeResult]:
        from polysignal_lab.app.scheduler_reporting import check_settlements

        return await check_settlements(self)

    async def generate_daily_report(self) -> DailyReport | None:
        from polysignal_lab.app.scheduler_reporting import generate_daily_report

        return await generate_daily_report(self)
```

- [ ] **Step 6: Remove runtime resting-order tick**

In `src/polysignal_lab/app/scheduler_runtime.py`, replace `_tick_resting_orders()` lines 206-215 with:

```python
def _tick_resting_orders(_scheduler: PolySignalScheduler) -> None:
    return None
```

Remove calls to `_tick_resting_orders(scheduler)` from the scheduler loop. If the loop contains this exact line:

```python
        _tick_resting_orders(scheduler)
```

Delete that line.

- [ ] **Step 7: Replace `paper_portfolio_service.py` with a no-execution health service**

Replace `src/polysignal_lab/app/services/paper_portfolio_service.py` with:

```python
from __future__ import annotations

import logging
from typing import Any


class PaperPortfolioService:
    name = "paper_portfolio_removed"

    def __init__(
        self,
        *,
        settings: Any,
        scheduler: Any = None,
        logger: logging.Logger | None = None,
        **_removed_dependencies: Any,
    ) -> None:
        self.settings = settings
        self.scheduler = scheduler
        self.logger = logger or logging.getLogger("polysignal_lab.scheduler.paper_portfolio_removed")

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def health(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": "removed",
            "metrics": {
                "open_positions": 0,
                "equity_source": "nautilus_cache_portfolio",
            },
        }

    def process_signal(self, _signal: Any, _result: dict[str, Any]) -> None:
        raise RuntimeError("Local paper execution was removed; submit orders through Nautilus strategy callbacks")

    def tick_resting_orders(self) -> list[Any]:
        return []

    async def check_settlements(self) -> list[Any]:
        if self.scheduler is None:
            return []
        from polysignal_lab.app.scheduler_reporting import check_settlements

        return await check_settlements(self.scheduler)

    async def generate_daily_report(self) -> Any:
        if self.scheduler is None:
            return None
        from polysignal_lab.app.scheduler_reporting import generate_daily_report

        return await generate_daily_report(self.scheduler)
```

This temporary service remains only so older imports fail loudly instead of executing local paper logic. Task 3 removes imports that still depend on it.

- [ ] **Step 8: Run task tests**

Run:

```bash
uv run pytest tests/test_scheduler_paper.py tests/test_scheduler_services.py tests/test_nautilus_safety_boundary.py::test_project_source_avoids_local_paper_execution_wheels -v
```

Expected: scheduler tests PASS; safety boundary still FAIL because paper modules still exist until Task 3.

- [ ] **Step 9: Commit scheduler paper removal**

```bash
git add src/polysignal_lab/app/main.py src/polysignal_lab/app/scheduler.py src/polysignal_lab/app/services/paper_portfolio_service.py src/polysignal_lab/app/scheduler_processing.py src/polysignal_lab/app/scheduler_runtime.py tests/test_scheduler_paper.py tests/test_scheduler_services.py
git commit -m "refactor: remove legacy scheduler paper execution"
```

---

### Task 3: 用 Nautilus-managed exit actions 替代 PaperExitEngine

**Files:**
- Create: `src/polysignal_lab/nautilus_runtime/exit_policy.py`
- Create: `src/polysignal_lab/nautilus_runtime/native_exit.py`
- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py`
- Test: `tests/test_nautilus_exit_policy.py`
- Test: `tests/test_nautilus_native_exit.py`

**Interfaces:**
- Consumes: Nautilus position projection rows with `instrument_id`, `quantity`, `avg_entry_price`, `opened_at`/`ts`, `is_closed`.
- Produces: `evaluate_exit_decision(position: Mapping[str, object], book: SideBookView, now: datetime, config: ExitPolicyConfig) -> NautilusExitDecision | None`.
- Produces: `submit_exit_decision(strategy: OrderSubmittingStrategy[OrderT], decision: NautilusExitDecision, *, instrument_id_resolver: Callable[[str], object]) -> OrderT`.
- Preserves PRD exit requirements: take-profit, stop-loss, max-hold-time remain, but execution is a Nautilus reduce-only sell order rather than local wallet mutation.

- [ ] **Step 1: Write failing exit policy tests**

Create `tests/test_nautilus_exit_policy.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from polysignal_lab.alpha.types import SideBookView
from polysignal_lab.nautilus_runtime.exit_policy import (
    ExitPolicyConfig,
    ExitReason,
    evaluate_exit_decision,
)


def _book(best_bid: float) -> SideBookView:
    return SideBookView(
        token_id="token-up",
        best_bid=best_bid,
        best_ask=best_bid + 0.01,
        spread=0.01,
        freshness_ms=100,
        min_order_size=1.0,
        tick_size=0.01,
        last_trade_price=best_bid,
        last_trade_size=10.0,
        last_trade_timestamp=None,
        received_at=datetime(2026, 7, 6, tzinfo=UTC),
        ask_levels=((best_bid + 0.01, 100.0),),
    )


def _position(opened_at: datetime, entry_price: float = 0.50) -> dict[str, object]:
    return {
        "position_id": "pos-1",
        "instrument_id": "token-up.POLYMARKET",
        "token_id": "token-up",
        "quantity": 20.0,
        "avg_entry_price": entry_price,
        "opened_at": opened_at.isoformat(),
        "is_closed": False,
    }


def _config() -> ExitPolicyConfig:
    return ExitPolicyConfig(
        mode="hold_to_resolution_with_optional_tp_sl",
        take_profit_enabled=True,
        stop_loss_enabled=True,
        take_profit_price=0.90,
        stop_loss_price=0.35,
        max_hold_time_sec=900,
    )


def test_take_profit_exit_uses_nautilus_projection_without_wallet() -> None:
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)

    decision = evaluate_exit_decision(_position(now), _book(0.91), now, _config())

    assert decision is not None
    assert decision.reason is ExitReason.TAKE_PROFIT
    assert decision.instrument_id == "token-up.POLYMARKET"
    assert decision.quantity == 20.0
    assert decision.limit_price == 0.91


def test_stop_loss_exit_uses_nautilus_projection_without_wallet() -> None:
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)

    decision = evaluate_exit_decision(_position(now), _book(0.44), now, _config())

    assert decision is not None
    assert decision.reason is ExitReason.STOP_LOSS
    assert decision.limit_price == 0.44


def test_max_hold_exit_uses_best_bid_after_hold_time() -> None:
    now = datetime(2026, 7, 6, 12, 20, tzinfo=UTC)
    opened_at = now - timedelta(seconds=901)

    decision = evaluate_exit_decision(_position(opened_at), _book(0.51), now, _config())

    assert decision is not None
    assert decision.reason is ExitReason.MAX_HOLD_TIME
    assert decision.limit_price == 0.51


def test_no_exit_when_thresholds_not_met() -> None:
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)

    assert evaluate_exit_decision(_position(now), _book(0.53), now, _config()) is None
```

- [ ] **Step 2: Write failing Nautilus exit order test**

Create `tests/test_nautilus_native_exit.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

from polysignal_lab.nautilus_runtime.exit_policy import ExitReason, NautilusExitDecision
from polysignal_lab.nautilus_runtime.native_exit import submit_exit_decision


class FakeOrderFactory:
    def limit(self, **kwargs):
        return kwargs


class FakeStrategy:
    def __init__(self) -> None:
        self.order_factory = FakeOrderFactory()
        self.submitted_orders = []

    def submit_order(self, order):
        self.submitted_orders.append(order)


def test_submit_exit_decision_submits_reduce_only_sell_order() -> None:
    strategy = FakeStrategy()
    decision = NautilusExitDecision(
        reason=ExitReason.TAKE_PROFIT,
        position_id="pos-1",
        instrument_id="token-up.POLYMARKET",
        quantity=20.0,
        limit_price=0.91,
        ts_event=datetime(2026, 7, 6, tzinfo=UTC),
    )

    order = submit_exit_decision(
        strategy,
        decision,
        instrument_id_resolver=lambda value: value,
    )

    assert order is strategy.submitted_orders[-1]
    assert order["instrument_id"] == "token-up.POLYMARKET"
    assert order["reduce_only"] is True
    assert "exit_reason=take_profit" in order["tags"]
```

- [ ] **Step 3: Write failing native strategy call-site test**

Append to `tests/test_nautilus_native_exit.py`:

```python
def test_evaluate_condition_submits_exit_order_for_qualifying_position(monkeypatch) -> None:
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from polysignal_lab.alpha.types import FreshnessView, MarketView, SideBookView
    from polysignal_lab.config import ExitModelConfig
    from polysignal_lab.domain.enums import Side
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    submitted = []

    class Core:
        def evaluate(self, view):
            return []

    class Assembler:
        def build(self, condition_id):
            now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
            up = SideBookView(
                token_id="token-up",
                best_bid=0.91,
                best_ask=0.92,
                spread=0.01,
                freshness_ms=100,
            )
            down = SideBookView(
                token_id="token-down",
                best_bid=0.10,
                best_ask=0.11,
                spread=0.01,
                freshness_ms=100,
            )
            return MarketView(
                view_id="view-1",
                market_id="mkt-1",
                market_slug="slug",
                condition_id=condition_id,
                asset="BTC",
                timeframe="5m",
                start_ts=None,
                end_ts=None,
                created_at=now,
                seconds_to_close=300,
                up=up,
                down=down,
                spot=None,
                price_to_beat=None,
                up_trades=(),
                down_trades=(),
                metrics={},
                freshness=FreshnessView(100, 100, None, 100),
            )

    class Registry:
        def by_condition(self, condition_id):
            return None

    strategy = PolySignalNativeStrategy(
        core=Core(),
        assembler=Assembler(),
        condition_ids=("condition-1",),
        strategy_name="test",
        registry=Registry(),
        sidecar=SimpleNamespace(),
        exit_model=ExitModelConfig(),
        instrument_id_resolver=lambda value: value,
    )
    strategy.cache_reader = SimpleNamespace(
        read_positions=lambda: [
            {
                "position_id": "pos-1",
                "condition_id": "condition-1",
                "instrument_id": "token-up.POLYMARKET",
                "token_id": "token-up",
                "quantity": 20.0,
                "avg_entry_price": 0.50,
                "opened_at": "2026-07-06T12:00:00+00:00",
                "is_closed": False,
            }
        ]
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.native_exit.submit_exit_decision",
        lambda _strategy, decision, **_kwargs: submitted.append(decision),
    )

    strategy.evaluate_condition("condition-1")

    assert len(submitted) == 1
    assert submitted[0].position_id == "pos-1"
```

- [ ] **Step 5: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_nautilus_exit_policy.py tests/test_nautilus_native_exit.py -v
```

Expected: FAIL because `exit_policy.py`, `native_exit.py`, and native strategy exit call-site do not exist.

- [ ] **Step 5: Implement Nautilus exit policy**

Create `src/polysignal_lab/nautilus_runtime/exit_policy.py`:

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

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


def _decision(
    reason: ExitReason,
    position_id: str,
    instrument_id: str,
    quantity: float,
    limit_price: float,
    now: datetime,
) -> NautilusExitDecision:
    return NautilusExitDecision(
        reason=reason,
        position_id=position_id,
        instrument_id=instrument_id,
        quantity=quantity,
        limit_price=limit_price,
        ts_event=now.astimezone(UTC),
    )


def _opened_at(position: Mapping[str, object]) -> datetime | None:
    value = position.get("opened_at") or position.get("ts")
    parsed = parse_dt(value)
    if parsed is None:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _float(value: object) -> float:
    if not isinstance(value, (int, float, str)):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
```

- [ ] **Step 6: Implement Nautilus reduce-only exit submission**

Create `src/polysignal_lab/nautilus_runtime/native_exit.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from polysignal_lab.nautilus_runtime.exit_policy import NautilusExitDecision
from polysignal_lab.nautilus_runtime.native_order import (
    OrderSubmittingStrategy,
    _enum_member,
    _instrument_id,
    _price_value,
    _quantity_value,
)

OrderT = TypeVar("OrderT")


def submit_exit_decision(
    strategy: OrderSubmittingStrategy[OrderT],
    decision: NautilusExitDecision,
    *,
    instrument_id_resolver: Callable[[str], object],
) -> OrderT:
    instrument = instrument_id_resolver(decision.instrument_id)
    order = strategy.order_factory.limit(
        instrument_id=_instrument_id(instrument),
        order_side=_enum_member("OrderSide", "SELL", "SELL"),
        quantity=_quantity_value(instrument, decision.quantity),
        price=_price_value(instrument, decision.limit_price),
        time_in_force=_enum_member("TimeInForce", "IOC", "IOC"),
        reduce_only=True,
        expire_time=None,
        tags=[
            f"exit_reason={decision.reason.value}",
            f"position_id={decision.position_id}",
        ],
    )
    strategy.submit_order(order)
    return order
```

- [ ] **Step 7: Wire exit policy into native strategy without local wallet state**

In `src/polysignal_lab/nautilus_runtime/native_strategy.py`, add an explicit cache-reader field and a method that reads Nautilus position projections from that field. The method must not import `polysignal_lab.paper.*`.

Add `exit_model: object | None = None` to `PolySignalNativeStrategy.__init__()` immediately after the `observability` parameter. Add these assignments after `self.observability` is assigned:

```python
        self.cache_reader: object | None = None
        self.exit_model: object | None = exit_model
```

In `src/polysignal_lab/nautilus_runtime/node.py`, pass the configured exit model when constructing each native strategy in `_build_native_strategies(...)`:

```python
            exit_model=settings.paper_trading.exit_model,
```

After `cache_reader = _attach_cache_projections(node, registry, assembler)`, add:

```python
    for strategy in strategies:
        setattr(strategy, "cache_reader", cache_reader)
```

In `evaluate_condition()`, after the loop that calls `self._handle_decision(decision, view)`, add this call site:

```python
        self.evaluate_exit_positions(condition_id, view)
```

Then add this method to `PolySignalNativeStrategy`:

```python
    def evaluate_exit_positions(self, condition_id: str, view: MarketView) -> None:
        cache_reader = getattr(self, "cache_reader", None)
        read_positions = getattr(cache_reader, "read_positions", None)
        if not callable(read_positions):
            return
        rows = read_positions()
        if not isinstance(rows, list):
            return
        from polysignal_lab.nautilus_runtime.exit_policy import ExitPolicyConfig, evaluate_exit_decision
        from polysignal_lab.nautilus_runtime.native_exit import submit_exit_decision

        raw_config = self.exit_model
        if raw_config is None:
            return
        config = ExitPolicyConfig(
            mode=str(getattr(raw_config, "mode", "hold_to_resolution_with_optional_tp_sl")),
            take_profit_enabled=bool(getattr(raw_config, "take_profit_enabled", True)),
            stop_loss_enabled=bool(getattr(raw_config, "stop_loss_enabled", True)),
            take_profit_price=float(getattr(raw_config, "take_profit_price", 0.90)),
            stop_loss_price=float(getattr(raw_config, "stop_loss_price", 0.35)),
            max_hold_time_sec=int(getattr(raw_config, "max_hold_time_sec", 900)),
        )
        now = view.created_at
        for position in rows:
            if not isinstance(position, dict):
                continue
            if str(position.get("condition_id") or "") != condition_id:
                continue
            token_id = str(position.get("token_id") or "")
            book = view.up if token_id == view.up.token_id else view.down if token_id == view.down.token_id else None
            if book is None:
                continue
            decision = evaluate_exit_decision(position, book, now, config)
            if decision is None:
                continue
            submit_exit_decision(
                self,
                decision,
                instrument_id_resolver=self.instrument_id_resolver,
            )
```

- [ ] **Step 8: Run exit tests**

Run:

```bash
uv run pytest tests/test_nautilus_exit_policy.py tests/test_nautilus_native_exit.py -v
```

Expected: PASS.

- [ ] **Step 9: Commit Nautilus-managed exit replacement**

```bash
git add src/polysignal_lab/nautilus_runtime/exit_policy.py src/polysignal_lab/nautilus_runtime/native_exit.py src/polysignal_lab/nautilus_runtime/native_strategy.py tests/test_nautilus_exit_policy.py tests/test_nautilus_native_exit.py
git commit -m "feat: manage exits through Nautilus orders"
```

---

### Task 4: 删除本地 paper execution 模块和测试

**Files:**
- Remove: `src/polysignal_lab/paper/fill_model.py`
- Remove: `src/polysignal_lab/paper/order_intent_executor.py`
- Remove: `src/polysignal_lab/paper/simulator.py`
- Remove: `src/polysignal_lab/paper/wallet.py`
- Remove: `src/polysignal_lab/paper/exit_engine.py`
- Remove: `src/polysignal_lab/paper/preflight.py`
- Modify: `src/polysignal_lab/paper/__init__.py`
- Remove: `tests/test_paper_simulation.py`
- Remove: `tests/test_paper_execution_preflight.py`
- Remove: `tests/test_exit_engine.py`
- Modify: tests importing deleted modules

**Interfaces:**
- Consumes: Task 2 signal-only scheduler path.
- Produces: no importable local execution modules under `polysignal_lab.paper`.

- [ ] **Step 1: Write import-deletion boundary test**

Append to `tests/test_nautilus_safety_boundary.py`:

```python
def test_local_paper_execution_modules_are_deleted() -> None:
    deleted_paths = [
        Path("src/polysignal_lab/paper/fill_model.py"),
        Path("src/polysignal_lab/paper/order_intent_executor.py"),
        Path("src/polysignal_lab/paper/simulator.py"),
        Path("src/polysignal_lab/paper/wallet.py"),
        Path("src/polysignal_lab/paper/exit_engine.py"),
        Path("src/polysignal_lab/paper/preflight.py"),
    ]

    assert [str(path) for path in deleted_paths if path.exists()] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_nautilus_safety_boundary.py::test_local_paper_execution_modules_are_deleted -v
```

Expected: FAIL with existing deleted_paths list.

- [ ] **Step 3: Remove local paper execution files**

Run:

```bash
git rm src/polysignal_lab/paper/fill_model.py src/polysignal_lab/paper/order_intent_executor.py src/polysignal_lab/paper/simulator.py src/polysignal_lab/paper/wallet.py src/polysignal_lab/paper/exit_engine.py src/polysignal_lab/paper/preflight.py tests/test_paper_simulation.py tests/test_paper_execution_preflight.py tests/test_exit_engine.py
```

Expected: all listed files removed from the index.

- [ ] **Step 4: Reduce `paper/__init__.py` to business-only package marker**

Replace `src/polysignal_lab/paper/__init__.py` with:

```python
"""Business reporting and Polymarket outcome resolution helpers.

This package intentionally contains no paper execution engine, wallet ledger,
fill model, or resting-order store. Paper execution belongs to Nautilus sandbox
execution; runtime state belongs to Nautilus cache and portfolio.
"""
```

- [ ] **Step 5: Find and remove imports of deleted modules**

Run:

```bash
uv run python - <<'PY'
from pathlib import Path
needles = (
    'polysignal_lab.paper.fill_model',
    'polysignal_lab.paper.order_intent_executor',
    'polysignal_lab.paper.simulator',
    'polysignal_lab.paper.wallet',
    'polysignal_lab.paper.exit_engine',
    'polysignal_lab.paper.preflight',
    'BestAskTakerExecutor',
    'PassiveGtdExecutor',
    'PaperSimulator',
    'from polysignal_lab.paper.wallet import',
    'PaperWallet(',
    'BestAskTakerFillModel',
    'PaperExecutionPreflight',
    'PaperExitEngine',
)
offenders = []
for path in Path('src').rglob('*.py'):
    text = path.read_text(encoding='utf-8')
    for needle in needles:
        if needle in text:
            offenders.append(f'{path}:{needle}')
print('\n'.join(offenders))
raise SystemExit(1 if offenders else 0)
PY
```

Expected before cleanup: printed offenders. Remove each import or test reference by deleting the code path that used local paper execution. Expected after cleanup: no output and exit code 0.

- [ ] **Step 6: Run boundary tests**

Run:

```bash
uv run pytest tests/test_nautilus_safety_boundary.py::test_local_paper_execution_modules_are_deleted tests/test_nautilus_safety_boundary.py::test_project_source_avoids_local_paper_execution_wheels -v
```

Expected: PASS.

- [ ] **Step 7: Commit module deletion**

```bash
git add src/polysignal_lab/paper/__init__.py tests/test_nautilus_safety_boundary.py
git add -u src/polysignal_lab/paper tests
git commit -m "refactor: delete local paper execution stack"
```

---

### Task 5: Make reporting and settlement Nautilus-projection-only

**Files:**
- Modify: `src/polysignal_lab/app/scheduler_reporting.py:37-588`
- Modify: `src/polysignal_lab/paper/report.py:1-236`
- Modify: `tests/test_nautilus_reporting_cache_source.py:1-117`
- Modify: `tests/test_scheduler_reports.py`

**Interfaces:**
- Consumes: `scheduler.nautilus_cache_reader` with `read_orders()`, `read_fills()`, `read_positions()`, `read_account_projection()`, `snapshot_portfolio_projection()`.
- Produces: `_report_equity_inputs(scheduler: PolySignalScheduler) -> tuple[float, float, int]` has no wallet fallback.
- Produces: `generate_daily_report()` reads Nautilus projections first and never accesses `scheduler.wallet`.

- [ ] **Step 1: Replace wallet fallback test with Nautilus-required behavior**

In `tests/test_nautilus_reporting_cache_source.py`, replace lines 111-117 with:

```python
def test_report_equity_inputs_requires_nautilus_cache_reader() -> None:
    scheduler = SimpleNamespace(
        settings=_settings(),
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 1_000.0, 0)
```

Append this test:

```python
def test_report_equity_inputs_ignores_shadow_wallet_without_cache_reader() -> None:
    scheduler = SimpleNamespace(
        settings=_settings(),
        wallet=SimpleNamespace(starting_balance=1_000.0, equity=1_025.0, open_position_count=3),
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 1_000.0, 0)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/test_nautilus_reporting_cache_source.py::test_report_equity_inputs_ignores_shadow_wallet_without_cache_reader -v
```

Expected: FAIL because current helper uses wallet fallback.

- [ ] **Step 3: Remove wallet fallback in reporting**

Replace `_report_equity_inputs()` in `src/polysignal_lab/app/scheduler_reporting.py` lines 345-362 with:

```python
def _report_equity_inputs(scheduler: PolySignalScheduler) -> tuple[float, float, int]:
    starting_equity = float(scheduler.settings.paper_trading.starting_balance_usdc)
    cache_reader = _nautilus_cache_reader(scheduler)
    if cache_reader is None:
        return starting_equity, starting_equity, 0
    return _report_equity_inputs_from_nautilus_cache(
        cache_reader,
        starting_equity=starting_equity,
    )
```

- [ ] **Step 4: Replace `check_settlements()` with projection-only no-wallet implementation**

Replace `check_settlements()` lines 37-156 with:

```python
async def check_settlements(scheduler: PolySignalScheduler) -> list[PaperTradeResult]:
    cache_reader = _nautilus_cache_reader(scheduler)
    if cache_reader is None:
        return []
    read_positions = getattr(cache_reader, "read_positions", None)
    if not callable(read_positions):
        return []
    raw_positions = read_positions()
    if not isinstance(raw_positions, list):
        return []

    settled: list[PaperTradeResult] = []
    for projection in raw_positions:
        if not isinstance(projection, dict):
            continue
        if bool(projection.get("is_closed")):
            continue
        market_id = str(projection.get("market_id") or "")
        token_id = str(projection.get("token_id") or projection.get("instrument_id") or "")
        if not market_id or not token_id:
            continue
        market = scheduler.ctx.markets.get(market_id)
        if market is None:
            rows = scheduler.persistence.query_json(
                "markets",
                where="WHERE market_id = ?",
                params=(market_id,),
            )
            if not rows:
                continue
            try:
                market = Market.model_validate(rows[0])
            except (TypeError, ValueError):
                continue
        decision = await scheduler.settlement_resolver.resolve_market(market)
        if decision.status != "resolved":
            continue
        outcome_value = decision.outcome_value_for(token_id)
        if outcome_value is None:
            continue
        result = _paper_trade_result_from_projection(
            projection,
            market=market,
            outcome_value=outcome_value,
            details=decision.details,
        )
        await _store_projection_result(scheduler, result)
        settled.append(result)
    return settled
```

Add these helpers below `check_settlements()`:

```python
def _paper_trade_result_from_projection(
    projection: dict[str, object],
    *,
    market: Market,
    outcome_value: float,
    details: dict[str, object],
) -> PaperTradeResult:
    quantity = _projection_float(projection, "quantity") or 0.0
    entry_price = _projection_float(projection, "avg_entry_price") or 0.0
    stake = quantity * entry_price
    settlement_value = quantity * float(outcome_value)
    pnl = settlement_value - stake
    return PaperTradeResult(
        paper_trade_id=new_id("ptr"),
        paper_position_id=str(projection.get("paper_position_id") or projection.get("position_id") or ""),
        market_id=market.market_id,
        market_slug=market.market_slug,
        token_id=str(projection.get("token_id") or projection.get("instrument_id") or ""),
        side=str(projection.get("side") or ""),
        entry_price=entry_price,
        exit_price=float(outcome_value),
        shares=quantity,
        stake_usdc=stake,
        settlement_value=settlement_value,
        pnl_usdc=pnl,
        result=TradeResultStatus.WIN if pnl > 0 else TradeResultStatus.LOSS,
        exit_mode=ExitMode.SETTLEMENT,
        opened_at=parse_dt(str(projection.get("ts") or "")) or utc_now(),
        closed_at=utc_now(),
        details=details,
    )


async def _store_projection_result(
    scheduler: PolySignalScheduler,
    result: PaperTradeResult,
) -> None:
    scheduler.persistence.insert_paper_trade_result(result)
    scheduler.persistence.append_log("paper_trade_results", result)
```

Add imports at top if missing:

```python
from polysignal_lab.domain.enums import ExitMode, TradeResultStatus
from polysignal_lab.utils import new_id, utc_now
```

- [ ] **Step 5: Run reporting tests**

Run:

```bash
uv run pytest tests/test_nautilus_reporting_cache_source.py tests/test_scheduler_reports.py -v
```

Expected: PASS after updating any report fixture that used `scheduler.wallet` to use `scheduler.nautilus_cache_reader`.

- [ ] **Step 6: Commit reporting projection cleanup**

```bash
git add src/polysignal_lab/app/scheduler_reporting.py src/polysignal_lab/paper/report.py tests/test_nautilus_reporting_cache_source.py tests/test_scheduler_reports.py
git commit -m "refactor: make reports use Nautilus projections only"
```

---

### Task 6: 删除 `native_strategy.py` 自建 subscription owner registry

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py:80-175,299-354,1004-1050`
- Modify: `tests/test_nautilus_strategy_base.py`
- Modify: `tests/test_nautilus_custom_data.py`
- Modify: `tests/test_nautilus_market_rotation.py`

**Interfaces:**
- Consumes: Nautilus strategy methods `subscribe_quote_ticks`, `subscribe_trade_ticks`, `subscribe_order_book_deltas`, and matching unsubscribe methods when present.
- Produces: `PolySignalNativeStrategy` no longer stores `_MarketDataSubscriptionGroup`; idempotence is local to `_subscription_state.wire_condition_ids` only.

- [ ] **Step 1: Add boundary test that the custom group is gone**

Append to `tests/test_nautilus_strategy_base.py`:

```python
def test_native_strategy_does_not_define_custom_market_data_subscription_group() -> None:
    import inspect
    import polysignal_lab.nautilus_runtime.native_strategy as native_strategy

    source = inspect.getsource(native_strategy)

    assert "class _MarketDataSubscriptionGroup" not in source
    assert "_polysignal_market_data_subscription_group" not in source
    assert "_market_data_subscription_group" not in source
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_nautilus_strategy_base.py::test_native_strategy_does_not_define_custom_market_data_subscription_group -v
```

Expected: FAIL because the class and field still exist.

- [ ] **Step 3: Remove custom subscription group code**

In `src/polysignal_lab/nautilus_runtime/native_strategy.py`, delete lines 103-175 completely:

```python
class _MarketDataSubscriptionGroup:
    ...
```

Delete this field assignment from `PolySignalNativeStrategy.__init__()`:

```python
        self._market_data_subscription_group: _MarketDataSubscriptionGroup = _market_data_subscription_group(registry)
        self._market_data_subscription_group.register(self)
```

- [ ] **Step 4: Replace subscription decision with direct Nautilus calls**

Replace `_subscribe_market_conditions()` lines 1004-1050 with:

```python
    def _subscribe_market_conditions(self, condition_ids: Sequence[str]) -> None:
        if self.registry is None:
            return
        for condition_id in condition_ids:
            if condition_id not in self._active_condition_ids:
                continue
            if condition_id in self._subscription_state.wire_condition_ids:
                self._subscription_state.pending_metadata_condition_ids.discard(condition_id)
                self._subscription_state.pending_subscribe_condition_ids.discard(condition_id)
                self._subscription_state.retained_wire_condition_ids.discard(condition_id)
                continue
            instrument_ids = _instrument_ids(self.registry, (condition_id,))
            if not instrument_ids:
                self._subscription_state.pending_metadata_condition_ids.add(condition_id)
                self._subscription_state.pending_subscribe_condition_ids.discard(condition_id)
                continue
            self._subscription_state.pending_metadata_condition_ids.discard(condition_id)
            for instrument_id in instrument_ids:
                self._subscribe_market_instrument(instrument_id)
            self._subscription_state.pending_subscribe_condition_ids.discard(condition_id)
            self._subscription_state.retained_wire_condition_ids.discard(condition_id)
            self._subscription_state.wire_condition_ids.add(condition_id)
```

Replace `_subscribe_market_instrument()` with this direct-call implementation:

```python
    def _subscribe_market_instrument(self, instrument_id: str) -> None:
        for data_name in self.data_names:
            method = getattr(self, f"subscribe_{data_name}", None)
            if callable(method):
                _ = method(instrument_id)
        if self.book_type == "L1_MBP":
            request_l1 = getattr(self, "request_order_book_snapshot", None)
            if callable(request_l1):
                _ = request_l1(instrument_id)
```

Replace `_unsubscribe_market_conditions()` with:

```python
    def _unsubscribe_market_conditions(self, condition_ids: Sequence[str]) -> None:
        if self.registry is None:
            return
        for condition_id in condition_ids:
            instrument_ids = _instrument_ids(self.registry, (condition_id,))
            for instrument_id in instrument_ids:
                self._unsubscribe_market_instrument(instrument_id)
            self._subscription_state.wire_condition_ids.discard(condition_id)
            self._subscription_state.retained_wire_condition_ids.discard(condition_id)
            self._subscription_state.pending_subscribe_condition_ids.discard(condition_id)
            self._subscription_state.pending_metadata_condition_ids.discard(condition_id)
```

Replace `_unsubscribe_market_instrument()` with:

```python
    def _unsubscribe_market_instrument(self, instrument_id: str) -> None:
        for data_name in self.data_names:
            method = getattr(self, f"unsubscribe_{data_name}", None)
            if callable(method):
                _ = method(instrument_id)
```

- [ ] **Step 5: Run strategy subscription tests**

Run:

```bash
uv run pytest tests/test_nautilus_strategy_base.py tests/test_nautilus_custom_data.py tests/test_nautilus_market_rotation.py -v
```

Expected: PASS. Existing tests that expected wire-owner behavior must be rewritten to assert direct Nautilus subscription calls and no custom owner registry.

- [ ] **Step 6: Commit subscription dedup**

```bash
git add src/polysignal_lab/nautilus_runtime/native_strategy.py tests/test_nautilus_strategy_base.py tests/test_nautilus_custom_data.py tests/test_nautilus_market_rotation.py
git commit -m "refactor: remove custom Nautilus subscription registry"
```

---

### Task 7: 删除 order mapping 中的 execution-like depth precheck

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/order_mapping.py:12-112`
- Modify: `src/polysignal_lab/nautilus_runtime/native_order.py:39-76`
- Modify: `src/polysignal_lab/nautilus_runtime/native_strategy.py` call sites for `submit_approved_decision(...)`
- Modify: `tests/test_nautilus_order_mapping.py`
- Modify: `tests/test_nautilus_native_order.py`

**Interfaces:**
- Produces: `order_spec_from_decision(decision, fixed_stake_usdc, best_ask=None) -> NautilusOrderSpec`
- Produces: `submit_approved_decision(strategy, approved, *, fixed_stake_usdc, best_ask, instrument_id_resolver, now=None) -> OrderT`
- Removes: `available_shares` parameter and all FOK/FAK/IOC depth rejection from mapping layer.

- [ ] **Step 1: Add tests that FOK maps instead of rejects on missing depth**

Append to `tests/test_nautilus_order_mapping.py`:

```python
def test_fok_order_mapping_does_not_pre_reject_missing_depth(approved_signal) -> None:
    approved_signal.signal.order_intent = "TAKER_FOK"

    spec = order_spec_from_decision(
        approved_signal,
        fixed_stake_usdc=10.0,
        best_ask=0.50,
    )

    assert spec.intent.value == "TAKER_FOK"
    assert spec.price == 0.50
    assert spec.quantity == 20.0
    assert spec.tags["time_in_force"] == "FOK"
```

Append to `tests/test_nautilus_native_order.py`:

```python
def test_submit_approved_decision_does_not_require_available_shares(fake_strategy, approved_signal) -> None:
    approved_signal.signal.order_intent = "TAKER_FOK"

    order = submit_approved_decision(
        fake_strategy,
        approved_signal,
        fixed_stake_usdc=10.0,
        best_ask=0.50,
        instrument_id_resolver=lambda value: value,
    )

    assert order is fake_strategy.submitted_orders[-1]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/test_nautilus_order_mapping.py::test_fok_order_mapping_does_not_pre_reject_missing_depth tests/test_nautilus_native_order.py::test_submit_approved_decision_does_not_require_available_shares -v
```

Expected: FAIL because current mapping requires `available_shares` for FOK.

- [ ] **Step 3: Remove `available_shares` from mapping**

Replace `order_spec_from_decision()` signature lines 12-17 with:

```python
def order_spec_from_decision(
    decision: ApprovedDecision | AlphaDecision | SignalCandidate,
    fixed_stake_usdc: float,
    best_ask: float | None = None,
) -> NautilusOrderSpec:
```

Delete lines 24-27:

```python
    if available_shares is None:
        available_shares = _metric_float(
            metrics, "available_ask_shares", "ask_available_shares", "depth_shares"
        )
```

Replace lines 56-61 with:

```python
    if quantity <= 0:
        raise ValueError("quantity must be positive")
```

- [ ] **Step 4: Remove `available_shares` from native order submission**

Replace `submit_approved_decision()` signature in `src/polysignal_lab/nautilus_runtime/native_order.py` lines 39-48 with:

```python
def submit_approved_decision(
    strategy: OrderSubmittingStrategy[OrderT],
    approved: ApprovedDecision,
    *,
    fixed_stake_usdc: float,
    best_ask: float | None,
    instrument_id_resolver: Callable[[str], object],
    now: Callable[[], datetime] | None = None,
) -> OrderT:
```

Replace the `order_spec_from_decision()` call lines 51-56 with:

```python
    spec = order_spec_from_decision(
        approved,
        fixed_stake_usdc=fixed_stake_usdc,
        best_ask=best_ask,
    )
```

- [ ] **Step 5: Update call sites**

Search references through LSP or CodeGraph before editing. Each call to `submit_approved_decision(...)` must remove `available_shares=...` and keep `best_ask=...`.

The resulting call shape must be:

```python
order = submit_approved_decision(
    self,
    approved,
    fixed_stake_usdc=self.fixed_stake_usdc,
    best_ask=view.best_ask,
    instrument_id_resolver=self.instrument_id_resolver,
)
```

- [ ] **Step 6: Run order tests**

Run:

```bash
uv run pytest tests/test_nautilus_order_mapping.py tests/test_nautilus_native_order.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit order mapping cleanup**

```bash
git add src/polysignal_lab/nautilus_runtime/order_mapping.py src/polysignal_lab/nautilus_runtime/native_order.py src/polysignal_lab/nautilus_runtime/native_strategy.py tests/test_nautilus_order_mapping.py tests/test_nautilus_native_order.py
git commit -m "refactor: delegate fillability to Nautilus sandbox"
```

---

### Task 8: 拆分大型 runtime/reporting 函数

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/node.py:276-376,998-1183`
- Modify: `src/polysignal_lab/app/scheduler_reporting.py:414-588`
- Modify: `tests/test_nautilus_node.py`
- Modify: `tests/test_nautilus_trading_node_runtime.py`
- Modify: `tests/test_scheduler_reports.py`

**Interfaces:**
- Produces: `create_trading_node(settings, instrument_config) -> tuple[object, object]`
- Produces: `wire_runtime_components(settings, node, configured_markets, configured_condition_ids, market_universe, store, health, observability) -> dict[str, object]`
- Produces: `collect_daily_report_inputs(scheduler, today, report_tz) -> DailyReportInputs`
- Produces: existing public `build_trading_node()`, `run_nautilus_cli_async()`, `run_nautilus_cli()`, `generate_daily_report()` signatures remain.

- [ ] **Step 1: Add function-size regression test**

Create `tests/test_function_size_boundaries.py`:

```python
from __future__ import annotations

import ast
from pathlib import Path


LIMITS = {
    "src/polysignal_lab/nautilus_runtime/node.py": {
        "build_trading_node": 55,
        "run_nautilus_cli_async": 70,
        "run_nautilus_cli": 70,
    },
    "src/polysignal_lab/app/scheduler_reporting.py": {
        "generate_daily_report": 80,
    },
}


def _function_lengths(path: Path) -> dict[str, int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lengths: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.end_lineno is not None:
            lengths[node.name] = node.end_lineno - node.lineno + 1
    return lengths


def test_runtime_functions_stay_reviewable() -> None:
    offenders: list[str] = []
    for path_text, limits in LIMITS.items():
        lengths = _function_lengths(Path(path_text))
        for name, limit in limits.items():
            actual = lengths[name]
            if actual > limit:
                offenders.append(f"{path_text}:{name}:{actual}>{limit}")

    assert offenders == []
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_function_size_boundaries.py -v
```

Expected: FAIL with current `build_trading_node`, `run_nautilus_cli_async`, `run_nautilus_cli`, and `generate_daily_report` lengths.

- [ ] **Step 3: Split `build_trading_node()`**

Add these helpers above `build_trading_node()` in `src/polysignal_lab/nautilus_runtime/node.py`:

```python
def _create_configured_trading_node(
    settings: Settings,
    configured_markets: Sequence[Market],
) -> tuple[_TradingNodeLike, object]:
    _ensure_nautilus_imports()
    trading_node_factory = TradingNode
    if trading_node_factory is None:
        raise RuntimeError("Nautilus TradingNode is unavailable")
    instrument_config = PolymarketInstrumentProviderConfig(
        load_ids=_instrument_load_ids(configured_markets),
    )
    config = build_paper_trading_node_config(settings, instrument_config=instrument_config)
    node = trading_node_factory(config=config)
    register_paper_factories(node)
    return cast(_TradingNodeLike, node), config


def _create_market_projection_components(
    configured_markets: Sequence[Market],
) -> tuple[PolymarketMarketRegistry, ExternalDataSidecar, MarketViewAssembler]:
    registry = PolymarketMarketRegistry()
    _register_markets(registry, configured_markets)
    sidecar = ExternalDataSidecar()
    assembler = MarketViewAssembler(
        registry=registry,
        books=_EmptyBookDataProvider(),
        sidecar=sidecar,
    )
    return registry, sidecar, assembler


def _attach_cache_projections(
    node: _TradingNodeLike,
    registry: PolymarketMarketRegistry,
    assembler: MarketViewAssembler,
) -> NautilusCacheReader:
    from polysignal_lab.nautilus_runtime.cache_market_data import NautilusCacheMarketDataProvider
    from polysignal_lab.nautilus_runtime.cache_reader import NautilusCacheReader

    kernel = getattr(node, "kernel", None)
    nautilus_cache = getattr(node, "cache", None) or getattr(kernel, "cache", None)
    assembler.books = NautilusCacheMarketDataProvider(
        nautilus_cache,
        registry=registry,
    )
    return NautilusCacheReader(
        nautilus_cache,
        portfolio=getattr(node, "portfolio", None) or getattr(kernel, "portfolio", None),
    )
```

Then replace `build_trading_node()` body with:

```python
    if settings is None:
        settings = load_settings()
    _ = wallet

    configured_markets = tuple(markets)
    configured_condition_ids = _configured_condition_ids(condition_ids, configured_markets)
    runtime_market_universe = (
        market_universe if market_universe is not None else _StaticMarketUniverse(configured_markets)
    )
    node, config = _create_configured_trading_node(settings, configured_markets)
    registry, sidecar, assembler = _create_market_projection_components(configured_markets)
    policy = _build_policy(settings)
    market_rotation_actor = _build_market_rotation_actor(
        settings=settings,
        startup_markets=configured_markets,
        market_universe=runtime_market_universe,
        registry=registry,
        sidecar=sidecar,
        store=store,
        health=health,
    )
    node.trader.add_actor(market_rotation_actor)
    strategies = _build_native_strategies(
        settings,
        assembler,
        policy,
        configured_condition_ids,
        registry,
        sidecar,
        observability,
    )
    for strategy in strategies:
        node.trader.add_strategy(strategy)
    node.build()
    cache_reader = _attach_cache_projections(node, registry, assembler)
    return _runtime_components(
        node=node,
        config=config,
        registry=registry,
        sidecar=sidecar,
        market_rotation_actor=market_rotation_actor,
        assembler=assembler,
        policy=policy,
        strategies=strategies,
        cache_reader=cache_reader,
    )
```

Add `_runtime_components()` helper:

```python
def _runtime_components(
    *,
    node: _TradingNodeLike,
    config: object,
    registry: PolymarketMarketRegistry,
    sidecar: ExternalDataSidecar,
    market_rotation_actor: object,
    assembler: MarketViewAssembler,
    policy: DecisionPolicyActor,
    strategies: Sequence[_NativeStrategyLike],
    cache_reader: object,
) -> dict[str, object]:
    return {
        "node": node,
        "config": config,
        "registry": registry,
        "sidecar": sidecar,
        "market_rotation_actor": market_rotation_actor,
        "assembler": assembler,
        "policy": policy,
        "strategies": list(strategies),
        "strategy_names": [strategy.strategy_name for strategy in strategies],
        "cache_reader": cache_reader,
    }
```

- [ ] **Step 4: Split daily report input collection**

Add this dataclass near the top of `scheduler_reporting.py`:

```python
@dataclass(frozen=True, slots=True)
class DailyReportInputs:
    today: date
    today_iso: str
    today_signals_raw: list[dict[str, object]]
    today_orders_raw: list[dict[str, object]]
    today_fills_raw: list[dict[str, object]]
    today_reject_orders_raw: list[dict[str, object]]
    trade_results: list[PaperTradeResult]
```

Add helper:

```python
def _collect_daily_report_inputs(
    scheduler: PolySignalScheduler,
    *,
    today: date,
    report_tz: ZoneInfo | timezone,
) -> DailyReportInputs:
    today_iso = today.isoformat()
    day_start_local = datetime.combine(today, time.min, tzinfo=report_tz)
    day_end_local = datetime.combine(today + timedelta(days=1), time.min, tzinfo=report_tz)
    day_start = day_start_local.astimezone(UTC)
    day_end = day_end_local.astimezone(UTC)
    day_params = (_utc_text_bound(day_start), _utc_text_bound(day_end))
    day_created_where = "WHERE created_at >= ? AND created_at < ?"
    day_closed_where = "WHERE closed_at >= ? AND closed_at < ?"

    trade_results = [
        PaperTradeResult(**result)
        for result in scheduler.persistence.query_json(
            "paper_trade_results",
            where=day_closed_where,
            params=day_params,
        )
    ]
    today_fills_raw = scheduler.persistence.query_json(
        "paper_fills",
        where=day_created_where,
        params=day_params,
        limit=10000,
    ) or _nautilus_projection_rows_for_day(
        scheduler,
        "read_fills",
        day_start=day_start,
        day_end=day_end,
    )
    today_orders_raw = scheduler.persistence.query_json(
        "paper_orders",
        where=day_created_where,
        params=day_params,
        limit=10000,
    ) or _nautilus_projection_rows_for_day(
        scheduler,
        "read_orders",
        day_start=day_start,
        day_end=day_end,
    )
    today_signals_raw = scheduler.persistence.query_json(
        "signals",
        where=day_created_where,
        params=day_params,
        limit=10000,
    )
    return DailyReportInputs(
        today=today,
        today_iso=today_iso,
        today_signals_raw=today_signals_raw,
        today_orders_raw=today_orders_raw,
        today_fills_raw=today_fills_raw,
        today_reject_orders_raw=list(today_orders_raw),
        trade_results=trade_results,
    )
```

Refactor `generate_daily_report()` to call `_collect_daily_report_inputs()` and `_build_daily_report_from_inputs()` so the public function is below 80 lines.

- [ ] **Step 5: Run function-size and regression tests**

Run:

```bash
uv run pytest tests/test_function_size_boundaries.py tests/test_nautilus_node.py tests/test_nautilus_trading_node_runtime.py tests/test_scheduler_reports.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit large-function split**

```bash
git add src/polysignal_lab/nautilus_runtime/node.py src/polysignal_lab/app/scheduler_reporting.py tests/test_function_size_boundaries.py tests/test_nautilus_node.py tests/test_nautilus_trading_node_runtime.py tests/test_scheduler_reports.py
git commit -m "refactor: split Nautilus runtime and reporting functions"
```

---

### Task 9: 更新文档并删除旧 paper 叙述

**Files:**
- Modify: `docs/NAUTILUS_BRIDGE_BOUNDARY.md:1-138`
- Modify: `docs/PRD.md:141-184`
- Modify: `docs/PROJECT_ARCHITECTURE_VISUAL.md`
- Modify: `docs/IMPLEMENTATION_SUMMARY.md`
- Modify: `docs/superpowers/plans/2026-07-05-nautilus-runtime-dedup-cleanup.md` only by appending final status note; do not rewrite historical task text.

**Interfaces:**
- Consumes: code state from Tasks 1-7.
- Produces: docs that state no local paper execution stack remains and `TradingNode` remains only as non-wheel design debt.

- [ ] **Step 1: Update bridge boundary final state**

Replace `docs/NAUTILUS_BRIDGE_BOUNDARY.md` lines 111-118 with:

```markdown
- Implemented components after final duplicate-platform cleanup:
  * Default runtime: Nautilus node owns lifecycle, data engine, execution engine, cache, portfolio, and sandbox execution.
  * Node surface: current default still uses legacy Nautilus `TradingNode`; this is a non-wheel design deviation tracked behind a separate `LiveNode.builder` migration gate.
  * Data: Polymarket market data uses `PolymarketLiveDataClientFactory`; business spot/PTB/market metadata uses Nautilus custom data.
  * Execution: paper execution uses `SandboxLiveExecClientFactory`; no local PaperSimulator, PaperWallet, FAK/FOK/GTD executor, fill model, exit engine, or local resting-order store remains.
  * Strategy: `PolySignalNativeStrategy` submits orders through Nautilus `order_factory` and `submit_order`; fillability and order lifecycle are delegated to Nautilus sandbox/cache/portfolio.
  * Market views: alpha views are read-only projections from Nautilus cache plus business custom data.
  * Observability: dashboard/report rows are read-only projections from Nautilus events/cache/portfolio; no local paper ledger drives runtime state.
  * Safety: project-wide source scan blocks live Polymarket execution symbols and local paper execution wheel symbols.
```

- [ ] **Step 2: Update PRD flow**

Replace `docs/PRD.md` lines 173-184 with:

```markdown
### 9.3 纸面交易流程

1. 通过 gate 的信号由 Nautilus strategy wrapper 映射为 Nautilus native order。
2. Strategy wrapper 调用 Nautilus `order_factory.limit(...)` 和 `submit_order(...)`。
3. Nautilus sandbox 根据当前 instrument、book、trade 数据处理 paper order。
4. 如果可成交，Nautilus 生成 fill、position、account/portfolio state。
5. PolySignal 只读投影 Nautilus cache/portfolio，用于 SQLite、JSONL、Telegram、日报和 dashboard。
6. 市场结束后的 win/loss 计算只读取 Nautilus position projection 和 Polymarket outcome resolution，不维护本地 PaperWallet。
7. 写入 PaperTradeResult projection。
8. 更新统计报表。
```

- [ ] **Step 3: Update implementation summary table**

Replace `docs/IMPLEMENTATION_SUMMARY.md` paper-related rows with:

```markdown
| Paper trading | Nautilus node, native order submission, Nautilus sandbox execution, cache/portfolio projections |
| Node surface | Current default uses legacy Nautilus `TradingNode`; this is tracked as a non-wheel design deviation with a separate `LiveNode.builder` migration gate |
| Exits/settlement | Prediction-market resolution remains business logic; runtime positions and account state come from Nautilus portfolio/cache projection |
| Reporting | Daily report, PnL, ROI, win rate, drawdown, profit factor, breakdowns over projected Nautilus state |
```

- [ ] **Step 4: Run documentation grep guard**

Run:

```bash
uv run python - <<'PY'
from pathlib import Path
forbidden = (
    'PaperSimulator',
    'from polysignal_lab.paper.wallet import',
    'PaperWallet(',
    'BestAskTakerExecutor',
    'PassiveGtdExecutor',
    'local paper execution',
    '本地撮合',
)
offenders = []
for path in [Path('docs/NAUTILUS_BRIDGE_BOUNDARY.md'), Path('docs/PRD.md'), Path('docs/PROJECT_ARCHITECTURE_VISUAL.md'), Path('docs/IMPLEMENTATION_SUMMARY.md')]:
    text = path.read_text(encoding='utf-8')
    for needle in forbidden:
        if needle in text:
            offenders.append(f'{path}:{needle}')
print('\n'.join(offenders))
raise SystemExit(1 if offenders else 0)
PY
```

Expected: no output and exit code 0.

- [ ] **Step 5: Commit docs**

```bash
git add docs/NAUTILUS_BRIDGE_BOUNDARY.md docs/PRD.md docs/PROJECT_ARCHITECTURE_VISUAL.md docs/IMPLEMENTATION_SUMMARY.md docs/superpowers/plans/2026-07-05-nautilus-runtime-dedup-cleanup.md
git commit -m "docs: document Nautilus-only paper runtime boundary"
```

---

### Task 10: Final verification suite

**Files:**
- No source edits expected.
- Verify: full source boundary, targeted Nautilus tests, scheduler/report tests.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: evidence that no duplicate local paper runtime remains.

- [ ] **Step 1: Run project-wide safety scan**

Run:

```bash
uv run python -m polysignal_lab.observability.safety src
```

Expected:

```text
Safety scan passed
```

- [ ] **Step 2: Run targeted Nautilus boundary tests**

Run:

```bash
uv run pytest tests/test_nautilus_safety_boundary.py tests/test_nautilus_execution.py tests/test_nautilus_trading_node_runtime.py tests/test_nautilus_node.py -v
```

Expected: all selected tests PASS.

- [ ] **Step 3: Run scheduler/reporting tests**

Run:

```bash
uv run pytest tests/test_scheduler_paper.py tests/test_scheduler_reports.py tests/test_nautilus_reporting_cache_source.py tests/test_function_size_boundaries.py -v
```

Expected: all selected tests PASS.

- [ ] **Step 4: Run import smoke**

Run:

```bash
uv run python - <<'PY'
import importlib
mods = [
    'polysignal_lab',
    'polysignal_lab.app.main',
    'polysignal_lab.app.scheduler',
    'polysignal_lab.nautilus_runtime.node',
    'polysignal_lab.nautilus_runtime.native_strategy',
    'polysignal_lab.nautilus_runtime.native_order',
]
for mod in mods:
    importlib.import_module(mod)
print('imports ok')
PY
```

Expected:

```text
imports ok
```

- [ ] **Step 5: Run forbidden symbol audit**

Run:

```bash
uv run python - <<'PY'
from pathlib import Path
forbidden = (
    'PaperSimulator',
    'from polysignal_lab.paper.wallet import',
    'PaperWallet(',
    'BestAskTakerExecutor',
    'PassiveGtdExecutor',
    'BestAskTakerFillModel',
    'PaperExecutionPreflight',
    'PaperExitEngine',
    'scheduler.wallet',
    'scheduler.paper',
    '_MarketDataSubscriptionGroup',
    '_polysignal_market_data_subscription_group',
)
offenders = []
for path in Path('src/polysignal_lab').rglob('*.py'):
    text = path.read_text(encoding='utf-8')
    for needle in forbidden:
        if needle in text:
            offenders.append(f'{path}:{needle}')
print('\n'.join(offenders))
raise SystemExit(1 if offenders else 0)
PY
```

Expected: no output and exit code 0.

- [ ] **Step 6: Commit final verification notes if any test fixture changed**

If Step 1-5 required fixture-only edits, commit them:

```bash
git add tests docs src
git commit -m "test: verify Nautilus-only runtime boundary"
```

Expected: either a commit is created for fixture corrections or Git reports no staged changes.

---

## Self-Review

**Spec coverage:**
- 删除本地 paper execution/wallet/fill/resting-order stack: Task 2, Task 4。
- 保留 TP/SL/max-hold 产品能力并改由 Nautilus reduce-only exit order 执行: Task 3。
- 删除默认 Nautilus 路径内自建 subscription owner registry: Task 6。
- Reporting/settlement 改为 Nautilus projection-only: Task 5。
- 删除 execution-like FOK/FAK/depth precheck: Task 7。
- 大型函数治理: Task 8。
- 文档同步: Task 9。
- 防回归: Task 1, Task 10。
- 保留 `TradingNode` 为非 wheel 设计偏差: Global Constraints, Task 9。

**Placeholder scan:** 已检查计划文本；未保留未定义占位、延后实现语句、泛化测试要求或跨任务省略引用。

**Type consistency:**
- `process_signal()` 返回 `ProcessSignalResult` 的四个字段：`signal_id`、`stored`、`published`、`publish_status`。
- `order_spec_from_decision()` 新签名为 `(decision, fixed_stake_usdc, best_ask=None)`。
- `submit_approved_decision()` 新签名移除 `available_shares`。
- Reporting helper `_report_equity_inputs()` 始终返回 `tuple[float, float, int]`。

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-06-nautilus-runtime-dedup-final-removal.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
