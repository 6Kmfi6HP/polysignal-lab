# Nautilus Runtime Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `polysignal-nautilus`'s dead keepalive loop with a paper-safe PolySignal-owned orchestrator that refreshes market data, syncs Nautilus bridge views, evaluates active strategy wrappers, records paper execution, runs position/settlement policies, and emits health.

**Architecture:** Reuse `PolySignalScheduler` as the owner of Gamma/CLOB/RTDS/PTB/persistence/publisher services, but do not run the legacy scheduler strategy loop. Add small adapters under `src/polysignal_lab/nautilus_runtime/` for book data, registry ingestion, observability, and orchestration; `node.py` becomes async runtime assembly plus lifecycle handling.

**Tech Stack:** Python 3.11 default runtime and tests, uv, pytest, asyncio, current PolySignal scheduler services, existing `nautilus_runtime` wrappers, existing `nautilus_bridge` market registry and sidecar, SQLite/JSONL persistence, Telegram publisher adapter. No default NautilusTrader import or Polymarket live execution path.

## Global Constraints

- Spec source: `docs/superpowers/specs/2026-06-25-nautilus-runtime-fix-design.md` is approved.
- Default runtime remains paper-safe and read-only.
- No `nautilus_trader` import at module load time in default runtime paths.
- No `PolymarketExecutionClient`, `PolymarketLiveExecClientFactory`, live `exec_clients`, allowance scripts, or API-key scripts.
- No reads of `POLYMARKET_PK`, `POLYMARKET_FUNDER`, `POLYMARKET_API_KEY`, `POLYMARKET_API_SECRET`, or `POLYMARKET_PASSPHRASE`.
- Do not use Nautilus `TradingNode.run()` or Nautilus Polymarket factories in this fix.
- Do not add a second public-data stack; reuse scheduler-owned Gamma/CLOB/RTDS/PTB services.
- Do not evaluate cross-market groups; `CrossMarketNautilusStrategy.evaluate_group(group)` remains out of scope until a real relation source exists.
- Paper specs are submitted exactly once: the strategy wrapper submitter is the only path that calls `PolySignalPaperExecutionClient.submit_spec()`.
- Market refresh cadence uses `settings.markets.refresh_interval_sec`, not `settings.app.refresh_interval_sec`.
- Run tests through `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest ...`.
- Runtime code changes intended for formal use require `docker compose up -d --build --force-recreate`, `docker compose ps`, and cache-busted `/health` verification at execution time.

---

## Research Evidence

- `src/polysignal_lab/nautilus_runtime/node.py:167-196` currently builds components, prints ready, registers signals, and sleeps with `time.sleep(1)`.
- `src/polysignal_lab/nautilus_runtime/node.py:50-118` currently returns a dict from `build_trading_node()` and passes `books=None` into `MarketViewAssembler`.
- `src/polysignal_lab/app/scheduler_market_data.py:47-85` refreshes markets, captures anchors, fetches CLOB books, and updates `scheduler.ctx.books`.
- `src/polysignal_lab/app/scheduler_market_data.py:126-142` starts book and spot websockets from scheduler-owned services.
- `src/polysignal_lab/data/state.py:31-48` exposes `MarketRegistry.active()` and `.markets`; `OrderBookRegistry` exposes `.books`, `.get()`, `.recent_trades()`, and `.get_state()` at `:50-72`.
- `src/polysignal_lab/nautilus_bridge/market_view_assembler.py:12-15` requires a `BookDataProvider` with `book_for_token()` and `trades_for_token()`.
- `src/polysignal_lab/nautilus_bridge/external_data.py:21-55` stores sidecar spot and price-to-beat values in local caches.
- `src/polysignal_lab/nautilus_runtime/sidecar_data.py:45-108` unconditionally calls `publisher.publish_data(...)`; do not use it with `publisher=None` for local sync.
- `src/polysignal_lab/nautilus_runtime/strategies/base.py:289-295` calls the injected submitter inside `_submit_spec()` and currently discards the `PaperExecutionResult` return value.
- `src/polysignal_lab/nautilus_runtime/execution.py:158-164` defines `PaperExecutionResult`; `:167-215` defines `PolySignalPaperExecutionClient.submit_spec()`.
- `src/polysignal_lab/nautilus_runtime/settlement.py:86-109` expects `dict[str, Market]` in `SettlementActor.periodic_check()`.
- `src/polysignal_lab/nautilus_runtime/position_policy.py:25-107` evaluates open positions with `current_bid` and closes through the wallet when an exit fires.
- `src/polysignal_lab/app/services/persistence_service.py:36-70` exposes typed persistence insert methods, but `ObservabilityActor.EventStore` currently expects generic `insert_json()` / `insert_many_json()`.

## Scope Check

This is one focused runtime fix. It touches data sync, strategy loop, paper execution recording, position/settlement, observability, and CLI lifecycle because all are required for one `polysignal-nautilus` iteration to do useful work. It explicitly does not implement a native Nautilus `TradingNode`, live Polymarket execution, cross-market group routing, or a new market-data client.

## File Structure

```text
src/polysignal_lab/nautilus_runtime/book_data.py
  New adapter from `OrderBookRegistry` / `OrderBook` into `SideBookView`, `TradeView`, and lightweight `BookSnapshot` for position policy.

src/polysignal_lab/nautilus_runtime/data_ingestor.py
  New local sync adapter from scheduler registries (`MarketRegistry`, `OrderBookRegistry`, `SpotRegistry`, market PTB/anchor data) into bridge registry, sidecar, book provider, and paper client.

src/polysignal_lab/nautilus_runtime/strategies/base.py
  Adds `StrategyEvaluationBatch`, per-iteration clearing, `execution_results`, and `evaluate_all_conditions()`.

src/polysignal_lab/nautilus_runtime/observability.py
  Adds `NautilusEventStoreAdapter` and `NautilusNotifierAdapter`; keeps `ObservabilityActor` as the typed event boundary.

src/polysignal_lab/nautilus_runtime/orchestrator.py
  New sequential async orchestrator with isolated phases and stop handling.

src/polysignal_lab/nautilus_runtime/node.py
  Replaces blocking CLI with async runtime assembly, scheduler-owned service startup/cleanup, real book provider wiring, observability adapters, and signal stop path.

src/polysignal_lab/nautilus_runtime/__init__.py
  Exports only safe runtime helpers; no NautilusTrader import.

tests/test_nautilus_book_data.py
  New tests for book/trade/snapshot conversion.

tests/test_nautilus_data_ingestor.py
  New tests for registry, order book, spot, and PTB sidecar sync.

tests/test_nautilus_orchestrator.py
  New tests for one-loop phase behavior, double-submit prevention, phase isolation, stop timing, and settlement market source.

tests/test_nautilus_strategy_base.py
  Extend with runtime-strategy batch tests while preserving existing bridge-strategy tests.

tests/test_nautilus_observability.py
  Extend with persistence/notifier adapter tests.

tests/test_nautilus_node.py
  Update for async runtime assembly and non-hanging CLI stop path.
```

