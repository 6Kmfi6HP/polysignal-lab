# Telegram Interactive Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a default-off Telegram private-chat operations bot that can show runtime state and toggle strategies without changing the existing channel publisher or any trading-capable path.

**Architecture:** Keep `TelegramPublisher` as the one-way channel notification sender. Add `TelegramBotService` as a supervised scheduler runtime service using `python-telegram-bot` embedded polling, with all reads going through `PersistenceService`, `OrderBookRegistry`, `MarketRegistry`, and `SignalPipeline`. Strategy toggles update a runtime disabled set plus `StateStore`; they never mutate the strategy list, YAML, positions, orders, or CLOB clients.

**Tech Stack:** Python 3.11, pydantic v2, pytest/pytest-asyncio, python-telegram-bot v22.5 (`ApplicationBuilder`, `CommandHandler`, `CallbackQueryHandler`, `InlineKeyboardMarkup`, `AIORateLimiter`), SQLite/JSONL/StateStore.

## Global Constraints

- Use `python-telegram-bot[rate-limiter]>=22.5`; do not add aiogram, Telethon, or a custom Telegram Bot API client.
- Do not directly call `https://api.telegram.org/bot...`, do not create a Telegram-specific `httpx.AsyncClient`, and do not hand-roll `getUpdates` polling.
- Existing `TelegramPublisher` stays direct HTTP for channel notifications; the new interactive bot is a separate runtime service.
- `interactive_enabled=false` keeps the service unregistered and preserves current behavior.
- `interactive_enabled=true` with no bot token or an empty allowlist fails closed: no polling and no interactive replies.
- Authorization requires private chat and both `chat.id` and `from_user.id` in `TelegramConfig.interactive_allowed_chat_ids`.
- Every callback branch calls `await query.answer(...)`, including unauthorized, unknown, and failure branches.
- Keep every `callback_data` value within Telegram's 1-64 byte limit; strategy toggle uses `tg:<strategy_name>` and only renders buttons whose UTF-8 byte length is at most 64.
- `start_polling()` uses `allowed_updates=("message", "callback_query")` and `drop_pending_updates=config.interactive_drop_pending_updates_on_start`.
- `interactive_dry_run` is independent from `dry_run`; `dry_run` controls channel publishing only.
- `/positions`, `/status`, `/signals`, and `/daily` are read-only.
- `/strategies` is the only write operation; it modifies only `SignalPipeline.disabled_strategies`, `StateStore`, and a `system_events` audit row.
- Never submit, cancel, close, redeem, or create real orders; never instantiate authenticated CLOB clients or introduce key material.
- Dynamic fields in HTML replies must be escaped with `html.escape` before insertion.
- Tests must not call the real Telegram API and must not require real tokens or real chat IDs.
- Use `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest` for pytest commands.
- After code/config changes intended for formal runtime, rebuild containers with `docker compose up -d --build --force-recreate`, then verify container status and health/logs.

---

## File Structure

- Modify `pyproject.toml`: add the PTB dependency to project dependencies.
- Modify `config/signal_bot.yaml`: add default interactive Telegram config keys under `telegram:`.
- Modify `src/polysignal_lab/config.py`: extend `TelegramConfig` with interactive fields.
- Modify `src/polysignal_lab/app/services/persistence_service.py`: expose `restore_daily_reports()` and `restore_latest_system_event()` proxies over `SQLiteStore`.
- Modify `src/polysignal_lab/strategies/readiness.py`: allow `StrategyMarketStatus.status == "inactive"` for manual/dependency-disabled runtime skips.
- Modify `src/polysignal_lab/app/services/signal_pipeline.py`: add `disabled_strategies`, strategy enable/disable helpers, and dependency skip reasoning.
- Modify `src/polysignal_lab/app/scheduler_processing.py`: skip disabled strategies before readiness/evaluation in the real scheduler path.
- Create `src/polysignal_lab/publish/telegram_bot.py`: PTB service, handler registration, authorization, keyboards, route rendering, health metrics, and safe reply/edit helpers.
- Modify `src/polysignal_lab/app/scheduler.py`: register `TelegramBotService` between `publish_service` and `health_service` when interactive mode is enabled; bind strategy dependency metadata after strategy construction.
- Modify or create `tests/test_telegram_bot_config.py`: dependency/config/proxy tests.
- Create `tests/test_signal_pipeline_manual_disable.py`: disabled strategy and dependency skip tests.
- Create `tests/test_telegram_bot_service.py`: PTB lifecycle, handlers, authorization, callback, dry-run, query formatting, and toggle tests.
- Modify `tests/test_scheduler_lifecycle.py`: scheduler service registration and health-supervisor integration tests.

---

### Task 1: Config, dependency, and persistence proxies

**Files:**
- Modify: `pyproject.toml`
- Modify: `config/signal_bot.yaml`
- Modify: `src/polysignal_lab/config.py`
- Modify: `src/polysignal_lab/app/services/persistence_service.py`
- Create: `tests/test_telegram_bot_config.py`
- Test command: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_telegram_bot_config.py tests/test_persistence_service.py -q`

**Interfaces:**
- Consumes: existing `TelegramConfig.resolved_bot_token`, `TelegramConfig.resolved_channel_id`, `SQLiteStore.restore_daily_reports(limit: int = 100) -> list[dict[str, Any]]`, `SQLiteStore.restore_latest_system_event(event_type: str) -> dict[str, Any] | None`.
- Produces: `TelegramConfig.interactive_enabled: bool`, `interactive_dry_run: bool`, `interactive_allowed_chat_ids: tuple[int, ...]`, `interactive_poll_interval_sec: float`, `interactive_poll_timeout_sec: int`, `interactive_drop_pending_updates_on_start: bool`; `PersistenceService.restore_daily_reports(limit: int = 100) -> list[dict[str, Any]]`; `PersistenceService.restore_latest_system_event(event_type: str) -> dict[str, Any] | None`.

- [ ] **Step 1: Write failing config and proxy tests**

Create `tests/test_telegram_bot_config.py`:

```python
from __future__ import annotations

from datetime import date

from polysignal_lab.app.services.persistence_service import PersistenceService
from polysignal_lab.config import Settings, TelegramConfig, load_settings
from polysignal_lab.domain.paper_result import DailyReport
from polysignal_lab.storage.jsonl_store import JSONLStore
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.storage.state_store import StateStore
from polysignal_lab.utils import new_id, utc_iso


def test_telegram_interactive_config_defaults_fail_closed() -> None:
    config = TelegramConfig()

    assert config.interactive_enabled is False
    assert config.interactive_dry_run is False
    assert config.interactive_allowed_chat_ids == ()
    assert config.interactive_poll_interval_sec == 0.0
    assert config.interactive_poll_timeout_sec == 30
    assert config.interactive_drop_pending_updates_on_start is True


def test_telegram_interactive_yaml_defaults_load() -> None:
    settings = load_settings("config/signal_bot.yaml")

    assert isinstance(settings, Settings)
    assert settings.telegram.interactive_enabled is False
    assert settings.telegram.interactive_dry_run is False
    assert settings.telegram.interactive_allowed_chat_ids == ()
    assert settings.telegram.interactive_poll_interval_sec == 0.0
    assert settings.telegram.interactive_poll_timeout_sec == 30
    assert settings.telegram.interactive_drop_pending_updates_on_start is True


def test_persistence_service_restores_daily_reports_and_latest_event(tmp_path) -> None:
    sqlite = SQLiteStore(tmp_path / "db.sqlite3")
    service = PersistenceService(
        JSONLStore(tmp_path / "logs"), sqlite, StateStore(tmp_path / "state")
    )
    report = DailyReport(
        report_date=date(2026, 6, 24),
        starting_equity=1000.0,
        ending_equity=1005.0,
        paper_pnl=5.0,
        paper_roi=0.005,
        total_signals=2,
        paper_orders=2,
        paper_fills=1,
        rejected_paper_orders=1,
        open_positions=1,
        closed_positions=1,
        win_count=1,
        loss_count=0,
        void_count=0,
        win_rate=1.0,
        total_pnl_usdc=5.0,
        average_roi=0.005,
        max_drawdown=0.0,
        profit_factor=None,
    )
    event = {
        "event_id": new_id("health_snapshot"),
        "event_type": "health_snapshot",
        "severity": "INFO",
        "created_at": utc_iso(),
        "status": "ok",
        "components": [],
    }

    service.insert_daily_report(report)
    service.insert_system_event(event)

    assert service.restore_daily_reports(limit=1)[0]["report_id"] == report.report_id
    assert service.restore_latest_system_event("health_snapshot") == event
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_telegram_bot_config.py -q
```

Expected: FAIL because `TelegramConfig` has no interactive fields and `PersistenceService` has no restore proxies.

- [ ] **Step 3: Add PTB dependency**

In `pyproject.toml`, change the project dependencies block to include PTB:

```toml
dependencies = [
  "pydantic>=2.8",
  "pydantic-settings>=2.4",
  "PyYAML>=6.0",
  "httpx>=0.27",
  "websockets>=12.0",
  "anyio>=4.0",
  "fastapi>=0.111",
  "uvicorn>=0.30",
  "py-clob-client-v2>=0.1.0",
  "python-telegram-bot[rate-limiter]>=22.5"
]
```

Run dependency sync after editing:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv sync --extra dev
```

Expected: PASS with dependencies resolved; `uv.lock` changes if the lockfile is present in the checkout.

- [ ] **Step 4: Extend `TelegramConfig` minimally**

In `src/polysignal_lab/config.py`, add these fields directly after `dry_run: bool = True`:

