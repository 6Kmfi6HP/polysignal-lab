# CLOB Book Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Polymarket order book state safe enough for signal gates and paper fills by treating WebSocket data as a reconciled local book, not as best-effort price hints.

**Architecture:** We track orderbook epoch states and check fill eligibility in the registry. Telemetry updates do not touch book depth, and tick size changes or sequence regressions invalidate the book's eligibility until a reseed snapshot is ingested.

**Tech Stack:** Python, Pydantic, WebSockets, asyncio, pytest

## Global Constraints

- Scope: One standalone architecture change. Do not execute with specs 02-08 in the same implementation batch.
- No live trading, order placement, cancellation, redemption, or authenticated CLOB access.
- No migration to another SDK in this spec.
- No full historical market-data warehouse.
- No scheduler decomposition; spec 08 covers lifecycle boundaries separately.

---

### Task 1: Add `hash` field to `OrderBook` Domain Model

**Files:**
- Modify: `src/polysignal_lab/domain/orderbook.py:16-81`
- Test: `tests/test_market_data.py`

**Interfaces:**
- Consumes: None
- Produces: `OrderBook.hash` property (type `str | None`)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_market_data.py`:
```python
def test_order_book_parses_hash_field() -> None:
    from polysignal_lab.domain.orderbook import OrderBook
    payload = {
        "market": "market-1",
        "asset_id": "token-up",
        "hash": "test-hash-value",
        "bids": [],
        "asks": []
    }
    book = OrderBook.from_polymarket(payload)
    assert book.hash == "test-hash-value"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_data.py::test_order_book_parses_hash_field -v`
Expected: FAIL with AttributeError or AssertionError on `book.hash`

- [ ] **Step 3: Write minimal implementation**

Modify `src/polysignal_lab/domain/orderbook.py`:
```python
class OrderBook(BaseModel):
    # Add hash field under schemas
    hash: str | None = None
