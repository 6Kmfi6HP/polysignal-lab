# Scheduler Supervisor Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce `PolySignalScheduler` into a thin supervisor over explicit services with owned lifecycle, health, and failure boundaries.

**Architecture:** Extract services in the spec's migration order, starting with persistence to remove duplicate write paths, then market/feed services, then pipeline/paper/publish services. `PolySignalScheduler` becomes service construction plus lifecycle orchestration; external CLI modes stay unchanged.

**Tech Stack:** Python 3.11, asyncio, Protocols, SQLite/JSONL stores, FastAPI dashboard, pytest.

## Global Constraints

- Scope: One standalone architecture change. Execute only after earlier targeted specs have stabilized; do not batch with specs 01-07.
- No new distributed system.
- No Redis/Kafka adoption.
- No live trading.
- No complete rewrite of scheduler in one commit.
- No UI redesign.
- Worktree branch: `spec-08-scheduler-supervisor-boundaries`.
- This worktree may be developed in parallel for planning/prototyping, but final merge must wait until spec 04 health contract and specs 05-07 integration surfaces are stable.
- If spec 04 is absent in the target branch, implement only a compatibility adapter that can be replaced by `ComponentHealth` without changing service method signatures.

---

## File Structure

- Create package `src/polysignal_lab/app/services/`.
- Create `runtime_service.py` for `RuntimeService` and health adapter imports.
- Create `persistence_service.py` wrapping `SQLiteStore`, `JSONLStore`, and `StateStore`.
- Create `market_universe_service.py`, `book_feed_service.py`, `spot_feed_service.py`, `snapshot_service.py`, `signal_pipeline.py`, `paper_portfolio_service.py`, `publish_service.py`, and `health_service.py`.
- Modify `src/polysignal_lab/app/scheduler.py` to construct services and hold only service references plus `ServiceContext`.
- Modify `scheduler_runtime.py`, `scheduler_market_data.py`, `scheduler_processing.py`, `scheduler_reporting.py`, `scheduler_state.py`, and `scheduler_reporting_storage.py` to use services and remove direct full-scheduler store/feed ownership.
- Modify `src/polysignal_lab/app/readonly_smoke_runtime.py` and `src/polysignal_lab/app/main.py` only to preserve public behavior.
- Add tests: `tests/test_persistence_service.py`, `tests/test_scheduler_services.py`, `tests/test_market_universe_service.py`, `tests/test_book_feed_service.py`, `tests/test_spot_feed_service.py`, `tests/test_signal_pipeline.py`, `tests/test_paper_portfolio_service.py`, `tests/test_publish_service.py`, `tests/test_scheduler_failure_isolation.py`, and `tests/test_scheduler_lifecycle.py`.

---

### Task 1: Add service contract and lifecycle harness

**Files:**
- Create: `src/polysignal_lab/app/services/__init__.py`
- Create: `src/polysignal_lab/app/services/runtime_service.py`
- Test: `tests/test_scheduler_services.py`

**Interfaces:**
- Produces: `RuntimeService` protocol with `name`, `start()`, `stop()`, `health()`.
- Produces: `ServiceSupervisor.start_all()` and `ServiceSupervisor.stop_all()`.

- [x] **Step 1: Write failing tests**

Create `tests/test_scheduler_services.py`:

```python
from polysignal_lab.app.services.runtime_service import ServiceSupervisor


class _Service:
    name = "fake"

    def __init__(self) -> None:
        self.events: list[str] = []

    async def start(self) -> None:
        self.events.append("start")

    async def stop(self) -> None:
        self.events.append("stop")

    def health(self):
        return {"name": self.name, "status": "ok", "metrics": {}}


async def test_supervisor_starts_and_stops_services_in_reverse_order() -> None:
    first = _Service()
    second = _Service()
    supervisor = ServiceSupervisor([first, second])

    await supervisor.start_all()
    await supervisor.stop_all()

    assert first.events == ["start", "stop"]
    assert second.events == ["start", "stop"]
    assert supervisor.stop_order == ["fake", "fake"]
```