```python
    interactive_enabled: bool = False
    interactive_dry_run: bool = False
    interactive_allowed_chat_ids: tuple[int, ...] = ()
    interactive_poll_interval_sec: float = 0.0
    interactive_poll_timeout_sec: int = 30
    interactive_drop_pending_updates_on_start: bool = True
```

- [ ] **Step 5: Add YAML defaults**

In `config/signal_bot.yaml`, add these keys directly after `dry_run: true`:

```yaml
  interactive_enabled: false
  interactive_dry_run: false
  interactive_allowed_chat_ids: []
  interactive_poll_interval_sec: 0.0
  interactive_poll_timeout_sec: 30
  interactive_drop_pending_updates_on_start: true
```

- [ ] **Step 6: Add `PersistenceService` proxies**

In `src/polysignal_lab/app/services/persistence_service.py`, add the methods after `restore_open_positions()`:

```python
    def restore_daily_reports(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.sqlite.restore_daily_reports(limit=limit)

    def restore_latest_system_event(self, event_type: str) -> dict[str, Any] | None:
        return self.sqlite.restore_latest_system_event(event_type)
```

- [ ] **Step 7: Run tests to verify GREEN**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_telegram_bot_config.py tests/test_persistence_service.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock config/signal_bot.yaml src/polysignal_lab/config.py src/polysignal_lab/app/services/persistence_service.py tests/test_telegram_bot_config.py
git commit -m "feat: add telegram interactive config"
```

---

### Task 2: Runtime strategy disable semantics

**Files:**
- Modify: `src/polysignal_lab/strategies/readiness.py`
- Modify: `src/polysignal_lab/app/services/signal_pipeline.py`
- Modify: `src/polysignal_lab/app/scheduler_processing.py`
- Create: `tests/test_signal_pipeline_manual_disable.py`
- Test command: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_signal_pipeline_manual_disable.py tests/test_signal_pipeline_equivalence.py tests/test_strategy_execution_order.py -q`

**Interfaces:**
- Consumes: `StrategyScheduleEntry(name: str, depends_on: tuple[str, ...])`, `StrategyMarketStatus(strategy, asset, timeframe, status, reason)`, `scheduler.signal_pipeline`, `scheduler.persistence`.
- Produces: `SignalPipeline.disabled_strategies: set[str]`, `set_strategy_enabled(name: str, enabled: bool) -> None`, `is_strategy_enabled(name: str) -> bool`, `skip_reason_for(name: str) -> str | None`, `set_strategy_dependencies(dependencies: dict[str, tuple[str, ...]]) -> None`.

- [ ] **Step 1: Write failing disabled-strategy tests**

Create `tests/test_signal_pipeline_manual_disable.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from factories import BookFactoryConfig, MarketFactoryConfig, sample_book, sample_market, sample_spot

from polysignal_lab.app.services.signal_pipeline import SignalPipeline
from polysignal_lab.app import scheduler_processing
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import FreshnessState, MarketSnapshot
from polysignal_lab.signal_layer.gate import GateDecision
from polysignal_lab.strategies.base import BaseStrategy
from polysignal_lab.strategies.execution import StrategyScheduleEntry


@dataclass
class _FakeStrategy(BaseStrategy):
    name: str
    calls: int = 0

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]:
        self.calls += 1
        return [_candidate(self.name, snapshot)]


class _FakePersistence:
    def __init__(self) -> None:
        self.logs: list[tuple[str, object]] = []
        self.statuses: list[object] = []

    def append_log(self, stream: str, payload: object) -> None:
        self.logs.append((stream, payload))

    def insert_strategy_status(self, status: object) -> None:
        self.statuses.append(status)

    def insert_rejected_signal(self, rejected: object) -> None:
        raise AssertionError("disabled strategies must not produce rejected signals")


class _FakeGate:
    def evaluate(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> GateDecision:
        return GateDecision(True, signal=candidate)


class _FakeConsensus:
    def add(self, signal: SignalCandidate) -> None:
        return None


class _FakeLogger:
    def exception(self, *_args, **_kwargs) -> None:
        raise AssertionError("unexpected exception log")


async def test_manual_disabled_strategy_skips_without_mutating_list() -> None:
    snapshot = _snapshot()
    first = _FakeStrategy("first")
    second = _FakeStrategy("second")
    persistence = _FakePersistence()
    pipeline = SignalPipeline(
        [first, second], _FakeGate(), _FakeConsensus(), persistence
    )
    pipeline.set_strategy_enabled("first", False)
    scheduler = SimpleNamespace(
        signal_pipeline=pipeline,
        strategies=[first, second],
        strategy_schedule=[
            _entry(first, 0),
            _entry(second, 1),
        ],
        gate=_FakeGate(),
        consensus=_FakeConsensus(),
        persistence=persistence,
        logger=_FakeLogger(),
    )

    envelopes = await scheduler_processing.evaluate_candidates_ordered(
        scheduler, [(0, snapshot)]
    )

    assert [envelope.strategy_name for envelope in envelopes] == ["second"]
    assert [strategy.name for strategy in scheduler.strategies] == ["first", "second"]
    assert first.calls == 0
    assert second.calls == 1
    assert persistence.statuses[0].strategy == "first"
    assert persistence.statuses[0].status == "inactive"
    assert persistence.statuses[0].reason == "manual_disabled"


async def test_dependency_disabled_skips_dependent_strategy() -> None:
    snapshot = _snapshot()
    base = _FakeStrategy("base")
    dependent = _FakeStrategy("dependent")
    persistence = _FakePersistence()
    pipeline = SignalPipeline([base, dependent], _FakeGate(), _FakeConsensus(), persistence)
    pipeline.set_strategy_dependencies({"dependent": ("base",)})
    pipeline.set_strategy_enabled("base", False)
    scheduler = SimpleNamespace(
        signal_pipeline=pipeline,
        strategies=[base, dependent],
        strategy_schedule=[
            _entry(base, 0),
            _entry(dependent, 1, depends_on=("base",)),
        ],
        gate=_FakeGate(),
        consensus=_FakeConsensus(),
        persistence=persistence,
        logger=_FakeLogger(),
    )

    envelopes = await scheduler_processing.evaluate_candidates_ordered(
        scheduler, [(0, snapshot)]
    )

    assert envelopes == []
    assert base.calls == 0
    assert dependent.calls == 0
    assert [(s.strategy, s.reason) for s in persistence.statuses] == [
        ("base", "manual_disabled"),
        ("dependent", "dependency_disabled:base"),
    ]


def _entry(
    strategy: _FakeStrategy, index: int, *, depends_on: tuple[str, ...] = ()
) -> StrategyScheduleEntry:
    return StrategyScheduleEntry(
        strategy=strategy,
        name=strategy.name,
        priority=10 + index,
        depends_on=depends_on,
        execution_mode="stateful",
        strategy_config_index=index,
    )


def _snapshot() -> MarketSnapshot:
    market = sample_market(MarketFactoryConfig(asset="BTC", timeframe="5m", seconds_to_close=120))
    return MarketSnapshot(
        snapshot_id=f"snapshot-{market.market_id}",
        market=market,
        up_book=sample_book(market.token_for(Side.UP).token_id, BookFactoryConfig(ask=0.45, bid=0.44, size=500)),
        down_book=sample_book(market.token_for(Side.DOWN).token_id, BookFactoryConfig(ask=0.55, bid=0.54, size=500)),
        spot=sample_spot(),
        price_to_beat=market.price_to_beat,
        freshness=FreshnessState(max_ms=10, up_book_ms=10, down_book_ms=10, spot_ms=10),
    )


def _candidate(strategy: str, snapshot: MarketSnapshot) -> SignalCandidate:
    return SignalCandidate.build(
        strategy=strategy,
        asset=snapshot.market.asset,
        timeframe=snapshot.market.timeframe,
        market_id=snapshot.market.market_id,
        market_slug=snapshot.market.market_slug,
        condition_id=snapshot.market.condition_id,
        token_id=snapshot.market.token_for(Side.UP).token_id,
        side=Side.UP,
        confidence=0.75,
        entry_reference_price=0.45,
        max_entry_price=0.60,
        seconds_to_close=snapshot.seconds_to_close,
        data_freshness_ms=snapshot.freshness.max_ms,
        reason_codes=["FAKE"],
        metrics={"max_spread": 0.2},
        snapshot_id=snapshot.snapshot_id,
    )
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_signal_pipeline_manual_disable.py -q
```

Expected: FAIL because `SignalPipeline.set_strategy_enabled` and dependency skip behavior do not exist.

- [ ] **Step 3: Extend `StrategyStatus`**

In `src/polysignal_lab/strategies/readiness.py`, add `"inactive"` to the `StrategyStatus` literal:

```python
StrategyStatus = Literal[
    "active",
    "disabled",
    "inactive",
    "unsupported_market",
    "missing_data",
    "uncalibrated",
]
```

- [ ] **Step 4: Add disabled state helpers to `SignalPipeline`**

In `src/polysignal_lab/app/services/signal_pipeline.py`, add imports:

```python
from collections.abc import Iterable
```

Change `__init__` to accept and store disabled/dependency state:

```python
        *,
        logger: logging.Logger | None = None,
        disabled_strategies: Iterable[str] = (),
        strategy_dependencies: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.strategies = strategies
        self.gate = gate
        self.consensus = consensus
        self.persistence = persistence
        self.disabled_strategies = set(disabled_strategies)
        self.strategy_dependencies = dict(strategy_dependencies or {})
        self.logger = logger or logging.getLogger("polysignal_lab.scheduler.signal_pipeline")
```

Add methods after `health()`:

```python
    def set_strategy_enabled(self, name: str, enabled: bool) -> None:
        if enabled:
            self.disabled_strategies.discard(name)
        else:
            self.disabled_strategies.add(name)

    def is_strategy_enabled(self, name: str) -> bool:
        return name not in self.disabled_strategies

    def set_strategy_dependencies(self, dependencies: dict[str, tuple[str, ...]]) -> None:
        self.strategy_dependencies = dict(dependencies)

    def skip_reason_for(self, name: str) -> str | None:
        if name in self.disabled_strategies:
            return "manual_disabled"
        for dependency_name in self.strategy_dependencies.get(name, ()):
            if dependency_name in self.disabled_strategies:
                return f"dependency_disabled:{dependency_name}"
        return None
```

Then add a skip check at the top of `evaluate_snapshot()` loop before readiness:

```python
            skip_reason = self.skip_reason_for(strategy_name)
            if skip_reason is not None:
                self._persist_inactive_strategy(snapshot, strategy_name, skip_reason)
                continue
```

Add `_persist_inactive_strategy()` below `_persist_rejection()`:

```python
    def _persist_inactive_strategy(self, snapshot: Any, strategy_name: str, reason: str) -> None:
        from polysignal_lab.strategies.readiness import StrategyMarketStatus

        market = getattr(snapshot, "market", None)
        status = StrategyMarketStatus(
            strategy=strategy_name,
            asset=getattr(market, "asset", "?"),
            timeframe=getattr(market, "timeframe", "?"),
            status="inactive",
            reason=reason,
        )
        self._persist_strategy_status(status, snapshot, strategy_name)
```

- [ ] **Step 5: Make real scheduler evaluation consult `SignalPipeline`**

In `src/polysignal_lab/app/scheduler_processing.py`, add helper functions before `_strategy_market_active()`:

```python
def _manual_strategy_skip_reason(
    scheduler: PolySignalScheduler, entry: StrategyScheduleEntry
) -> str | None:
    pipeline = getattr(scheduler, "signal_pipeline", None)
    if pipeline is None or not hasattr(pipeline, "skip_reason_for"):
        return None
    return pipeline.skip_reason_for(entry.name)


def _persist_inactive_strategy(
    scheduler: PolySignalScheduler,
    entry: StrategyScheduleEntry,
    snapshot: MarketSnapshot,
    reason: str,
) -> None:
    from polysignal_lab.strategies.readiness import StrategyMarketStatus

    status = StrategyMarketStatus(
        strategy=entry.name,
        asset=snapshot.market.asset.upper(),
        timeframe=snapshot.market.timeframe,
        status="inactive",
        reason=reason,
    )
    persistence = getattr(scheduler, "persistence", _LegacyRejectionPersistence(scheduler))
    try:
        persistence.append_log("strategy_status", status)
        persistence.insert_strategy_status(status)
    except Exception:
        scheduler.logger.exception(
            "Failed to persist strategy status for market %s strategy %s status %s",
            snapshot.market.market_slug,
            entry.name,
            status.status,
        )
```

Then make `_strategy_market_active()` check manual skip before readiness:

```python
    manual_reason = _manual_strategy_skip_reason(scheduler, entry)
    if manual_reason is not None:
        _persist_inactive_strategy(scheduler, entry, snapshot, manual_reason)
        return False
```

- [ ] **Step 6: Run tests to verify GREEN**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_signal_pipeline_manual_disable.py tests/test_signal_pipeline_equivalence.py tests/test_strategy_execution_order.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/polysignal_lab/strategies/readiness.py src/polysignal_lab/app/services/signal_pipeline.py src/polysignal_lab/app/scheduler_processing.py tests/test_signal_pipeline_manual_disable.py
git commit -m "feat: add runtime strategy disable gates"
```

---

### Task 3: PTB service lifecycle, handler registration, authorization, and health

**Files:**
- Create: `src/polysignal_lab/publish/telegram_bot.py`
- Create: `tests/test_telegram_bot_service.py`
- Test command: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_telegram_bot_service.py::test_telegram_bot_registers_ptb_handlers tests/test_telegram_bot_service.py::test_telegram_bot_start_uses_embedded_ptb_lifecycle tests/test_telegram_bot_service.py::test_telegram_bot_start_polling_uses_drop_pending_updates tests/test_telegram_bot_service.py::test_telegram_bot_stop_uses_ptb_shutdown_order tests/test_telegram_bot_service.py::test_telegram_bot_rejects_group_chat tests/test_telegram_bot_service.py::test_telegram_bot_rejects_private_chat_not_in_allowlist -q`

**Interfaces:**
- Consumes: `TelegramConfig`, `PersistenceService`, `SignalPipeline`, `OrderBookRegistry`, `MarketRegistry`, `MessageFormatter`.
- Produces: `TelegramBotService(config, persistence, signal_pipeline, books, markets, formatter, scheduler=None, application=None)`, `configure_handlers() -> None`, `start() -> None`, `stop() -> None`, `health() -> dict[str, object]`.

- [ ] **Step 1: Write failing service lifecycle tests**

Create `tests/test_telegram_bot_service.py` with shared fakes and lifecycle/auth tests:

```python
from __future__ import annotations

from types import SimpleNamespace

import pytest
from telegram.ext import CallbackQueryHandler, CommandHandler

from polysignal_lab.app.services.signal_pipeline import SignalPipeline
from polysignal_lab.config import TelegramConfig
from polysignal_lab.data.state import MarketRegistry, OrderBookRegistry
from polysignal_lab.publish.telegram_bot import TelegramBotService
from polysignal_lab.signal_layer.formatter import MessageFormatter


class _FakeUpdater:
    def __init__(self, calls: list[tuple[str, dict[str, object]]]) -> None:
        self.calls = calls
        self.running = False

    async def start_polling(self, **kwargs: object) -> None:
        self.calls.append(("updater.start_polling", dict(kwargs)))
        self.running = True

    async def stop(self) -> None:
        self.calls.append(("updater.stop", {}))
        self.running = False


class _FakeApplication:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.handlers: list[object] = []
        self.updater = _FakeUpdater(self.calls)
        self.running = False

    def add_handler(self, handler: object) -> None:
        self.handlers.append(handler)

    async def initialize(self) -> None:
        self.calls.append(("initialize", {}))

    async def start(self) -> None:
        self.calls.append(("start", {}))
        self.running = True

    async def stop(self) -> None:
        self.calls.append(("stop", {}))
        self.running = False

    async def shutdown(self) -> None:
        self.calls.append(("shutdown", {}))


class _FakePersistence:
    def __init__(self) -> None:
        self.state: dict[str, object] = {}

    def counts(self) -> dict[str, int]:
        return {}

    def restore_open_positions(self) -> list[dict[str, object]]:
        return []

    def restore_latest_wallet_snapshot(self) -> dict[str, object] | None:
        return None

    def restore_latest_system_event(self, event_type: str) -> dict[str, object] | None:
        return None

    def restore_daily_reports(self, limit: int = 100) -> list[dict[str, object]]:
        return []

    def query_json(self, table: str, limit: int = 100, where: str = "", params=()) -> list[dict[str, object]]:
        return []

    def read_state(self, name: str, default: object = None) -> object:
        return self.state.get(name, default)

    def write_state(self, name: str, value: object) -> None:
        self.state[name] = value

    def insert_system_event(self, event: dict[str, object]) -> None:
        self.state["last_event"] = event


class _FakeMessage:
    def __init__(self) -> None:
        self.replies: list[dict[str, object]] = []

    async def reply_text(self, text: str, **kwargs: object) -> None:
        self.replies.append({"text": text, **kwargs})


def _service(
    *,
    allowed: tuple[int, ...] = (123,),
    enabled: bool = True,
    dry_run: bool = False,
    application: _FakeApplication | None = None,
) -> TelegramBotService:
    config = TelegramConfig(
        interactive_enabled=enabled,
        interactive_dry_run=dry_run,
        interactive_allowed_chat_ids=allowed,
        retry_attempts=1,
    )
    return TelegramBotService(
        config=config,
        persistence=_FakePersistence(),
        signal_pipeline=SignalPipeline([], object(), object(), None),
        books=OrderBookRegistry(),
        markets=MarketRegistry(),
        formatter=MessageFormatter(),
        application=application,
    )


def _update(chat_id: int, user_id: int, chat_type: str = "private") -> SimpleNamespace:
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id, type=chat_type),
        effective_user=SimpleNamespace(id=user_id),
        effective_message=_FakeMessage(),
        callback_query=None,
    )


def test_telegram_bot_registers_ptb_handlers() -> None:
    app = _FakeApplication()
    service = _service(application=app)

    service.configure_handlers()

    command_names = {
        command
        for handler in app.handlers
        if isinstance(handler, CommandHandler)
        for command in handler.commands
    }
    assert command_names == {"start", "positions", "status", "signals", "strategies", "daily"}
    assert any(isinstance(handler, CallbackQueryHandler) for handler in app.handlers)


async def test_telegram_bot_start_uses_embedded_ptb_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _FakeApplication()
    service = _service(application=app)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")

    await service.start()

    assert [name for name, _ in app.calls[:3]] == [
        "initialize",
        "start",
        "updater.start_polling",
    ]
    assert service.health()["status"] == "ok"


async def test_telegram_bot_start_polling_uses_drop_pending_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _FakeApplication()
    service = _service(application=app)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")

    await service.start()

    polling = dict(app.calls[2][1])
    assert polling["allowed_updates"] == ("message", "callback_query")
    assert polling["drop_pending_updates"] is True
    assert polling["poll_interval"] == 0.0
    assert polling["timeout"] == 30


async def test_telegram_bot_stop_uses_ptb_shutdown_order(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _FakeApplication()
    service = _service(application=app)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    await service.start()

    await service.stop()

    assert [name for name, _ in app.calls[-3:]] == ["updater.stop", "stop", "shutdown"]
    assert service.health()["metrics"]["running"] is False


async def test_telegram_bot_rejects_group_chat() -> None:
    service = _service()
    update = _update(123, 123, chat_type="group")

    await service._status(update, SimpleNamespace())

    assert update.effective_message.replies == []
    assert service.health()["metrics"]["unauthorized_updates"] == 1


async def test_telegram_bot_rejects_private_chat_not_in_allowlist() -> None:
    service = _service(allowed=(123,))
    update = _update(123, 999, chat_type="private")

    await service._status(update, SimpleNamespace())

    assert update.effective_message.replies == []
    assert service.health()["metrics"]["unauthorized_updates"] == 1
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_telegram_bot_service.py::test_telegram_bot_registers_ptb_handlers -q
```

