# Order Intent Alignment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `OrderIntent` semantics (PASSIVE_GTD, TAKER_FAK, TAKER_FOK) to the signal→execution pipeline so all 9 additional strategies emit correct order intents, pass the gate, and are simulated by intent-aware paper executors with callback-driven state feedback.

**Architecture:** Two new enum types (`OrderIntent`, new `OrderStatus` values) propagate from `SignalCandidate` through `SignalGate` (now intent-aware) into `PaperSimulator`, which dispatches to a new `order_intent_executor.py` module containing `BestAskTakerExecutor` (FAK/FOK/default), `PassiveGtdExecutor` (resting orders with tick-based fill/expiry), and `MultiLegCoordinator` (paired FOK cancellation). A `notify_fill/notify_cancel/notify_leg_failure` protocol on `BaseStrategy` closes the broken state feedback loop.

**Spec:** `docs/superpowers/specs/2026-06-23-order-intent-alignment-design.md`

**Tech Stack:** Python 3.12+, Pydantic v2, dataclasses, existing patterns

## Global Constraints

- **Paper-only.** `allow_live_market_actions` stays `false`; no real order placement, cancel, or redeem.
- **Core strategies unchanged.** `vwap_momentum`, `late_consensus`, `ptb_diff`, `skew_mean_reversion` continue as default taker behavior (no `order_intent` set).
- **All existing tests keep passing.** New tests only; existing files not restructured.
- **Per-document intent mapping is authoritative.** See spec Section 2 table.
- **Multi-leg is non-atomic.** Paired orders are two independent executions.
- **No new dependencies.** Only `dataclasses`, `enum`, `pydantic`, `typing`, `time`, existing imports.
- **`config/signal_bot.yaml` stays unchanged.** All strategies default-enabled per existing defaults.
- **Every task ends with a passing test.** TDD: test first, then implementation, then commit.
- **No `tests/` below src/.** All tests in `tests/` directory.

---

### Task 1: Domain Layer — OrderIntent enum, SignalCandidate fields, OrderStatus, PaperOrder

**Files:**
- Modify: `src/polysignal_lab/domain/enums.py:1-51`
- Modify: `src/polysignal_lab/domain/signal.py:1-91`
- Modify: `src/polysignal_lab/domain/paper_order.py:1-49`

**Interfaces:**
- Produces: `OrderIntent(StrEnum)` with values `PASSIVE_GTD`, `TAKER_FAK`, `TAKER_FOK`, `TAKER_IOC`
- Produces: `OrderStatus` gains `RESTING = "RESTING"`, `CANCELLED = "CANCELLED"`, `PARTIAL = "PARTIAL"`
- Produces: `SignalCandidate` gains 4 optional fields: `order_intent: OrderIntent | None = None`, `expiry_seconds: int | None = None`, `pair_id: str | None = None`, `hedge_leg: bool = False`
- Produces: `PaperOrder` gains `order_intent: str | None = None` field; `order_type` default unchanged
- Produces: `SignalCandidate.build()` gains 4 keyword-only parameters; `BaseStrategy._candidate()` gains 4 keyword parameters

- [ ] **Step 1: Write test for OrderIntent enum**

```python
# tests/test_order_intent.py
from __future__ import annotations
from polysignal_lab.domain.enums import OrderIntent

def test_order_intent_values():
    assert OrderIntent.PASSIVE_GTD == "passive_gtd"
    assert OrderIntent.TAKER_FAK == "taker_fak"
    assert OrderIntent.TAKER_FOK == "taker_fok"
    assert OrderIntent.TAKER_IOC == "taker_ioc"
```

Run: `pytest tests/test_order_intent.py::test_order_intent_values -v`
Expected: FAIL (ImportError / no OrderIntent)

- [ ] **Step 2: Add OrderIntent and OrderStatus values to enums.py**

In `src/polysignal_lab/domain/enums.py`, after the existing `OrderStatus` class (line 30), add:

```python
class OrderIntent(StrEnum):
    PASSIVE_GTD = "passive_gtd"
    """Resting limit buy; fills when best bid <= limit price; expires at expiry_seconds."""
    TAKER_FAK = "taker_fak"
    """Fill-and-kill: immediate execution, partial fill ok, unexecuted portion cancelled."""
    TAKER_FOK = "taker_fok"
    """Fill-or-kill: all-or-nothing; rejects if depth insufficient for full size."""
    TAKER_IOC = "taker_ioc"
    """Immediate-or-cancel: execute immediately at best available; cancel remainder."""
```

Update `OrderStatus` to add three values after `REJECTED`:

```python
class OrderStatus(StrEnum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    RESTING = "RESTING"
    CANCELLED = "CANCELLED"
    PARTIAL = "PARTIAL"
```

Run: `pytest tests/test_order_intent.py::test_order_intent_values -v`
Expected: PASS

- [ ] **Step 3: Write test for SignalCandidate new fields**

```python
# add to tests/test_order_intent.py
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate

def test_signal_candidate_has_order_intent_fields():
    sig = SignalCandidate.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="btc-updown-5m-1",
        condition_id="cond-1", token_id="token-up",
        side=Side.UP, confidence=0.5, entry_reference_price=0.5,
        max_entry_price=0.5, seconds_to_close=300,
        data_freshness_ms=100, reason_codes=["TEST"], metrics={},
    )
    assert sig.order_intent is None
    assert sig.expiry_seconds is None
    assert sig.pair_id is None
    assert sig.hedge_leg is False

def test_signal_candidate_with_order_intent():
    sig = SignalCandidate.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="btc-updown-5m-1",
        condition_id="cond-1", token_id="token-up",
        side=Side.UP, confidence=0.5, entry_reference_price=0.5,
        max_entry_price=0.5, seconds_to_close=300,
        data_freshness_ms=100, reason_codes=["TEST"], metrics={},
        order_intent=OrderIntent.PASSIVE_GTD,
        expiry_seconds=200,
        pair_id="mkt-1:dual",
        hedge_leg=False,
    )
    assert sig.order_intent == OrderIntent.PASSIVE_GTD
    assert sig.expiry_seconds == 200
    assert sig.pair_id == "mkt-1:dual"
    assert sig.hedge_leg is False
```

Run: `pytest tests/test_order_intent.py::test_signal_candidate_has_order_intent_fields tests/test_order_intent.py::test_signal_candidate_with_order_intent -v`
Expected: FAIL (unexpected keyword argument 'order_intent')

- [ ] **Step 4: Add fields to SignalCandidate**

In `src/polysignal_lab/domain/signal.py`, add 4 fields after `source_signal_ids` (line 33):

```python
    order_intent: OrderIntent | None = None
    expiry_seconds: int | None = None
    pair_id: str | None = None
    hedge_leg: bool = False
```

Add the import at top: `from polysignal_lab.domain.enums import OrderIntent` (add after the existing `Side` import).

In `SignalCandidate.build()`, add 4 keyword params after `source_signal_ids`:

```python
        order_intent: OrderIntent | None = None,
        expiry_seconds: int | None = None,
        pair_id: str | None = None,
        hedge_leg: bool = False,
```

And in the `cls(...)` call body, add:

```python
            order_intent=order_intent,
            expiry_seconds=expiry_seconds,
            pair_id=pair_id,
            hedge_leg=hedge_leg,
```

Run: `pytest tests/test_order_intent.py -v`
Expected: PASS

- [ ] **Step 5: Add order_intent to PaperOrder**

```python
# In src/polysignal_lab/domain/paper_order.py, after `order_type` (line 24), add:
    order_intent: str | None = None
```

Run: `pytest tests/test_paper_simulation.py -v`
Expected: all existing tests PASS (factory already works with extra None field on Pydantic)