```
And inside `from_polymarket`:
```python
        return cls(
            market_id=str(payload.get("market")) if payload.get("market") is not None else None,
            token_id=str(payload.get("asset_id") or payload.get("token_id") or payload.get("assetId")),
            bids=sorted(bids, key=lambda x: x.price, reverse=True),
            asks=sorted(asks, key=lambda x: x.price),
            last_trade_price=safe_float(payload.get("last_trade_price") or payload.get("lastTradePrice")),
            min_order_size=safe_float(payload.get("min_order_size")),
            tick_size=safe_float(payload.get("tick_size")),
            source_timestamp=str(payload.get("timestamp")) if payload.get("timestamp") is not None else None,
            hash=payload.get("hash"),
            received_at=received_at or utc_now(),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_data.py::test_order_book_parses_hash_field -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/domain/orderbook.py tests/test_market_data.py
git commit -m "feat: add hash field to OrderBook model"
```

---

### Task 2: Create `BookEpochState` dataclass

**Files:**
- Create: `src/polysignal_lab/data/book_reconciliation.py`
- Test: `tests/test_market_data.py`

**Interfaces:**
- Consumes: None
- Produces: `BookEpochState` class with dataclass fields

- [ ] **Step 1: Write the failing test**

Add to `tests/test_market_data.py`:
```python
def test_book_epoch_state_instantiation() -> None:
    from polysignal_lab.data.book_reconciliation import BookEpochState
    state = BookEpochState(
        token_id="token-1",
        epoch=1,
        has_snapshot=True,
        stale_reason=None,
        last_hash="hash-1",
        last_source_timestamp=None,
        last_received_at=None
    )
    assert state.token_id == "token-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_data.py::test_book_epoch_state_instantiation -v`
Expected: FAIL with ModuleNotFoundError for `polysignal_lab.data.book_reconciliation`

- [ ] **Step 3: Write minimal implementation**

Create `src/polysignal_lab/data/book_reconciliation.py`:
```python
from dataclasses import dataclass
from datetime import datetime

@dataclass(slots=True)
class BookEpochState:
    token_id: str
    epoch: int
    has_snapshot: bool
    stale_reason: str | None
    last_hash: str | None
    last_source_timestamp: datetime | None
    last_received_at: datetime | None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_data.py::test_book_epoch_state_instantiation -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/data/book_reconciliation.py tests/test_market_data.py
git commit -m "feat: create BookEpochState dataclass"
```

---

### Task 3: OrderBookRegistry additions for reconciliation

**Files:**
- Modify: `src/polysignal_lab/data/state.py:32-50`
- Test: `tests/test_market_data.py`

**Interfaces:**
- Consumes: `BookEpochState`
- Produces: `mark_stale`, `is_fill_eligible`, `update_from_snapshot`, `update_from_delta`, `telemetry_for`, `update_telemetry` on `OrderBookRegistry`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_market_data.py`:
```python
def test_registry_reconciliation_methods() -> None:
    from polysignal_lab.data.state import OrderBookRegistry
    from polysignal_lab.domain.orderbook import OrderBook
    from polysignal_lab.utils import utc_now

    registry = OrderBookRegistry()
    now = utc_now()

    # 1. Delta without snapshot is ignored/counted
    delta_book = OrderBook(token_id="token-1", source_timestamp="1710000000100", received_at=now)
    registry.update_from_delta(delta_book)
    assert registry.get("token-1") is None
    assert registry.metrics.snapshot()["counters"].get("delta_without_snapshot") == 1

    # 2. Snapshot creates eligibility
    snapshot_book = OrderBook(token_id="token-1", source_timestamp="1710000000000", received_at=now)
    registry.update_from_snapshot(snapshot_book)
    assert registry.get("token-1") == snapshot_book
    assert registry.is_fill_eligible("token-1", 10000, now) is True

    # 3. Delta after snapshot is accepted
    registry.update_from_delta(delta_book)
    assert registry.get("token-1") == delta_book

    # 4. Regression invalidates
    regressed_book = OrderBook(token_id="token-1", source_timestamp="1700000000000", received_at=now)
    registry.update_from_delta(regressed_book)
    assert registry.is_fill_eligible("token-1", 10000, now) is False
    assert registry.metrics.snapshot()["counters"].get("book_sequence_invalid") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_data.py::test_registry_reconciliation_methods -v`
Expected: FAIL on AttributeError for `update_from_delta` or `update_from_snapshot`

- [ ] **Step 3: Write minimal implementation**

Modify `src/polysignal_lab/data/state.py` to import `BookEpochState`, define the parsing helper, and implement registry reconciliation methods.

```python
# Add imports at top of src/polysignal_lab/data/state.py:
from datetime import timezone
from polysignal_lab.data.book_reconciliation import BookEpochState
from polysignal_lab.observability.metrics import MetricsRegistry
from typing import Any

# Define timestamp helper:
def parse_source_timestamp(ts_val: Any) -> datetime | None:
    if not ts_val:
        return None
    try:
        val = float(ts_val)
        if val > 1e11:
            val = val / 1000.0
        return datetime.fromtimestamp(val, tz=timezone.utc)
    except (ValueError, TypeError, OverflowError):
        try:
            return datetime.fromisoformat(str(ts_val).replace("Z", "+00:00"))
        except ValueError:
            return None

# Update OrderBookRegistry:
@dataclass
class OrderBookRegistry:
    books: dict[str, OrderBook] = field(default_factory=dict)
    states: dict[str, BookEpochState] = field(default_factory=dict)
    telemetries: dict[str, dict[str, Any]] = field(default_factory=dict)
    metrics: MetricsRegistry = field(default_factory=MetricsRegistry)
    _lock: Lock = field(default_factory=Lock)

    def update(self, book: OrderBook) -> None:
        self.update_from_snapshot(book)

    def get(self, token_id: str) -> OrderBook | None:
        with self._lock:
            return self.books.get(token_id)

    def get_state(self, token_id: str) -> BookEpochState | None:
        with self._lock:
            return self.states.get(token_id)

    def mark_stale(self, token_id: str, reason: str) -> None:
        with self._lock:
            state = self.states.get(token_id)
            if state is None:
                state = BookEpochState(
                    token_id=token_id,
                    epoch=2,
                    has_snapshot=False,
                    stale_reason=reason,
                    last_hash=None,
                    last_source_timestamp=None,
                    last_received_at=None
                )
                self.states[token_id] = state
            else:
                state.epoch += 1
                state.has_snapshot = False
                state.stale_reason = reason
                state.last_hash = None

    def is_fill_eligible(self, token_id: str, max_staleness_ms: int, now: datetime) -> bool:
        with self._lock:
            state = self.states.get(token_id)
            if state is None or not state.has_snapshot:
                reason = state.stale_reason if state else "NO_SNAPSHOT"
                self.metrics.inc(f"paper_fill_rejected_{reason}")
                return False

            book = self.books.get(token_id)
            if book is None:
                self.metrics.inc("paper_fill_rejected_MISSING_BOOK")
                return False

            staleness_ms = int((now - book.received_at).total_seconds() * 1000)
            if staleness_ms > max_staleness_ms:
                self.metrics.inc("paper_fill_rejected_STALE_ORDERBOOK")
                return False

            return True

    def update_from_snapshot(self, book: OrderBook) -> None:
        token_id = book.token_id
        with self._lock:
            state = self.states.get(token_id)
            new_ts = parse_source_timestamp(book.source_timestamp)
            if state is None:
                state = BookEpochState(
                    token_id=token_id,
                    epoch=1,
                    has_snapshot=True,
                    stale_reason=None,
                    last_hash=getattr(book, "hash", None),
                    last_source_timestamp=new_ts,
                    last_received_at=book.received_at
                )
                self.states[token_id] = state
            else:
                if new_ts and state.last_source_timestamp and new_ts < state.last_source_timestamp:
                    state.has_snapshot = False
                    state.stale_reason = "BOOK_SEQUENCE_INVALID"
                    self.metrics.inc("book_sequence_invalid")
                    return

                state.has_snapshot = True
                state.stale_reason = None
                state.last_hash = getattr(book, "hash", None)
                state.last_source_timestamp = new_ts or state.last_source_timestamp
                state.last_received_at = book.received_at

            self.books[token_id] = book

    def update_from_delta(self, book: OrderBook) -> None:
        token_id = book.token_id
        with self._lock:
            state = self.states.get(token_id)
            if state is None or not state.has_snapshot:
                self.metrics.inc("delta_without_snapshot")
                return

            new_ts = parse_source_timestamp(book.source_timestamp)
            if new_ts and state.last_source_timestamp and new_ts < state.last_source_timestamp:
                state.has_snapshot = False
                state.stale_reason = "BOOK_SEQUENCE_INVALID"
                self.metrics.inc("book_sequence_invalid")
                return

            state.last_source_timestamp = new_ts or state.last_source_timestamp
            state.last_received_at = book.received_at
            self.books[token_id] = book

    def update_telemetry(self, token_id: str, best_bid: float | None, best_ask: float | None) -> None:
        with self._lock:
            telemetry = self.telemetries.setdefault(token_id, {})
            if best_bid is not None:
                telemetry["best_bid"] = best_bid
            if best_ask is not None:
                telemetry["best_ask"] = best_ask

    def update_last_trade(self, token_id: str, price: float) -> None:
        with self._lock:
            book = self.books.get(token_id)
            if book is not None:
                updated = book.model_copy(deep=True)
                updated.last_trade_price = price
                updated.received_at = utc_now()
                self.books[token_id] = updated

    def telemetry_for(self, token_id: str) -> dict[str, str | int | float | None]:
        with self._lock:
            state = self.states.get(token_id)
            book = self.books.get(token_id)
            telemetry = self.telemetries.get(token_id, {})

            best_bid = telemetry.get("best_bid")
            best_ask = telemetry.get("best_ask")

            if best_bid is None and book is not None:
                best_bid = book.best_bid
            if best_ask is None and book is not None:
                best_ask = book.best_ask

            return {
                "token_id": token_id,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "last_trade_price": book.last_trade_price if book else None,
                "epoch": state.epoch if state else 0,
                "has_snapshot": state.has_snapshot if state else False,
                "stale_reason": state.stale_reason if state else "NO_SNAPSHOT",
            }

    def books_for_market(self, market: Market) -> tuple[OrderBook | None, OrderBook | None]:
        up = self.get(market.token_for(Side.UP).token_id) if any(t.side == Side.UP for t in market.outcome_tokens) else None
        down = self.get(market.token_for(Side.DOWN).token_id) if any(t.side == Side.DOWN for t in market.outcome_tokens) else None
        return up, down
```

- [ ] **Step 4: Run test to verify it passes**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_data.py::test_registry_reconciliation_methods -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/data/state.py tests/test_market_data.py
git commit -m "feat: implement OrderBookRegistry additions for book reconciliation"
```

---

### Task 4: Modify `PolymarketMarketWebSocket` to handle all WS message types properly

**Files:**
- Modify: `src/polysignal_lab/data/polymarket_clob_ws.py:40-146`
- Test: `tests/test_market_data.py`, `tests/test_websocket_contracts.py`

**Interfaces:**
- Consumes: `OrderBookRegistry` updates (`update_from_snapshot`, `update_from_delta`, `update_telemetry`, `update_last_trade`)
- Produces: Correct handling of `book`, `price_change`, `best_bid_ask`, `tick_size_change`, `market_resolved`, and unknown events in `PolymarketMarketWebSocket.handle_message`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_market_data.py`:
```python
def test_websocket_event_types_reconciliation() -> None:
    from polysignal_lab.data.polymarket_clob_ws import PolymarketMarketWebSocket
    from polysignal_lab.data.state import OrderBookRegistry
    from polysignal_lab.domain.orderbook import OrderBook
    from polysignal_lab.utils import utc_now

    registry = OrderBookRegistry()
    ws = PolymarketMarketWebSocket(None, registry)

    # Pre-seed a valid snapshot
    registry.update_from_snapshot(OrderBook(token_id="token-up", source_timestamp="1710000000000"))

    # 1. Tick size change
    ws.handle_message({"event_type": "tick_size_change", "asset_id": "token-up"})
    assert registry.is_fill_eligible("token-up", 10000, utc_now()) is False
    assert registry.get_state("token-up").stale_reason == "TICK_SIZE_CHANGE_RESEED_REQUIRED"
    assert registry.metrics.snapshot()["counters"].get("ws_event_tick_size_change") == 1

    # 2. Unknown event type
    ws.handle_message({"event_type": "some_unknown_event_type"})
    assert registry.metrics.snapshot()["counters"].get("ws_event_unknown_some_unknown_event_type") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_data.py::test_websocket_event_types_reconciliation -v`
Expected: FAIL on assertions for tick size change or metric counts.

- [ ] **Step 3: Write minimal implementation**

Modify `src/polysignal_lab/data/polymarket_clob_ws.py` to handle all events correctly. We remove `_with_best_bid_ask` and clean up `_apply_single_price_change`, `_apply_best_bid_ask`, `_apply_last_trade` and `handle_message`.

```python
    def handle_message(self, message: str | bytes | JsonObject | list[JsonValue]) -> None:
        if isinstance(message, (str, bytes)):
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                self.registry.metrics.inc("ws_decode_errors")
                return
        else:
            payload = message
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    self.handle_message(item)
            return
        if not isinstance(payload, dict):
            return
        event_type = payload.get("event_type") or payload.get("type")
        match event_type:
            case "book":
                self.registry.update_from_snapshot(OrderBook.from_polymarket(payload, received_at=utc_now()))
            case "price_change" | "price_changes":
                self._apply_price_change(payload)
            case "best_bid_ask":
                self._apply_best_bid_ask(payload)
            case "last_trade_price":
                self._apply_last_trade(payload)
            case "tick_size_change":
                self.registry.metrics.inc("ws_event_tick_size_change")
                token_id = _token_id(payload)
                if token_id:
                    self.registry.mark_stale(token_id, "TICK_SIZE_CHANGE_RESEED_REQUIRED")
            case "market_resolved":
                self.registry.metrics.inc("ws_event_market_resolved")
                self.resolved_events.put_nowait({"event_id": new_id("resolved"), **payload})
            case "new_market" | None:
                return
            case _:
                self.registry.metrics.inc(f"ws_event_unknown_{event_type}")
                return

    def _apply_price_change(self, payload: JsonObject) -> None:
        raw_changes = payload.get("price_changes") or payload.get("changes") or [payload]
        if not isinstance(raw_changes, list):
            return
        for change in raw_changes:
            if isinstance(change, dict):
                self._apply_single_price_change(change)

    def _apply_single_price_change(self, change: JsonObject) -> None:
        token_id = _token_id(change)
        if token_id is None:
            return
        book = self.registry.get(token_id)
        if not book:
            return
        price = safe_float(change.get("price"))
        size = safe_float(change.get("size"), 0.0)
        if price is None or size is None:
            return
        updated = book.model_copy(deep=True)
        target = updated.bids if str(change.get("side") or "").upper() == "BUY" else updated.asks
        target[:] = [level for level in target if level.price != price]
        if size > 0:
            target.append(BookLevel(price=price, size=size))
        updated.bids = sorted(updated.bids, key=lambda level: level.price, reverse=True)
        updated.asks = sorted(updated.asks, key=lambda level: level.price)
        updated.received_at = utc_now()

        # Telemetry updates (do not alter book bids/asks arrays)
        best_bid = safe_float(change.get("best_bid"))
        best_ask = safe_float(change.get("best_ask"))
        if best_bid is not None or best_ask is not None:
            self.registry.update_telemetry(token_id, best_bid, best_ask)

        self.registry.update_from_delta(updated)

    def _apply_best_bid_ask(self, payload: JsonObject) -> None:
        token_id = _token_id(payload)
        if token_id is None:
            return
        best_bid = safe_float(payload.get("best_bid"))
        best_ask = safe_float(payload.get("best_ask"))
        self.registry.update_telemetry(token_id, best_bid, best_ask)

    def _apply_last_trade(self, payload: JsonObject) -> None:
        token_id = _token_id(payload)
        if token_id is None:
            return
        price = safe_float(payload.get("price") or payload.get("last_trade_price"))
        if price is None:
            return
        self.registry.update_last_trade(token_id, price)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_data.py tests/test_websocket_contracts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/data/polymarket_clob_ws.py tests/test_market_data.py tests/test_websocket_contracts.py
git commit -m "feat: handle all WebSocket message types and separate telemetry from depth"
```

---

### Task 5: Add batch reseed hook to `PolymarketMarketWebSocket` and wire it up in `PolySignalScheduler`

**Files:**
- Modify: `src/polysignal_lab/data/polymarket_clob_ws.py:18-36`
- Modify: `src/polysignal_lab/app/scheduler.py:90-112`
- Test: `tests/test_websocket_contracts.py`

**Interfaces:**
- Consumes: `reseed_hook` signature `Callable[[list[str]], Coroutine[Any, Any, None]]`
- Produces: Reseed on WS connection/reconnection before Delta messages.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_websocket_contracts.py`:
```python
async def test_websocket_subscribe_calls_reseed_hook() -> None:
    from unittest.mock import AsyncMock
    from polysignal_lab.data.polymarket_clob_ws import PolymarketMarketWebSocket
    from polysignal_lab.data.state import OrderBookRegistry

    registry = OrderBookRegistry()
    ws = PolymarketMarketWebSocket(None, registry)
    ws.reseed_hook = AsyncMock()

    ws.config = type("Config", (), {"market_ws_url": "ws://dummy"})()
    from unittest.mock import patch
    with patch("websockets.connect", side_effect=ValueError("stop")):
        try:
            ws.running = True
            await ws.subscribe(["token-1"])
        except ValueError as e:
            assert str(e) == "stop"
    ws.reseed_hook.assert_awaited_once_with(["token-1"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_websocket_contracts.py::test_websocket_subscribe_calls_reseed_hook -v`
Expected: FAIL on `assert_awaited_once_with` or attribute missing.

- [ ] **Step 3: Write minimal implementation**

Modify `src/polysignal_lab/data/polymarket_clob_ws.py` to add `reseed_hook` and await it inside the connection loop:
```python
from typing import Callable, Coroutine

class PolymarketMarketWebSocket:
    def __init__(self, config: PolymarketDataConfig, registry: OrderBookRegistry):
        self.config = config
        self.registry = registry
        self.resolved_events: Queue[JsonObject] = Queue()
        self.running = False
        self.reseed_hook: Callable[[list[str]], Coroutine[Any, Any, None]] | None = None
```
And in `subscribe`:
```python
    async def subscribe(self, token_ids: list[str]) -> None:
        self.running = True
        payload = {"assets_ids": token_ids, "type": "market", "custom_feature_enabled": True}
        while self.running:
            try:
                # Reseed before connection block
                if self.reseed_hook is not None:
                    try:
                        await self.reseed_hook(token_ids)
                    except Exception:
                        pass

                async with websockets.connect(self.config.market_ws_url, ping_interval=20, ping_timeout=20) as ws:
                    await ws.send(json.dumps(payload))
                    async for message in ws:
                        self.handle_message(message)
            except (OSError, TimeoutError, websockets.exceptions.WebSocketException):
                await anyio.sleep(2.0)
```
And wire it up in `src/polysignal_lab/app/scheduler.py`:
```python
        self.poly_ws = PolymarketMarketWebSocket(settings.data.polymarket, self.ctx.books)
        self.poly_ws.reseed_hook = self._reseed_ws_books
```
Add the hook implementation to `PolySignalScheduler`:
```python
    async def _reseed_ws_books(self, token_ids: list[str]) -> None:
        try:
            books = await self.rest.get_books(token_ids)
            for book in books:
                self.ctx.books.update_from_snapshot(book)
        except Exception as e:
            self.logger.exception("Failed to reseed order books on WebSocket reconnect: %s", e)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_websocket_contracts.py::test_websocket_subscribe_calls_reseed_hook -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/data/polymarket_clob_ws.py src/polysignal_lab/app/scheduler.py tests/test_websocket_contracts.py
git commit -m "feat: add and wire up websocket reconnect reseed hook"
```

---

### Task 6: Check Order Book eligibility in Paper Simulation fill models and executors

**Files:**
- Modify: `src/polysignal_lab/paper/fill_model.py:19-70`
- Modify: `src/polysignal_lab/paper/order_intent_executor.py:36-110,243-326`
- Modify: `src/polysignal_lab/paper/simulator.py:32-41`
- Modify: `src/polysignal_lab/app/scheduler.py:112-123`
- Test: `tests/test_paper_simulation.py`

**Interfaces:**
- Consumes: `OrderBookRegistry.is_fill_eligible`
- Produces: Ineligibility validation prior to taker fill and GTD resting fill simulations.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_paper_simulation.py`:
```python
async def test_reconciliation_ineligibility_rejects_fills(snapshot, settings) -> None:
    from polysignal_lab.data.state import OrderBookRegistry
    from polysignal_lab.domain.orderbook import OrderBook
    from polysignal_lab.domain.enums import OrderIntent
    from polysignal_lab.paper.simulator import PaperSimulator
    from polysignal_lab.paper.wallet import PaperWallet

    registry = OrderBookRegistry()
    wallet = PaperWallet(1000)
    sim = PaperSimulator(settings.paper_trading, settings.data.polymarket, wallet, registry)

    sig = (await _signal(snapshot, settings)).model_copy(update={"order_intent": OrderIntent.TAKER_FOK})

    # 1. Delta before snapshot -> ineligible
    delta_book = OrderBook(token_id=sig.token_id, source_timestamp="1710000000000")
    registry.update_from_delta(delta_book)
    res = sim.process_signal(sig, delta_book)
    assert res.status == "REJECTED"
    assert res.order.reject_reason == "NO_SNAPSHOT"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_paper_simulation.py::test_reconciliation_ineligibility_rejects_fills -v`
Expected: FAIL (rejects with a different reason or doesn't reject).

- [ ] **Step 3: Write minimal implementation**

Modify `src/polysignal_lab/paper/fill_model.py` to accept `registry`:
```python
class BestAskTakerFillModel:
    def __init__(self, config: FillModelConfig, max_book_staleness_ms: int, registry: OrderBookRegistry | None = None):
        self.config = config
        self.max_book_staleness_ms = max_book_staleness_ms
        self.registry = registry

    def fill(self, order: PaperOrder, orderbook: OrderBook) -> FillDecision:
        if orderbook.token_id != order.token_id:
            return FillDecision(False, reason_code="MALFORMED_ORDERBOOK")
        if self.registry is not None:
            if not self.registry.is_fill_eligible(order.token_id, self.max_book_staleness_ms, order.created_at):
                state = self.registry.get_state(order.token_id)
                reason = state.stale_reason if state else "NO_SNAPSHOT"
                return FillDecision(False, reason_code=reason or "STALE_ORDERBOOK")
        else:
            if not orderbook.is_fresh(self.max_book_staleness_ms, order.created_at):
                return FillDecision(False, reason_code="STALE_ORDERBOOK")
```

Modify `src/polysignal_lab/paper/order_intent_executor.py`:
```python
class BestAskTakerExecutor:
    def __init__(self, fill_model: FillModelConfig, max_book_staleness_ms: int, registry: OrderBookRegistry | None = None):
        self.fill_model = fill_model
        self.max_book_staleness_ms = max_book_staleness_ms
        self.registry = registry

    def execute(self, order: PaperOrder, book: OrderBook, intent: OrderIntent | None = None) -> IntentDispatchResult:
        if book.token_id != order.token_id:
            return self._reject(order, "MALFORMED_ORDERBOOK")
        if self.registry is not None:
            if not self.registry.is_fill_eligible(order.token_id, self.max_book_staleness_ms, order.created_at):
                state = self.registry.get_state(order.token_id)
                reason = state.stale_reason if state else "NO_SNAPSHOT"
                return self._reject(order, reason or "STALE_ORDERBOOK")
        else:
            if not book.is_fresh(self.max_book_staleness_ms, order.created_at):
                return self._reject(order, "STALE_ORDERBOOK")
```

And in `PassiveGtdExecutor.tick`:
```python
class PassiveGtdExecutor:
    def __init__(self, max_book_staleness_ms: int = 10000):
        self._store: dict[str, list[RestingOrder]] = defaultdict(list)
        self.max_book_staleness_ms = max_book_staleness_ms

    def tick(self, books, wallet, risk_check=None) -> list[IntentDispatchResult]:
        from datetime import datetime, timezone
        now = time.time()
        now_dt = datetime.fromtimestamp(now, tz=timezone.utc)
        results: list[IntentDispatchResult] = []
        for token_id in list(self._store.keys()):
            book = books.get(token_id)
            surviving: list[RestingOrder] = []
            for resting in self._store[token_id]:
                if now >= resting.expiry_ts:
                    resting.order.status = OrderStatus.CANCELLED
                    resting.order.reject_reason = "GTD_EXPIRED"
                    results.append(IntentDispatchResult(
                        order=resting.order, status=OrderStatus.CANCELLED, reject_reason="GTD_EXPIRED"
                    ))
                    continue
                if book is not None and book.best_bid is not None and book.best_bid >= resting.limit_price:
                    # Eligibility Check before execution simulating
                    if hasattr(books, "is_fill_eligible") and not books.is_fill_eligible(token_id, self.max_book_staleness_ms, now_dt):
                        state = books.get_state(token_id)
                        reason = state.stale_reason if state else "NO_SNAPSHOT"
                        resting.order.status = OrderStatus.REJECTED
                        resting.order.reject_reason = reason or "STALE_ORDERBOOK"
                        results.append(IntentDispatchResult(
                            order=resting.order, status=OrderStatus.REJECTED, reject_reason=resting.order.reject_reason
                        ))
                        continue
                    can_fill = wallet.can_afford(resting.order.stake_usdc)
```

Modify `src/polysignal_lab/paper/simulator.py`:
```python
class PaperSimulator:
    def __init__(self, config: PaperTradingConfig, data_config: PolymarketDataConfig, wallet: PaperWallet, registry: OrderBookRegistry | None = None):
        self.config = config
        self.wallet = wallet
        self.registry = registry
        self.fill_model = BestAskTakerFillModel(config.fill_model, data_config.max_book_staleness_ms, registry)
        self.taker = BestAskTakerExecutor(config.fill_model, data_config.max_book_staleness_ms, registry)
        self.passive = PassiveGtdExecutor(max_book_staleness_ms=data_config.max_book_staleness_ms)
```

And in `src/polysignal_lab/app/scheduler.py`:
```python
        self.paper = PaperSimulator(
            self.settings.paper_trading, self.settings.data.polymarket, self.wallet, self.ctx.books
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_paper_simulation.py tests/test_resting_orders.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/paper/fill_model.py src/polysignal_lab/paper/order_intent_executor.py src/polysignal_lab/paper/simulator.py src/polysignal_lab/app/scheduler.py tests/test_paper_simulation.py
git commit -m "feat: check orderbook eligibility in paper simulator fill models and executors"
```
