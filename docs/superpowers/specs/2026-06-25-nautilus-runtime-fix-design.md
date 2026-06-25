# Nautilus Runtime Fix: Orchestrator Processing Loop Design

**Status:** Approved
**Scope:** Replace the dead `run_nautilus_cli()` keepalive loop with a paper-safe PolySignal orchestrator that reuses existing data services and current Nautilus-runtime wrappers. This fix does **not** introduce live NautilusTrader `TradingNode` execution or Polymarket authenticated execution.

---

## 1. Goal

`src/polysignal_lab/nautilus_runtime/node.py` currently builds a component dict and then blocks:

```python
while not shutdown:
    time.sleep(1)
```

That keeps the container alive but drives no market refresh, no strategy evaluation, no paper fills, no position checks, no settlement, and no health snapshots.

Add a `NautilusOrchestrator` that drives the existing PolySignal paper runtime in explicit phases:

1. refresh/synchronize market data using existing scheduler data services;
2. synchronize current registries into the Nautilus bridge sidecar/market registry/book provider;
3. evaluate currently active condition IDs through existing Nautilus strategy wrappers;
4. record paper execution results without submitting the same spec twice;
5. evaluate open positions for TP/SL/max-hold exits;
6. scan settleable markets;
7. write health/observability events.

The orchestrator must fix the runtime silence without changing safety posture: no module-load `nautilus_trader` import, no live Polymarket execution client, no `POLYMARKET_*` credential reads, no allowance/API-key helper scripts.

---

## 2. Official NautilusTrader documentation used

Official sources checked while revising this design:

- Live overview: `TradingNode` ingests data and events from data/execution clients on a single asyncio event loop. Source: https://nautilustrader.io/docs/latest/concepts/overview/
- Live node configuration: live nodes must be standalone services, must not block the event loop, and are configured through `TradingNodeConfig` plus data/exec clients. Source: https://nautilustrader.io/docs/latest/how_to/configure_live_trading/
- Strategy callbacks: Nautilus strategies are normally driven by `on_data`, `on_order_book_*`, order-event, and position-event callbacks. Source: https://nautilustrader.io/docs/latest/concepts/strategies/
- Polymarket integration: official adapter exposes Polymarket data/execution clients and factories, and its config can source `POLYMARKET_PK`, `POLYMARKET_FUNDER`, `POLYMARKET_API_KEY`, `POLYMARKET_API_SECRET`, and `POLYMARKET_PASSPHRASE` from environment variables. Source: https://nautilustrader.io/docs/latest/integrations/polymarket/

Design consequence: the default PolySignal runtime must not use `TradingNode.run()` or Nautilus Polymarket factories. This project intentionally uses a paper-safe, PolySignal-owned loop that mirrors the same broad boundaries (data, strategy, execution, position, settlement, observability) without starting Nautilus live internals.

---

## 3. Current code facts this design depends on

These are verified against the current repository and must remain true or the plan must be updated before implementation:

- `run_nautilus_cli()` builds components and sleeps forever in `src/polysignal_lab/nautilus_runtime/node.py`.
- `build_trading_node()` currently defaults `condition_ids=()`. A CLI runtime that does not discover active markets and pass condition IDs will evaluate nothing.
- `MarketViewAssembler.build()` requires `books.book_for_token()`, but current `build_trading_node()` passes `books=None`. The new book provider must be connected before wrappers evaluate.
- `OrderBookRegistry` exposes `books`, `get(token_id)`, `recent_trades(token_id)`, and `get_state(token_id)`; it does **not** expose `_books` or `book_for()`.
- `ExternalDataSidecar` stores `_spots` and `_ptb`; those are caches, not upstream data feeds.
- `SidecarDataActor(publisher=None)` cannot call `publish_*()` safely today because methods unconditionally call `publisher.publish_data(...)`.
- `PolySignalNautilusStrategy._submit_spec()` already calls the injected `submitter`; in `node.py` that submitter is `paper_client.submit_spec`. The orchestrator must never call `paper_client.submit_spec(spec)` again for returned specs.
- `CrossMarketNautilusStrategy` exposes `evaluate_group(group)`, not `evaluate_groups()`, and current node assembly does not create cross-market wrappers or relation groups. Cross-market orchestration is out of scope for this fix.
- `SettlementActor.periodic_check()` needs `dict[str, Market]`; `PolymarketMarketRegistry` stores bridge metadata, not domain `Market` objects. Settlement must use `scheduler.ctx.markets.markets` or another real `MarketRegistry` source.
- The real refresh interval is `settings.markets.refresh_interval_sec`, not `settings.app.refresh_interval_sec`.

