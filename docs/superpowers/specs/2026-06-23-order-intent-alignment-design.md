# Order Intent Alignment — Design Spec

**Status:** Approved
**Date:** 2026-06-24

> **Goal:** Bring all 9 additional strategies into code-document alignment by adding
> `OrderIntent` semantics to the signal pipeline and extending the paper simulator
> to support passive GTD bids, FAK, FOK, and multi-leg coordination.

**Architecture:** The signal pipeline gains an `order_intent` field on
`SignalCandidate`. Gate checks become intent-aware (passive bids skip
`_max_entry`). `PaperSimulator` dispatches to intent-specific executors:
a `BestAskTakerExecutor` (existing behavior + FAK/FOK depth variants), a
`PassiveGtdExecutor` backed by a `RestingOrderStore`, and a
`MultiLegCoordinator` for paired fills. A `notify_fill` callback protocol
on `BaseStrategy` closes the broken state-feedback loop found in the
assessment.

**Tech Stack:** Python 3.12+, Pydantic v2, existing `PaperSimulator` /
`SignalGate` / `BaseStrategy` patterns.

## Global Constraints

- **Paper-only.** `allow_live_market_actions` stays `false`; no real order
  placement, cancel, or redeem is introduced. This design extends the paper
  simulation, not the live execution layer.
- **Core strategies unchanged.** `vwap_momentum`, `late_consensus`,
  `ptb_diff`, `skew_mean_reversion` continue as default taker behavior.
- **All existing tests keep passing.** New tests cover the new behavior;
  existing test files are not restructured.
- **Per-document intent mapping is authoritative.** The strategy-to-intent
  table in this spec governs what each strategy emits. If the document says
  FAK/FOK, the code emits FAK/FOK.
- **Multi-leg is non-atomic.** Paired orders are two independent
  executions. Partial-fill repair, leg timeout, and forced unwind follow
  the document's rules (section "Multi-leg strategies are not atomic on the
  CLOB").
- **No new dependencies.** All new modules use only existing standard
  library and installed packages (`pydantic`, `dataclasses`, `enum`).

---

## 1. New Domain Types

### 1.1 `OrderIntent` enum (`src/polysignal_lab/domain/enums.py`)

```python
class OrderIntent(StrEnum):
    PASSIVE_GTD = "passive_gtd"
    """Resting limit buy; fills when best bid <= limit price; expires at expiry_seconds."""
    TAKER_FAK = "taker_fak"
    """Fill-and-kill: immediate execution, partial fill ok, unexecuted portion cancelled."""
    TAKER_FOK = "taker_fok"
    """Fill-or-kill: all-or-nothing; rejects if depth insufficient for full size."""
    TAKER_IOC = "taker_ioc"
    """Immediate-or-cancel: execute immediately at best available; cancel remainder.
    Currently unused by strategies but available for future use."""
```

### 1.2 Updated `SignalCandidate` (`src/polysignal_lab/domain/signal.py`)

Add four optional fields. None required — absence = existing default-taker behavior.

```python
order_intent: OrderIntent | None = None
"""If None, treated as default marketable-limit taker."""
expiry_seconds: int | None = None
"""For PASSIVE_GTD only: seconds from signal creation until the resting order expires."""
pair_id: str | None = None
"""Multi-leg coordination key. All legs in the same pair share the same pair_id."""
hedge_leg: bool = False
"""True if this leg hedges a prior one-legged position (dump-hedge, low-side)."""
```

### 1.3 Updated `OrderStatus` (`src/polysignal_lab/domain/enums.py`)

```python
class OrderStatus(StrEnum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    RESTING = "RESTING"        # new: passive order resting on the simulated book
    CANCELLED = "CANCELLED"    # new: expired or explicitly cancelled
    PARTIAL = "PARTIAL"        # new: FAK partial fill (remainder killed)
```

---

## 2. Strategy Intent Map

Every strategy's `evaluate()` sets `order_intent` and optional fields on
`SignalCandidate` per this table. This table is the single source of truth;
strategy implementations MUST match it exactly.