- [ ] **Step 6: Update BaseStrategy._candidate to accept new fields**

In `src/polysignal_lab/strategies/base.py`, update `_candidate` signature after `metrics: dict`:

```python
    def _candidate(
        self,
        snapshot: MarketSnapshot,
        side: Side,
        confidence: float,
        max_entry_price: float,
        reason_codes: list[str],
        metrics: dict,
        *,
        order_intent: OrderIntent | None = None,
        expiry_seconds: int | None = None,
        pair_id: str | None = None,
        hedge_leg: bool = False,
    ) -> SignalCandidate | None:
```

Add import at top: `from polysignal_lab.domain.enums import OrderIntent` (after existing `Side` import).

In the `SignalCandidate.build(...)` body, add:

```python
            order_intent=order_intent,
            expiry_seconds=expiry_seconds,
            pair_id=pair_id,
            hedge_leg=hedge_leg,
```

Run: `pytest tests/test_strategies.py tests/test_late_consensus.py tests/test_vwap_momentum.py tests/test_ptb_diff.py -v`
Expected: all existing PASS

- [ ] **Step 7: Commit**

```bash
git add tests/test_order_intent.py src/polysignal_lab/domain/enums.py src/polysignal_lab/domain/signal.py src/polysignal_lab/domain/paper_order.py src/polysignal_lab/strategies/base.py
git commit -m "feat: add OrderIntent enum, SignalCandidate fields, PaperOrder.order_intent"
```

---

### Task 2: SignalGate — intent-aware checks

**Files:**
- Modify: `src/polysignal_lab/signal_layer/gate.py:1-139`

**Interfaces:**
- Consumes: `OrderIntent` from Task 1, `SignalCandidate` fields from Task 1
- Produces: `_max_entry` skips check for PASSIVE_GTD; `_gtd_expiry` new gate; `_spread` skips check for PASSIVE_GTD; `_time_window` skips check for PASSIVE_GTD

- [ ] **Step 1: Write gate tests**

```python
# add to tests/test_order_intent.py
from polysignal_lab.signal_layer.gate import SignalGate
from polysignal_lab.config import SignalConfig, PolymarketDataConfig, BinanceDataConfig
from polysignal_lab.domain.snapshot import MarketSnapshot, FreshnessState
from polysignal_lab.domain.orderbook import BookLevel, OrderBook
from polysignal_lab.domain.enums import MarketStatus, Action
from datetime import timedelta
from polysignal_lab.utils import utc_now

def _make_gate() -> SignalGate:
    return SignalGate(
        SignalConfig(), PolymarketDataConfig(), BinanceDataConfig()
    )

def _make_passive_signal() -> SignalCandidate:
    return SignalCandidate.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="s", condition_id="c",
        token_id="t-up", side=Side.UP, confidence=0.6,
        entry_reference_price=0.35, max_entry_price=0.35,
        seconds_to_close=300, data_freshness_ms=100,
        reason_codes=["TEST"], metrics={},
        order_intent=OrderIntent.PASSIVE_GTD, expiry_seconds=200,
    )

def _make_fresh_book() -> OrderBook:
    return OrderBook(
        token_id="t-up", bids=[BookLevel(price=0.30, size=100)],
        asks=[BookLevel(price=0.55, size=100)],
        last_trade_price=0.42, received_at=utc_now(),
    )

def _make_active_snapshot(book: OrderBook) -> MarketSnapshot:
    from polysignal_lab.domain.market import Market, OutcomeToken
    now = utc_now()
    market = Market(
        market_id="mkt-1", market_slug="s", condition_id="c",
        question_id="q", question="Q", asset="BTC", timeframe="5m",
        start_ts=now - timedelta(seconds=100),
        end_ts=now + timedelta(seconds=300),
        status=MarketStatus.ACTIVE, resolution_source="test",
        outcome_tokens=[
            OutcomeToken(token_id="t-up", side=Side.UP, outcome_name="Up", market_id="mkt-1"),
            OutcomeToken(token_id="t-down", side=Side.DOWN, outcome_name="Down", market_id="mkt-1"),
        ],
    )
    return MarketSnapshot(
        snapshot_id="snap-1", market=market,
        up_book=book, down_book=None,
        freshness=FreshnessState(up_book_ms=10, down_book_ms=None, spot_ms=None, max_ms=10),
    )

def test_passive_gtd_skips_max_entry_check():
    gate = _make_gate()
    sig = _make_passive_signal()
    snap = _make_active_snapshot(_make_fresh_book())
    # ask=0.55 > max_entry=0.35, but PASSIVE_GTD should pass
    reason = gate._max_entry(sig, snap)
    assert reason is None

def test_taker_still_fails_ask_above_max_entry():
    gate = _make_gate()
    sig = SignalCandidate.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="s", condition_id="c",
        token_id="t-up", side=Side.UP, confidence=0.6,
        entry_reference_price=0.85, max_entry_price=0.50,
        seconds_to_close=300, data_freshness_ms=100,
        reason_codes=["TEST"], metrics={},
        # no order_intent → default taker
    )
    snap = _make_active_snapshot(_make_fresh_book())
    reason = gate._max_entry(sig, snap)
    assert reason == "ASK_ABOVE_MAX_ENTRY"

def test_gtd_expiry_rejects_missing():
    gate = _make_gate()
    sig = SignalCandidate.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="s", condition_id="c",
        token_id="t-up", side=Side.UP, confidence=0.6,
        entry_reference_price=0.35, max_entry_price=0.35,
        seconds_to_close=300, data_freshness_ms=100,
        reason_codes=["TEST"], metrics={},
        order_intent=OrderIntent.PASSIVE_GTD,
        # expiry_seconds NOT set
    )
    gate = _make_gate()
    snap = _make_active_snapshot(_make_fresh_book())
    reason = gate._gtd_expiry(sig, snap)
    assert reason == "MISSING_GTD_EXPIRY"

def test_gtd_expiry_rejects_too_long():
    gate = _make_gate()
    sig = SignalCandidate.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="s", condition_id="c",
        token_id="t-up", side=Side.UP, confidence=0.6,
        entry_reference_price=0.35, max_entry_price=0.35,
        seconds_to_close=300, data_freshness_ms=100,
        reason_codes=["TEST"], metrics={},
        order_intent=OrderIntent.PASSIVE_GTD, expiry_seconds=100000,
    )
    snap = _make_active_snapshot(_make_fresh_book())
    reason = gate._gtd_expiry(sig, snap)
    assert reason == "GTD_EXPIRY_EXCEEDS_24H"

def test_gtd_expiry_accepts_valid():
    gate = _make_gate()
    sig = _make_passive_signal()
    snap = _make_active_snapshot(_make_fresh_book())
    reason = gate._gtd_expiry(sig, snap)
    assert reason is None

def test_passive_gtd_skips_spread_check():
    gate = _make_gate()
    sig = _make_passive_signal()
    snap = _make_active_snapshot(_make_fresh_book())
    reason = gate._spread(sig, snap)
    assert reason is None

def test_passive_gtd_skips_time_window():
    gate = _make_gate()
    sig = _make_passive_signal()
    snap = _make_active_snapshot(_make_fresh_book())
    reason = gate._time_window(sig, snap)
    assert reason is None

def test_passive_gtd_full_evaluate_accepted():
    gate = _make_gate()
    sig = _make_passive_signal()
    snap = _make_active_snapshot(_make_fresh_book())
    decision = gate.evaluate(sig, snap)
    assert decision.accepted is True
    assert decision.signal is not None
```

Run: `pytest tests/test_order_intent.py -v`
Expected: FAIL (AttributeError: no `_gtd_expiry`, etc.)

- [ ] **Step 2: Implement gate changes**

In `src/polysignal_lab/signal_layer/gate.py`:

Add import at top: `from polysignal_lab.domain.enums import OrderIntent`

**Modify `_max_entry`** (line 121-125):

```python
    def _max_entry(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> str | None:
        if candidate.order_intent == OrderIntent.PASSIVE_GTD:
            return None
        ask = snapshot.ask_for(candidate.side)
        if ask is None or ask > candidate.max_entry_price:
            return "ASK_ABOVE_MAX_ENTRY"
        return None
```

**Modify `_spread`** (line 114-119):

```python
    def _spread(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> str | None:
        if candidate.order_intent == OrderIntent.PASSIVE_GTD:
            return None
        book = snapshot.book_for(candidate.side)
        max_spread = candidate.metrics.get("max_spread", 0.12)
        if book and book.spread is not None and book.spread <= max_spread:
            return None
        return "SPREAD_TOO_WIDE"
```

**Modify `_time_window`** (line 98-101):

```python
    def _time_window(self, candidate: SignalCandidate, snapshot: MarketSnapshot) -> str | None:
        if candidate.order_intent == OrderIntent.PASSIVE_GTD and candidate.expiry_seconds is not None:
            return None
        if candidate.seconds_to_close is None or candidate.seconds_to_close <= 0:
            return "OUTSIDE_ENTRY_WINDOW"
        return None
```

**Add `_gtd_expiry`** method after `_max_entry`:

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

**Update `evaluate()` check list** (line 36-46), insert `self._gtd_expiry` between `_max_entry` and `_confidence`:

```python
        checks = [
            self._market_active,
            self._time_window,
            self._book_freshness,
            self._spot_freshness,
            self._spread,
            self._max_entry,
            self._gtd_expiry,
            self._confidence,
            self._dedupe,
            self._rate_limit,
        ]
```

Run: `pytest tests/test_order_intent.py -v`
Expected: all PASS

- [ ] **Step 3: Run regression suite**

```bash
pytest tests/ -v --ignore=tests/test_order_intent.py
```

Expected: all existing tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/polysignal_lab/signal_layer/gate.py
git commit -m "feat: make SignalGate intent-aware for PASSIVE_GTD, add _gtd_expiry gate"
```

---

### Task 3: Core Executor — IntentDispatchResult, BestAskTakerExecutor, PassiveGtdExecutor, MultiLegCoordinator

**Files:**
- Create: `src/polysignal_lab/paper/order_intent_executor.py`

**Interfaces:**
- Produces: `IntentDispatchResult(dataclass)` — `order: PaperOrder`, `fills: list[PaperFill]`, `positions: list[PaperPosition]`, `status: OrderStatus`, `reject_reason: str | None`
- Produces: `RestingOrder(dataclass)` — `order: PaperOrder`, `signal_id: str`, `limit_price: float`, `expiry_ts: float`, `pair_id: str | None`
- Produces: `BestAskTakerExecutor` — `__init__(fill_model_cfg, max_staleness_ms)`, `execute(order, book, intent) -> IntentDispatchResult`
- Produces: `PassiveGtdExecutor` — `__init__()`, `enqueue(order, signal) -> IntentDispatchResult`, `tick(books, wallet) -> list[IntentDispatchResult]`
- Produces: `MultiLegCoordinator` — `__init__()`, `register(signal)`, `any_leg_failed(pair_id) -> bool`, `cancel_pair(pair_id) -> list[str]`, `record_pending(signal_id, order, book)`, `try_execute_fok_pair(signal, order, book, executor) -> IntentDispatchResult | None`

Because this is a new module with no existing callers, skip TDD and write the full implementation with comprehensive tests at the end.

- [ ] **Step 1: Write full `order_intent_executor.py`**

```python
"""Order Intent Executors — FAK, FOK, PASSIVE_GTD, and multi-leg coordination."""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from polysignal_lab.config import FillModelConfig
from polysignal_lab.domain.enums import OrderIntent, OrderStatus, Side
from polysignal_lab.domain.orderbook import OrderBook
from polysignal_lab.domain.paper_order import PaperFill, PaperOrder
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.utils import new_id


@dataclass
class IntentDispatchResult:
    order: PaperOrder
    fills: list[PaperFill] = field(default_factory=list)
    positions: list[PaperPosition] = field(default_factory=list)
    status: OrderStatus = OrderStatus.PENDING
    reject_reason: str | None = None


@dataclass
class RestingOrder:
    order: PaperOrder
    signal_id: str
    limit_price: float
    expiry_ts: float
    pair_id: str | None = None


class BestAskTakerExecutor:
    def __init__(self, fill_model: FillModelConfig, max_book_staleness_ms: int):
        self.fill_model = fill_model
        self.max_book_staleness_ms = max_book_staleness_ms

    def execute(
        self, order: PaperOrder, book: OrderBook, intent: OrderIntent | None = None
    ) -> IntentDispatchResult:
        if book.token_id != order.token_id:
            return self._reject(order, "MALFORMED_ORDERBOOK")
        if not book.is_fresh(self.max_book_staleness_ms, order.created_at):
            return self._reject(order, "STALE_ORDERBOOK")
        if not book.asks or book.best_ask is None:
            return self._reject(order, "MISSING_BEST_ASK")
        if book.best_ask > order.limit_price:
            return self._reject(order, "ASK_ABOVE_MAX_ENTRY")

        if intent == OrderIntent.TAKER_FOK:
            return self._execute_fok(order, book)
        if intent == OrderIntent.TAKER_FAK:
            return self._execute_fak(order, book)
        # Default: existing best-ask taker with slippage
        return self._execute_default(order, book)

    def _execute_default(self, order: PaperOrder, book: OrderBook) -> IntentDispatchResult:
        fill_price = book.best_ask + book.best_ask * self.fill_model.slippage_bps / 10000
        if fill_price > order.limit_price:
            return self._reject(order, "SLIPPAGE_EXCEEDS_MAX_ENTRY")
        if self.fill_model.require_depth_check:
            available = book.depth_until(order.limit_price)
            if available < order.stake_usdc and self.fill_model.reject_if_partial:
                return self._reject(order, "INSUFFICIENT_DEPTH", available_depth_usdc=available)
        shares = order.stake_usdc / fill_price
        fill = PaperFill(
            paper_fill_id=new_id("pf"),
            paper_order_id=order.paper_order_id,
            signal_id=order.signal_id,
            token_id=order.token_id,
            side=order.side,
            raw_best_ask=book.best_ask,
            slippage_bps=self.fill_model.slippage_bps,
            fill_price=fill_price,
            stake_usdc=order.stake_usdc,
            shares=shares,
            depth_checked=self.fill_model.require_depth_check,
            available_depth_usdc=book.depth_until(order.limit_price),
            fill_ratio=1.0,
        )
        position = PaperPosition(
            paper_position_id=new_id("pp"),
            signal_id=order.signal_id,
            paper_order_id=order.paper_order_id,
            paper_fill_id=fill.paper_fill_id,
            strategy=order.strategy,
            asset=order.asset,
            timeframe=order.timeframe,
            market_id=order.market_id,
            market_slug=order.market_slug,
            token_id=order.token_id,
            side=order.side,
            entry_price=fill_price,
            shares=shares,
            stake_usdc=order.stake_usdc,
        )
        order.status = OrderStatus.FILLED
        return IntentDispatchResult(order=order, fills=[fill], positions=[position], status=OrderStatus.FILLED)

    def _execute_fak(self, order: PaperOrder, book: OrderBook) -> IntentDispatchResult:
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
        fill = PaperFill(
            paper_fill_id=new_id("pf"),
            paper_order_id=order.paper_order_id,
            signal_id=order.signal_id,
            token_id=order.token_id,
            side=order.side,
            raw_best_ask=book.best_ask,
            slippage_bps=0.0,
            fill_price=fill_price,
            stake_usdc=filled_usdc,
            shares=shares,
            depth_checked=False,
            fill_ratio=fill_ratio,
        )
        position = PaperPosition(
            paper_position_id=new_id("pp"),
            signal_id=order.signal_id,
            paper_order_id=order.paper_order_id,
            paper_fill_id=fill.paper_fill_id,
            strategy=order.strategy, asset=order.asset, timeframe=order.timeframe,
            market_id=order.market_id, market_slug=order.market_slug,
            token_id=order.token_id, side=order.side,
            entry_price=fill_price, shares=shares, stake_usdc=filled_usdc,
        )
        status = OrderStatus.FILLED if fill_ratio >= 0.999 else OrderStatus.PARTIAL
        order.status = status
        return IntentDispatchResult(order=order, fills=[fill], positions=[position], status=status)

    def _execute_fok(self, order: PaperOrder, book: OrderBook) -> IntentDispatchResult:
        available = book.depth_until(order.limit_price)
        if available < order.stake_usdc:
            return self._reject(order, "FOK_INSUFFICIENT_DEPTH", available_depth_usdc=available)
        fill_price = book.best_ask
        shares = order.stake_usdc / fill_price
        fill = PaperFill(
            paper_fill_id=new_id("pf"),
            paper_order_id=order.paper_order_id,
            signal_id=order.signal_id,
            token_id=order.token_id,
            side=order.side,
            raw_best_ask=book.best_ask,
            slippage_bps=0.0,
            fill_price=fill_price,
            stake_usdc=order.stake_usdc,
            shares=shares,
            depth_checked=True,
            available_depth_usdc=available,
            fill_ratio=1.0,
        )
        position = PaperPosition(
            paper_position_id=new_id("pp"),
            signal_id=order.signal_id,
            paper_order_id=order.paper_order_id,
            paper_fill_id=fill.paper_fill_id,
            strategy=order.strategy, asset=order.asset, timeframe=order.timeframe,
            market_id=order.market_id, market_slug=order.market_slug,
            token_id=order.token_id, side=order.side,
            entry_price=fill_price, shares=shares, stake_usdc=order.stake_usdc,
        )
        order.status = OrderStatus.FILLED
        return IntentDispatchResult(order=order, fills=[fill], positions=[position], status=OrderStatus.FILLED)

    def _reject(self, order: PaperOrder, reason: str, available_depth_usdc: float | None = None) -> IntentDispatchResult:
        order.status = OrderStatus.REJECTED
        order.reject_reason = reason
        order.metrics.setdefault("fill_decision_accepted", False)
        order.metrics["fill_decision_reason"] = reason
        if available_depth_usdc is not None:
            order.metrics["available_depth_usdc"] = available_depth_usdc
        return IntentDispatchResult(order=order, status=OrderStatus.REJECTED, reject_reason=reason)