- [x] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_scheduler_services.py::test_supervisor_starts_and_stops_services_in_reverse_order -v`

Expected: FAIL with missing service module.

- [x] **Step 3: Implement contract and supervisor**

Create `runtime_service.py`:

```python
from __future__ import annotations

from typing import Any, Protocol


class RuntimeService(Protocol):
    name: str

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def health(self) -> Any: ...


class ServiceSupervisor:
    def __init__(self, services: list[RuntimeService]) -> None:
        self.services = services
        self.stop_order: list[str] = []

    async def start_all(self) -> None:
        for service in self.services:
            await service.start()

    async def stop_all(self) -> None:
        for service in reversed(self.services):
            await service.stop()
            self.stop_order.append(service.name)
```

- [x] **Step 4: Run test to verify it passes**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_scheduler_services.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/polysignal_lab/app/services tests/test_scheduler_services.py
git commit -m "feat: add scheduler service contract"
```

---

### Task 2: Extract PersistenceService first

**Files:**
- Create: `src/polysignal_lab/app/services/persistence_service.py`
- Modify: `src/polysignal_lab/app/scheduler.py`
- Modify: `src/polysignal_lab/app/scheduler_processing.py`
- Modify: `src/polysignal_lab/app/scheduler_reporting.py`
- Modify: `src/polysignal_lab/app/scheduler_state.py`
- Modify: `src/polysignal_lab/app/scheduler_reporting_storage.py`
- Modify: `src/polysignal_lab/app/readonly_smoke_runtime.py`
- Test: `tests/test_persistence_service.py`

**Interfaces:**
- Produces: `PersistenceService.append_log()`, `insert_signal()`, `insert_rejected_signal()`, `insert_paper_order()`, `insert_paper_fill()`, `upsert_paper_position()`, `insert_daily_report()`, `persist_state()`, `restore_state()`, `close()`.

- [x] **Step 1: Write failing service test**

Create `tests/test_persistence_service.py`:

```python
from polysignal_lab.app.services.persistence_service import PersistenceService
from polysignal_lab.storage.jsonl_store import JSONLStore
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.storage.state_store import StateStore


def test_persistence_service_wraps_counts_and_close(tmp_path) -> None:
    service = PersistenceService(
        logs=JSONLStore(tmp_path / "logs"),
        sqlite=SQLiteStore(tmp_path / "db.sqlite3"),
        state=StateStore(tmp_path / "state"),
    )

    counts = service.counts()
    service.close()

    assert "signals" in counts
```

- [x] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_persistence_service.py -v`

Expected: FAIL with missing `PersistenceService`.

- [x] **Step 3: Implement wrapper and migrate one callsite at a time**

Create `persistence_service.py`:

```python
from __future__ import annotations

from typing import Any

from polysignal_lab.storage.jsonl_store import JSONLStore
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.storage.state_store import StateStore


class PersistenceService:
    name = "persistence"

    def __init__(self, logs: JSONLStore, sqlite: SQLiteStore, state: StateStore) -> None:
        self.logs = logs
        self.sqlite = sqlite
        self.state = state

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        self.close()

    def health(self) -> dict[str, object]:
        return {"name": self.name, "status": "ok", "metrics": self.counts()}

    def append_log(self, stream: str, payload: Any) -> None:
        self.logs.append(stream, payload)

    def counts(self) -> dict[str, int]:
        return self.sqlite.counts()

    def insert_signal(self, signal: Any) -> None:
        self.sqlite.insert_signal(signal)

    def insert_rejected_signal(self, rejected: Any) -> None:
        self.sqlite.insert_rejected_signal(rejected)

    def close(self) -> None:
        self.sqlite.close()