---

## 4. Architecture

### 4.1 Runtime composition

Use existing scheduler data services for market discovery, public CLOB books, spot feeds, PTB/anchor service, persistence, Telegram publisher, and health. Do **not** run the legacy scheduler strategy loop.

Startup sequence:

1. `run_nautilus_cli_async(settings)` builds a `PolySignalScheduler(settings)` as the source of shared data services and registries.
2. Run one initial `scheduler_market_data.refresh_markets_once(scheduler)` to populate `scheduler.ctx.markets` and `scheduler.ctx.books`.
3. Derive active condition IDs from `scheduler.ctx.markets.active()`.
4. Build Nautilus runtime components with those condition IDs and a real `NautilusBookDataProvider` wired into `MarketViewAssembler`.
5. Start existing websocket services with `scheduler_market_data.start_websockets(scheduler)` so book and spot registries continue updating out of band.
6. Run `NautilusOrchestrator.run()` until SIGTERM/SIGINT/cancellation.
7. On exit, stop websocket tasks through existing scheduler market-data cleanup.

This is the smallest safe cutover: reuse working public data services instead of inventing a second CLOB/RTDS/Gamma stack.

### 4.2 Orchestrator phases

`NautilusOrchestrator.run_once()` performs one sequential iteration:

1. **Market refresh:** periodically call `refresh_markets_once(scheduler)` according to `settings.markets.refresh_interval_sec`; do not refresh every 1s.
2. **Bridge sync:** copy current domain registries into bridge types:
   - active `Market` objects -> `PolymarketMarketRegistry.register(MarketPairMeta.from_market(market))`;
   - `OrderBookRegistry.books` -> `NautilusBookDataProvider.update_book()` and `paper_client.update_book()`;
   - `SpotRegistry` current spot prices -> `ExternalDataSidecar.update_spot()`;
   - `PriceToBeatProvider`/anchor output -> `ExternalDataSidecar.update_price_to_beat()`.
3. **Strategy evaluation:** call `strategy.evaluate_all_conditions(active_condition_ids)` for each wrapper. The wrapper submits through its existing submitter exactly once and returns a batch describing specs, rejects, and paper execution results.
4. **Execution observability:** record decisions/orders/fills/positions from the returned batch. Do not submit specs again.
5. **Position policy:** iterate `paper_client.wallet.open_positions`, get current bid from `NautilusBookDataProvider.snapshot_for_token(position.token_id)`, and call `PositionPolicyActor.evaluate(position, current_bid=...)`.
6. **Settlement:** call `await settlement_actor.periodic_check(scheduler.ctx.markets.markets)`.
7. **Health heartbeat:** `health.mark_ok("orchestrator", ...)` and `observability.record_health_snapshot()`.

Each phase catches its own expected failures, marks only that component degraded/down, and lets later phases run.

### 4.3 Explicitly out of scope

- Native Nautilus `TradingNode.run()`.
- Nautilus Polymarket data/execution factories.
- Authenticated Polymarket execution.
- Cross-market group evaluation. The current cross-market wrapper lacks a runtime relation source; do not fake one in this fix.
- New abstractions for future venues.

---

## 5. Component changes

### 5.1 `src/polysignal_lab/nautilus_runtime/book_data.py` (new)

Purpose: adapt current `OrderBookRegistry`/`OrderBook` data to `MarketViewAssembler`'s `BookDataProvider` protocol.

Public API:

```python
@dataclass(frozen=True, slots=True)
class BookSnapshot:
    token_id: str
    bid: float | None
    ask: float | None
    spread: float | None
    freshness_ms: int | None
    received_at: datetime | None

class NautilusBookDataProvider:
    def __init__(self, registry: OrderBookRegistry | None = None) -> None: ...
    def update_from_registry(self, registry: OrderBookRegistry) -> None: ...
    def update_book(self, token_id: str, book: OrderBook) -> None: ...
    def book_for_token(self, token_id: str) -> SideBookView | None: ...
    def trades_for_token(self, token_id: str) -> Sequence[TradeView]: ...
    def snapshot_for_token(self, token_id: str) -> BookSnapshot | None: ...
```

Rules:

- Use `registry.books`, `registry.get()`, `registry.recent_trades()`, and `registry.get_state()`; do not use `_books` or `book_for()`.
- Compute freshness from `book.received_at` when no registry state exists.
- Empty bids/asks produce `best_bid=None`, `best_ask=None`, `spread=None`.
- Convert only existing data; no network I/O.

### 5.2 `src/polysignal_lab/nautilus_runtime/data_ingestor.py` (new)

Purpose: synchronize existing PolySignal registries into bridge-side runtime caches. It is a local adapter, not a feed client.

Public API:

```python
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
    ) -> None: ...

    def active_condition_ids(self) -> tuple[str, ...]: ...
    def sync_all(self) -> tuple[str, ...]: ...
    def sync_markets(self) -> tuple[str, ...]: ...
    def sync_orderbooks(self) -> None: ...
    def sync_spots(self) -> None: ...
    def sync_price_to_beat(self) -> None: ...
```

Rules:

- `sync_all()` returns active condition IDs after successful market sync.
- `sync_orderbooks()` loops over `books.books.items()` and calls both `book_data_provider.update_book(token_id, book)` and `paper_client.update_book(token_id, book)`.
- `sync_spots()` reads the real `SpotRegistry`, not `sidecar.sidecar._spots`.
- `sync_price_to_beat()` reads the real PTB/anchor provider or stored anchor data, not `sidecar._ptb`.
- Do not call `SidecarDataActor.publish_*()` when publisher is `None`; update `ExternalDataSidecar` directly.
- Each sync method must be a no-op when the corresponding registry is empty.

### 5.3 `src/polysignal_lab/nautilus_runtime/strategies/base.py`

Add a batch evaluation method that clears per-iteration tracking and avoids double submission.

```python
@dataclass(frozen=True, slots=True)
class StrategyEvaluationBatch:
    strategy: str
    submitted_specs: tuple[NautilusOrderSpec, ...]
    rejected_decisions: tuple[RejectedDecision, ...]
    execution_results: tuple[PaperExecutionResult, ...]

class PolySignalNautilusStrategy:
    def evaluate_all_conditions(
        self,
        condition_ids: Sequence[str] | None = None,
    ) -> StrategyEvaluationBatch: ...
```

Required behavior:

- Clear `submitted_specs`, `rejected_decisions`, and new `execution_results` at the start of each call.
- Iterate `condition_ids` when provided; otherwise use `self.condition_ids`.
- Keep current submitter behavior: `_submit_spec()` is still the only place that invokes `self.submitter(spec)`.
- Capture the submitter return value when it is a `PaperExecutionResult` so observability can record orders/fills/positions.
- Return immutable tuples so the orchestrator cannot mutate strategy internals.

### 5.4 `src/polysignal_lab/nautilus_runtime/orchestrator.py` (new)

Public API:

```python
class NautilusOrchestrator:
    def __init__(
        self,
        *,
        scheduler: PolySignalScheduler,
        registered_strategies: Sequence[PolySignalNautilusStrategy],
        data_ingestor: NautilusDataIngestor,
        book_data_provider: NautilusBookDataProvider,
        paper_client: PolySignalPaperExecutionClient,
        position_policy: PositionPolicyActor,
        settlement_actor: SettlementActor,
        observability: ObservabilityActor,
        health: HealthRegistry,
        refresh_interval_sec: float,
        logger: logging.Logger | None = None,
    ) -> None: ...

    async def run(self, stop_event: asyncio.Event | None = None) -> None: ...
    async def run_once(self) -> None: ...
    def stop(self) -> None: ...
```