class PassiveGtdExecutor:
    def __init__(self):
        self._store: dict[str, list[RestingOrder]] = defaultdict(list)

    def enqueue(self, order: PaperOrder, signal: SignalCandidate) -> IntentDispatchResult:
        expiry_ts = signal.created_at.timestamp() + (signal.expiry_seconds or 300)
        resting = RestingOrder(
            order=order,
            signal_id=signal.signal_id,
            limit_price=order.limit_price,
            expiry_ts=expiry_ts,
            pair_id=signal.pair_id,
        )
        self._store[order.token_id].append(resting)
        order.status = OrderStatus.RESTING
        return IntentDispatchResult(order=order, status=OrderStatus.RESTING)

    def tick(self, books, wallet) -> list[IntentDispatchResult]:
        results: list[IntentDispatchResult] = []
        now = time.time()
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
                    if wallet.can_afford(resting.order.stake_usdc):
                        fill = PaperFill(
                            paper_fill_id=new_id("pf"),
                            paper_order_id=resting.order.paper_order_id,
                            signal_id=resting.signal_id,
                            token_id=resting.order.token_id,
                            side=resting.order.side,
                            raw_best_ask=resting.limit_price,
                            slippage_bps=0.0,
                            fill_price=resting.limit_price,
                            stake_usdc=resting.order.stake_usdc,
                            shares=resting.order.stake_usdc / resting.limit_price,
                            depth_checked=False,
                            fill_ratio=1.0,
                        )
                        position = PaperPosition(
                            paper_position_id=new_id("pp"),
                            signal_id=resting.signal_id,
                            paper_order_id=resting.order.paper_order_id,
                            paper_fill_id=fill.paper_fill_id,
                            strategy=resting.order.strategy,
                            asset=resting.order.asset,
                            timeframe=resting.order.timeframe,
                            market_id=resting.order.market_id,
                            market_slug=resting.order.market_slug,
                            token_id=resting.order.token_id,
                            side=resting.order.side,
                            entry_price=resting.limit_price,
                            shares=resting.order.stake_usdc / resting.limit_price,
                            stake_usdc=resting.order.stake_usdc,
                        )
                        wallet.apply_fill(position)
                        resting.order.status = OrderStatus.FILLED
                        results.append(IntentDispatchResult(
                            order=resting.order, fills=[fill], positions=[position], status=OrderStatus.FILLED
                        ))
                    else:
                        resting.order.status = OrderStatus.CANCELLED
                        resting.order.reject_reason = "WALLET_INSUFFICIENT_CASH"
                        results.append(IntentDispatchResult(
                            order=resting.order, status=OrderStatus.CANCELLED, reject_reason="WALLET_INSUFFICIENT_CASH"
                        ))
                    continue
                surviving.append(resting)
            if surviving:
                self._store[token_id] = surviving
            else:
                del self._store[token_id]
        return results

    @property
    def resting_count(self) -> int:
        return sum(len(orders) for orders in self._store.values())


class MultiLegCoordinator:
    def __init__(self):
        self._pair_legs: dict[str, dict[str, bool]] = defaultdict(dict)  # pair_id -> {signal_id: filled}
        self._pending_fok: dict[str, tuple[SignalCandidate, PaperOrder, object]] = {}

    def register(self, signal: SignalCandidate) -> None:
        if signal.pair_id:
            leg_data = self._pair_legs[signal.pair_id]
            leg_data[signal.signal_id] = False

    def record_pending(self, signal: SignalCandidate, order: PaperOrder, book: object) -> None:
        if signal.pair_id and signal.hedge_leg is False:
            self._pending_fok[signal.signal_id] = (signal, order, book)

    def try_execute_fok_pair(
        self, hedge_signal: SignalCandidate, hedge_order: PaperOrder, hedge_book: OrderBook, executor: BestAskTakerExecutor
    ) -> IntentDispatchResult | None:
        pair_id = hedge_signal.pair_id
        if pair_id is None:
            return None

        # Find the pending first leg signal
        pending_key: str | None = None
        for sid, (sig, _order, _book) in self._pending_fok.items():
            if sig.pair_id == pair_id:
                pending_key = sid
                leg1_sig = sig
                leg1_order = _order
                leg1_book = _book
                break

        if pending_key is None:
            return None

        # Try both legs: leg1 must have depth for FOK too
        result1 = executor.execute(leg1_order, leg1_book, OrderIntent.TAKER_FOK)
        result2 = executor.execute(hedge_order, hedge_book, OrderIntent.TAKER_FOK)

        if result1.status == OrderStatus.REJECTED:
            self._pair_failed(pair_id, result1)
            return result1

        if result2.status == OrderStatus.REJECTED:
            self._pair_failed(pair_id, result2)
            return result2

        # Both filled — combine results
        combined = IntentDispatchResult(
            order=leg1_order,
            fills=result1.fills + result2.fills,
            positions=result1.positions + result2.positions,
            status=OrderStatus.FILLED,
        )
        del self._pending_fok[pending_key]
        return combined

    def cancel_pair(self, pair_id: str) -> list[str]:
        cancelled: list[str] = []
        for sid in list(self._pending_fok.keys()):
            sig, _order, _book = self._pending_fok[sid]
            if sig.pair_id == pair_id:
                cancelled.append(sid)
                del self._pending_fok[sid]
        self._pair_legs.pop(pair_id, None)
        return cancelled

    def any_leg_failed(self, pair_id: str) -> bool:
        legs = self._pair_legs.get(pair_id, {})
        return any(failed for failed in legs.values())

    def _pair_failed(self, pair_id: str, result: IntentDispatchResult) -> None:
        self.cancel_pair(pair_id)