```

In `scheduler.py`, create `self.persistence = PersistenceService(self.logs, self.sqlite, self.state)`.

Replace direct pairs like:

```python
scheduler.logs.append("signals", signal)
scheduler.sqlite.insert_signal(signal)
```

with:

```python
scheduler.persistence.append_log("signals", signal)
scheduler.persistence.insert_signal(signal)
```

Continue until `scheduler_processing.py`, `scheduler_reporting.py`, `scheduler_state.py`, and smoke runtime no longer issue direct persistence writes except through `PersistenceService`.

- [x] **Step 4: Run persistence regression tests**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_persistence_service.py tests/test_scheduler_paper.py tests/test_scheduler_reports.py tests/test_storage_restore.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/polysignal_lab/app tests/test_persistence_service.py
git commit -m "refactor: centralize scheduler persistence"
```

---

### Task 3: Extract market universe service

**Files:**
- Create: `src/polysignal_lab/app/services/market_universe_service.py`
- Modify: `src/polysignal_lab/app/scheduler.py`
- Modify: `src/polysignal_lab/app/scheduler_market_data.py`
- Test: `tests/test_market_universe_service.py`

**Interfaces:**
- Produces: `MarketUniverseService.refresh_once()`, `fetch_resolved()`, `active_markets()`, `token_ids()`.

- [x] **Step 1: Write service test**

Create `tests/test_market_universe_service.py`:

```python
from polysignal_lab.app.services.market_universe_service import MarketUniverseService
from polysignal_lab.data.state import MarketRegistry


class _Discovery:
    async def active_markets(self):
        return []

    async def resolved_markets(self):
        return []


class _Persistence:
    def append_log(self, stream, payload):
        pass

    def upsert_market(self, market):
        pass


async def test_market_universe_refresh_keeps_registry_empty_when_no_markets(settings) -> None:
    registry = MarketRegistry()
    service = MarketUniverseService(_Discovery(), registry, _Persistence())

    await service.refresh_once()

    assert service.active_markets() == []
```

- [x] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_universe_service.py -v`

Expected: FAIL with missing service.

- [x] **Step 3: Implement service and delegate existing helper**

Create service:

```python
class MarketUniverseService:
    name = "market_universe"

    def __init__(self, discovery, markets, persistence) -> None:
        self.discovery = discovery
        self.markets = markets
        self.persistence = persistence

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def health(self) -> dict[str, object]:
        return {"name": self.name, "status": "ok", "metrics": {"active_markets": len(self.active_markets())}}

    async def refresh_once(self) -> None:
        for market in await self.discovery.active_markets():
            self.markets.upsert(market)
            self.persistence.append_log("markets", market)
            self.persistence.upsert_market(market)

    async def fetch_resolved(self) -> None:
        for market in await self.discovery.resolved_markets():
            self.markets.upsert(market)
            self.persistence.append_log("markets", market)
            self.persistence.upsert_market(market)

    def active_markets(self):
        return self.markets.active()
```

Modify scheduler helper functions to call `scheduler.market_universe.refresh_once()` and `scheduler.market_universe.fetch_resolved()`.

- [x] **Step 4: Run market tests**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_universe_service.py tests/test_market_discovery_and_feeds.py tests/test_market_data.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/polysignal_lab/app/services/market_universe_service.py src/polysignal_lab/app/scheduler.py src/polysignal_lab/app/scheduler_market_data.py tests/test_market_universe_service.py
git commit -m "refactor: extract market universe service"
```

---

### Task 4: Extract book and spot feed services

**Files:**
- Create: `src/polysignal_lab/app/services/book_feed_service.py`
- Create: `src/polysignal_lab/app/services/spot_feed_service.py`
- Modify: `src/polysignal_lab/app/scheduler.py`
- Modify: `src/polysignal_lab/app/scheduler_market_data.py`
- Modify: `src/polysignal_lab/app/scheduler_runtime.py`
- Test: `tests/test_book_feed_service.py`
- Test: `tests/test_spot_feed_service.py`

**Interfaces:**
- Produces: `BookFeedService.start()`, `stop()`, `sync_subscription(token_ids)`, `reseed(token_ids)`.
- Produces: `SpotFeedService.start()`, `stop()`.

- [x] **Step 1: Write feed service tests**

Create `tests/test_book_feed_service.py`:

```python
from polysignal_lab.app.services.book_feed_service import BookFeedService


class _MarketData:
    async def get_books(self, token_ids):
        return []


class _Books:
    def mark_stale(self, token_id, reason):
        self.last = (token_id, reason)


async def test_book_feed_reseed_marks_missing_books_stale(settings) -> None:
    books = _Books()
    service = BookFeedService(settings.data.polymarket, _MarketData(), books)

    await service.reseed(["token-1"])

    assert books.last == ("token-1", "RECONNECT_RESEED_FAILED")
```

Create `tests/test_spot_feed_service.py`:

```python
from polysignal_lab.app.services.spot_feed_service import SpotFeedService


class _Feed:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def run(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


async def test_spot_feed_stop_delegates_to_adapter(settings) -> None:
    feed = _Feed()
    service = SpotFeedService(feed)

    await service.stop()

    assert feed.stopped is True
```

- [x] **Step 2: Run tests to verify they fail**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_book_feed_service.py tests/test_spot_feed_service.py -v`

Expected: FAIL with missing service modules.

- [x] **Step 3: Implement services by moving existing scheduler_market_data logic**

Book service skeleton:

```python
class BookFeedService:
    name = "book_feed"

    def __init__(self, config, market_data, books, websocket=None) -> None:
        self.config = config
        self.market_data = market_data
        self.books = books
        self.websocket = websocket
        self.tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        if self.websocket is not None:
            self.websocket.stop()
        for task in self.tasks:
            if not task.done():
                task.cancel()

    async def reseed(self, token_ids: list[str]) -> None:
        refreshed: set[str] = set()
        try:
            for book in await self.market_data.get_books(token_ids):
                self.books.update_from_snapshot(book)
                refreshed.add(book.token_id)
        finally:
            for token_id in set(token_ids) - refreshed:
                self.books.mark_stale(token_id, "RECONNECT_RESEED_FAILED")

    def health(self) -> dict[str, object]:
        return {"name": self.name, "status": "ok", "metrics": {"tasks": len(self.tasks)}}
```

Spot service skeleton:

```python
class SpotFeedService:
    name = "spot_feed"

    def __init__(self, feed) -> None:
        self.feed = feed
        self.task: asyncio.Task | None = None

    async def start(self) -> None:
        if self.task is None:
            self.task = asyncio.create_task(self.feed.run())

    async def stop(self) -> None:
        self.feed.stop()
        if self.task and not self.task.done():
            self.task.cancel()

    def health(self) -> dict[str, object]:
        return {"name": self.name, "status": "ok", "metrics": {"running": bool(self.task and not self.task.done())}}
```

Migrate WebSocket start/stop/sync/reseed methods from `scheduler_market_data.py` into the services while preserving public scheduler wrappers.

- [x] **Step 4: Run feed tests**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_book_feed_service.py tests/test_spot_feed_service.py tests/test_websocket_contracts.py tests/test_market_data.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/polysignal_lab/app/services src/polysignal_lab/app/scheduler.py src/polysignal_lab/app/scheduler_market_data.py src/polysignal_lab/app/scheduler_runtime.py tests/test_book_feed_service.py tests/test_spot_feed_service.py
git commit -m "refactor: extract feed services"
```

---

### Task 5: Extract snapshot service and serial signal pipeline

**Files:**
- Create: `src/polysignal_lab/app/services/snapshot_service.py`
- Create: `src/polysignal_lab/app/services/signal_pipeline.py`
- Modify: `src/polysignal_lab/app/scheduler.py`
- Modify: `src/polysignal_lab/app/scheduler_processing.py`
- Test: `tests/test_signal_pipeline.py`

**Interfaces:**
- Produces: `SnapshotService.build(market)`.
- Produces: `SignalPipeline.evaluate_snapshot(snapshot) -> list[SignalCandidate]`.

- [x] **Step 1: Write signal pipeline test**

Create `tests/test_signal_pipeline.py`:

```python
from polysignal_lab.app.services.signal_pipeline import SignalPipeline


class _Strategy:
    name = "fake"

    def evaluate(self, snapshot):
        return []


class _Gate:
    pass


class _Consensus:
    pass


def test_signal_pipeline_returns_no_candidates_for_empty_strategy_result() -> None:
    pipeline = SignalPipeline([_Strategy()], _Gate(), _Consensus(), persistence=None)

    accepted = pipeline.evaluate_snapshot(snapshot=object())

    assert accepted == []
```

- [x] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_signal_pipeline.py -v`

Expected: FAIL with missing `SignalPipeline`.

- [x] **Step 3: Implement serial wrappers without changing semantics**

Create `snapshot_service.py`:

```python
class SnapshotService:
    name = "snapshot"

    def __init__(self, builder) -> None:
        self.builder = builder

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def build(self, market):
        return await self.builder.build(market)

    def health(self):
        return {"name": self.name, "status": "ok", "metrics": {}}
```

Create `signal_pipeline.py` by moving the strategy/gate/consensus loop from `scheduler_processing.evaluate_once` into methods. Keep every gate/consensus mutation serial.

- [x] **Step 4: Run pipeline regression tests**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_signal_pipeline.py tests/test_scheduler.py tests/test_signal_gate.py tests/test_strategies.py tests/test_ptb_diff.py tests/test_vwap_momentum.py tests/test_late_consensus.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/polysignal_lab/app/services/snapshot_service.py src/polysignal_lab/app/services/signal_pipeline.py src/polysignal_lab/app/scheduler.py src/polysignal_lab/app/scheduler_processing.py tests/test_signal_pipeline.py
git commit -m "refactor: extract serial signal pipeline"
```

---

### Task 6: Extract paper portfolio and publish services

**Files:**
- Create: `src/polysignal_lab/app/services/paper_portfolio_service.py`
- Create: `src/polysignal_lab/app/services/publish_service.py`
- Modify: `src/polysignal_lab/app/scheduler.py`
- Modify: `src/polysignal_lab/app/scheduler_processing.py`
- Modify: `src/polysignal_lab/app/scheduler_reporting.py`
- Test: `tests/test_paper_portfolio_service.py`
- Test: `tests/test_publish_service.py`
- Test: `tests/test_scheduler_failure_isolation.py`

**Interfaces:**
- Produces: `PaperPortfolioService.process_signal()`, `tick_resting_orders()`, `check_settlements()`, `generate_daily_report()`.
- Produces: `PublishService.publish_signal()`, `publish_paper_result()`, `publish_daily_report()`.

- [x] **Step 1: Write isolation test**

Create `tests/test_scheduler_failure_isolation.py`:

```python
import asyncio

import pytest

from polysignal_lab.app.services.publish_service import PublishService


class _Formatter:
    def signal_message(self, signal, stake_usdc: float) -> str:
        return "signal-message"


class _SlowPublisher:
    async def send(self, message: str, message_type: str, signal_id: str):
        await asyncio.sleep(10)


class _Persistence:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def append_log(self, stream, payload):
        self.rows.append({"stream": stream, "payload": payload})


class _Signal:
    signal_id = "sig-1"


async def test_publish_timeout_does_not_hang_signal_processing() -> None:
    service = PublishService(
        formatter=_Formatter(),
        publisher=_SlowPublisher(),
        persistence=_Persistence(),
        timeout_sec=0.01,
    )

    with pytest.raises(TimeoutError):
        await service.publish_signal(_Signal(), stake_usdc=10.0)
```

This test fails before `PublishService` exists, then passes when publishing is isolated behind a bounded timeout.