Required behavior:

- `stop()` is synchronous and sets an internal event.
- `run(stop_event)` exits when either internal stop or external `stop_event` is set.
- `run()` uses `asyncio.wait_for(stop.wait(), timeout=refresh_interval_sec)` instead of `time.sleep()`.
- `CancelledError` exits cleanly after shutdown notification.
- Market refresh is async and bounded; local sync/evaluation is synchronous and short.
- Use `settings.markets.refresh_interval_sec` for cadence.
- Do not import `nautilus_trader`.

### 5.5 `src/polysignal_lab/nautilus_runtime/node.py`

Replace the blocking CLI with async runtime assembly.

Required changes:

- Add `build_nautilus_runtime(settings) -> NautilusRuntimeBundle` async helper.
- Build `PolySignalScheduler(settings)` to reuse public data services.
- Run initial `refresh_markets_once(scheduler)` before creating wrappers so condition IDs are known.
- Create `NautilusBookDataProvider` before `MarketViewAssembler`; never pass `books=None`.
- Create `ObservabilityActor(health=scheduler.health, store=NautilusEventStoreAdapter(scheduler.persistence), notifier=NautilusNotifierAdapter(scheduler.publisher))`; current `PersistenceService` does not implement `insert_json`, and current `TelegramPublisher.send()` is synchronous, so both need thin adapters.
- Register SIGTERM/SIGINT with `loop.add_signal_handler()` where available; handler must call `orchestrator.stop()` or set the same stop event passed to `run()`.
- Preserve fallback `signal.signal()` for environments where `add_signal_handler()` is unavailable.
- Stop websocket/feed tasks in `finally`.

No code in `node.py` may import or instantiate Nautilus `TradingNode`, Polymarket live data factories, or Polymarket live execution factories.

### 5.6 `src/polysignal_lab/nautilus_runtime/observability.py`

Keep `ObservabilityActor` as the single notification/recording boundary, but make it compatible with existing scheduler services.

Required additions:

- `NautilusEventStoreAdapter(PersistenceService)` implementing the existing `EventStore` protocol by routing known tables to current persistence methods (`insert_signal`, `insert_paper_order`, `insert_paper_fill`, `upsert_paper_position`, `insert_paper_trade_result`, `insert_system_event`). Unknown tables raise `ValueError` instead of silently dropping data.
- `NautilusNotifierAdapter(TelegramPublisher)` implementing async `send(message, msg_type)` by using `asyncio.to_thread()` around the synchronous publisher call.
- No per-iteration Telegram spam. Startup/shutdown notify once; decision/fill/settlement notifications only for actual new events from a `StrategyEvaluationBatch` or position/settlement result.
- `notify_decision()` must not be called for every unchanged rejection on every loop.

---

## 6. Error handling

Phase failures are isolated:

| Phase | Failure handling |
|---|---|
| Market refresh | mark `gamma`/`clob_rest` degraded/down via existing scheduler health; continue with last registries |
| Bridge sync | mark `data_ingestor` degraded; skip strategy eval if no active condition IDs |
| Strategy eval | mark `strategy_<name>` degraded; continue to next strategy |
| Execution observability | log and continue; do not re-submit orders |
| Position policy | mark `position_policy` degraded; continue to next position |
| Settlement | mark `settlement_actor` degraded; continue to heartbeat |
| Observability heartbeat | log only; avoid recursive health writes |

Stop-the-world conditions:

1. SIGTERM/SIGINT sets the orchestrator stop event.
2. `KeyboardInterrupt` in the outer entrypoint exits normally.
3. `CancelledError` from service shutdown exits after best-effort shutdown notification.

---

## 7. Testing plan

Use project Python 3.11:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest \
  tests/test_nautilus_orchestrator.py \
  tests/test_nautilus_book_data.py \
  tests/test_nautilus_data_ingestor.py \
  tests/test_nautilus_strategy_base.py \
  -v