Expected: FAIL because `polysignal_lab.publish.telegram_bot` does not exist.

- [ ] **Step 3: Create `TelegramBotService` imports and constructor**

Create `src/polysignal_lab/publish/telegram_bot.py`:

```python
from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType, ParseMode
from telegram.error import NetworkError, RetryAfter, TelegramError, TimedOut
from telegram.ext import (
    AIORateLimiter,
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from polysignal_lab.app.services.persistence_service import PersistenceService
from polysignal_lab.app.services.signal_pipeline import SignalPipeline
from polysignal_lab.config import TelegramConfig
from polysignal_lab.data.state import MarketRegistry, OrderBookRegistry
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import DailyReport
from polysignal_lab.signal_layer.formatter import MessageFormatter
from polysignal_lab.utils import new_id, utc_iso


class TelegramBotService:
    name = "telegram_bot"

    def __init__(
        self,
        *,
        config: TelegramConfig,
        persistence: PersistenceService,
        signal_pipeline: SignalPipeline,
        books: OrderBookRegistry,
        markets: MarketRegistry,
        formatter: MessageFormatter,
        scheduler: Any | None = None,
        application: Application | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.persistence = persistence
        self.signal_pipeline = signal_pipeline
        self.books = books
        self.markets = markets
        self.formatter = formatter
        self.scheduler = scheduler
        self.application = application
        self.logger = logger or logging.getLogger("polysignal_lab.telegram_bot")
        self._running = False
        self._last_update_id: int | None = None
        self._last_update_at: str | None = None
        self._error: str | None = None
        self._poll_success = 0
        self._poll_failure = 0
        self._send_success = 0
        self._send_failure = 0
        self._rate_limited = 0
        self._unauthorized_updates = 0
```

- [ ] **Step 4: Add handler registration**

In `telegram_bot.py`, add `configure_handlers()`:

```python
    def configure_handlers(self) -> None:
        if self.application is None:
            raise RuntimeError("telegram application is not configured")
        self.application.add_handler(CommandHandler("start", self._start))
        self.application.add_handler(CommandHandler("positions", self._positions))
        self.application.add_handler(CommandHandler("status", self._status))
        self.application.add_handler(CommandHandler("signals", self._signals))
        self.application.add_handler(CommandHandler("strategies", self._strategies))
        self.application.add_handler(CommandHandler("daily", self._daily))
        self.application.add_handler(CallbackQueryHandler(self._callback))
```

- [ ] **Step 5: Add start/stop lifecycle**

In `telegram_bot.py`, add `start()` and `stop()`:

```python
    async def start(self) -> None:
        if not self.config.interactive_enabled:
            return
        if self.config.interactive_dry_run:
            self.logger.info("Telegram interactive bot interactive_dry_run enabled")
        if not self.config.resolved_bot_token:
            self._error = "missing bot token"
            self.logger.warning("Telegram interactive bot disabled: missing bot token")
            return
        if not self.config.interactive_allowed_chat_ids:
            self._error = "no allowed chat ids"
            self.logger.warning("Telegram interactive bot disabled: no allowed chat ids")
            return
        if self.scheduler is not None and hasattr(self.scheduler, "strategy_schedule"):
            self.signal_pipeline.set_strategy_dependencies(
                {entry.name: tuple(entry.depends_on) for entry in self.scheduler.strategy_schedule}
            )
        self.application = self.application or (
            ApplicationBuilder()
            .token(self.config.resolved_bot_token)
            .rate_limiter(AIORateLimiter(max_retries=self.config.retry_attempts))
            .build()
        )
        self.configure_handlers()
        try:
            await self.application.initialize()
            await self.application.start()
            if self.application.updater is None:
                raise RuntimeError("telegram application updater is not available")
            await self.application.updater.start_polling(
                poll_interval=self.config.interactive_poll_interval_sec,
                timeout=self.config.interactive_poll_timeout_sec,
                allowed_updates=("message", "callback_query"),
                drop_pending_updates=self.config.interactive_drop_pending_updates_on_start,
            )
        except RetryAfter as exc:
            self._rate_limited += 1
            self._poll_failure += 1
            self._error = f"rate limited: retry after {exc.retry_after}s"
            self.logger.warning("Telegram interactive bot rate limited")
            return
        except (TimedOut, NetworkError, TelegramError, RuntimeError) as exc:
            self._poll_failure += 1
            self._error = type(exc).__name__
            self.logger.warning("Telegram interactive bot start failed: %s", type(exc).__name__)
            return
        self._running = True
        self._poll_success += 1
        self._error = None

    async def stop(self) -> None:
        self._running = False
        if self.application is None:
            return
        if self.application.updater is not None and self.application.updater.running:
            await self.application.updater.stop()
        if self.application.running:
            await self.application.stop()
        await self.application.shutdown()
        self.application = None
```

- [ ] **Step 6: Add authorization and health**

In `telegram_bot.py`, add helpers:

```python
    def _authorized(self, update: Update) -> bool:
        chat = update.effective_chat
        user = update.effective_user
        allowed_ids = set(self.config.interactive_allowed_chat_ids)
        allowed = (
            chat is not None
            and user is not None
            and str(chat.type) == ChatType.PRIVATE
            and int(chat.id) in allowed_ids
            and int(user.id) in allowed_ids
        )
        if allowed:
            self._last_update_id = getattr(update, "update_id", None)
            self._last_update_at = utc_iso()
            return True
        self._unauthorized_updates += 1
        self.logger.warning(
            "Unauthorized Telegram interactive update chat_id=%s user_id=%s",
            getattr(chat, "id", None),
            getattr(user, "id", None),
        )
        return False

    def health(self) -> dict[str, object]:
        if not self.config.interactive_enabled:
            status = "disabled"
        elif self._running and self._error is None:
            status = "ok"
        else:
            status = "degraded" if self._error else "disabled"
        return {
            "name": self.name,
            "status": status,
            "metrics": {
                "enabled": self.config.interactive_enabled,
                "running": self._running,
                "authorized_chat_count": len(self.config.interactive_allowed_chat_ids),
                "last_update_id": self._last_update_id,
                "last_update_at": self._last_update_at,
                "poll_success": self._poll_success,
                "poll_failure": self._poll_failure,
                "send_success": self._send_success,
                "send_failure": self._send_failure,
                "rate_limited": self._rate_limited,
                "unauthorized_updates": self._unauthorized_updates,
            },
            "error": self._error,
        }
```

- [ ] **Step 7: Add temporary command handlers needed by lifecycle tests**

Add these minimal handlers; later tasks replace their render methods with real content:

```python
    async def _start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await self._reply(update, "PolySignal Lab\n选择操作：", self._main_keyboard())

    async def _status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await self._reply(update, self._format_status(), self._back_keyboard())

    async def _positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await self._reply(update, "暂无 open paper positions。", self._back_keyboard())

    async def _signals(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await self._reply(update, "暂无 recent signals。", self._back_keyboard())

    async def _strategies(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await self._reply(update, "⚙️ Strategies", self._back_keyboard())

    async def _daily(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await self._reply(update, "暂无 daily report。", self._back_keyboard())
```

Add keyboards and reply helper:

```python
    def _main_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("💼 持仓", callback_data="p"),
                    InlineKeyboardButton("📊 状态", callback_data="st"),
                ],
                [
                    InlineKeyboardButton("📡 最近信号", callback_data="sg"),
                    InlineKeyboardButton("⚙️ 策略", callback_data="str"),
                ],
                [InlineKeyboardButton("📋 每日报告", callback_data="dy")],
            ]
        )

    def _back_keyboard(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ 返回", callback_data="bk")]])

    async def _reply(
        self, update: Update, text: str, keyboard: InlineKeyboardMarkup | None = None
    ) -> None:
        if self.config.interactive_dry_run:
            self.logger.info("telegram interactive_dry_run reply: %s", text)
            return
        message = update.effective_message
        if message is None:
            self._send_failure += 1
            return
        try:
            await message.reply_text(
                self._truncate(text),
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            self._send_success += 1
        except RetryAfter:
            self._rate_limited += 1
            self._send_failure += 1
        except (TimedOut, NetworkError, TelegramError):
            self._send_failure += 1
```

Add `_format_status()` and `_truncate()` with concrete output:

```python
    def _format_status(self) -> str:
        counts = self.persistence.counts()
        return "\n".join(
            [
                "🟢 PolySignal Lab: ok",
                f"Markets     {len(self.markets.markets)} tracked",
                f"Signals     {counts.get('signals', 0)} accepted / {counts.get('rejected_signals', 0)} rejected",
            ]
        )

    def _truncate(self, text: str) -> str:
        if len(text) <= self.config.max_message_chars:
            return text
        return text[: self.config.max_message_chars - 32] + "\n[truncated for Telegram]"
```