---

### Task 1: Book Data Provider

**Files:**
- Create: `src/polysignal_lab/nautilus_runtime/book_data.py`
- Create: `tests/test_nautilus_book_data.py`

**Interfaces:**
- Consumes: `OrderBookRegistry.books`, `OrderBookRegistry.get()`, `OrderBookRegistry.recent_trades()`, `OrderBookRegistry.get_state()`, `OrderBook.best_bid`, `OrderBook.best_ask`, `OrderBook.bids`, `OrderBook.asks`, `OrderBook.received_at`.
- Produces: `BookSnapshot`; `NautilusBookDataProvider.book_for_token(token_id) -> SideBookView | None`; `trades_for_token(token_id) -> Sequence[TradeView]`; `snapshot_for_token(token_id) -> BookSnapshot | None`.

- [ ] **Step 1: Write failing conversion tests**

Add `tests/test_nautilus_book_data.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from polysignal_lab.data.state import OrderBookRegistry
from polysignal_lab.domain.orderbook import OrderBook, OrderBookLevel
from polysignal_lab.domain.trade import Trade
from polysignal_lab.nautilus_runtime.book_data import NautilusBookDataProvider


def _book(token_id: str = "up-token") -> OrderBook:
    now = datetime.now(UTC)
    return OrderBook(
        token_id=token_id,
        bids=[OrderBookLevel(price=0.81, size=10.0)],
        asks=[OrderBookLevel(price=0.83, size=12.0)],
        received_at=now,
        source_timestamp=now.isoformat(),
    )


def test_book_for_token_converts_orderbook_to_side_view() -> None:
    registry = OrderBookRegistry()
    registry.update(_book())
    provider = NautilusBookDataProvider(registry)

    view = provider.book_for_token("up-token")

    assert view is not None
    assert view.token_id == "up-token"
    assert view.best_bid == 0.81
    assert view.best_ask == 0.83
    assert view.spread == 0.02
    assert view.ask_levels == ((0.83, 12.0),)
    assert view.received_at is not None


def test_trades_for_token_uses_registry_recent_trades_copy() -> None:
    registry = OrderBookRegistry()
    registry.trade_events["up-token"] = [Trade(price=0.82, size=5.0, side="BUY", timestamp=1.0)]
    provider = NautilusBookDataProvider(registry)

    trades = provider.trades_for_token("up-token")

    assert len(trades) == 1
    assert trades[0].price == 0.82
    assert trades[0].size == 5.0
    assert trades[0].side == "BUY"


def test_empty_book_has_no_best_prices() -> None:
    provider = NautilusBookDataProvider()
    provider.update_book(
        "empty-token",
        OrderBook(token_id="empty-token", bids=[], asks=[], received_at=datetime.now(UTC)),
    )

    view = provider.book_for_token("empty-token")
    snapshot = provider.snapshot_for_token("empty-token")

    assert view is not None
    assert view.best_bid is None
    assert view.best_ask is None
    assert view.spread is None
    assert snapshot is not None
    assert snapshot.bid is None
    assert snapshot.ask is None


def test_snapshot_freshness_falls_back_to_book_received_at() -> None:
    provider = NautilusBookDataProvider()
    received_at = datetime.now(UTC) - timedelta(milliseconds=25)
    provider.update_book(
        "up-token",
        OrderBook(
            token_id="up-token",
            bids=[OrderBookLevel(price=0.80, size=3.0)],
            asks=[OrderBookLevel(price=0.84, size=4.0)],
            received_at=received_at,
        ),
    )

    snapshot = provider.snapshot_for_token("up-token")

    assert snapshot is not None
    assert snapshot.freshness_ms is not None
    assert snapshot.freshness_ms >= 0
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_book_data.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'polysignal_lab.nautilus_runtime.book_data'`.

- [ ] **Step 3: Implement provider**

Create `src/polysignal_lab/nautilus_runtime/book_data.py` with this shape:

```python
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from polysignal_lab.alpha.types import SideBookView, TradeView
from polysignal_lab.data.state import OrderBookRegistry
from polysignal_lab.domain.orderbook import OrderBook


@dataclass(frozen=True, slots=True)
class BookSnapshot:
    token_id: str
    bid: float | None
    ask: float | None
    spread: float | None
    freshness_ms: int | None
    received_at: datetime | None


class NautilusBookDataProvider:
    def __init__(self, registry: OrderBookRegistry | None = None) -> None:
        self._registry = registry
        self._books: dict[str, OrderBook] = {}
        if registry is not None:
            self.update_from_registry(registry)

    def update_from_registry(self, registry: OrderBookRegistry) -> None:
        self._registry = registry
        for token_id, book in registry.books.items():
            self.update_book(token_id, book)

    def update_book(self, token_id: str, book: OrderBook) -> None:
        self._books[token_id] = book

    def book_for_token(self, token_id: str) -> SideBookView | None:
        book = self._book(token_id)
        if book is None:
            return None
        bid = book.best_bid
        ask = book.best_ask
        spread = ask - bid if bid is not None and ask is not None else None
        return SideBookView(
            token_id=token_id,
            best_bid=bid,
            best_ask=ask,
            spread=spread,
            freshness_ms=self._freshness_ms(token_id, book),
            min_order_size=getattr(book, "min_order_size", None),
            tick_size=getattr(book, "tick_size", None),
            last_trade_price=book.last_trade_price,
            last_trade_size=book.last_trade_size,
            last_trade_timestamp=book.last_trade_timestamp,
            received_at=book.received_at,
            ask_levels=tuple((float(level.price), float(level.size)) for level in book.asks),
        )

    def trades_for_token(self, token_id: str) -> Sequence[TradeView]:
        if self._registry is None:
            return ()
        return tuple(
            TradeView(price=trade.price, size=trade.size, side=trade.side, ts=getattr(trade, "datetime", None))
            for trade in self._registry.recent_trades(token_id)
        )

    def snapshot_for_token(self, token_id: str) -> BookSnapshot | None:
        book = self._book(token_id)
        if book is None:
            return None
        bid = book.best_bid
        ask = book.best_ask
        spread = ask - bid if bid is not None and ask is not None else None
        return BookSnapshot(token_id=token_id, bid=bid, ask=ask, spread=spread, freshness_ms=self._freshness_ms(token_id, book), received_at=book.received_at)

    def _book(self, token_id: str) -> OrderBook | None:
        if self._registry is not None:
            return self._registry.get(token_id) or self._books.get(token_id)
        return self._books.get(token_id)

    def _freshness_ms(self, token_id: str, book: OrderBook) -> int | None:
        if self._registry is not None:
            state = self._registry.get_state(token_id)
            if state is not None and state.last_received_at is not None:
                return max(0, int((datetime.now(UTC) - state.last_received_at).total_seconds() * 1000))
        if book.received_at is None:
            return None
        return max(0, int((datetime.now(UTC) - book.received_at).total_seconds() * 1000))
```