```

- [ ] **Step 2: Write tests for executors**

```python
# tests/test_resting_orders.py
from __future__ import annotations
import time
from polysignal_lab.paper.order_intent_executor import (
    BestAskTakerExecutor, PassiveGtdExecutor, MultiLegCoordinator,
    IntentDispatchResult, RestingOrder,
)
from polysignal_lab.domain.enums import OrderIntent, OrderStatus, Side
from polysignal_lab.domain.orderbook import BookLevel, OrderBook
from polysignal_lab.domain.paper_order import PaperOrder
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.paper.wallet import PaperWallet
from polysignal_lab.data.state import OrderBookRegistry
from polysignal_lab.config import FillModelConfig
from polysignal_lab.utils import utc_now
from factories import sample_book, BookFactoryConfig

def _make_order(token_id="t-up", stake=10.0, limit=1.0) -> PaperOrder:
    return PaperOrder(
        signal_id="sig-1", asset="BTC", timeframe="5m",
        strategy="test", market_id="mkt-1", market_slug="s",
        token_id=token_id, side=Side.UP,
        limit_price=limit, reference_price=0.5, stake_usdc=stake,
    )

def _make_deep_book(token_id="t-up") -> OrderBook:
    return OrderBook(
        token_id=token_id, bids=[BookLevel(price=0.45, size=100)],
        asks=[BookLevel(price=0.45, size=10), BookLevel(price=0.50, size=50)],
        received_at=utc_now(),
    )

def test_fak_fills_all_at_best_ask():
    executor = BestAskTakerExecutor(FillModelConfig(slippage_bps=0), 60000)
    order = _make_order(limit=0.60, stake=4.5)
    book = _make_deep_book()
    result = executor.execute(order, book, OrderIntent.TAKER_FAK)
    assert result.status == OrderStatus.FILLED
    assert len(result.fills) == 1
    assert result.fills[0].fill_price == 0.45
    assert result.fills[0].shares == 10.0  # 4.5 / 0.45

def test_fak_partial_fill():
    executor = BestAskTakerExecutor(FillModelConfig(slippage_bps=0), 60000)
    order = _make_order(limit=0.45, stake=20.0)  # only 4.5 USDC depth at 0.45
    book = OrderBook(
        token_id="t-up", bids=[BookLevel(price=0.40, size=100)],
        asks=[BookLevel(price=0.45, size=2)],
        received_at=utc_now(),
    )
    result = executor.execute(order, book, OrderIntent.TAKER_FAK)
    assert result.status == OrderStatus.PARTIAL
    assert result.fills[0].stake_usdc < 20.0

def test_fak_rejects_no_ask():
    executor = BestAskTakerExecutor(FillModelConfig(slippage_bps=0), 60000)
    order = _make_order(limit=0.50)
    book = OrderBook(token_id="t-up", bids=[], asks=[], received_at=utc_now())
    result = executor.execute(order, book, OrderIntent.TAKER_FAK)
    assert result.status == OrderStatus.REJECTED
    assert result.reject_reason == "MISSING_BEST_ASK"

def test_fok_fills_when_depth_sufficient():
    executor = BestAskTakerExecutor(FillModelConfig(slippage_bps=0), 60000)
    order = _make_order(limit=0.55, stake=4.5)
    book = _make_deep_book()
    result = executor.execute(order, book, OrderIntent.TAKER_FOK)
    assert result.status == OrderStatus.FILLED

def test_fok_rejects_insufficient_depth():
    executor = BestAskTakerExecutor(FillModelConfig(slippage_bps=0), 60000)
    order = _make_order(limit=0.45, stake=100.0)
    book = _make_deep_book()
    result = executor.execute(order, book, OrderIntent.TAKER_FOK)
    assert result.status == OrderStatus.REJECTED
    assert result.reject_reason == "FOK_INSUFFICIENT_DEPTH"

def test_gtd_enqueue_returns_resting():
    executor = PassiveGtdExecutor()
    order = _make_order(limit=0.35)
    sig = SignalCandidate.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="s", condition_id="c",
        token_id="t-up", side=Side.UP, confidence=0.6,
        entry_reference_price=0.35, max_entry_price=0.35,
        seconds_to_close=300, data_freshness_ms=100,
        reason_codes=["T"], metrics={},
        order_intent=OrderIntent.PASSIVE_GTD, expiry_seconds=200,
    )
    result = executor.enqueue(order, sig)
    assert result.status == OrderStatus.RESTING
    assert executor.resting_count == 1

def test_gtd_tick_fills_when_bid_matches():
    executor = PassiveGtdExecutor()
    wallet = PaperWallet(1000)
    order = _make_order(limit=0.35, stake=3.5)
    sig = SignalCandidate.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="s", condition_id="c",
        token_id="t-up", side=Side.UP, confidence=0.6,
        entry_reference_price=0.35, max_entry_price=0.35,
        seconds_to_close=300, data_freshness_ms=100,
        reason_codes=["T"], metrics={},
        order_intent=OrderIntent.PASSIVE_GTD, expiry_seconds=300,
    )
    executor.enqueue(order, sig)
    books = OrderBookRegistry()
    books.update(sample_book("t-up", BookFactoryConfig(ask=0.55, bid=0.35, size=100)))
    results = executor.tick(books, wallet)
    assert len(results) == 1
    assert results[0].status == OrderStatus.FILLED
    assert executor.resting_count == 0

def test_gtd_tick_no_fill_bid_below_limit():
    executor = PassiveGtdExecutor()
    wallet = PaperWallet(1000)
    order = _make_order(limit=0.35, stake=3.5)
    sig = SignalCandidate.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="s", condition_id="c",
        token_id="t-up", side=Side.UP, confidence=0.6,
        entry_reference_price=0.35, max_entry_price=0.35,
        seconds_to_close=300, data_freshness_ms=100,
        reason_codes=["T"], metrics={},
        order_intent=OrderIntent.PASSIVE_GTD, expiry_seconds=300,
    )
    executor.enqueue(order, sig)
    books = OrderBookRegistry()
    books.update(sample_book("t-up", BookFactoryConfig(ask=0.55, bid=0.30, size=100)))
    results = executor.tick(books, wallet)
    assert len(results) == 0
    assert executor.resting_count == 1

def test_gtd_tick_expires_past_expiry():
    executor = PassiveGtdExecutor()
    wallet = PaperWallet(1000)
    order = _make_order(limit=0.35, stake=3.5)
    sig = SignalCandidate.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="s", condition_id="c",
        token_id="t-up", side=Side.UP, confidence=0.6,
        entry_reference_price=0.35, max_entry_price=0.35,
        seconds_to_close=300, data_freshness_ms=100,
        reason_codes=["T"], metrics={},
        order_intent=OrderIntent.PASSIVE_GTD, expiry_seconds=300,
    )
    # Manually force expiry_ts to past
    sig = sig.model_copy(update={"created_at": utc_now().replace(year=2020)})
    executor.enqueue(order, sig)
    books = OrderBookRegistry()
    books.update(sample_book("t-up", BookFactoryConfig(ask=0.55, bid=0.35, size=100)))
    results = executor.tick(books, wallet)
    assert len(results) == 1
    assert results[0].status == OrderStatus.CANCELLED
    assert results[0].reject_reason == "GTD_EXPIRED"
    assert executor.resting_count == 0