| Strategy | `order_intent` | `expiry_seconds` | `pair_id` | `hedge_leg` |
|---|---|---|---|---|
| `one_cent_buy` | PASSIVE_GTD | from config expiry | no | no |
| `ninety_nine_cent_sniper` | TAKER_FOK | no | no | no |
| `low_side_dual_reversion` (initial) | PASSIVE_GTD | from config | `{market_id}:dual` | no (both legs are initial) |
| `low_side_dual_reversion` (hedge) | TAKER_FAK | no | `{market_id}:dual` | yes |
| `low_side_dual_reversion` (stop-loss) | TAKER_FAK | no | `{market_id}:dual` | yes |
| `pre_order_market` (initial) | PASSIVE_GTD | computed from open time | `{market_id}:pre` | no |
| `pre_order_market` (reconcile) | TAKER_FAK | no | `{market_id}:pre` | yes |
| `cross_market_bot` | TAKER_FOK | no | `{relation_id}` | no |
| `mid_price_sizing` (entry/add) | TAKER_FAK | no | no | no |
| `fibonacci_bot` | PASSIVE_GTD | 300s (or configurable) | no | no |
| `binary_momentum` | TAKER_FAK | no | no | no |
| `dump_hedge` (leg 1) | TAKER_FAK | no | `{market_id}:dump` | no |
| `dump_hedge` (leg 2 hedge) | TAKER_FOK | no | `{market_id}:dump` | yes |
| `dump_hedge` (leg 2 stop) | TAKER_FOK | no | `{market_id}:dump` | yes |

### 2.1 OneCentBuy detailed changes

Current `evaluate()` emits signals with `max_entry_price = entry_price`
(0.01-0.03). These are PASSIVE_GTD:

- Add `order_intent=OrderIntent.PASSIVE_GTD`
- Add `expiry_seconds = int(snapshot.seconds_to_close) - int(config.cancel_before_close_seconds)`
- Metric: include `order_type: "PASSIVE_GTD"` in `metrics`
- Already correctly skips ask-above-price (line 117: `best_ask <= price → continue`)
- Gate will now pass thanks to intent-aware `_max_entry`

### 2.2 NinetyNineCentSniper detailed changes

Current `evaluate()` emits near-resolution buy signals at high probability.

- Add `order_intent=OrderIntent.TAKER_FOK`
- Reason codes add `"FOK_EXECUTION"`
- No other changes — the existing gate logic already works for taker intent

### 2.3 LowSideDualReversion detailed changes

Current: emits UP/DOWN passive signals, has hedge/stop-loss logic in `_try_hedge`.

- Initial pair: `order_intent=OrderIntent.PASSIVE_GTD`, `pair_id=f"{market_id}:dual"`, `expiry_seconds=min(seconds_to_close - 60, 300)`
- Hedge (from `_try_hedge` plan A): `order_intent=OrderIntent.TAKER_FAK`, `pair_id=f"{market_id}:dual"`, `hedge_leg=True`
- Stop-loss (from `_try_hedge` plan B): `order_intent=OrderIntent.TAKER_FAK`, `pair_id=f"{market_id}:dual"`, `hedge_leg=True`
- Override `notify_fill` to update `self._positions[market_id]["hedged"] = True`

### 2.4 PreOrderMarket detailed changes

- Initial: `order_intent=OrderIntent.PASSIVE_GTD`, `pair_id=f"{market_id}:pre"`, `expiry_seconds=seconds_until_open + seconds_after_open_expiry`
- Reconcile hedge: `order_intent=OrderIntent.TAKER_FAK`, `pair_id=f"{market_id}:pre"`, `hedge_leg=True`
- Override `notify_fill` to update `self._positions[market_id]["hedged"] = True`

### 2.5 CrossMarketBot detailed changes

- Every leg: `order_intent=OrderIntent.TAKER_FOK`, `pair_id=relation_id`
- Override `notify_leg_failure` to mark basket as failed
- Override `notify_fill` to track per-leg fill state

### 2.6 MidPriceSizing detailed changes

- Initial entry and additions: `order_intent=OrderIntent.TAKER_FAK`
- Override `notify_fill` to update `self._layer_count` and `self._entry_prices`
- This closes the broken state loop — layers now increment on actual paper fills

### 2.7 FibonacciBot detailed changes

- Every signal: `order_intent=OrderIntent.PASSIVE_GTD`, `expiry_seconds=300`
- The strategy already uses `max_entry_price` near the fib level; gate will now pass

### 2.8 BinaryMomentum detailed changes

- Every signal: `order_intent=OrderIntent.TAKER_FAK`
- Existing reason codes and confidence unchanged

### 2.9 DumpHedge detailed changes