Use actual `Trade` timestamp fields if the test reveals a different attribute name; keep the provider network-free.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_book_data.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/nautilus_runtime/book_data.py tests/test_nautilus_book_data.py
git commit -m "feat: add nautilus book data provider"
```

---

### Task 2: Data Ingestor

**Files:**
- Create: `src/polysignal_lab/nautilus_runtime/data_ingestor.py`
- Create: `tests/test_nautilus_data_ingestor.py`

**Interfaces:**
- Consumes: `MarketRegistry.active()`, `OrderBookRegistry.books`, `SpotRegistry.spots`, `MarketPairMeta.from_market()`, `ExternalDataSidecar.update_spot()`, `ExternalDataSidecar.update_price_to_beat()`, `NautilusBookDataProvider.update_book()`, `PolySignalPaperExecutionClient.update_book()`.
- Produces: `NautilusDataIngestor.active_condition_ids() -> tuple[str, ...]`; `sync_all() -> tuple[str, ...]`; idempotent local cache sync with no network I/O.

- [ ] **Step 1: Write failing ingest tests**

Add `tests/test_nautilus_data_ingestor.py` with fixtures that build one active binary `Market`, one `OrderBook`, and one `SpotPrice`:

```python
from __future__ import annotations

from datetime import UTC, datetime

from polysignal_lab.alpha.types import SpotView
from polysignal_lab.data.state import MarketRegistry, OrderBookRegistry, SpotRegistry
from polysignal_lab.domain.enums import MarketStatus, Side
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.domain.orderbook import OrderBook, OrderBookLevel
from polysignal_lab.domain.spot import SpotPrice
from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
from polysignal_lab.nautilus_bridge.market_registry import PolymarketMarketRegistry
from polysignal_lab.nautilus_runtime.book_data import NautilusBookDataProvider
from polysignal_lab.nautilus_runtime.data_ingestor import NautilusDataIngestor
from polysignal_lab.nautilus_runtime.execution import PolySignalPaperExecutionClient


def _market(active: bool = True) -> Market:
    return Market(
        market_id="m1",
        market_slug="btc-updown-5m",
        condition_id="c1",
        asset="BTC",
        timeframe="5m",
        status=MarketStatus.ACTIVE if active else MarketStatus.CLOSED,
        price_to_beat=100_000.0,
        outcome_tokens=[
            OutcomeToken(token_id="up-token", side=Side.UP, outcome_name="Up", market_id="m1"),
            OutcomeToken(token_id="down-token", side=Side.DOWN, outcome_name="Down", market_id="m1"),
        ],
    )


def _book(token_id: str) -> OrderBook:
    return OrderBook(
        token_id=token_id,
        bids=[OrderBookLevel(price=0.81, size=10.0)],
        asks=[OrderBookLevel(price=0.83, size=10.0)],
        received_at=datetime.now(UTC),
    )


def _ingestor() -> tuple[NautilusDataIngestor, PolymarketMarketRegistry, ExternalDataSidecar, NautilusBookDataProvider, PolySignalPaperExecutionClient]:
    markets = MarketRegistry()
    markets.upsert_many([_market()])
    books = OrderBookRegistry()
    books.update(_book("up-token"))
    spots = SpotRegistry()
    spots.update(SpotPrice(asset="BTC", symbol="BTC/USD", price=100_010.0, source="test", received_at=datetime.now(UTC)))
    bridge_registry = PolymarketMarketRegistry()
    sidecar = ExternalDataSidecar()
    provider = NautilusBookDataProvider()
    paper = PolySignalPaperExecutionClient()
    return (
        NautilusDataIngestor(
            markets=markets,
            books=books,
            spots=spots,
            bridge_registry=bridge_registry,
            sidecar=sidecar,
            book_data_provider=provider,
            paper_client=paper,
        ),
        bridge_registry,
        sidecar,
        provider,
        paper,
    )


def test_sync_all_registers_active_markets_and_returns_condition_ids() -> None:
    ingestor, bridge_registry, sidecar, _, _ = _ingestor()

    condition_ids = ingestor.sync_all()

    assert condition_ids == ("c1",)
    assert bridge_registry.by_condition("c1") is not None
    assert sidecar.ptb_for("c1") is not None


def test_sync_orderbooks_updates_provider_and_paper_client() -> None:
    ingestor, _, _, provider, paper = _ingestor()

    ingestor.sync_orderbooks()

    assert provider.book_for_token("up-token") is not None
    assert paper.book_for("up-token") is not None


def test_sync_spots_reads_real_spot_registry() -> None:
    ingestor, _, sidecar, _, _ = _ingestor()

    ingestor.sync_spots()

    spot = sidecar.spot_for("BTC")
    assert isinstance(spot, SpotView)
    assert spot.price == 100_010.0
    assert spot.source == "test"


def test_empty_registries_are_noop() -> None:
    bridge_registry = PolymarketMarketRegistry()
    sidecar = ExternalDataSidecar()
    ingestor = NautilusDataIngestor(
        markets=MarketRegistry(),
        books=OrderBookRegistry(),
        spots=SpotRegistry(),
        bridge_registry=bridge_registry,
        sidecar=sidecar,
        book_data_provider=NautilusBookDataProvider(),
        paper_client=PolySignalPaperExecutionClient(),
    )

    assert ingestor.sync_all() == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_data_ingestor.py -v
```

Expected: FAIL with missing `NautilusDataIngestor`.

- [ ] **Step 3: Implement ingestor**

Create `src/polysignal_lab/nautilus_runtime/data_ingestor.py`:

```python
from __future__ import annotations