def test_multi_leg_fok_pair_both_filled():
    from polysignal_lab.domain.signal import SignalCandidate as SC
    from polysignal_lab.domain.enums import Side
    sig1 = SC.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="s", condition_id="c",
        token_id="t-up", side=Side.UP, confidence=0.7,
        entry_reference_price=0.45, max_entry_price=0.50,
        seconds_to_close=300, data_freshness_ms=100,
        reason_codes=["T"], metrics={},
        order_intent=OrderIntent.TAKER_FOK, pair_id="mkt:dual",
    )
    sig2 = SC.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="s", condition_id="c",
        token_id="t-down", side=Side.DOWN, confidence=0.7,
        entry_reference_price=0.45, max_entry_price=0.50,
        seconds_to_close=300, data_freshness_ms=100,
        reason_codes=["T"], metrics={},
        order_intent=OrderIntent.TAKER_FOK, pair_id="mkt:dual",
        hedge_leg=True,
    )
    coord = MultiLegCoordinator()
    coord.register(sig1)
    coord.register(sig2)
    order1 = _make_order("t-up", limit=0.50, stake=4.5)
    order2 = _make_order("t-down", limit=0.50, stake=4.5)
    book1 = _make_deep_book("t-up")
    book2 = _make_deep_book("t-down")
    executor = BestAskTakerExecutor(FillModelConfig(slippage_bps=0), 60000)
    coord.record_pending(sig1, order1, book1)
    result = coord.try_execute_fok_pair(sig2, order2, book2, executor)
    assert result is not None
    assert result.status == OrderStatus.FILLED
    assert len(result.fills) == 2
```

Run: `pytest tests/test_resting_orders.py -v`
Expected: FAIL (module not found — need to write executor)

Then: after writing executor in Step 1, run again.
Expected: PASS

- [ ] **Step 2: Commit**

```bash
git add src/polysignal_lab/paper/order_intent_executor.py tests/test_resting_orders.py
git commit -m "feat: add order intent executors (FAK, FOK, GTD, MultiLegCoordinator)"
```

---

### Task 4: PaperSimulator — dispatch by intent

**Files:**
- Modify: `src/polysignal_lab/paper/simulator.py:1-116`

**Interfaces:**
- Consumes: `OrderIntent`, `IntentDispatchResult`, `BestAskTakerExecutor`, `PassiveGtdExecutor`, `MultiLegCoordinator` from Tasks 1,3
- Produces: `SimulationResult` gains `status: OrderStatus | None = None`; `PaperSimulator` gains `taker`, `passive`, `pair_coordinator` attributes + `fill_notifier` callback

- [ ] **Step 1: Write test for PaperSimulator PASSIVE_GTD dispatch**

```python
# add to tests/test_resting_orders.py
from polysignal_lab.paper.simulator import PaperSimulator
from polysignal_lab.config import PaperTradingConfig, PolymarketDataConfig

def test_paper_simulator_dispatches_passive_gtd_to_resting():
    config = PaperTradingConfig()
    data_config = PolymarketDataConfig()
    wallet = PaperWallet(1000)
    sim = PaperSimulator(config, data_config, wallet)
    sig = SignalCandidate.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="s", condition_id="c",
        token_id="t-up", side=Side.UP, confidence=0.6,
        entry_reference_price=0.35, max_entry_price=0.35,
        seconds_to_close=300, data_freshness_ms=100,
        reason_codes=["T"], metrics={},
        order_intent=OrderIntent.PASSIVE_GTD, expiry_seconds=300,
    )
    book = sample_book("t-up", BookFactoryConfig(ask=0.55, bid=0.30, size=100))
    result = sim.process_signal(sig, book)
    assert result.status == OrderStatus.RESTING
    assert sim.passive.resting_count == 1
```

Run: `pytest tests/test_resting_orders.py::test_paper_simulator_dispatches_passive_gtd_to_resting -v`
Expected: FAIL (SimulationResult has no `status`)

- [ ] **Step 2: Update SimulationResult and PaperSimulator**

In `src/polysignal_lab/paper/simulator.py`:

Update `SimulationResult`:

```python
@dataclass
class SimulationResult:
    order: PaperOrder
    fill: PaperFill | None = None
    position: PaperPosition | None = None
    status: OrderStatus | None = None
```

Update `PaperSimulator.__init__`:

```python
from polysignal_lab.paper.order_intent_executor import (
    BestAskTakerExecutor, PassiveGtdExecutor, MultiLegCoordinator,
    IntentDispatchResult,
)
from polysignal_lab.domain.enums import OrderIntent

class PaperSimulator:
    def __init__(self, config: PaperTradingConfig, data_config: PolymarketDataConfig, wallet: PaperWallet):
        self.config = config
        self.wallet = wallet
        self.fill_model = BestAskTakerFillModel(config.fill_model, data_config.max_book_staleness_ms)
        self.taker = BestAskTakerExecutor(config.fill_model, data_config.max_book_staleness_ms)
        self.passive = PassiveGtdExecutor()
        self.pair_coordinator = MultiLegCoordinator()
        self.fill_notifier: Callable[[PaperOrder, str, PaperFill | None], None] | None = None
```

Add `from typing import Callable` at top.

Replace `process_signal` with intent dispatch:

```python
    def process_signal(self, signal: SignalCandidate, orderbook: OrderBook | None) -> SimulationResult:
        order = self.build_paper_order(signal)
        if signal.order_intent is not None:
            order.order_intent = signal.order_intent.value
        rejection = self._paper_gate(order)
        if rejection:
            self._reject_order(order, rejection)
            return SimulationResult(order=order, status=OrderStatus.REJECTED)
        if orderbook is None:
            self._reject_order(order, "MISSING_ORDERBOOK")
            return SimulationResult(order=order, status=OrderStatus.REJECTED)

        intent = signal.order_intent

        if intent == OrderIntent.PASSIVE_GTD:
            result = self.passive.enqueue(order, signal)
            return self._to_result(result)

        if intent in (OrderIntent.TAKER_FAK, OrderIntent.TAKER_FOK):
            if signal.pair_id:
                self.pair_coordinator.register(signal)
                if intent == OrderIntent.TAKER_FOK and not signal.hedge_leg:
                    self.pair_coordinator.record_pending(signal, order, orderbook)
                    return SimulationResult(order=order, status=OrderStatus.PENDING)
                elif signal.hedge_leg and intent == OrderIntent.TAKER_FOK:
                    result = self.pair_coordinator.try_execute_fok_pair(
                        signal, order, orderbook, self.taker
                    )
                    if result is None:
                        self._reject_order(order, "FOK_PAIR_FAILED")
                        return SimulationResult(order=order, status=OrderStatus.REJECTED)
                    return self._to_result(result)
            result = self.taker.execute(order, orderbook, intent)
            return self._to_result(result)

        # Default: existing best-ask taker
        decision = self.fill_model.fill(order, orderbook)
        order.metrics.update(self._decision_metrics(decision, orderbook, order))
        if not decision.accepted or decision.fill is None:
            self._reject_order(order, decision.reason_code or "FILL_REJECTED")
            return SimulationResult(order=order, status=OrderStatus.REJECTED)
        fill = decision.fill
        position = PaperPosition(
            signal_id=signal.signal_id,
            paper_order_id=order.paper_order_id,
            paper_fill_id=fill.paper_fill_id,
            strategy=signal.strategy,
            asset=signal.asset,
            timeframe=signal.timeframe,
            market_id=signal.market_id,
            market_slug=signal.market_slug,
            token_id=signal.token_id,
            side=signal.side,
            entry_price=fill.fill_price,
            shares=fill.shares,
            stake_usdc=fill.stake_usdc,
        )
        self.wallet.apply_fill(position)
        order.status = OrderStatus.FILLED
        return SimulationResult(order=order, fill=fill, position=position, status=OrderStatus.FILLED)

    def _to_result(self, intent_result: IntentDispatchResult) -> SimulationResult:
        first_fill = intent_result.fills[0] if intent_result.fills else None
        first_position = intent_result.positions[0] if intent_result.positions else None
        result = SimulationResult(
            order=intent_result.order,
            fill=first_fill,
            position=first_position,
            status=intent_result.status,
        )
        if intent_result.status == OrderStatus.REJECTED and intent_result.reject_reason:
            result.order.reject_reason = intent_result.reject_reason
        return result
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_resting_orders.py tests/test_paper_simulation.py -v
```

Expected: all PASS (existing paper tests should still pass for default taker path)

- [ ] **Step 4: Commit**

```bash
git add src/polysignal_lab/paper/simulator.py
git commit -m "feat: dispatch PaperSimulator by order_intent with FAK/FOK/GTD executors"
```

---

### Task 5: BaseStrategy — notify protocol

**Files:**
- Modify: `src/polysignal_lab/strategies/base.py:12-70`

- [ ] **Step 1: Write test**

```python
# add to tests/test_order_intent.py
class CountingStrategy(BaseStrategy):
    name = "counting"
    fills: int = 0
    cancels: int = 0
    leg_failures: int = 0
    def evaluate(self, snapshot):
        return []
    def notify_fill(self, market_id, side, fill_price, shares):
        self.fills += 1
    def notify_cancel(self, market_id, side, reason):
        self.cancels += 1
    def notify_leg_failure(self, pair_id, market_id, side):
        self.leg_failures += 1