- Leg 1 detection: `order_intent=OrderIntent.TAKER_FAK`, `pair_id=f"{market_id}:dump"`
- Leg 2 hedge: `order_intent=OrderIntent.TAKER_FOK`, `pair_id=f"{market_id}:dump"`, `hedge_leg=True`
- Leg 2 stop: `order_intent=OrderIntent.TAKER_FOK`, `pair_id=f"{market_id}:dump"`, `hedge_leg=True`
- Override `notify_fill` for leg 1 to create `self._positions[market_id] = {side, filled_at}`
- Override `notify_fill` / `notify_leg_failure` for leg 2

---

## 3. Gate Changes (`src/polysignal_lab/signal_layer/gate.py`)

### 3.1 Intent-aware `_max_entry`

```python
def _max_entry(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> str | None:
    if candidate.order_intent == OrderIntent.PASSIVE_GTD:
        # Passive bids rest below the ask — this is intentional
        return None
    ask = snapshot.ask_for(candidate.side)
    if ask is None or ask > candidate.max_entry_price:
        return "ASK_ABOVE_MAX_ENTRY"
    return None
```

### 3.2 New `_gtd_expiry` check

```python
def _gtd_expiry(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> str | None:
    if candidate.order_intent != OrderIntent.PASSIVE_GTD:
        return None
    if candidate.expiry_seconds is None or candidate.expiry_seconds <= 0:
        return "MISSING_GTD_EXPIRY"
    if candidate.expiry_seconds > 86400:
        return "GTD_EXPIRY_EXCEEDS_24H"
    return None
```

Add `_gtd_expiry` to the check list in `evaluate()` (between `_max_entry` and `_confidence`).

### 3.3 Intent-aware `_spread`

```python
def _spread(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> str | None:
    if candidate.order_intent == OrderIntent.PASSIVE_GTD:
        # Wide spreads are expected for deep passive bids
        return None
    book = snapshot.book_for(candidate.side)
    max_spread = candidate.metrics.get("max_spread", 0.12)
    if book and book.spread is not None and book.spread <= max_spread:
        return None
    return "SPREAD_TOO_WIDE"
```

### 3.4 Intent-aware `_time_window`

Passive GTD orders should not be killed by `_time_window` when the order
is placed before the strategy's normal entry window:

```python
def _time_window(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> str | None:
    if candidate.order_intent == OrderIntent.PASSIVE_GTD and candidate.expiry_seconds is not None:
        # GTD orders have their own expiry; skip the entry window check
        return None
    if candidate.seconds_to_close is None or candidate.seconds_to_close <= 0:
        return "OUTSIDE_ENTRY_WINDOW"
    return None
```

---

## 4. Paper Simulator (`src/polysignal_lab/paper/`)

### 4.1 New module: `paper/order_intent_executor.py`

Three executor classes plus a coordination helper:

```python
@dataclass
class IntentDispatchResult:
    order: PaperOrder
    fills: list[PaperFill]  # empty if rejected/resting
    positions: list[PaperPosition]  # empty if rejected/resting
    status: OrderStatus  # FILLED | RESTING | CANCELLED | REJECTED | PARTIAL
    reject_reason: str | None = None

class BestAskTakerExecutor:
    """Handles default, TAKER_FAK, and TAKER_FOK."""
    def __init__(self, fill_model: FillModelConfig, max_book_staleness_ms: int): ...
    def execute(self, order: PaperOrder, book: OrderBook) -> IntentDispatchResult: ...

class PassiveGtdExecutor:
    """Manages a resting order store and polls for fills each scheduler tick."""
    def __init__(self): ...
    def enqueue(self, order: PaperOrder, signal: SignalCandidate) -> IntentDispatchResult: ...
    def tick(self, books: OrderBookRegistry, wallet: PaperWallet):
        """Called each scheduler tick. Matches resting bids against current best bid.
        Fills orders where best_bid <= limit_price. Expires orders past expiry_seconds.
        Yields (fill, position) tuples for filled/expired orders."""
        ...

class MultiLegCoordinator:
    """Tracks pair_id state across signal processing calls."""
    def register(self, signal: SignalCandidate): ...
    def check_pair_ready(self, pair_id: str) -> bool:
        """True when all legs of a pair have been seen (for FOK pairs)."""
        ...
    def any_leg_failed(self, pair_id: str) -> bool: ...
    def cancel_pair(self, pair_id: str) -> list[str]:
        """Return signal_ids to cancel."""
        ...
```