- [ ] **Step 8: Run tests to verify GREEN**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_telegram_bot_service.py::test_telegram_bot_registers_ptb_handlers tests/test_telegram_bot_service.py::test_telegram_bot_start_uses_embedded_ptb_lifecycle tests/test_telegram_bot_service.py::test_telegram_bot_start_polling_uses_drop_pending_updates tests/test_telegram_bot_service.py::test_telegram_bot_stop_uses_ptb_shutdown_order tests/test_telegram_bot_service.py::test_telegram_bot_rejects_group_chat tests/test_telegram_bot_service.py::test_telegram_bot_rejects_private_chat_not_in_allowlist -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/polysignal_lab/publish/telegram_bot.py tests/test_telegram_bot_service.py
git commit -m "feat: add telegram bot service lifecycle"
```

---

### Task 4: Menus, callbacks, callback acknowledgement, and dry-run replies

**Files:**
- Modify: `src/polysignal_lab/publish/telegram_bot.py`
- Modify: `tests/test_telegram_bot_service.py`
- Test command: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_telegram_bot_service.py::test_telegram_bot_uses_ptb_inline_keyboard_markup tests/test_telegram_bot_service.py::test_telegram_bot_callback_always_answers tests/test_telegram_bot_service.py::test_telegram_bot_interactive_dry_run_logs_no_send -q`

**Interfaces:**
- Consumes: `_main_keyboard()`, `_back_keyboard()`, `_reply()` from Task 3.
- Produces: `_callback(update, context) -> None`, `_render_callback(data: str) -> tuple[str, InlineKeyboardMarkup | None]`, `_edit_or_reply(update, text, keyboard) -> None`.

- [ ] **Step 1: Add callback and keyboard tests**

Append to `tests/test_telegram_bot_service.py`:

```python
from telegram import InlineKeyboardMarkup


class _FakeCallbackQuery:
    def __init__(self, data: str, chat_id: int = 123, user_id: int = 123) -> None:
        self.data = data
        self.answers: list[dict[str, object]] = []
        self.edits: list[dict[str, object]] = []
        self.message = _FakeMessage()
        self.from_user = SimpleNamespace(id=user_id)
        self.chat_id = chat_id

    async def answer(self, text: str | None = None, **kwargs: object) -> None:
        self.answers.append({"text": text, **kwargs})

    async def edit_message_text(self, text: str, **kwargs: object) -> None:
        self.edits.append({"text": text, **kwargs})


def _callback_update(query: _FakeCallbackQuery, *, chat_id: int = 123, user_id: int = 123, chat_type: str = "private") -> SimpleNamespace:
    return SimpleNamespace(
        update_id=42,
        effective_chat=SimpleNamespace(id=chat_id, type=chat_type),
        effective_user=SimpleNamespace(id=user_id),
        effective_message=query.message,
        callback_query=query,
    )


def test_telegram_bot_uses_ptb_inline_keyboard_markup() -> None:
    service = _service()

    keyboard = service._main_keyboard()

    assert isinstance(keyboard, InlineKeyboardMarkup)
    callback_values = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert callback_values == ["p", "st", "sg", "str", "dy"]
    assert all(1 <= len(value.encode("utf-8")) <= 64 for value in callback_values)


async def test_telegram_bot_callback_always_answers() -> None:
    service = _service()

    known = _FakeCallbackQuery("st")
    await service._callback(_callback_update(known), SimpleNamespace())
    unknown = _FakeCallbackQuery("unknown")
    await service._callback(_callback_update(unknown), SimpleNamespace())
    unauthorized = _FakeCallbackQuery("st", user_id=999)
    await service._callback(_callback_update(unauthorized, user_id=999), SimpleNamespace())

    assert len(known.answers) == 1
    assert known.answers[0]["text"] is None
    assert len(unknown.answers) == 1
    assert unknown.answers[0]["text"] == "Unknown action"
    assert unknown.answers[0]["show_alert"] is True
    assert len(unauthorized.answers) == 1
    assert unauthorized.answers[0]["text"] == "Unauthorized"
    assert unauthorized.answers[0]["show_alert"] is True


async def test_telegram_bot_interactive_dry_run_logs_no_send(caplog: pytest.LogCaptureFixture) -> None:
    service = _service(dry_run=True)
    update = _update(123, 123)

    await service._status(update, SimpleNamespace())

    assert update.effective_message.replies == []
    assert "telegram interactive_dry_run reply" in caplog.text
    assert service.health()["metrics"]["send_success"] == 0
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_telegram_bot_service.py::test_telegram_bot_callback_always_answers -q
```

Expected: FAIL because `_callback()` is not implemented.

- [ ] **Step 3: Implement callback rendering and edit fallback**

In `telegram_bot.py`, add `_render_callback()`, `_callback()`, and `_edit_or_reply()`:

```python
    def _render_callback(self, data: str) -> tuple[str, InlineKeyboardMarkup | None]:
        match data:
            case "m" | "bk":
                return "PolySignal Lab\n选择操作：", self._main_keyboard()
            case "p":
                return self._format_positions(), self._back_keyboard()
            case "st":
                return self._format_status(), self._back_keyboard()
            case "sg":
                return self._format_signals(), self._back_keyboard()
            case "dy":
                return self._format_daily(), self._back_keyboard()
            case "str":
                return self._format_strategies(), self._strategies_keyboard()
            case _:
                raise ValueError("Unknown action")

    async def _callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return
        if not self._authorized(update):
            await query.answer("Unauthorized", show_alert=True)
            return
        try:
            if (query.data or "").startswith("tg:"):
                text, keyboard = self._toggle_strategy(query.data or "")
            else:
                text, keyboard = self._render_callback(query.data or "")
        except ValueError as exc:
            await query.answer(str(exc), show_alert=True)
            return
        except Exception:
            await query.answer("Action failed", show_alert=True)
            self.logger.exception("Telegram callback failed")
            return
        await query.answer()
        await self._edit_or_reply(update, text, keyboard)

    async def _edit_or_reply(
        self, update: Update, text: str, keyboard: InlineKeyboardMarkup | None = None
    ) -> None:
        if self.config.interactive_dry_run:
            self.logger.info("telegram interactive_dry_run callback reply: %s", text)
            return
        query = update.callback_query
        try:
            if query is not None and getattr(query, "message", None) is not None:
                await query.edit_message_text(
                    text=self._truncate(text),
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )
            else:
                await self._reply(update, text, keyboard)
            self._send_success += 1
        except RetryAfter:
            self._rate_limited += 1
            self._send_failure += 1
        except (TimedOut, NetworkError, TelegramError):
            self._send_failure += 1
```

- [ ] **Step 4: Add temporary render methods for callbacks**

Add these methods; Task 5 replaces the bodies with data-backed output:

```python
    def _format_positions(self) -> str:
        return "暂无 open paper positions。"

    def _format_signals(self) -> str:
        return "暂无 recent signals。"

    def _format_daily(self) -> str:
        return "暂无 daily report。"

    def _format_strategies(self) -> str:
        return "⚙️ Strategies"

    def _strategies_keyboard(self) -> InlineKeyboardMarkup:
        return self._back_keyboard()

    def _toggle_strategy(self, data: str) -> tuple[str, InlineKeyboardMarkup | None]:
        raise ValueError("Unknown strategy")
```

- [ ] **Step 5: Point command handlers at real render methods**

Update command handlers from Task 3 so they use the render methods:

```python
    async def _positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await self._reply(update, self._format_positions(), self._back_keyboard())

    async def _signals(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await self._reply(update, self._format_signals(), self._back_keyboard())

    async def _strategies(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await self._reply(update, self._format_strategies(), self._strategies_keyboard())

    async def _daily(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await self._reply(update, self._format_daily(), self._back_keyboard())
```

- [ ] **Step 6: Run tests to verify GREEN**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_telegram_bot_service.py::test_telegram_bot_uses_ptb_inline_keyboard_markup tests/test_telegram_bot_service.py::test_telegram_bot_callback_always_answers tests/test_telegram_bot_service.py::test_telegram_bot_interactive_dry_run_logs_no_send -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/polysignal_lab/publish/telegram_bot.py tests/test_telegram_bot_service.py
git commit -m "feat: add telegram bot callbacks"
```

---

### Task 5: Read-only command formatting for status, positions, signals, and daily report

**Files:**
- Modify: `src/polysignal_lab/publish/telegram_bot.py`
- Modify: `tests/test_telegram_bot_service.py`
- Test command: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_telegram_bot_service.py::test_telegram_bot_positions_marks_live_book_when_available tests/test_telegram_bot_service.py::test_telegram_bot_positions_shows_mark_na_without_live_book tests/test_telegram_bot_service.py::test_telegram_bot_signals_merges_accepted_and_rejected tests/test_telegram_bot_service.py::test_telegram_bot_daily_validates_payload_before_formatter tests/test_telegram_bot_service.py::test_telegram_bot_status_includes_health_wallet_counts_and_disabled_strategies -q`

**Interfaces:**
- Consumes: `PersistenceService.restore_open_positions()`, `restore_latest_wallet_snapshot()`, `restore_latest_system_event("health_snapshot")`, `restore_daily_reports(limit=1)`, `query_json(table, where, limit)`, `OrderBookRegistry.get(token_id)`, `MarketRegistry.markets`, `DailyReport.model_validate(payload)`, `MessageFormatter.daily_report_message(report)`.
- Produces: `_format_positions() -> str`, `_format_status() -> str`, `_format_signals() -> str`, `_format_daily() -> str`.

- [ ] **Step 1: Add command formatting tests**

Append to `tests/test_telegram_bot_service.py`:

```python
from datetime import date, datetime, timezone

from polysignal_lab.domain.enums import PositionStatus, Side
from polysignal_lab.domain.orderbook import BookLevel, OrderBook
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import DailyReport


class _FormattingPersistence(_FakePersistence):
    def __init__(self) -> None:
        super().__init__()
        self.positions: list[dict[str, object]] = []
        self.signals: list[dict[str, object]] = []
        self.rejected: list[dict[str, object]] = []
        self.reports: list[dict[str, object]] = []
        self.wallet: dict[str, object] | None = None
        self.health_event: dict[str, object] | None = None
        self.table_counts = {"signals": 0, "rejected_signals": 0}

    def counts(self) -> dict[str, int]:
        return self.table_counts

    def restore_open_positions(self) -> list[dict[str, object]]:
        return self.positions

    def restore_latest_wallet_snapshot(self) -> dict[str, object] | None:
        return self.wallet

    def restore_latest_system_event(self, event_type: str) -> dict[str, object] | None:
        assert event_type == "health_snapshot"
        return self.health_event

    def restore_daily_reports(self, limit: int = 100) -> list[dict[str, object]]:
        return self.reports[:limit]

    def query_json(self, table: str, limit: int = 100, where: str = "", params=()) -> list[dict[str, object]]:
        if table == "signals":
            return self.signals[:limit]
        if table == "rejected_signals":
            return self.rejected[:limit]
        raise AssertionError(table)


def _formatting_service(persistence: _FormattingPersistence) -> TelegramBotService:
    return TelegramBotService(
        config=TelegramConfig(interactive_enabled=True, interactive_allowed_chat_ids=(123,)),
        persistence=persistence,
        signal_pipeline=SignalPipeline([], object(), object(), persistence),
        books=OrderBookRegistry(),
        markets=MarketRegistry(),
        formatter=MessageFormatter(),
    )


def test_telegram_bot_positions_marks_live_book_when_available() -> None:
    persistence = _FormattingPersistence()
    position = PaperPosition(
        signal_id="sig_1",
        paper_order_id="po_1",
        paper_fill_id="pf_1",
        strategy="vwap_momentum",
        asset="BTC",
        timeframe="15m",
        market_id="m_1",
        market_slug="btc-15m",
        token_id="token-up",
        side=Side.UP,
        entry_price=0.64,
        shares=500.0,
        stake_usdc=320.0,
        opened_at=datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc),
        status=PositionStatus.OPEN,
    )
    persistence.positions = [position.model_dump(mode="json")]
    service = _formatting_service(persistence)
    service.books.update(
        OrderBook(
            token_id="token-up",
            bids=[BookLevel(price=0.71, size=100)],
            asks=[BookLevel(price=0.72, size=100)],
        )
    )

    text = service._format_positions()

    assert "📈 BTC 15m · UP" in text
    assert "Strategy  vwap_momentum" in text
    assert "Entry     0.6400" in text
    assert "Mark      0.7100" in text
    assert "Shares    500.0000" in text
    assert "PnL       +35.00 USDC (+10.94%)" in text
    assert "ID        " in text


def test_telegram_bot_positions_shows_mark_na_without_live_book() -> None:
    persistence = _FormattingPersistence()
    position = PaperPosition(
        signal_id="sig_1",
        paper_order_id="po_1",
        paper_fill_id="pf_1",
        strategy="vwap_momentum",
        asset="BTC",
        timeframe="15m",
        market_id="m_1",
        market_slug="btc-15m",
        token_id="missing-token",
        side=Side.UP,
        entry_price=0.64,
        shares=500.0,
        stake_usdc=320.0,
        status=PositionStatus.OPEN,
    )
    persistence.positions = [position.model_dump(mode="json")]
    service = _formatting_service(persistence)

    text = service._format_positions()

    assert "Mark      n/a (live book unavailable)" in text
    assert "PnL       n/a" in text


def test_telegram_bot_signals_merges_accepted_and_rejected() -> None:
    persistence = _FormattingPersistence()
    persistence.signals = [
        {
            "signal_id": "sig_new",
            "strategy": "vwap_momentum",
            "asset": "BTC",
            "timeframe": "15m",
            "action": "BUY",
            "side": "UP",
            "created_at": "2026-06-24T12:02:00Z",
        }
    ]
    persistence.rejected = [
        {
            "rejected_id": "rej_old",
            "reason_code": "stale_book",
            "rejected_at": "2026-06-24T12:00:00Z",
            "candidate": {
                "signal_id": "sig_old",
                "strategy": "late_consensus",
                "asset": "ETH",
                "timeframe": "5m",
                "action": "BUY",
                "side": "DOWN",
            },
        }
    ]
    service = _formatting_service(persistence)

    text = service._format_signals()

    assert "🟢 accepted · BTC 15m BUY UP" in text
    assert "vwap_momentum · sig_new" in text
    assert "🔴 rejected · ETH 5m BUY DOWN" in text
    assert "late_consensus · stale_book" in text
    assert text.index("sig_new") < text.index("sig_old")


def test_telegram_bot_daily_validates_payload_before_formatter() -> None:
    persistence = _FormattingPersistence()
    report = DailyReport(
        report_date=date(2026, 6, 24),
        starting_equity=1000.0,
        ending_equity=1005.0,
        paper_pnl=5.0,
        paper_roi=0.005,
        total_signals=2,
        paper_orders=2,
        paper_fills=1,
        rejected_paper_orders=1,
        open_positions=1,
        closed_positions=1,
        win_count=1,
        loss_count=0,
        void_count=0,
        win_rate=1.0,
        total_pnl_usdc=5.0,
        average_roi=0.005,
        max_drawdown=0.0,
        profit_factor=None,
    )
    persistence.reports = [report.model_dump(mode="json")]
    service = _formatting_service(persistence)

    text = service._format_daily()

    assert "<b>📊 Daily Paper Report</b>" in text
    assert "2026-06-24" in text


def test_telegram_bot_status_includes_health_wallet_counts_and_disabled_strategies() -> None:
    persistence = _FormattingPersistence()
    persistence.table_counts = {"signals": 142, "rejected_signals": 91}
    persistence.wallet = {"equity": 987.5, "cash_balance": 900.0, "open_position_count": 3}
    persistence.health_event = {
        "status": "ok",
        "created_at": "2026-06-24T12:00:00Z",
        "components": [],
    }
    service = _formatting_service(persistence)
    service.markets.markets["m1"] = object()
    service.markets.markets["m2"] = object()
    service.signal_pipeline.strategies = [SimpleNamespace(name="a"), SimpleNamespace(name="b")]
    service.signal_pipeline.set_strategy_enabled("b", False)

    text = service._format_status()

    assert "🟢 PolySignal Lab: ok" in text
    assert "Markets     2 tracked" in text
    assert "Positions   3 open" in text
    assert "Wallet      987.50 USDC equity" in text
    assert "Signals     142 accepted / 91 rejected" in text
    assert "Strategies  1/2 enabled" in text
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_telegram_bot_service.py::test_telegram_bot_positions_marks_live_book_when_available tests/test_telegram_bot_service.py::test_telegram_bot_signals_merges_accepted_and_rejected -q
```

Expected: FAIL because render methods still return fixed text.

- [ ] **Step 3: Add safe formatting helpers**

In `telegram_bot.py`, add helpers near `_truncate()`:

```python
    def _safe(self, value: object) -> str:
        return html.escape(str(value))

    def _parse_time(self, value: object) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    def _format_age(self, value: object) -> str:
        dt = self._parse_time(value)
        if dt is None:
            return "unknown"
        seconds = max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
        if seconds < 60:
            return f"{seconds}s ago"
        if seconds < 3600:
            return f"{seconds // 60}m ago"
        return f"{seconds // 3600}h{(seconds % 3600) // 60}m ago"
```

- [ ] **Step 4: Implement positions rendering**

Replace `_format_positions()` with:

```python
    def _format_positions(self) -> str:
        rows = self.persistence.restore_open_positions()
        if not rows:
            return "暂无 open paper positions。"
        blocks: list[str] = []
        for row in rows:
            position = PaperPosition.model_validate(row)
            book = self.books.get(position.token_id)
            mark = book.best_bid if book is not None else None
            lines = [
                f"📈 {self._safe(position.asset)} {self._safe(position.timeframe)} · {self._safe(position.side.value)}",
                f"Strategy  {self._safe(position.strategy)}",
                f"Entry     {position.entry_price:.4f}",
            ]
            if mark is None:
                lines.extend(["Mark      n/a (live book unavailable)", "PnL       n/a"])
            else:
                pnl = (mark - position.entry_price) * position.shares
                roi = pnl / position.stake_usdc if position.stake_usdc else 0.0
                sign = "+" if pnl >= 0 else ""
                lines.extend(
                    [
                        f"Mark      {mark:.4f}",
                        f"Shares    {position.shares:.4f}",
                        f"PnL       {sign}{pnl:.2f} USDC ({sign}{roi:.2%})",
                    ]
                )
            lines.extend(
                [
                    f"Opened    {self._format_age(position.opened_at)}",
                    f"ID        {self._safe(position.paper_position_id)}",
                ]
            )
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)
```

- [ ] **Step 5: Implement status rendering**

Replace `_format_status()` with:

```python
    def _format_status(self) -> str:
        counts = self.persistence.counts()
        positions = self.persistence.restore_open_positions()
        wallet = self.persistence.restore_latest_wallet_snapshot() or {}
        health = self.persistence.restore_latest_system_event("health_snapshot") or {}
        status = str(health.get("status") or "unknown")
        emoji = "🟢" if status == "ok" else "🟡" if status == "degraded" else "🔴"
        strategies = [getattr(strategy, "name", "?") for strategy in self.signal_pipeline.strategies]
        enabled_count = sum(1 for name in strategies if self.signal_pipeline.is_strategy_enabled(name))
        total_count = len(strategies)
        equity = float(wallet.get("equity", 0.0) or 0.0)
        health_age = self._format_age(health.get("created_at")) if health else "n/a"
        return "\n".join(
            [
                f"{emoji} PolySignal Lab: {self._safe(status)}",
                f"Health age  {health_age}",
                f"Markets     {len(self.markets.markets)} tracked",
                f"Positions   {len(positions)} open",
                f"Wallet      {equity:.2f} USDC equity",
                f"Signals     {counts.get('signals', 0)} accepted / {counts.get('rejected_signals', 0)} rejected",
                f"Strategies  {enabled_count}/{total_count} enabled",
                f"Telegram    {'polling ok' if self._running else 'not polling'}",
            ]
        )
```

- [ ] **Step 6: Implement signal merge rendering**

Replace `_format_signals()` with:

```python
    def _format_signals(self) -> str:
        accepted = self.persistence.query_json(
            "signals", where="ORDER BY created_at DESC", limit=5
        )
        rejected = self.persistence.query_json(
            "rejected_signals", where="ORDER BY rejected_at DESC", limit=5
        )
        items: list[tuple[datetime, str]] = []
        for row in accepted:
            ts = self._parse_time(row.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc)
            items.append((ts, self._format_accepted_signal(row)))
        for row in rejected:
            ts = self._parse_time(row.get("rejected_at")) or datetime.min.replace(tzinfo=timezone.utc)
            items.append((ts, self._format_rejected_signal(row)))
        if not items:
            return "暂无 recent signals。"
        return "\n\n".join(text for _, text in sorted(items, key=lambda item: item[0], reverse=True)[:5])

    def _format_accepted_signal(self, row: dict[str, Any]) -> str:
        return "\n".join(
            [
                f"🟢 accepted · {self._safe(row.get('asset', '?'))} {self._safe(row.get('timeframe', '?'))} {self._safe(row.get('action', '?'))} {self._safe(row.get('side', '?'))}",
                f"{self._format_age(row.get('created_at'))} · {self._safe(row.get('strategy', '?'))} · {self._safe(row.get('signal_id', '?'))}",
            ]
        )

    def _format_rejected_signal(self, row: dict[str, Any]) -> str:
        candidate = row.get("candidate") if isinstance(row.get("candidate"), dict) else {}
        return "\n".join(
            [
                f"🔴 rejected · {self._safe(candidate.get('asset', '?'))} {self._safe(candidate.get('timeframe', '?'))} {self._safe(candidate.get('action', '?'))} {self._safe(candidate.get('side', '?'))}",
                f"{self._format_age(row.get('rejected_at'))} · {self._safe(candidate.get('strategy', '?'))} · {self._safe(row.get('reason_code', '?'))}",
                f"ID        {self._safe(candidate.get('signal_id', '?'))}",
            ]
        )
```

- [ ] **Step 7: Implement daily report rendering**

Replace `_format_daily()` with:

```python
    def _format_daily(self) -> str:
        reports = self.persistence.restore_daily_reports(limit=1)
        if not reports:
            return "暂无 daily report。"
        payload = reports[0]
        try:
            report = DailyReport.model_validate(payload)
            return self.formatter.daily_report_message(report)
        except Exception:
            self.logger.exception("Invalid daily report payload")
            return "\n".join(
                [
                    "<b>📊 Daily Paper Report</b>",
                    self._safe(payload.get("report_date", "unknown")),
                    f"Signals {self._safe(payload.get('total_signals', 'unknown'))}",
                    f"PnL     {self._safe(payload.get('total_pnl_usdc', payload.get('paper_pnl', 'unknown')))} USDC",
                    f"WR      {self._safe(payload.get('win_rate', 'unknown'))}",
                    f"ID      {self._safe(payload.get('report_id', 'unknown'))}",
                ]
            )
```

- [ ] **Step 8: Run tests to verify GREEN**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_telegram_bot_service.py::test_telegram_bot_positions_marks_live_book_when_available tests/test_telegram_bot_service.py::test_telegram_bot_positions_shows_mark_na_without_live_book tests/test_telegram_bot_service.py::test_telegram_bot_signals_merges_accepted_and_rejected tests/test_telegram_bot_service.py::test_telegram_bot_daily_validates_payload_before_formatter tests/test_telegram_bot_service.py::test_telegram_bot_status_includes_health_wallet_counts_and_disabled_strategies -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/polysignal_lab/publish/telegram_bot.py tests/test_telegram_bot_service.py
git commit -m "feat: add telegram bot read commands"
```

---

### Task 6: Strategy menu toggles, persisted disabled set, and audit events

**Files:**
- Modify: `src/polysignal_lab/publish/telegram_bot.py`
- Modify: `src/polysignal_lab/app/scheduler.py`
- Modify: `tests/test_telegram_bot_service.py`
- Test command: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_telegram_bot_service.py::test_telegram_bot_strategies_menu_uses_short_callback_data tests/test_telegram_bot_service.py::test_telegram_bot_strategy_toggle_persists_state_and_event tests/test_telegram_bot_service.py::test_telegram_bot_strategy_toggle_rejects_unknown_strategy -q`

**Interfaces:**
- Consumes: `SignalPipeline.set_strategy_enabled(name, enabled)`, `SignalPipeline.disabled_strategies`, `PersistenceService.write_state(name, value)`, `PersistenceService.insert_system_event(event)`.
- Produces: `_format_strategies() -> str`, `_strategies_keyboard() -> InlineKeyboardMarkup`, `_toggle_strategy(data: str) -> tuple[str, InlineKeyboardMarkup | None]`, persisted state key `telegram_disabled_strategies`.

- [ ] **Step 1: Add strategy toggle tests**

Append to `tests/test_telegram_bot_service.py`:

```python

def test_telegram_bot_strategies_menu_uses_short_callback_data() -> None:
    persistence = _FormattingPersistence()
    service = _formatting_service(persistence)
    service.signal_pipeline.strategies = [
        SimpleNamespace(name="vwap_momentum"),
        SimpleNamespace(name="late_consensus"),
        SimpleNamespace(name="x" * 70),
    ]

    text = service._format_strategies()
    keyboard = service._strategies_keyboard()

    assert "✅ vwap_momentum" in text
    assert "✅ late_consensus" in text
    assert "cannot be toggled from Telegram" in text
    values = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert "tg:vwap_momentum" in values
    assert "tg:late_consensus" in values
    assert all(len(value.encode("utf-8")) <= 64 for value in values)
    assert "tg:" + "x" * 70 not in values


def test_telegram_bot_strategy_toggle_persists_state_and_event() -> None:
    persistence = _FormattingPersistence()
    service = _formatting_service(persistence)
    service.signal_pipeline.strategies = [SimpleNamespace(name="vwap_momentum")]

    text, keyboard = service._toggle_strategy("tg:vwap_momentum")

    assert "⏸ vwap_momentum" in text
    assert "vwap_momentum" in service.signal_pipeline.disabled_strategies
    assert persistence.state["telegram_disabled_strategies"] == ["vwap_momentum"]
    event = persistence.state["last_event"]
    assert event["event_type"] == "strategy_toggle"
    assert event["strategy"] == "vwap_momentum"
    assert event["enabled"] is False
    assert isinstance(keyboard, InlineKeyboardMarkup)


def test_telegram_bot_strategy_toggle_rejects_unknown_strategy() -> None:
    persistence = _FormattingPersistence()
    service = _formatting_service(persistence)
    service.signal_pipeline.strategies = [SimpleNamespace(name="vwap_momentum")]

    with pytest.raises(ValueError, match="Unknown strategy"):
        service._toggle_strategy("tg:not_real")
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_telegram_bot_service.py::test_telegram_bot_strategy_toggle_persists_state_and_event -q
```

Expected: FAIL because `_toggle_strategy()` always rejects.

- [ ] **Step 3: Add strategy name helpers**

In `telegram_bot.py`, add:

```python
    def _strategy_names(self) -> list[str]:
        return [
            str(getattr(strategy, "name", ""))
            for strategy in self.signal_pipeline.strategies
            if getattr(strategy, "name", "")
        ]

    def _toggle_callback_for(self, name: str) -> str | None:
        data = f"tg:{name}"
        return data if len(data.encode("utf-8")) <= 64 else None
```

- [ ] **Step 4: Implement strategies text and keyboard**

Replace `_format_strategies()` and `_strategies_keyboard()`:

```python
    def _format_strategies(self) -> str:
        lines = ["⚙️ Strategies"]
        for name in self._strategy_names():
            enabled = self.signal_pipeline.is_strategy_enabled(name)
            prefix = "✅" if enabled else "⏸"
            suffix = ""
            if self._toggle_callback_for(name) is None:
                suffix = " (cannot be toggled from Telegram)"
            reason = self.signal_pipeline.skip_reason_for(name)
            if reason and reason.startswith("dependency_disabled:"):
                suffix = f" ({reason})"
            lines.append(f"{prefix} {self._safe(name)}{suffix}")
        return "\n".join(lines)

    def _strategies_keyboard(self) -> InlineKeyboardMarkup:
        rows: list[list[InlineKeyboardButton]] = []
        for name in self._strategy_names():
            callback_data = self._toggle_callback_for(name)
            if callback_data is None:
                continue
            enabled = self.signal_pipeline.is_strategy_enabled(name)
            label = f"{'⏸' if enabled else '▶️'} {name}"
            rows.append([InlineKeyboardButton(label, callback_data=callback_data)])
        rows.append([InlineKeyboardButton("⬅️ 返回", callback_data="bk")])
        return InlineKeyboardMarkup(rows)
```