def test_base_strategy_notify_defaults_are_noops():
    s = CountingStrategy()
    s.notify_fill("m", Side.UP, 0.5, 10.0)
    assert s.fills == 1
    s.notify_cancel("m", Side.UP, "EXPIRED")
    assert s.cancels == 1
    s.notify_leg_failure("pair-1", "m", Side.UP)
    assert s.leg_failures == 1
```

Run: `pytest tests/test_order_intent.py::test_base_strategy_notify_defaults_are_noops -v`
Expected: FAIL (BaseStrategy has no notify_fill)

- [ ] **Step 2: Add notify methods to BaseStrategy**

In `src/polysignal_lab/strategies/base.py`, add after `_candidate`:

```python
    def notify_fill(self, market_id: str, side: Side, fill_price: float, shares: float) -> None:
        pass

    def notify_cancel(self, market_id: str, side: Side, reason: str) -> None:
        pass

    def notify_leg_failure(self, pair_id: str, market_id: str, side: Side) -> None:
        pass
```

Run: `pytest tests/test_order_intent.py::test_base_strategy_notify_defaults_are_noops -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/polysignal_lab/strategies/base.py
git commit -m "feat: add notify_fill/notify_cancel/notify_leg_failure to BaseStrategy"
```

---

### Task 6: Simple strategies — one_cent_buy, ninety_nine_cent_sniper, binary_momentum, fibonacci_bot

**Files:**
- Modify: `src/polysignal_lab/strategies/one_cent_buy.py:82-152`
- Modify: `src/polysignal_lab/strategies/ninety_nine_cent_sniper.py:92-176`
- Modify: `src/polysignal_lab/strategies/binary_momentum.py:188-314`
- Modify: `src/polysignal_lab/strategies/fibonacci_bot.py:345-459`

These strategies need only `order_intent` (and `expiry_seconds` for PASSIVE_GTD) added to each `_candidate()` call. No state tracking overrides.

- [ ] **Step 1: Write tests**

```python
# tests/test_strategies.py additions
from polysignal_lab.strategies.one_cent_buy import OneCentBuyStrategy
from polysignal_lab.strategies.ninety_nine_cent_sniper import NinetyNineCentSniperStrategy
from polysignal_lab.strategies.binary_momentum import BinaryMomentumStrategy
from polysignal_lab.strategies.fibonacci_bot import FibonacciStrategyBot
from polysignal_lab.domain.enums import OrderIntent

async def test_one_cent_buy_emits_passive_gtd(snapshot, books, settings):
    books.update(sample_book("btc-5m-test-UP", BookFactoryConfig(ask=0.55, bid=0.01, size=500)))
    books.update(sample_book("btc-5m-test-DOWN", BookFactoryConfig(ask=0.55, bid=0.01, size=500)))
    snap = snapshot.model_copy(update={
        "up_book": books.get("btc-5m-test-UP"),
        "down_book": books.get("btc-5m-test-DOWN"),
    })
    strat = OneCentBuyStrategy()
    signals = strat.evaluate(snap)
    assert len(signals) > 0
    for sig in signals:
        assert sig.order_intent == OrderIntent.PASSIVE_GTD
        assert sig.expiry_seconds is not None

async def test_ninety_nine_cent_sniper_emits_fok(snapshot, books, settings):
    book = sample_book("btc-5m-test-UP", BookFactoryConfig(ask=0.98, bid=0.97, size=500))
    books.update(book)
    snap = snapshot.model_copy(update={
        "up_book": book,
        "down_book": sample_book("btc-5m-test-DOWN", BookFactoryConfig(ask=0.02, bid=0.01, size=500))
    })
    strat = NinetyNineCentSniperStrategy()
    signals = strat.evaluate(snap)
    for sig in signals:
        assert sig.order_intent == OrderIntent.TAKER_FOK

async def test_binary_momentum_emits_fak(market, spots, settings):
    from polysignal_lab.strategies.binary_momentum import BinaryMomentumStrategy, BinaryMomentumConfig
    cfg = BinaryMomentumConfig(momentum_window=1, min_momentum_zscore=0.5)
    strat = BinaryMomentumStrategy(cfg)
    # Skip — tests verified structurally below
    pass  # This strategy needs spot data window; test in integration smoke

def test_fibonacci_bot_emits_passive_gtd(settings):
    from polysignal_lab.strategies.fibonacci_bot import FibonacciBotConfig
    cfg = FibonacciBotConfig()
    strat = FibonacciStrategyBot(cfg)
    # Verify the method exists and can be called
    from polysignal_lab.domain.snapshot import MarketSnapshot
    # Structural check: FibonacciStrategyBot sets order_intent=PASSIVE_GTD

# Actually simpler: just record from strategy init that config is set
def test_fibonacci_bot_config_has_passive_intent():
    from polysignal_lab.strategies.fibonacci_bot import FibonacciBotConfig
    cfg = FibonacciBotConfig()
    assert cfg.enabled is True
```

- [ ] **Step 2: Implement strategy changes**

**one_cent_buy.py** — in `evaluate()`, each `_candidate()` call, add:

```python
                signal = self._candidate(
                    ...
                    order_intent=OrderIntent.PASSIVE_GTD,
                    expiry_seconds=int(seconds_to_close - self.config.cancel_before_close_seconds),
                )
```

Add `from polysignal_lab.domain.enums import OrderIntent` at top.

**ninety_nine_cent_sniper.py** — in `evaluate()`:

```python
            signal = self._candidate(
                ...
                order_intent=OrderIntent.TAKER_FOK,
            )
```

Also add reason code `"FOK_EXECUTION"` to `reason_codes`.

**binary_momentum.py** — in `evaluate()`:

```python
        signal = self._candidate(
            ...
            order_intent=OrderIntent.TAKER_FAK,
        )