#### 4.1.1 FAK execution logic

```python
def _execute_fak(self, order: PaperOrder, book: OrderBook) -> IntentDispatchResult:
    if not book.asks or book.best_ask is None or book.best_ask > order.limit_price:
        return self._reject(order, "ASK_ABOVE_MAX_ENTRY")
    # Walk the book from best ask up to limit_price, accumulate shares
    remaining = order.stake_usdc
    fill_price = book.best_ask
    filled_usdc = 0.0
    for level in sorted(book.asks, key=lambda x: x.price):
        if level.price > order.limit_price:
            break
        available = level.price * level.size
        take = min(remaining, available)
        filled_usdc += take
        remaining -= take
        if remaining <= 0:
            break
    if filled_usdc <= 0:
        return self._reject(order, "FAK_NO_LIQUIDITY")
    fill_ratio = filled_usdc / order.stake_usdc
    shares = filled_usdc / fill_price
    fill = PaperFill(..., fill_ratio=fill_ratio, shares=shares, stake_usdc=filled_usdc)
    position = PaperPosition(...)
    status = OrderStatus.FILLED if fill_ratio >= 0.999 else OrderStatus.PARTIAL
    return IntentDispatchResult(order=order, fills=[fill], positions=[position], status=status)
```

#### 4.1.2 FOK execution logic

```python
def _execute_fok(self, order: PaperOrder, book: OrderBook) -> IntentDispatchResult:
    # Reject if depth insufficient for FULL fill
    available = book.depth_until(order.limit_price)
    if available < order.stake_usdc:
        return self._reject(order, "FOK_INSUFFICIENT_DEPTH")
    fill = PaperFill(..., fill_ratio=1.0, ...)
    position = PaperPosition(...)
    return IntentDispatchResult(order=order, fills=[fill], positions=[position], status=OrderStatus.FILLED)
```

#### 4.1.3 Passive GTD execution logic

```python
def enqueue(self, order: PaperOrder, signal: SignalCandidate) -> IntentDispatchResult:
    expiry_ts = signal.created_at.timestamp() + signal.expiry_seconds
    resting = RestingOrder(
        order=order,
        signal_id=signal.signal_id,
        limit_price=order.limit_price,
        expiry_ts=expiry_ts,
        pair_id=signal.pair_id,
    )
    self._store[order.token_id].append(resting)
    return IntentDispatchResult(order=order, status=OrderStatus.RESTING)

def tick(self, books: OrderBookRegistry, wallet: PaperWallet) -> list[IntentDispatchResult]:
    results = []
    now = time.time()
    for token_id, orders in list(self._store.items()):
        book = books.get(token_id)
        if book is None:
            continue
        surviving = []
        for resting in orders:
            if now >= resting.expiry_ts:
                # Expired: cancel
                results.append(self._cancel(resting, "GTD_EXPIRED"))
                continue
            if book.best_bid is not None and book.best_bid >= resting.limit_price:
                # Fill at resting price (simulated fill at limit)
                fill = PaperFill(
                    paper_order_id=resting.order.paper_order_id,
                    fill_price=resting.limit_price,
                    fill_ratio=1.0,
                    shares=resting.order.stake_usdc / resting.limit_price,
                    stake_usdc=resting.order.stake_usdc,
                    ...
                )
                position = PaperPosition(...)
                if wallet.can_afford(resting.order.stake_usdc):
                    wallet.apply_fill(position)
                    results.append(IntentDispatchResult(
                        order=resting.order, fills=[fill],
                        positions=[position], status=OrderStatus.FILLED
                    ))
                else:
                    results.append(self._cancel(resting, "WALLET_INSUFFICIENT_CASH"))
                continue
            surviving.append(resting)
        if surviving:
            self._store[token_id] = surviving
        else:
            del self._store[token_id]
    return results
```

### 4.2 Updated `PaperSimulator` (`src/polysignal_lab/paper/simulator.py`)