- [ ] **Step 5: Implement toggle persistence and audit event**

Replace `_toggle_strategy()`:

```python
    def _toggle_strategy(self, data: str) -> tuple[str, InlineKeyboardMarkup | None]:
        if not data.startswith("tg:"):
            raise ValueError("Unknown strategy")
        name = data[3:]
        names = set(self._strategy_names())
        if name not in names:
            raise ValueError("Unknown strategy")
        enabled = not self.signal_pipeline.is_strategy_enabled(name)
        self.signal_pipeline.set_strategy_enabled(name, enabled)
        disabled = sorted(self.signal_pipeline.disabled_strategies)
        self.persistence.write_state("telegram_disabled_strategies", disabled)
        self.persistence.insert_system_event(
            {
                "event_id": new_id("strategy_toggle"),
                "event_type": "strategy_toggle",
                "severity": "INFO",
                "created_at": utc_iso(),
                "strategy": name,
                "enabled": enabled,
                "disabled_strategies": disabled,
            }
        )
        return self._format_strategies(), self._strategies_keyboard()
```

- [ ] **Step 6: Load persisted disabled strategies during scheduler strategy initialization**

In `src/polysignal_lab/app/scheduler.py`, after `self.signal_pipeline.strategies = self.strategies` in `_initialize_trading_components()`, add:

```python
        self.signal_pipeline.set_strategy_dependencies(
            {entry.name: tuple(entry.depends_on) for entry in self.strategy_schedule}
        )
        known_strategy_names = {entry.name for entry in self.strategy_schedule}
        disabled = self.persistence.read_state("telegram_disabled_strategies", default=[])
        for name in disabled if isinstance(disabled, list) else []:
            if name in known_strategy_names:
                self.signal_pipeline.set_strategy_enabled(str(name), False)
```

- [ ] **Step 7: Run tests to verify GREEN**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_telegram_bot_service.py::test_telegram_bot_strategies_menu_uses_short_callback_data tests/test_telegram_bot_service.py::test_telegram_bot_strategy_toggle_persists_state_and_event tests/test_telegram_bot_service.py::test_telegram_bot_strategy_toggle_rejects_unknown_strategy -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/polysignal_lab/publish/telegram_bot.py src/polysignal_lab/app/scheduler.py tests/test_telegram_bot_service.py
git commit -m "feat: add telegram strategy toggles"
```

---

### Task 7: Scheduler registration, health inclusion, and end-to-end verification

**Files:**
- Modify: `src/polysignal_lab/app/scheduler.py`
- Modify: `tests/test_scheduler_lifecycle.py`
- Test: `tests/test_scheduler_lifecycle.py`, `tests/test_telegram_bot_service.py`, `tests/test_signal_pipeline_manual_disable.py`
- Runtime verification: Docker rebuild and health/log smoke after tests pass.

**Interfaces:**
- Consumes: `TelegramBotService` from Task 3, `HealthService(core_services)` from existing scheduler init.
- Produces: scheduler registration only when `settings.telegram.interactive_enabled` is true; `telegram_bot` appears in `scheduler.services`, `scheduler.supervisor.services`, and `scheduler.health_service.services`.

- [ ] **Step 1: Add scheduler registration tests**

In `tests/test_scheduler_lifecycle.py`, add:

```python

def test_scheduler_does_not_register_telegram_bot_by_default(settings, tmp_path) -> None:
    settings.telegram.interactive_enabled = False

    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)

    names = [service.name for service in scheduler.services]
    assert "telegram_bot" not in names
    assert scheduler.supervisor.services == scheduler.services


def test_scheduler_registers_telegram_bot_in_init_when_interactive_enabled(settings, tmp_path) -> None:
    settings.telegram.interactive_enabled = True
    settings.telegram.interactive_allowed_chat_ids = (123,)

    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)

    names = [service.name for service in scheduler.services]
    assert "telegram_bot" in names
    assert names.index("publish") < names.index("telegram_bot") < names.index("health")
    assert scheduler.supervisor.services == scheduler.services
    assert any(service.name == "telegram_bot" for service in scheduler.health_service.services)
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_scheduler_lifecycle.py::test_scheduler_registers_telegram_bot_in_init_when_interactive_enabled -q
```

Expected: FAIL because `PolySignalScheduler.__init__` does not register `TelegramBotService`.

- [ ] **Step 3: Import the bot service**

In `src/polysignal_lab/app/scheduler.py`, add near the existing Telegram publisher imports:

```python
from polysignal_lab.publish.telegram_bot import TelegramBotService
```

- [ ] **Step 4: Register the bot service between publish and health**

In `PolySignalScheduler.__init__`, replace the `core_services = [...]` block with this construction:

```python
        core_services = [
            self.persistence,
            self.market_universe,
            self.book_feed,
            self.spot_feed,
            self.snapshot_service,
            self.signal_pipeline,
            self.paper_portfolio,
            self.publish_service,
        ]
        self.telegram_bot = None
        if settings.telegram.interactive_enabled:
            self.telegram_bot = TelegramBotService(
                config=settings.telegram,
                persistence=self.persistence,
                signal_pipeline=self.signal_pipeline,
                books=self.ctx.books,
                markets=self.ctx.markets,
                formatter=self.formatter,
                scheduler=self,
                logger=self.logger,
            )
            core_services.append(self.telegram_bot)
        self.health_service = HealthService(core_services)
        self.services = [*core_services, self.health_service]
        self.supervisor = ServiceSupervisor(self.services)
```

Keep `HealthService` and `ServiceSupervisor` creation in `__init__`; do not rebuild them later.

- [ ] **Step 5: Run scheduler registration tests to verify GREEN**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_scheduler_lifecycle.py::test_scheduler_does_not_register_telegram_bot_by_default tests/test_scheduler_lifecycle.py::test_scheduler_registers_telegram_bot_in_init_when_interactive_enabled -q
```

Expected: PASS.

- [ ] **Step 6: Run targeted regression suite**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_telegram_bot_config.py tests/test_telegram_bot_service.py tests/test_signal_pipeline_manual_disable.py tests/test_scheduler_lifecycle.py tests/test_signal_pipeline_equivalence.py tests/test_strategy_execution_order.py tests/test_storage_reporting_publish.py -q
```

Expected: PASS.

- [ ] **Step 7: Run full project tests**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest
```

Expected: PASS for the full suite.

- [ ] **Step 8: Run pre-commit and safety scan**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run pre-commit run --all-files
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run polysignal-safety-scan
```

Expected: both commands PASS. The safety scan must not report `ClobClient(` or live action patterns from this work.

- [ ] **Step 9: Rebuild formal runtime containers**

Run:

```bash
docker compose up -d --build --force-recreate
```

Expected: build completes and containers start.

- [ ] **Step 10: Verify containers and runtime health**

Run:

```bash
docker compose ps
```

Expected: application containers are `running` or `healthy`.

Then verify dashboard health with a cache-busting URL:

```bash
python - <<'PY'
from urllib.request import urlopen
from time import time
url = f"http://127.0.0.1:8081/health?fresh={int(time())}"
print(urlopen(url, timeout=5).read().decode()[:1000])
PY
```

Expected: response contains current health JSON/text and no startup failure. If the deployed dashboard port differs, use the project’s active dashboard port from `docker compose ps` before reading health.

- [ ] **Step 11: Inspect container logs for bot safety outcomes**

Run:

```bash
docker compose logs --tail=200
```

Expected: with default config, no `telegram_bot` polling starts because `interactive_enabled` is false. If interactive config is enabled in the runtime environment, missing token or missing allowlist logs a fail-closed warning and the scheduler continues running.

- [ ] **Step 12: Commit final integration**

```bash
git add src/polysignal_lab/app/scheduler.py tests/test_scheduler_lifecycle.py
git commit -m "feat: wire telegram bot service"
```

---

## Self-Review Checklist

- Spec coverage: Tasks 1-7 cover SDK dependency, embedded lifecycle, handlers, buttons, callback acknowledgement, authorization allowlist, fail-closed config, read-only commands, strategy toggle boundary, disabled strategy evaluation, persistence proxies, scheduler registration, health inclusion, tests, and Docker runtime verification.
- Current-repo correction: `MarketRegistry.active()` exists in current `src/polysignal_lab/data/state.py`; `/status` still uses `len(markets.markets)` for tracked count because the spec asks for the runtime registry size.
- Type consistency: `SignalPipeline.set_strategy_enabled(name: str, enabled: bool) -> None`, `is_strategy_enabled(name: str) -> bool`, `skip_reason_for(name: str) -> str | None`, and `set_strategy_dependencies(dependencies: dict[str, tuple[str, ...]]) -> None` are the same in tests, service, scheduler, and scheduler processing.
- PTB consistency: The plan uses `ApplicationBuilder().token(...).rate_limiter(AIORateLimiter(...)).build()`, `CommandHandler`, `CallbackQueryHandler`, `InlineKeyboardButton`, `InlineKeyboardMarkup`, `reply_text()`, and `edit_message_text()` only; no hand-written Bot API requests.
- Persistence consistency: daily reports and latest health/system events are accessed through `PersistenceService` proxies, not through direct `SQLiteStore` reach-through in the bot.
- Safety consistency: The only interactive write is `telegram_disabled_strategies` state plus `strategy_toggle` audit event; no order, position, YAML, key, redemption, or authenticated CLOB path is introduced.
- Red-flag scan: No step asks the engineer to invent behavior; code snippets give exact signatures, assertions, command invocations, and expected outcomes.