```

New tests:

- `tests/test_nautilus_book_data.py`
  - converts real `OrderBook` bids/asks to `SideBookView`;
  - uses `OrderBookRegistry.books/get/recent_trades`, not `_books`;
  - empty book returns no best prices.
- `tests/test_nautilus_data_ingestor.py`
  - syncs `MarketRegistry.active()` to `PolymarketMarketRegistry` and returns condition IDs;
  - syncs `OrderBookRegistry.books` into both provider and paper client;
  - syncs real `SpotRegistry` into `ExternalDataSidecar` without `SidecarDataActor.publish_*()`;
  - empty registries are no-op.
- `tests/test_nautilus_strategy_base.py`
  - `evaluate_all_conditions()` clears stale tracking;
  - submitter is called exactly once per approved spec;
  - returned batch includes specs, rejects, and `PaperExecutionResult` objects.
- `tests/test_nautilus_orchestrator.py`
  - `run_once()` with active condition IDs evaluates strategy and does not call `paper_client.submit_spec()` outside the strategy submitter;
  - phase failure does not block later phases;
  - stop event ends `run()` without waiting full interval;
  - settlement receives `scheduler.ctx.markets.markets`.
- `tests/test_nautilus_node.py`
  - CLI assembly wires `MarketViewAssembler.books` to `NautilusBookDataProvider`;
  - SIGTERM handler calls the same stop path used by `orchestrator.run()`;
  - boundary tests still prove no forbidden Nautilus/Polymarket live symbols in default runtime.

Regression tests to run with new tests:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest \
  tests/test_nautilus_platform_boundary.py \
  tests/test_nautilus_runtime_config.py \
  tests/test_nautilus_node.py \
  tests/test_nautilus_cutover.py \
  tests/test_nautilus_execution.py \
  tests/test_nautilus_strategy_base.py \
  -v
```

---

## 8. Safety constraints

- Default runtime remains paper-safe and read-only.
- No `nautilus_trader` import at module load time in default runtime paths.
- No `PolymarketExecutionClient`, `PolymarketLiveExecClientFactory`, live `exec_clients`, allowance scripts, or API-key scripts.
- No reads of `POLYMARKET_PK`, `POLYMARKET_FUNDER`, `POLYMARKET_API_KEY`, `POLYMARKET_API_SECRET`, or `POLYMARKET_PASSPHRASE`.
- No second public-data stack for Gamma/CLOB/RTDS unless the existing scheduler services cannot be reused.
- No duplicate paper order submission.
- No cross-market runtime until a real relation source and `evaluate_group()` orchestration contract exist.

---

## 9. Files

Create:

- `src/polysignal_lab/nautilus_runtime/orchestrator.py`
- `src/polysignal_lab/nautilus_runtime/book_data.py`
- `src/polysignal_lab/nautilus_runtime/data_ingestor.py`
- `tests/test_nautilus_orchestrator.py`
- `tests/test_nautilus_book_data.py`
- `tests/test_nautilus_data_ingestor.py`

Modify:

- `src/polysignal_lab/nautilus_runtime/node.py`
- `src/polysignal_lab/nautilus_runtime/strategies/base.py`
- `src/polysignal_lab/nautilus_runtime/observability.py`
- `src/polysignal_lab/nautilus_runtime/__init__.py`
- `tests/test_nautilus_node.py`
- `tests/test_nautilus_strategy_base.py`

No changes expected:

- `pyproject.toml`
- `uv.lock`
- `Dockerfile`
- `config/signal_bot.yaml`

---

## 10. Acceptance criteria

The implementation is acceptable only when all are true:

1. `polysignal-nautilus` no longer sleeps without work; one `run_once()` refreshes/syncs/evaluates/observes.
2. At least one active market condition ID from `MarketRegistry.active()` reaches a Nautilus strategy wrapper in tests.
3. `MarketViewAssembler.books` is never `None` in the runtime bundle.
4. Paper order specs are submitted exactly once.
5. Position policy and settlement use current wallet and real domain market registry data.
6. SIGTERM/SIGINT exits through the orchestrator stop path.
7. Default boundary tests still pass: no forbidden Nautilus/Polymarket live execution imports or credentials in default runtime.
8. Official Nautilus docs remain cited in this spec with source URLs.