```python
class PaperSimulator:
    def __init__(self, config: PaperTradingConfig, data_config: PolymarketDataConfig, wallet: PaperWallet):
        self.config = config
        self.wallet = wallet
        self.fill_model = BestAskTakerFillModel(config.fill_model, data_config.max_book_staleness_ms)
        self.taker = BestAskTakerExecutor(config.fill_model, data_config.max_book_staleness_ms)
        self.passive = PassiveGtdExecutor()
        self.pair_coordinator = MultiLegCoordinator()

    # fill_notifier callback — set by scheduler after strategy init
    fill_notifier: Callable[[str, str], None] | None = None

    def process_signal(self, signal: SignalCandidate, orderbook: OrderBook | None) -> SimulationResult:
        order = self.build_paper_order(signal)
        rejection = self._paper_gate(order)
        if rejection:
            return self._reject(order, rejection)
        if orderbook is None:
            return self._reject(order, "MISSING_ORDERBOOK")

        intent = signal.order_intent

        if intent == OrderIntent.PASSIVE_GTD:
            result = self.passive.enqueue(order, signal)
            return self._to_simulation_result(result)

        if intent in (OrderIntent.TAKER_FAK, OrderIntent.TAKER_FOK):
            if signal.pair_id:
                self.pair_coordinator.register(signal)
                # For FOK pairs, check if all legs can fill
                if intent == OrderIntent.TAKER_FOK and not signal.hedge_leg:
                    # Leg 1 of a FOK pair: defer until the pair is complete
                    # In single-snapshot eval, pair legs arrive sequentially;
                    # we store the first leg and process on the second.
                    self.pair_coordinator.store_pending_leg(signal, order, orderbook)
                    return SimulationResult(order=order, status=OrderStatus.PENDING)
                elif signal.hedge_leg and intent == OrderIntent.TAKER_FOK:
                    # Hedge leg arrived: try to process the full pair
                    result = self.pair_coordinator.execute_fok_pair(
                        signal, order, orderbook, self.taker
                    )
                    if result is None:
                        return self.pair_coordinator.cancel_pair_result(signal.pair_id)
                    return self._to_simulation_result(result)

            # Standalone FAK/FOK
            result = self.taker.execute(order, orderbook, intent)
            return self._to_simulation_result(result)

        # Default: existing best-ask taker behavior (unchanged)
        decision = self.fill_model.fill(order, orderbook)
        ...
```

### 4.3 Scheduler tick integration (`src/polysignal_lab/app/scheduler_processing.py`)

Add a per-tick function called after signal evaluation:

```python
async def tick_resting_orders(scheduler: PolySignalScheduler) -> list[IntentDispatchResult]:
    """Poll resting GTD orders for fills/expiry each scheduler cycle."""
    return scheduler.paper.passive.tick(scheduler.ctx.books, scheduler.wallet)
```

Wire into the main loop in `scheduler_runtime.py`:

```python
async def run_loop(scheduler):
    ...
    await evaluate_once(scheduler)
    tick_results = await tick_resting_orders(scheduler)
    for result in tick_results:
        if result.fills:
            for fill in result.fills:
                _store_fill(scheduler, result.order, fill)
                if scheduler.paper.fill_notifier:
                    scheduler.paper.fill_notifier(result.order.signal_id, "filled")
        if result.status == OrderStatus.CANCELLED:
            if scheduler.paper.fill_notifier:
                scheduler.paper.fill_notifier(result.order.signal_id, "cancelled")
    ...
```

### 4.4 Fill notification to strategies

Scheduler wires the callback after strategy init:

```python
def _initialize_trading_components(self) -> None:
    ...
    self.strategies = build_strategies(self.settings.strategies)
    self.paper = PaperSimulator(...)
    # PaperOrder carries `strategy` and `market_id`; PaperFill carries price/shares
    self.paper.fill_notifier = _make_fill_notifier(self.strategies)

The `_make_fill_notifier` helper (module-level in `scheduler.py`):

```python
def _make_fill_notifier(strategies: list[BaseStrategy]) -> Callable[[PaperOrder, str, PaperFill | None], None]:
    def notify(order: PaperOrder, event: str, fill: PaperFill | None = None) -> None:
        for strat in strategies:
            if strat.name != order.strategy:
                continue
            if event == "filled" and fill is not None:
                strat.notify_fill(order.market_id, order.side, fill.fill_price, fill.shares)
            elif event == "cancelled":
                strat.notify_cancel(order.market_id, order.side, order.reject_reason or "GTD_EXPIRED")
    return notify