import logging
from datetime import UTC, datetime

from polysignal_lab.alpha.types import SpotView
from polysignal_lab.data.price_to_beat_provider import PriceToBeatProvider
from polysignal_lab.data.state import MarketRegistry, OrderBookRegistry, SpotRegistry
from polysignal_lab.domain.market import Market
from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
from polysignal_lab.nautilus_bridge.market_registry import MarketPairMeta, PolymarketMarketRegistry
from polysignal_lab.nautilus_runtime.book_data import NautilusBookDataProvider
from polysignal_lab.nautilus_runtime.execution import PolySignalPaperExecutionClient


class NautilusDataIngestor:
    def __init__(
        self,
        *,
        markets: MarketRegistry,
        books: OrderBookRegistry,
        spots: SpotRegistry,
        bridge_registry: PolymarketMarketRegistry,
        sidecar: ExternalDataSidecar,
        book_data_provider: NautilusBookDataProvider,
        paper_client: PolySignalPaperExecutionClient,
        price_to_beat_provider: PriceToBeatProvider | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.markets = markets
        self.books = books
        self.spots = spots
        self.bridge_registry = bridge_registry
        self.sidecar = sidecar
        self.book_data_provider = book_data_provider
        self.paper_client = paper_client
        self.price_to_beat_provider = price_to_beat_provider
        self.logger = logger or logging.getLogger(__name__)

    def active_condition_ids(self) -> tuple[str, ...]:
        return tuple(m.condition_id for m in self.markets.active() if m.condition_id)

    def sync_all(self) -> tuple[str, ...]:
        ids = self.sync_markets()
        self.sync_orderbooks()
        self.sync_spots()
        self.sync_price_to_beat()
        return ids

    def sync_markets(self) -> tuple[str, ...]:
        condition_ids: list[str] = []
        for market in self.markets.active():
            try:
                self.bridge_registry.register(MarketPairMeta.from_market(market))
            except (KeyError, ValueError) as exc:
                self.logger.debug("skipping market %s for bridge sync: %s", market.market_id, exc)
                continue
            condition_ids.append(market.condition_id)
        return tuple(condition_ids)

    def sync_orderbooks(self) -> None:
        for token_id, book in self.books.books.items():
            self.book_data_provider.update_book(token_id, book)
            self.paper_client.update_book(token_id, book)

    def sync_spots(self) -> None:
        now = datetime.now(UTC)
        for spot in self.spots.spots.values():
            freshness_ms = max(0, int((now - spot.received_at).total_seconds() * 1000)) if spot.received_at else None
            self.sidecar.update_spot(
                SpotView(
                    asset=spot.asset,
                    symbol=spot.symbol,
                    price=spot.price,
                    source=spot.source,
                    freshness_ms=freshness_ms,
                )
            )

    def sync_price_to_beat(self) -> None:
        for market in self.markets.active():
            value, source, verified, anchor_source, anchor_lag_ms, from_anchor = self._ptb_for_market(market)
            if value is None:
                continue
            self.sidecar.update_price_to_beat(
                condition_id=market.condition_id,
                value=value,
                source=source,
                verified=verified,
                from_anchor_service=from_anchor,
                anchor_source=anchor_source,
                anchor_lag_ms=anchor_lag_ms,
            )

    def _ptb_for_market(self, market: Market) -> tuple[float | None, str, bool, str | None, int | None, bool]:
        anchor_store = getattr(self.price_to_beat_provider, "anchor_store", None) if self.price_to_beat_provider is not None else None
        if anchor_store is not None:
            anchor = anchor_store.get_verified_anchor_price(market.asset, market.timeframe, market.market_slug)
            if anchor is not None and anchor.price is not None:
                return anchor.price, f"anchor_service:{anchor.source}", True, anchor.source, anchor.lag_ms, True
        if market.price_to_beat is not None:
            return market.price_to_beat, "market_metadata", True, None, None, False
        return None, "unavailable", False, None, None, False
```

Keep it synchronous: do not call `PriceToBeatProvider.get()` here because it is async and may use optional web API I/O.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_data_ingestor.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/nautilus_runtime/data_ingestor.py tests/test_nautilus_data_ingestor.py
git commit -m "feat: sync nautilus runtime data caches"
```

---

### Task 3: Strategy Batch Evaluation

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/strategies/base.py`
- Modify: `tests/test_nautilus_strategy_base.py`

**Interfaces:**
- Consumes: `PolySignalNautilusStrategy.evaluate_condition(condition_id)`, `_submit_spec()`, `PaperExecutionResult`.
- Produces: `StrategyEvaluationBatch(strategy, submitted_specs, rejected_decisions, execution_results)` and `evaluate_all_conditions(condition_ids: Sequence[str] | None = None)`.

- [ ] **Step 1: Write failing batch tests**

Append to `tests/test_nautilus_strategy_base.py` without deleting existing bridge tests:

```python
from polysignal_lab.nautilus_runtime.execution import PaperExecutionResult
from polysignal_lab.nautilus_runtime.strategies.base import PolySignalNautilusStrategy as RuntimeStrategy
from polysignal_lab.domain.enums import OrderStatus


class RuntimeFakePolicy:
    def evaluate(self, decision, view):
        from polysignal_lab.nautilus_runtime.decision_policy import ApprovedDecision
        from polysignal_lab.domain.signal import SignalCandidate
        candidate = SignalCandidate.build(
            strategy=decision.strategy,
            asset=decision.asset,
            timeframe=decision.timeframe,
            market_id=decision.market_id,
            market_slug=decision.market_slug,
            condition_id=decision.condition_id,
            token_id=decision.token_id,
            side=decision.side,
            confidence=decision.confidence,
            entry_reference_price=decision.entry_reference_price,
            max_entry_price=decision.max_entry_price,
            seconds_to_close=decision.seconds_to_close,
            data_freshness_ms=decision.data_freshness_ms,
            reason_codes=list(decision.reason_codes),
            metrics=dict(decision.metrics),
            order_intent=decision.order_intent.intent if decision.order_intent else None,
            expiry_seconds=decision.order_intent.expiry_seconds if decision.order_intent else None,
            pair_id=decision.order_intent.pair_id if decision.order_intent else None,
            hedge_leg=decision.hedge_leg,
        )
        return ApprovedDecision(signal=candidate)


def test_runtime_strategy_evaluate_all_conditions_clears_tracking_and_captures_results() -> None:
    submitted = []

    def submitter(spec):
        submitted.append(spec)
        return PaperExecutionResult(status=OrderStatus.FILLED)

    strategy = RuntimeStrategy(
        core=FakeCore([_decision()]),
        assembler=FakeAssembler(object()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        submitter=submitter,
    )
    strategy.submitted_specs.append(object())

    batch = strategy.evaluate_all_conditions()

    assert batch.strategy == "ptb_diff"
    assert len(batch.submitted_specs) == 1
    assert len(batch.execution_results) == 1
    assert batch.execution_results[0].status == OrderStatus.FILLED
    assert submitted == list(batch.submitted_specs)


def test_runtime_strategy_evaluate_all_conditions_uses_override_condition_ids() -> None:
    class RecordingAssembler(FakeAssembler):
        def __init__(self):
            super().__init__(object())
            self.seen = []

        def build(self, condition_id: str):
            self.seen.append(condition_id)
            return self.view

    assembler = RecordingAssembler()
    strategy = RuntimeStrategy(
        core=FakeCore([]),
        assembler=assembler,
        condition_ids=("old",),
        strategy_name="ptb_diff",
    )

    batch = strategy.evaluate_all_conditions(("new",))

    assert assembler.seen == ["new"]
    assert batch.submitted_specs == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_strategy_base.py -v
```

Expected: FAIL with missing `evaluate_all_conditions` or `StrategyEvaluationBatch`.

- [ ] **Step 3: Implement batch tracking**

In `src/polysignal_lab/nautilus_runtime/strategies/base.py`:

```python
from dataclasses import dataclass
from polysignal_lab.nautilus_runtime.execution import PaperExecutionResult


@dataclass(frozen=True, slots=True)
class StrategyEvaluationBatch:
    strategy: str
    submitted_specs: tuple[NautilusOrderSpec, ...]
    rejected_decisions: tuple[RejectedDecision, ...]
    execution_results: tuple[PaperExecutionResult, ...]
```

Add `self.execution_results: list[PaperExecutionResult] = []` in `__init__()`.

Add method:

```python
def evaluate_all_conditions(
    self,
    condition_ids: Sequence[str] | None = None,
) -> StrategyEvaluationBatch:
    self.submitted_specs.clear()
    self.rejected_decisions.clear()
    self.execution_results.clear()
    for condition_id in tuple(condition_ids) if condition_ids is not None else self.condition_ids:
        self.evaluate_condition(condition_id)
    return StrategyEvaluationBatch(
        strategy=self.strategy_name,
        submitted_specs=tuple(self.submitted_specs),
        rejected_decisions=tuple(self.rejected_decisions),
        execution_results=tuple(self.execution_results),
    )
```

Change `_submit_spec()` to capture submitter output once:

```python
def _submit_spec(self, spec: NautilusOrderSpec, submitted: list[NautilusOrderSpec]) -> None:
    self.submitted_specs.append(spec)
    if self.submitter is not None:
        result = self.submitter(spec)
        if isinstance(result, PaperExecutionResult):
            self.execution_results.append(result)
    submitted.append(spec)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_strategy_base.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/nautilus_runtime/strategies/base.py tests/test_nautilus_strategy_base.py
git commit -m "feat: batch nautilus strategy evaluations"
```

---

### Task 4: Observability Adapters

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/observability.py`
- Modify: `tests/test_nautilus_observability.py`

**Interfaces:**
- Consumes: `PersistenceService.insert_paper_order()`, `insert_paper_fill()`, `upsert_paper_position()`, `insert_paper_trade_result()`, `insert_system_event()`; `TelegramPublisher.send(message, msg_type)`.
- Produces: `NautilusEventStoreAdapter.insert_json()` / `insert_many_json()` and `NautilusNotifierAdapter.send()`.

- [ ] **Step 1: Write failing adapter tests**

Append to `tests/test_nautilus_observability.py`:

```python
import asyncio
import pytest
from polysignal_lab.nautilus_runtime.observability import NautilusEventStoreAdapter, NautilusNotifierAdapter


class FakePersistence:
    def __init__(self):
        self.calls = []

    def insert_paper_order(self, payload): self.calls.append(("insert_paper_order", payload))
    def insert_paper_fill(self, payload): self.calls.append(("insert_paper_fill", payload))
    def upsert_paper_position(self, payload): self.calls.append(("upsert_paper_position", payload))
    def insert_paper_trade_result(self, payload): self.calls.append(("insert_paper_trade_result", payload))
    def insert_system_event(self, payload): self.calls.append(("insert_system_event", payload))


class FakePublisher:
    def __init__(self):
        self.calls = []

    def send(self, message: str, msg_type: str = "") -> None:
        self.calls.append((message, msg_type))


def test_event_store_routes_known_tables_and_rejects_unknown() -> None:
    persistence = FakePersistence()
    adapter = NautilusEventStoreAdapter(persistence)

    adapter.insert_json("orders", {"paper_order_id": "o1"})
    adapter.insert_json("fills", {"paper_fill_id": "f1"})
    adapter.insert_json("positions", {"paper_position_id": "p1"})
    adapter.insert_json("settlements", {"paper_trade_id": "t1"})
    adapter.insert_json("health_snapshot", {"event_id": "h1", "event_type": "health_snapshot", "severity": "info", "created_at": "now"})

    assert [name for name, _ in persistence.calls] == [
        "insert_paper_order",
        "insert_paper_fill",
        "upsert_paper_position",
        "insert_paper_trade_result",
        "insert_system_event",
    ]
    with pytest.raises(ValueError, match="Unknown Nautilus event table"):
        adapter.insert_json("unknown", {})


def test_notifier_adapter_sends_in_thread() -> None:
    publisher = FakePublisher()
    adapter = NautilusNotifierAdapter(publisher)

    asyncio.run(adapter.send("started", "startup"))

    assert publisher.calls == [("started", "startup")]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_observability.py -v
```

Expected: FAIL with missing adapters.

- [ ] **Step 3: Implement adapters**

In `src/polysignal_lab/nautilus_runtime/observability.py`, add:

```python
import asyncio
from collections.abc import Callable


class NautilusEventStoreAdapter:
    def __init__(self, persistence: object) -> None:
        self.persistence = persistence
        self._routes: dict[str, Callable[[object], None]] = {
            "orders": persistence.insert_paper_order,
            "fills": persistence.insert_paper_fill,
            "positions": persistence.upsert_paper_position,
            "settlements": persistence.insert_paper_trade_result,
            "health_snapshot": persistence.insert_system_event,
            "system_events": persistence.insert_system_event,
        }

    def insert_json(self, table: str, data: Mapping[str, object]) -> None:
        route = self._routes.get(table)
        if route is None:
            raise ValueError(f"Unknown Nautilus event table: {table}")
        payload = dict(data)
        if table == "health_snapshot":
            payload.setdefault("event_type", "health_snapshot")
            payload.setdefault("severity", "info")
            payload.setdefault("created_at", payload.get("ts", utc_iso()))
            payload.setdefault("event_id", f"nautilus_health:{payload['created_at']}")
        route(payload)

    def insert_many_json(self, table: str, rows: Sequence[Mapping[str, object]]) -> None:
        for row in rows:
            self.insert_json(table, row)


class NautilusNotifierAdapter:
    def __init__(self, publisher: object) -> None:
        self.publisher = publisher

    async def send(self, message: str, msg_type: str = "") -> None:
        await asyncio.to_thread(self.publisher.send, message, msg_type)
```

If typed persistence rejects lightweight dicts for orders/fills/positions, update `ObservabilityActor.record_order()`, `record_fill()`, `record_position()`, and `record_settlement()` to pass the original domain objects to `insert_json()` instead of reduced dictionaries. Keep existing `FakeStore` tests by allowing both object and mapping payloads.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_observability.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/nautilus_runtime/observability.py tests/test_nautilus_observability.py
git commit -m "feat: adapt nautilus observability services"
```

---

### Task 5: Orchestrator Loop

**Files:**
- Create: `src/polysignal_lab/nautilus_runtime/orchestrator.py`
- Create: `tests/test_nautilus_orchestrator.py`

**Interfaces:**
- Consumes: `PolySignalScheduler`, `scheduler_market_data.refresh_markets_once(scheduler)`, `NautilusDataIngestor.sync_all()`, strategy `evaluate_all_conditions()`, `PolySignalPaperExecutionClient.wallet.open_positions`, `NautilusBookDataProvider.snapshot_for_token()`, `PositionPolicyActor.evaluate()`, `SettlementActor.periodic_check(markets)`, `ObservabilityActor`.
- Produces: `NautilusOrchestrator.run_once()`, `run(stop_event=None)`, `stop()`.

- [ ] **Step 1: Write failing orchestrator tests**

Add `tests/test_nautilus_orchestrator.py` with fakes:

```python
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from polysignal_lab.nautilus_runtime.orchestrator import NautilusOrchestrator


class FakeHealth:
    def __init__(self): self.calls = []
    def mark_ok(self, name, **metrics): self.calls.append(("ok", name, metrics))
    def mark_down(self, name, reason, **metrics): self.calls.append(("down", name, reason, metrics))
    def mark_degraded(self, name, reason, **metrics): self.calls.append(("degraded", name, reason, metrics))


class FakeObservability:
    def __init__(self): self.orders = []; self.fills = []; self.positions = []; self.settlements = []; self.health = 0; self.shutdowns = 0
    def record_order(self, result): self.orders.append(result)
    def record_fill(self, fill): self.fills.append(fill)
    def record_position(self, position): self.positions.append(position)
    def record_settlement(self, result): self.settlements.append(result)
    def record_health_snapshot(self): self.health += 1
    async def notify_shutdown(self): self.shutdowns += 1


class FakeIngestor:
    def __init__(self, ids=("c1",)): self.ids = ids; self.calls = 0
    def sync_all(self): self.calls += 1; return self.ids


class FakeStrategy:
    strategy_name = "ptb_diff"
    def __init__(self): self.seen = []
    def evaluate_all_conditions(self, ids):
        self.seen.append(tuple(ids))
        return SimpleNamespace(strategy="ptb_diff", submitted_specs=(object(),), rejected_decisions=(), execution_results=())


class FakeSettlement:
    def __init__(self): self.markets_seen = None
    async def periodic_check(self, markets):
        self.markets_seen = markets
        return []


def _orchestrator(**overrides):
    scheduler = SimpleNamespace(ctx=SimpleNamespace(markets=SimpleNamespace(markets={"m1": object()})))
    defaults = dict(
        scheduler=scheduler,
        registered_strategies=[FakeStrategy()],
        data_ingestor=FakeIngestor(),
        book_data_provider=SimpleNamespace(snapshot_for_token=lambda token_id: None),
        paper_client=SimpleNamespace(wallet=SimpleNamespace(open_positions={})),
        position_policy=SimpleNamespace(evaluate=lambda position, current_bid=None: None),
        settlement_actor=FakeSettlement(),
        observability=FakeObservability(),
        health=FakeHealth(),
        refresh_interval_sec=0.01,
    )
    defaults.update(overrides)
    return NautilusOrchestrator(**defaults)


async def test_run_once_syncs_evaluates_and_settles_real_market_registry() -> None:
    orch = _orchestrator()

    await orch.run_once()

    assert orch.data_ingestor.calls == 1
    assert orch.registered_strategies[0].seen == [("c1",)]
    assert orch.settlement_actor.markets_seen == {"m1": orch.scheduler.ctx.markets.markets["m1"]}
    assert any(call[1] == "orchestrator" for call in orch.health.calls)
    assert orch.observability.health == 1


async def test_phase_failure_does_not_block_settlement_or_heartbeat() -> None:
    class FailingStrategy(FakeStrategy):
        def evaluate_all_conditions(self, ids):
            raise RuntimeError("boom")

    settlement = FakeSettlement()
    observability = FakeObservability()
    orch = _orchestrator(registered_strategies=[FailingStrategy()], settlement_actor=settlement, observability=observability)

    await orch.run_once()

    assert settlement.markets_seen == orch.scheduler.ctx.markets.markets
    assert observability.health == 1
    assert any(call[0] == "degraded" and call[1] == "strategy_ptb_diff" for call in orch.health.calls)


async def test_stop_event_ends_run_without_full_interval() -> None:
    orch = _orchestrator(refresh_interval_sec=60.0)
    stop = asyncio.Event()
    task = asyncio.create_task(orch.run(stop))
    await asyncio.sleep(0)
    stop.set()
    await asyncio.wait_for(task, timeout=1.0)

    assert orch.observability.shutdowns == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_orchestrator.py -v
```

Expected: FAIL with missing `orchestrator.py`.

- [ ] **Step 3: Implement orchestrator**

Create `src/polysignal_lab/nautilus_runtime/orchestrator.py` with explicit phase helpers. Core shape:

```python
from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from polysignal_lab.app import scheduler_market_data
from polysignal_lab.app.scheduler import PolySignalScheduler
from polysignal_lab.nautilus_runtime.book_data import NautilusBookDataProvider
from polysignal_lab.nautilus_runtime.data_ingestor import NautilusDataIngestor
from polysignal_lab.nautilus_runtime.execution import PolySignalPaperExecutionClient
from polysignal_lab.nautilus_runtime.observability import ObservabilityActor
from polysignal_lab.nautilus_runtime.position_policy import PositionPolicyActor
from polysignal_lab.nautilus_runtime.settlement import SettlementActor
from polysignal_lab.nautilus_runtime.strategies.base import PolySignalNautilusStrategy
from polysignal_lab.observability.health import HealthRegistry


class NautilusOrchestrator:
    def __init__(self, *, scheduler: PolySignalScheduler, registered_strategies: Sequence[PolySignalNautilusStrategy], data_ingestor: NautilusDataIngestor, book_data_provider: NautilusBookDataProvider, paper_client: PolySignalPaperExecutionClient, position_policy: PositionPolicyActor, settlement_actor: SettlementActor, observability: ObservabilityActor, health: HealthRegistry, refresh_interval_sec: float, logger: logging.Logger | None = None) -> None:
        self.scheduler = scheduler
        self.registered_strategies = list(registered_strategies)
        self.data_ingestor = data_ingestor
        self.book_data_provider = book_data_provider
        self.paper_client = paper_client
        self.position_policy = position_policy
        self.settlement_actor = settlement_actor
        self.observability = observability
        self.health = health
        self.refresh_interval_sec = refresh_interval_sec
        self.logger = logger or logging.getLogger(__name__)
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def run(self, stop_event: asyncio.Event | None = None) -> None:
        try:
            while not self._stop.is_set() and not (stop_event is not None and stop_event.is_set()):
                await self.run_once()
                waiters = [asyncio.create_task(self._stop.wait())]
                if stop_event is not None:
                    waiters.append(asyncio.create_task(stop_event.wait()))
                done, pending = await asyncio.wait(waiters, timeout=self.refresh_interval_sec, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                for task in done:
                    task.result()
        except asyncio.CancelledError:
            raise
        finally:
            await self.observability.notify_shutdown()

    async def run_once(self) -> None:
        await self._phase_market_refresh()
        condition_ids = self._phase_sync()
        if condition_ids:
            self._phase_strategy_eval(condition_ids)
        self._phase_position_policy()
        await self._phase_settlement()
        self._phase_health()
```

Implement each `_phase_*` with `try/except Exception` that marks only its component degraded/down and continues. In `_phase_strategy_eval()`, iterate `batch.execution_results`; call `observability.record_order(result)`, then each fill and position from the result. Do not call `paper_client.submit_spec()` anywhere in `orchestrator.py`.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_orchestrator.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/nautilus_runtime/orchestrator.py tests/test_nautilus_orchestrator.py
git commit -m "feat: drive nautilus orchestrator loop"
```

---

### Task 6: Runtime Assembly and CLI Lifecycle

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/node.py`
- Modify: `src/polysignal_lab/nautilus_runtime/__init__.py`
- Modify: `tests/test_nautilus_node.py`

**Interfaces:**
- Consumes: `PolySignalScheduler`, `scheduler_market_data.refresh_markets_once()`, `scheduler_market_data.start_websockets()`, scheduler stop/cleanup, `NautilusBookDataProvider`, `NautilusDataIngestor`, `NautilusOrchestrator`, observability adapters.
- Produces: `NautilusRuntimeBundle`; `async build_nautilus_runtime(settings) -> NautilusRuntimeBundle`; async `run_nautilus_cli_async(settings, stop_event=None)`; sync `run_nautilus_cli(settings)` wrapper for script compatibility.

- [ ] **Step 1: Write failing node assembly tests**

Update `tests/test_nautilus_node.py` so `run_nautilus_cli()` does not require an infinite loop. Add:

```python
import asyncio
from types import SimpleNamespace

from polysignal_lab.nautilus_runtime.node import build_nautilus_runtime
from polysignal_lab.nautilus_runtime.book_data import NautilusBookDataProvider


async def test_build_nautilus_runtime_wires_real_book_provider(monkeypatch) -> None:
    async def fake_refresh(scheduler):
        scheduler.ctx.markets.upsert_many([])

    async def fake_start_websockets(scheduler):
        return []

    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node.scheduler_market_data.refresh_markets_once", fake_refresh)
    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node.scheduler_market_data.start_websockets", fake_start_websockets)

    bundle = await build_nautilus_runtime()

    assert isinstance(bundle.book_data_provider, NautilusBookDataProvider)
    assert bundle.components["assembler"].books is bundle.book_data_provider
    assert bundle.orchestrator is not None


async def test_run_nautilus_cli_async_exits_on_stop_event(monkeypatch) -> None:
    class FakeOrchestrator:
        def __init__(self): self.stopped = False
        async def run(self, stop_event=None):
            assert stop_event is not None
            stop_event.set()
        def stop(self): self.stopped = True

    fake_bundle = SimpleNamespace(orchestrator=FakeOrchestrator(), websocket_tasks=[], scheduler=SimpleNamespace(stop=lambda: None))

    async def fake_build(settings=None):
        return fake_bundle

    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node.build_nautilus_runtime", fake_build)

    await run_nautilus_cli_async(stop_event=asyncio.Event())
```

Keep or rewrite the existing `test_run_nautilus_cli_prints_ready()` so it patches `run_nautilus_cli_async()` and asserts the sync wrapper returns without hanging.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_node.py -v
```

Expected: FAIL with missing `build_nautilus_runtime` / `run_nautilus_cli_async`.

- [ ] **Step 3: Implement async bundle assembly**

In `node.py`, add a dataclass:

```python
@dataclass(slots=True)
class NautilusRuntimeBundle:
    scheduler: PolySignalScheduler
    components: dict[str, Any]
    bridge_registry: PolymarketMarketRegistry
    sidecar: ExternalDataSidecar
    book_data_provider: NautilusBookDataProvider
    data_ingestor: NautilusDataIngestor
    paper_client: PolySignalPaperExecutionClient
    observability: ObservabilityActor
    orchestrator: NautilusOrchestrator
    websocket_tasks: list[asyncio.Task]
```

Add `async def build_nautilus_runtime(settings: Settings | None = None) -> NautilusRuntimeBundle:` that:

1. loads settings when missing;
2. creates `PolySignalScheduler(settings)`;
3. awaits `scheduler_market_data.refresh_markets_once(scheduler)`;
4. creates `NautilusBookDataProvider(scheduler.ctx.books)`;
5. calls `build_trading_node(settings, condition_ids=tuple(m.condition_id for m in scheduler.ctx.markets.active()), books=book_data_provider, scheduler=scheduler)` or updates `build_trading_node()` signature to accept injected `books`, `sidecar`, `registry`, `paper_client`, and observability;
6. creates `NautilusDataIngestor(...)` from scheduler registries;
7. creates `ObservabilityActor(health=scheduler.health, store=NautilusEventStoreAdapter(scheduler.persistence), notifier=NautilusNotifierAdapter(scheduler.publisher))`;
8. awaits `scheduler_market_data.start_websockets(scheduler)`;
9. creates `NautilusOrchestrator(refresh_interval_sec=settings.markets.refresh_interval_sec, ...)`.

Ensure `MarketViewAssembler(..., books=book_data_provider, ...)` is never passed `None`.

- [ ] **Step 4: Implement CLI stop handling**

Add:

```python
async def run_nautilus_cli_async(settings: Settings | None = None, stop_event: asyncio.Event | None = None) -> None:
    event = stop_event or asyncio.Event()
    bundle = await build_nautilus_runtime(settings)
    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        bundle.orchestrator.stop()
        event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, request_stop)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, lambda _signum, _frame: request_stop())

    try:
        await bundle.observability.notify_startup([s.strategy_name for s in bundle.components["strategies"]])
        await bundle.orchestrator.run(event)
    finally:
        request_stop()
        await bundle.scheduler.stop()
```

Keep sync wrapper:

```python
def run_nautilus_cli(settings: Settings | None = None) -> None:
    asyncio.run(run_nautilus_cli_async(settings))
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_nautilus_node.py -v
```

Expected: PASS, no hanging test.

- [ ] **Step 6: Commit**

```bash
git add src/polysignal_lab/nautilus_runtime/node.py src/polysignal_lab/nautilus_runtime/__init__.py tests/test_nautilus_node.py
git commit -m "feat: assemble nautilus runtime loop"
```

---

### Task 7: Acceptance and Boundary Verification

**Files:**
- Modify: `tests/test_nautilus_node.py`
- Modify: `tests/test_nautilus_platform_boundary.py` if the boundary scan needs the new files explicitly covered.
- No production config, Dockerfile, `pyproject.toml`, or `uv.lock` changes expected.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: passing targeted suite and unchanged safety boundary.

- [ ] **Step 1: Add explicit double-submit regression test**

In `tests/test_nautilus_orchestrator.py`, add a fake `paper_client` with a `submit_spec()` method that raises if called by the orchestrator:

```python
async def test_orchestrator_never_submits_specs_outside_strategy_submitter() -> None:
    class PaperClient:
        wallet = SimpleNamespace(open_positions={})
        def submit_spec(self, spec):
            raise AssertionError("orchestrator must not submit specs")

    orch = _orchestrator(paper_client=PaperClient())

    await orch.run_once()

    assert orch.registered_strategies[0].seen == [("c1",)]
```

- [ ] **Step 2: Run all new and touched Nautilus tests**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest \
  tests/test_nautilus_orchestrator.py \
  tests/test_nautilus_book_data.py \
  tests/test_nautilus_data_ingestor.py \
  tests/test_nautilus_strategy_base.py \
  tests/test_nautilus_observability.py \
  tests/test_nautilus_node.py \
  -v
```

Expected: PASS.

- [ ] **Step 3: Run regression boundary suite**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest \
  tests/test_nautilus_platform_boundary.py \
  tests/test_nautilus_runtime_config.py \
  tests/test_nautilus_cutover.py \
  tests/test_nautilus_execution.py \
  tests/test_nautilus_position_policy.py \
  tests/test_nautilus_settlement_actor.py \
  -v
```

Expected: PASS and no forbidden live Nautilus/Polymarket symbols in default runtime source.

- [ ] **Step 4: Run safety scanner test**

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_safety.py -v
```

Expected: PASS; no `ClobClient(` or live Polymarket execution pattern findings.

- [ ] **Step 5: Docker runtime verification for formal deployment**

Only after code tests pass, run:

```bash
docker compose up -d --build --force-recreate
docker compose ps
```

Then verify health with a cache-busted URL:

```bash
python - <<'PY'
from urllib.request import urlopen
from time import time
print(urlopen(f"http://127.0.0.1:8081/health?fresh={time()}", timeout=10).read().decode()[:2000])
PY
```

Expected: compose services are healthy; `/health` returns current runtime health JSON. If execution happens in an isolated worktree without Docker access, record the exact skipped prerequisite and do not claim live runtime deployment.

- [ ] **Step 6: Commit verification updates**

```bash
git add tests/test_nautilus_orchestrator.py tests/test_nautilus_platform_boundary.py
git commit -m "test: verify nautilus runtime fix boundaries"
```

---

## Self-Review

**Spec coverage:**
- Market refresh cadence: Task 5 and Task 6 use scheduler market data and `settings.markets.refresh_interval_sec`.
- Bridge sync: Task 1 and Task 2 sync active markets, books, spots, and PTB into bridge caches.
- Strategy evaluation: Task 3 adds immutable batches and single-submit tracking.
- Execution observability: Task 4 and Task 5 record returned execution results without resubmission.
- Position policy and settlement: Task 5 uses wallet open positions, book snapshots, and `scheduler.ctx.markets.markets`.
- CLI lifecycle: Task 6 replaces `time.sleep()` with async run/stop and signal handling.
- Safety constraints: Task 7 runs platform, runtime config, cutover, execution, position, settlement, and safety tests.

**Placeholder scan:** No prohibited placeholder markers or unspecified test commands remain. Each task has concrete file paths, test code, implementation shape, commands, expected outcomes, and commit messages.

**Type consistency:** `NautilusBookDataProvider`, `NautilusDataIngestor`, `StrategyEvaluationBatch`, `NautilusEventStoreAdapter`, `NautilusNotifierAdapter`, `NautilusOrchestrator`, and `NautilusRuntimeBundle` are defined before later tasks consume them. The plan intentionally keeps `NautilusDataIngestor.sync_price_to_beat()` synchronous by using stored market/anchor data and avoiding async `PriceToBeatProvider.get()`.