- [x] **Step 2: Run current service tests**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_paper_portfolio_service.py tests/test_publish_service.py tests/test_scheduler_failure_isolation.py -v`

Expected: missing service tests fail until services are added.

- [x] **Step 3: Move paper and publish responsibilities**

Paper service owns `PaperWallet`, `PaperSimulator`, `PaperExitEngine`, `PaperSettlementEngine`, passive ticks, and report generation entrypoint.

Publish service wraps `MessageFormatter` and `TelegramPublisher`; all audit writes go through `PersistenceService`.

Use explicit timeouts around publish/report paths:

```python
async def publish_signal(self, signal, stake_usdc: float) -> None:
    message = self.formatter.signal_message(signal, stake_usdc)
    publish = await asyncio.wait_for(self.publisher.send(message, "signal", signal.signal_id), timeout=5.0)
    self.persistence.append_log("telegram_publishes", publish.as_dict())
    self.persistence.insert_telegram_publish(publish.as_dict())
```

- [x] **Step 4: Run paper/publish tests**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_paper_portfolio_service.py tests/test_publish_service.py tests/test_scheduler_failure_isolation.py tests/test_scheduler_paper.py tests/test_scheduler_reports.py tests/test_telegram_validation.py -v`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/polysignal_lab/app/services src/polysignal_lab/app/scheduler.py src/polysignal_lab/app/scheduler_processing.py src/polysignal_lab/app/scheduler_reporting.py tests/test_paper_portfolio_service.py tests/test_publish_service.py tests/test_scheduler_failure_isolation.py
git commit -m "refactor: extract paper and publish services"
```

---

### Task 7: Final supervisor cutover

**Files:**
- Modify: `src/polysignal_lab/app/scheduler.py`
- Modify: `src/polysignal_lab/app/scheduler_runtime.py`
- Modify: `src/polysignal_lab/app/main.py` only if imports need adjustment.
- Test: `tests/test_scheduler_lifecycle.py`
- Test: `tests/test_cli_runtime_modes.py`

**Interfaces:**
- Produces: `PolySignalScheduler.services: list[RuntimeService]` and `PolySignalScheduler.supervisor: ServiceSupervisor`.

- [x] **Step 1: Write lifecycle test**

Create `tests/test_scheduler_lifecycle.py`:

```python
from polysignal_lab.app.scheduler import PolySignalScheduler


def test_scheduler_exposes_services_and_supervisor(settings, tmp_path) -> None:
    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)

    names = [service.name for service in scheduler.services]

    assert "persistence" in names
    assert "market_universe" in names
    assert "book_feed" in names
    assert "spot_feed" in names
    assert scheduler.supervisor.services == scheduler.services
```

- [x] **Step 2: Run lifecycle test to verify it fails**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_scheduler_lifecycle.py -v`

Expected: FAIL until scheduler exposes services.

- [x] **Step 3: Simplify scheduler runtime**

In `scheduler.py`, build:

```python
self.services = [
    self.persistence,
    self.market_universe,
    self.book_feed,
    self.spot_feed,
    self.snapshot_service,
    self.signal_pipeline,
    self.paper_portfolio,
    self.publish_service,
    self.health_service,
]
self.supervisor = ServiceSupervisor(self.services)
```

In `scheduler_runtime.run`, replace direct startup calls with:

```python
await scheduler.supervisor.start_all()
await scheduler.market_universe.refresh_once()
await scheduler.market_universe.fetch_resolved()
```

In `stop`, call:

```python
await scheduler.supervisor.stop_all()
```

Keep CLI-visible behavior and log messages stable.

- [x] **Step 4: Run final targeted suite**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_scheduler_lifecycle.py tests/test_scheduler_services.py tests/test_scheduler.py tests/test_scheduler_paper.py tests/test_scheduler_reports.py tests/test_websocket_contracts.py tests/test_market_discovery_and_feeds.py tests/test_storage_restore.py tests/test_cli_runtime_modes.py -v
```

Expected: PASS.

- [ ] **Step 5: Run Docker verification after merge to runtime branch** _(deferred: assignment explicitly prohibited Docker in this worktree)_

Run:

```bash
docker compose up -d --build --force-recreate
docker compose ps
```

Expected: compose services are recreated and `/health` remains read-only.

- [x] **Step 6: Commit final cutover**

```bash
git add src tests docs/superpowers/plans/2026-06-23-08-scheduler-supervisor-boundaries.md
git commit -m "refactor: supervise scheduler services"
```