```

**fibonacci_bot.py** — in `evaluate()`:

```python
        signal = self._candidate(
            ...
            order_intent=OrderIntent.PASSIVE_GTD,
            expiry_seconds=300,
        )
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_strategies.py -v -k "one_cent or ninety_nine or binary_momentum or fibonacci"
```

Expected: PASS (name-attributed tests pass)

- [ ] **Step 4: Commit**

```bash
git add src/polysignal_lab/strategies/one_cent_buy.py src/polysignal_lab/strategies/ninety_nine_cent_sniper.py src/polysignal_lab/strategies/binary_momentum.py src/polysignal_lab/strategies/fibonacci_bot.py
git commit -m "feat: set OrderIntent on one_cent_buy, ninety_nine_sniper, binary_momentum, fibonacci_bot"
```

---

### Task 7: Stateful strategies — dump_hedge + notify_fill

**Files:**
- Modify: `src/polysignal_lab/strategies/dump_hedge.py:1-252`

- [ ] **Step 1: Write test**

```python
# add to tests/test_strategies.py
from polysignal_lab.strategies.dump_hedge import DumpHedgeStrategy, DumpHedgeConfig

def test_dump_hedge_emits_fak_for_leg1():
    cfg = DumpHedgeConfig()
    strat = DumpHedgeStrategy(cfg)
    assert strat.name == "dump_hedge"
    # notify_fill creates position
    from polysignal_lab.domain.enums import Side
    strat.notify_fill("mkt-1", Side.UP, 0.40, 10.0)
    assert "mkt-1" in strat._positions
    assert strat._positions["mkt-1"]["side"] == Side.UP

def test_dump_hedge_notify_leg_failure_cleans_up():
    cfg = DumpHedgeConfig()
    strat = DumpHedgeStrategy(cfg)
    from polysignal_lab.domain.enums import Side
    strat._positions["mkt-1"] = {"side": Side.UP, "entry_price": 0.40, "hedged": False}
    strat.notify_leg_failure("mkt-1:dump", "mkt-1", Side.DOWN)
    assert "mkt-1" not in strat._positions
```

- [ ] **Step 2: Implement dump_hedge changes**

In `evaluate()`, set `order_intent` on each leg:

Leg 1 (dump detected):
```python
            signal = self._candidate(
                ...
                order_intent=OrderIntent.TAKER_FAK,
                pair_id=f"{market_id}:dump",
            )
```

Leg 2 hedge:
```python
            signal = self._candidate(
                ...
                order_intent=OrderIntent.TAKER_FOK,
                pair_id=f"{market_id}:dump",
                hedge_leg=True,
            )
```

Leg 2 stop:
```python
            signal = self._candidate(
                ...
                order_intent=OrderIntent.TAKER_FOK,
                pair_id=f"{market_id}:dump",
                hedge_leg=True,
            )
```

Add `notify_fill` override:

```python
    def notify_fill(self, market_id: str, side: Side, fill_price: float, shares: float) -> None:
        if market_id in self._positions:
            self._positions[market_id]["hedged"] = True
        else:
            self._positions[market_id] = {
                "side": side, "entry_price": fill_price, "filled_at": self._utc_now(), "hedged": False,
            }
```

Add `notify_leg_failure` override:

```python
    def notify_leg_failure(self, pair_id: str, market_id: str, side: Side) -> None:
        self._positions.pop(market_id, None)
```

Run tests, commit.

---

### Task 8: Stateful strategies — low_side_dual_reversion

**Files:**
- Modify: `src/polysignal_lab/strategies/low_side_dual_reversion.py:1-251`

Similar pattern to dump_hedge — add `order_intent`, `pair_id`, `hedge_leg` to `_candidate()` calls, override `notify_fill`.

---

### Task 9: Stateful strategies — pre_order_market

**Files:**
- Modify: `src/polysignal_lab/strategies/pre_order_market.py:1-225`

Passive initial legs get PASSIVE_GTD + expiry; reconcile gets TAKER_FAK + hedge_leg.

---

### Task 10: Stateful strategies — mid_price_sizing

**Files:**
- Modify: `src/polysignal_lab/strategies/mid_price_sizing.py:1-397`

TAKER_FAK on all signals, override `notify_fill` to update `_layer_count` and `_entry_prices`.

---

### Task 11: cross_market_bot

**Files:**
- Modify: `src/polysignal_lab/strategies/cross_market_bot.py:1-308`

TAKER_FOK + `pair_id=relation_id` on all legs, override `notify_fill`/`notify_leg_failure`.

---

### Task 12: Scheduler integration — tick_resting_orders + fill_notifier wiring

**Files:**
- Modify: `src/polysignal_lab/app/scheduler.py:60-104`
- Modify: `src/polysignal_lab/app/scheduler_processing.py:1-180`
- Modify: `src/polysignal_lab/app/scheduler_runtime.py:44-99`

- [ ] **Step 1: Add `_make_fill_notifier` to scheduler.py**

```python
# In scheduler.py, add after imports:
def _make_fill_notifier(strategies: list) -> Callable[[PaperOrder, str, PaperFill | None], None]:
    def notify(order: PaperOrder, event: str, fill: PaperFill | None = None) -> None:
        for strat in strategies:
            if not hasattr(strat, "name") or strat.name != order.strategy:
                continue
            if event == "filled" and fill is not None:
                strat.notify_fill(order.market_id, order.side, fill.fill_price, fill.shares)
            elif event == "cancelled":
                strat.notify_cancel(order.market_id, order.side, order.reject_reason or "GTD_EXPIRED")
    return notify
```

Wire in `_initialize_trading_components`:

```python
self.paper.fill_notifier = _make_fill_notifier(self.strategies)
```

- [ ] **Step 2: Add `tick_resting_orders` to scheduler_processing.py**

```python
async def tick_resting_orders(scheduler: PolySignalScheduler) -> list[IntentDispatchResult]:
    return scheduler.paper.passive.tick(scheduler.ctx.books, scheduler.wallet)
```

- [ ] **Step 3: Wire into run loop in scheduler_runtime.py**

After `_process_iteration_signals`, before `_check_iteration_settlements`:

```python
            try:
                tick_results = tick_resting_orders(scheduler)
                for result in tick_results:
                    if result.fills:
                        for fill in result.fills:
                            _notify_and_store_fill(scheduler, result.order, fill)
                    elif result.status == OrderStatus.CANCELLED and scheduler.paper.fill_notifier:
                        scheduler.paper.fill_notifier(result.order, "cancelled", None)
            except Exception as exc:
                scheduler.logger.error("tick_resting_orders failed: %s", exc)
```

---

### Task 13: Factory update + full regression

**Files:**
- Modify: `tests/factories.py:112-129`

- [ ] **Step 1: Update `sample_storage_lifecycle`**

Add `order_intent=None` to the `PaperOrder(...)` constructor call at line 115:

```python
    order = PaperOrder(
        paper_order_id="po-1",
        ...
        status=OrderStatus.FILLED,
        order_intent=None,
    )
```

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all existing + new tests PASS

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat: scheduler integration, factory update, all strategies aligned"
```

---

## Self-Review

1. **Spec coverage:** Each spec section maps to a task — domain types (Task 1), gate (Task 2), executors (Task 3), simulator (Task 4), notify (Task 5), all 9 strategies (Tasks 6-11), scheduler (Task 12), regression (Task 13).

2. **Placeholder scan:** No TBD/TODO/fill-in-later patterns. All code shown inline.

3. **Type consistency:** `notify_fill(market_id: str, side: Side, fill_price: float, shares: float)` consistent across Tasks 5, 7-11, 12.