```

---

## 5. Strategy `BaseStrategy` Protocol (`src/polysignal_lab/strategies/base.py`)

Add three optional-override methods:

```python
class BaseStrategy(ABC):
    name: str

    @abstractmethod
    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalCandidate]: ...

    def notify_fill(self, market_id: str, side: Side, fill_price: float, shares: float) -> None:
        """Called when a paper fill occurs for this strategy.
        Strategies with state tracking override to update internal dictionaries."""
        pass

    def notify_cancel(self, market_id: str, side: Side, reason: str) -> None:
        """Called when a resting order expires or is explicitly cancelled."""
        pass

    def notify_leg_failure(self, pair_id: str, market_id: str, side: Side) -> None:
        """Called when a multi-leg pair has a leg that failed to fill."""
        pass
```

### 5.1 Strategy-specific overrides

- **LowSideDualReversion**: `notify_fill` sets `self._positions[market_id]["hedged"] = True` and `self._entered_markets.add(market_id)`
- **PreOrderMarket**: `notify_fill` for first leg stores `self._positions[market_id] = {...}`; for second leg marks `hedged = True`
- **DumpHedge**: `notify_fill` for leg 1 creates `self._positions[market_id]`; for leg 2 marks `hedged = True`. `notify_leg_failure` cleans up.
- **MidPriceSizing**: `notify_fill` increments `self._layer_count[key]` and appends to `self._entry_prices[key]`
- **CrossMarketBot**: `notify_fill` tracks per-leg fills in `self._active_baskets[relation_id]`; `notify_leg_failure` marks basket failed

---

## 6. File Map

| File | Action | What Changes |
|---|---|---|
| `domain/enums.py` | Modify | Add `OrderIntent`, new `OrderStatus` values |
| `domain/signal.py` | Modify | Add `order_intent`, `expiry_seconds`, `pair_id`, `hedge_leg` |
| `domain/paper_order.py` | Modify | Add `order_intent` field |
| `signal_layer/gate.py` | Modify | Intent-aware checks, `_gtd_expiry` gate |
| `paper/order_intent_executor.py` | Create | `BestAskTakerExecutor`, `PassiveGtdExecutor`, `MultiLegCoordinator`, `RestingOrder` dataclass |
| `paper/simulator.py` | Modify | Dispatch by intent, inject `fill_notifier`, wire `RestingOrderStore.tick()` |
| `strategies/base.py` | Modify | Add `notify_fill`, `notify_cancel`, `notify_leg_failure` |
| `strategies/one_cent_buy.py` | Modify | Set PASSIVE_GTD, expiry, reason codes |
| `strategies/ninety_nine_cent_sniper.py` | Modify | Set TAKER_FOK |
| `strategies/low_side_dual_reversion.py` | Modify | Set PASSIVE_GTD/TAKER_FAK, pair_id, hedge_leg, notify_fill override |
| `strategies/pre_order_market.py` | Modify | Set PASSIVE_GTD/TAKER_FAK, pair_id, hedge_leg, notify_fill override |
| `strategies/cross_market_bot.py` | Modify | Set TAKER_FOK, pair_id, notify_fill/notify_leg_failure overrides |
| `strategies/mid_price_sizing.py` | Modify | Set TAKER_FAK, notify_fill override |
| `strategies/fibonacci_bot.py` | Modify | Set PASSIVE_GTD, expiry |
| `strategies/binary_momentum.py` | Modify | Set TAKER_FAK |
| `strategies/dump_hedge.py` | Modify | Set TAKER_FAK/TAKER_FOK, pair_id, hedge_leg, notify_fill override |
| `app/scheduler_processing.py` | Modify | Add `tick_resting_orders()`, wire fill notifier callbacks |
| `app/scheduler_runtime.py` | Modify | Call `tick_resting_orders()` in main loop |
| `tests/test_order_intent.py` | Create | Gate + executor unit tests for each intent |
| `tests/test_strategies.py` | Modify | Intent-check tests for all 9 strategies |
| `tests/test_resting_orders.py` | Create | GTD enqueue, fill, expiry unit tests |

---

## 7. Testing Plan

### 7.1 `tests/test_order_intent.py` (new)

| Test | What it verifies |
|---|---|
| `test_passive_gtd_skips_max_entry_check` | Gate accepts PASSIVE_GTD signal even when ask > max_entry |
| `test_passive_gtd_skips_spread_check` | Wide spreads don't reject passive signals |
| `test_passive_gtd_rejects_missing_expiry` | Gate rejects PASSIVE_GTD without `expiry_seconds` |
| `test_fak_partial_fill` | FAK accepts partial fill, returns PARTIAL status |
| `test_fak_rejects_no_liquidity` | FAK rejects when zero depth at limit |
| `test_fok_all_or_nothing` | FOK rejects when depth < stake; fills when depth >= stake |
| `test_default_taker_unchanged` | Signals without order_intent use existing best-ask taker path |
| `test_pair_coordinator_fok_both_legs` | Two FOK legs with same pair_id: both fill or both cancel |
| `test_gtd_enqueue_and_tick_fill` | PassiveGtdExecutor enqueues order; tick with best_bid >= limit fills it |
| `test_gtd_expiry` | PassiveGtdExecutor expires order past expiry_ts |

### 7.2 `tests/test_strategies.py` (modified)

| Test | What it verifies |
|---|---|
| `test_one_cent_buy_emits_passive_gtd` | Every signal from OneCentBuy has `order_intent=PASSIVE_GTD` and `expiry_seconds` |
| `test_ninety_nine_sniper_emits_fok` | Signals from NinetyNineCentSniper have `order_intent=TAKER_FOK` |
| `test_low_side_dual_emits_passive_with_pair_id` | Initial pair signals have PASSIVE_GTD + shared pair_id |
| `test_dump_hedge_emits_fak_then_fok` | Leg1 = TAKER_FAK, leg2 signals = TAKER_FOK + hedge_leg=True |
| `test_pre_order_emits_passive_gtd_with_expiry` | Signals have PASSIVE_GTD + expiry computed from market start |
| `test_binary_momentum_emits_fak` | All signals have TAKER_FAK |
| `test_fibonacci_emits_passive_gtd` | All signals have PASSIVE_GTD + expiry_seconds |
| `test_mid_price_sizing_emits_fak` | All signals have TAKER_FAK |
| `test_mid_price_sizing_notify_fill_updates_layers` | `notify_fill` increments layer count |
| `test_cross_market_emits_fok_with_relation_pair_id` | Signals carry TAKER_FOK + relation-based pair_id |

### 7.3 `tests/test_resting_orders.py` (new)

| Test | What it verifies |
|---|---|
| `test_enqueue_returns_resting_status` | Enqueued GTD returns RESTING, no fill |
| `test_tick_fills_when_bid_matches` | Best bid at or above limit fills the resting order |
| `test_tick_does_not_fill_when_bid_below_limit` | Best bid below limit keeps order resting |
| `test_tick_expires_past_expiry` | Past-expiry orders produce CANCELLED status |
| `test_tick_rejects_when_wallet_insufficient` | Wallet can't afford → CANCELLED with reason |
| `test_tick_multiple_orders_same_token` | Multiple resting orders on same token handle correctly |

### 7.4 Regression

All existing tests in `tests/` must pass unchanged. Core strategies
(`vwap_momentum`, `late_consensus`, `ptb_diff`, `skew_mean_reversion`) do
not set `order_intent`, so their signal flow is identical.

---

## 8. Out of Scope (explicitly deferred)

- Tick-size normalization and `tick_size_change` WS handling
- Neg-risk / multi-outcome market support
- Historical replay engine for GTD/FAK/FOK
- Live order execution (secured by existing safety layer)
- Global `cancel_all()` kill switch in paper mode
- Cross-market actual multi-snapshot synchronization (strategy already flags this as future work)
- Strategy-to-order-type mapping for `config/signal_bot.yaml` — defaults remain, explicit config deferred

---

## 9. Migration Notes

- `PaperOrder.order_type` changes from `"SIMULATED_MARKETABLE_LIMIT"` to reflect the actual intent (e.g., `"PASSIVE_GTD"`, `"TAKER_FAK"`).
- Existing SQLite schema: `paper_orders` table stores `order_type` as TEXT — no schema migration needed, just new string values.
- `SimulationResult` gains `status: OrderStatus = FILLED` field (default preserves existing behavior).
- Strategies that had broken `_positions` state (`low_side_dual_reversion`, `dump_hedge`, `pre_order_market`, `mid_price_sizing`) now receive state updates via `notify_fill`. Their `evaluate()` methods should check real state rather than assuming fills.
- `config/signal_bot.yaml` at `paper_trading.fill_model`: the existing `fill_model.slippage_bps` applies to FAK fills; FOK and GTD use their own execution logic (FOK = depth check, GTD = limit match).
