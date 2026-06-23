# Paper Execution Realism Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make paper trading results more trustworthy by revalidating execution-time market conditions, preserving accepted signals even when paper execution rejects, and reporting why paper fills or rejects happened.

**Architecture:** Add a focused `PaperExecutionPreflight` service in `src/polysignal_lab/paper/` that evaluates execution-time book freshness, intent-specific depth, max-entry movement, and supported edge metrics before the existing fill executors run. Keep existing fill behavior as the source of fill construction; preflight only rejects impossible paper executions early and writes normalized report-facing `PAPER_*` metrics while preserving original simulator/fill/wallet reasons. Extend daily report/domain/dashboard payloads to aggregate paper attempts, fills, partial fills, rejects, staleness, executable depth, and assumptions from stored `paper_orders` / `paper_fills` rows.

**Spec:** `docs/superpowers/specs/2026-06-23-03-paper-execution-realism-design.md`

**Tech Stack:** Python 3.11+, Pydantic v2, dataclasses, existing SQLite JSON payload storage, FastAPI dashboard, existing pytest/uv workflow.

## Global Constraints

- **Standalone batch.** Do not execute with specs 01-02 or 04-08 in the same implementation batch.
- **Paper-only.** No live trading, no authenticated CLOB user channel, no real order placement, no cancel/redeem controls.
- **Strategy logic unchanged.** Do not change `BaseStrategy.evaluate()` implementations or signal gate acceptance rules.
- **Accepted signals still persist and publish.** Paper execution rejection must not suppress the accepted signal row or Telegram signal publish.
- **Fill behavior unchanged after preflight accepts.** Existing best-ask taker, FAK, FOK, and PASSIVE_GTD fill/enqueue behavior remains authoritative.
- **Intent-aware preflight.** Default taker keeps current slippage/depth config; `TAKER_FAK` allows partial executable fills; `TAKER_FOK` requires full executable depth; `PASSIVE_GTD` must not require immediate taker depth.
- **Depth uses full price ladder.** Full-fill checks use `OrderBook.depth_until(limit_price)`, not a top-N depth cap.
- **Reason preservation.** Store normalized `PAPER_*` report reason and original simulator/fill/wallet reason in order metrics.
- **No new dependencies.** Use standard library, existing Pydantic models, existing app modules.
- **Project test runner.** Use `UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest ...`.
- **Formal runtime requires container rebuild.** After implementation verification, run `docker compose up -d --build --force-recreate`, then verify `docker compose ps` and startup logs/health before calling the new version live.

---

## File Structure

- Create `src/polysignal_lab/paper/preflight.py`: preflight decision dataclass, normalized reason mapping, metrics helpers, and intent-aware execution checks.
- Modify `src/polysignal_lab/paper/simulator.py`: instantiate preflight, run it after wallet/exposure gate and before fill/enqueue dispatch, merge preflight metrics into `PaperOrder.metrics`.
- Modify `src/polysignal_lab/domain/paper_result.py`: add defaulted daily report aggregate fields so existing stored/report construction remains compatible.
- Modify `src/polysignal_lab/paper/report.py`: derive paper execution aggregate fields from stored order/fill payloads.
- Modify `src/polysignal_lab/app/scheduler_reporting.py`: pass raw paper order/fill payloads and fill-model assumptions into `PaperReportService.build_daily_report()`.
- Modify `src/polysignal_lab/dashboard/app.py`: expose paper order rows and show latest report execution-quality fields in dashboard/overview.
- Modify `src/polysignal_lab/signal_layer/formatter.py`: include compact paper execution quality lines in the daily Telegram report.
- Add `tests/test_paper_execution_preflight.py`: direct preflight unit coverage and normalized reason mapping.
- Modify `tests/test_paper_simulation.py`: simulator regression coverage for normalized paper rejects, stale/missing/thin books, and edge-vanish preflight.
- Modify `tests/test_order_intent.py`: intent regression coverage that FAK partial and PASSIVE_GTD semantics are not collapsed by preflight.
- Modify `tests/test_reporting.py`, `tests/test_scheduler_reports.py`, `tests/test_storage_reporting_publish.py`, and `tests/test_dashboard.py`: aggregate/report/dashboard/formatter coverage.

---

### Task 1: PaperExecutionPreflight service and reason mapping

**Files:**
- Create: `src/polysignal_lab/paper/preflight.py`
- Create: `tests/test_paper_execution_preflight.py`

**Interfaces:**
- Produces: `PaperExecutionDecision(accepted: bool, reason_code: str, metrics: dict[str, bool | float | str | None])`
- Produces: `normalize_paper_reject_reason(reason: str | None) -> str`
- Produces: `PaperExecutionPreflight.__init__(fill_model: FillModelConfig, max_book_staleness_ms: int, fixed_stake_usdc: float, registry: OrderBookRegistry | None = None)`
- Produces: `PaperExecutionPreflight.evaluate(signal: SignalCandidate, orderbook: OrderBook | None, now: datetime, intent: OrderIntent | None = None) -> PaperExecutionDecision`
- Consumes: `SignalCandidate.metrics` keys when present: `directional_probability`, `probability_edge`, `min_probability_edge`, `min_token_price`, `entry_prob`

- [ ] **Step 1: Write failing tests for normalized reason mapping**

Add this file:

```python
# tests/test_paper_execution_preflight.py
from __future__ import annotations

from datetime import timedelta

import pytest

from polysignal_lab.config import FillModelConfig
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.orderbook import BookLevel, OrderBook
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.paper.preflight import PaperExecutionPreflight, normalize_paper_reject_reason
from polysignal_lab.utils import utc_now


def _signal(**updates) -> SignalCandidate:
    payload = dict(
        signal_id="sig-preflight",
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="mkt-1",
        market_slug="btc-updown-5m",
        condition_id="cond-1",
        token_id="token-up",
        side=Side.UP,
        confidence=0.7,
        entry_reference_price=0.50,
        max_entry_price=0.60,
        seconds_to_close=120,
        data_freshness_ms=100,
        reason_codes=["TEST"],
        metrics={},
        dedupe_key="BTC:5m:mkt-1:UP:test",
    )
    payload.update(updates)
    return SignalCandidate(**payload)


def _book(*, ask: float = 0.50, size: float = 100.0, received_delta_ms: int = 0) -> OrderBook:
    return OrderBook(
        market_id="mkt-1",
        token_id="token-up",
        bids=[BookLevel(price=max(0.01, ask - 0.03), size=size)],
        asks=[BookLevel(price=ask, size=size), BookLevel(price=min(0.99, ask + 0.02), size=size)],
        received_at=utc_now() - timedelta(milliseconds=received_delta_ms),
    )


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("MISSING_ORDERBOOK", "PAPER_MISSING_ORDERBOOK"),
        ("NO_SNAPSHOT", "PAPER_STALE_ORDERBOOK"),
        ("STALE_ORDERBOOK", "PAPER_STALE_ORDERBOOK"),
        ("ASK_ABOVE_MAX_ENTRY", "PAPER_ENTRY_PRICE_MOVED"),
        ("SLIPPAGE_EXCEEDS_MAX_ENTRY", "PAPER_EXTREME_SLIPPAGE"),
        ("INSUFFICIENT_DEPTH", "PAPER_DEPTH_TOO_THIN"),
        ("FOK_INSUFFICIENT_DEPTH", "PAPER_DEPTH_TOO_THIN"),
        ("FAK_NO_LIQUIDITY", "PAPER_DEPTH_TOO_THIN"),
        ("EXPOSURE_LIMIT_REACHED", "PAPER_EXPOSURE_LIMIT_REACHED"),
        ("MAX_OPEN_POSITIONS_REACHED", "PAPER_EXPOSURE_LIMIT_REACHED"),
        ("WALLET_INSUFFICIENT_CASH", "PAPER_WALLET_INSUFFICIENT_CASH"),
        ("GTD_EXPIRED", "PAPER_GTD_EXPIRED"),
        ("MALFORMED_ORDERBOOK", "PAPER_MALFORMED_ORDERBOOK"),
        ("UNKNOWN_REASON", "PAPER_FILL_REJECTED"),
    ],
)
def test_normalize_paper_reject_reason(raw: str, normalized: str) -> None:
    assert normalize_paper_reject_reason(raw) == normalized
```

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_paper_execution_preflight.py::test_normalize_paper_reject_reason -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'polysignal_lab.paper.preflight'`.

- [ ] **Step 2: Add preflight dataclass and reason mapping**

Create `src/polysignal_lab/paper/preflight.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any

from polysignal_lab.config import FillModelConfig
from polysignal_lab.data.state import OrderBookRegistry
from polysignal_lab.domain.enums import OrderIntent
from polysignal_lab.domain.orderbook import OrderBook
from polysignal_lab.domain.signal import SignalCandidate

PAPER_MISSING_ORDERBOOK = "PAPER_MISSING_ORDERBOOK"
PAPER_STALE_ORDERBOOK = "PAPER_STALE_ORDERBOOK"
PAPER_DEPTH_TOO_THIN = "PAPER_DEPTH_TOO_THIN"
PAPER_ENTRY_PRICE_MOVED = "PAPER_ENTRY_PRICE_MOVED"
PAPER_EDGE_VANISHED = "PAPER_EDGE_VANISHED"
PAPER_EXTREME_SLIPPAGE = "PAPER_EXTREME_SLIPPAGE"
PAPER_EXPOSURE_LIMIT_REACHED = "PAPER_EXPOSURE_LIMIT_REACHED"
PAPER_WALLET_INSUFFICIENT_CASH = "PAPER_WALLET_INSUFFICIENT_CASH"
PAPER_GTD_EXPIRED = "PAPER_GTD_EXPIRED"
PAPER_MALFORMED_ORDERBOOK = "PAPER_MALFORMED_ORDERBOOK"
PAPER_FILL_REJECTED = "PAPER_FILL_REJECTED"
PAPER_ACCEPTED = "PAPER_ACCEPTED"

_REASON_MAP: dict[str, str] = {
    "MISSING_ORDERBOOK": PAPER_MISSING_ORDERBOOK,
    "MISSING_BEST_ASK": PAPER_MISSING_ORDERBOOK,
    "NO_SNAPSHOT": PAPER_STALE_ORDERBOOK,
    "STALE_ORDERBOOK": PAPER_STALE_ORDERBOOK,
    "HASH_REGRESSION": PAPER_STALE_ORDERBOOK,
    "DELTA_BEFORE_SNAPSHOT": PAPER_STALE_ORDERBOOK,
    "INSUFFICIENT_DEPTH": PAPER_DEPTH_TOO_THIN,
    "FOK_INSUFFICIENT_DEPTH": PAPER_DEPTH_TOO_THIN,
    "FAK_NO_LIQUIDITY": PAPER_DEPTH_TOO_THIN,
    "ASK_ABOVE_MAX_ENTRY": PAPER_ENTRY_PRICE_MOVED,
    "SLIPPAGE_EXCEEDS_MAX_ENTRY": PAPER_EXTREME_SLIPPAGE,
    "EXPOSURE_LIMIT_REACHED": PAPER_EXPOSURE_LIMIT_REACHED,
    "MAX_OPEN_POSITIONS_REACHED": PAPER_EXPOSURE_LIMIT_REACHED,
    "WALLET_INSUFFICIENT_CASH": PAPER_WALLET_INSUFFICIENT_CASH,
    "GTD_EXPIRED": PAPER_GTD_EXPIRED,
    "MALFORMED_ORDERBOOK": PAPER_MALFORMED_ORDERBOOK,
}


def normalize_paper_reject_reason(reason: str | None) -> str:
    if reason is None or reason == "":
        return PAPER_FILL_REJECTED
    if reason.startswith("PAPER_"):
        return reason
    return _REASON_MAP.get(reason, PAPER_FILL_REJECTED)


@dataclass(frozen=True, slots=True)
class PaperExecutionDecision:
    accepted: bool
    reason_code: str
    metrics: dict[str, bool | float | str | None]


class PaperExecutionPreflight:
    def __init__(
        self,
        fill_model: FillModelConfig,
        max_book_staleness_ms: int,
        fixed_stake_usdc: float,
        registry: OrderBookRegistry | None = None,
    ) -> None:
        self.fill_model = fill_model
        self.max_book_staleness_ms = max_book_staleness_ms
        self.fixed_stake_usdc = fixed_stake_usdc
        self.registry = registry

    def evaluate(
        self,
        signal: SignalCandidate,
        orderbook: OrderBook | None,
        now: datetime,
        intent: OrderIntent | None = None,
    ) -> PaperExecutionDecision:
        metrics = self._base_metrics(signal, orderbook, now, intent)
        if orderbook is None:
            return self._reject("MISSING_ORDERBOOK", metrics)
        malformed = self._malformed_book_reason(signal, orderbook)
        if malformed is not None:
            return self._reject(malformed, metrics)
        stale_reason = self._stale_reason(signal.token_id, orderbook, now)
        metrics["paper_orderbook_fresh"] = stale_reason is None
        metrics["paper_orderbook_staleness_ms"] = float(orderbook.freshness_ms(now))
        metrics["paper_execution_best_ask"] = orderbook.best_ask
        metrics["paper_execution_best_bid"] = orderbook.best_bid
        metrics["paper_available_depth_usdc"] = orderbook.depth_until(signal.max_entry_price)
        if stale_reason is not None:
            return self._reject(stale_reason, metrics)
        if intent == OrderIntent.PASSIVE_GTD:
            metrics["paper_depth_revalidated"] = False
            metrics["paper_edge_revalidated"] = False
            return PaperExecutionDecision(True, PAPER_ACCEPTED, metrics)
        if orderbook.best_ask is None:
            return self._reject("MISSING_BEST_ASK", metrics)
        if orderbook.best_ask > signal.max_entry_price:
            return self._reject("ASK_ABOVE_MAX_ENTRY", metrics)
        slippage_price = orderbook.best_ask + orderbook.best_ask * self.fill_model.slippage_bps / 10000
        metrics["paper_slippage_bps"] = self.fill_model.slippage_bps
        metrics["paper_slippage_price"] = slippage_price
        if intent not in (OrderIntent.TAKER_FAK, OrderIntent.TAKER_FOK) and slippage_price > signal.max_entry_price:
            return self._reject("SLIPPAGE_EXCEEDS_MAX_ENTRY", metrics)
        if intent == OrderIntent.TAKER_FOK:
            metrics["paper_depth_revalidated"] = True
            if float(metrics["paper_available_depth_usdc"] or 0.0) < self.fixed_stake_usdc:
                return self._reject("FOK_INSUFFICIENT_DEPTH", metrics)
        elif intent == OrderIntent.TAKER_FAK:
            metrics["paper_depth_revalidated"] = True
            if float(metrics["paper_available_depth_usdc"] or 0.0) <= 0.0:
                return self._reject("FAK_NO_LIQUIDITY", metrics)
        elif self.fill_model.require_depth_check:
            metrics["paper_depth_revalidated"] = True
            available = float(metrics["paper_available_depth_usdc"] or 0.0)
            fill_ratio = min(1.0, available / self.fixed_stake_usdc) if self.fixed_stake_usdc else 0.0
            metrics["paper_depth_fill_ratio"] = fill_ratio
            if fill_ratio < self.fill_model.min_fill_ratio and self.fill_model.reject_if_partial:
                return self._reject("INSUFFICIENT_DEPTH", metrics)
        else:
            metrics["paper_depth_revalidated"] = False
        edge_reason = self._edge_reason(signal, orderbook.best_ask, metrics)
        if edge_reason is not None:
            return self._reject(edge_reason, metrics)
        return PaperExecutionDecision(True, PAPER_ACCEPTED, metrics)

    def _base_metrics(
        self,
        signal: SignalCandidate,
        orderbook: OrderBook | None,
        now: datetime,
        intent: OrderIntent | None,
    ) -> dict[str, bool | float | str | None]:
        return {
            "paper_preflight_checked": True,
            "paper_execution_checked_at": now.isoformat(),
            "paper_order_intent": intent.value if intent is not None else None,
            "paper_original_reason": None,
            "paper_normalized_reason": None,
            "paper_orderbook_token_id": orderbook.token_id if orderbook is not None else None,
            "paper_signal_token_id": signal.token_id,
            "paper_limit_price": signal.max_entry_price,
            "paper_stake_usdc": self.fixed_stake_usdc,
        }

    def _reject(
        self, reason: str,
        metrics: dict[str, bool | float | str | None],
    ) -> PaperExecutionDecision:
        normalized = normalize_paper_reject_reason(reason)
        metrics["paper_original_reason"] = reason
        metrics["paper_normalized_reason"] = normalized
        return PaperExecutionDecision(False, normalized, metrics)

    def _malformed_book_reason(self, signal: SignalCandidate, orderbook: OrderBook) -> str | None:
        if orderbook.token_id != signal.token_id:
            return "MALFORMED_ORDERBOOK"
        if any(
            not isfinite(level.price) or not isfinite(level.size) or level.price <= 0 or level.size <= 0
            for level in [*orderbook.asks, *orderbook.bids]
        ):
            return "MALFORMED_ORDERBOOK"
        return None

    def _stale_reason(self, token_id: str, orderbook: OrderBook, now: datetime) -> str | None:
        if self.registry is not None:
            if self.registry.is_fill_eligible(token_id, self.max_book_staleness_ms, now):
                return None
            state = self.registry.get_state(token_id)
            return state.stale_reason if state and state.stale_reason else "NO_SNAPSHOT"
        if not orderbook.is_fresh(self.max_book_staleness_ms, now):
            return "STALE_ORDERBOOK"
        return None

    def _edge_reason(
        self,
        signal: SignalCandidate,
        execution_ask: float,
        metrics: dict[str, bool | float | str | None],
    ) -> str | None:
        signal_metrics: dict[str, Any] = signal.metrics
        metrics["paper_edge_revalidated"] = False
        min_probability_edge = _finite_float(signal_metrics.get("min_probability_edge"))
        directional_probability = _finite_float(signal_metrics.get("directional_probability"))
        if min_probability_edge is not None and min_probability_edge > 0 and directional_probability is not None:
            current_edge = directional_probability - execution_ask
            metrics["paper_execution_probability_edge"] = current_edge
            metrics["paper_required_probability_edge"] = min_probability_edge
            metrics["paper_edge_revalidated"] = True
            if current_edge < min_probability_edge:
                return PAPER_EDGE_VANISHED
            return None
        min_token_price = _finite_float(signal_metrics.get("min_token_price"))
        if min_token_price is not None and min_token_price > 0:
            metrics["paper_execution_min_token_price"] = min_token_price
            metrics["paper_edge_revalidated"] = True
            if execution_ask < min_token_price:
                return PAPER_EDGE_VANISHED
        return None


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None
```

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_paper_execution_preflight.py::test_normalize_paper_reject_reason -v
```

Expected: PASS.

- [ ] **Step 3: Write failing tests for preflight rejection branches**

Append to `tests/test_paper_execution_preflight.py`:

```python

def _preflight(*, max_staleness_ms: int = 1000, require_depth_check: bool = True) -> PaperExecutionPreflight:
    return PaperExecutionPreflight(
        FillModelConfig(require_depth_check=require_depth_check, min_fill_ratio=1.0, reject_if_partial=True),
        max_book_staleness_ms=max_staleness_ms,
        fixed_stake_usdc=10.0,
    )


def test_preflight_rejects_missing_book_with_normalized_reason() -> None:
    decision = _preflight().evaluate(_signal(), None, utc_now())
    assert decision.accepted is False
    assert decision.reason_code == "PAPER_MISSING_ORDERBOOK"
    assert decision.metrics["paper_original_reason"] == "MISSING_ORDERBOOK"


def test_preflight_rejects_stale_book() -> None:
    now = utc_now()
    decision = _preflight(max_staleness_ms=100).evaluate(
        _signal(), _book(received_delta_ms=250), now
    )
    assert decision.accepted is False
    assert decision.reason_code == "PAPER_STALE_ORDERBOOK"
    assert decision.metrics["paper_orderbook_fresh"] is False


def test_preflight_rejects_price_moved_above_max_entry() -> None:
    decision = _preflight().evaluate(_signal(max_entry_price=0.55), _book(ask=0.61), utc_now())
    assert decision.accepted is False
    assert decision.reason_code == "PAPER_ENTRY_PRICE_MOVED"


def test_preflight_rejects_full_fill_depth_for_fok() -> None:
    decision = _preflight().evaluate(
        _signal(order_intent=OrderIntent.TAKER_FOK),
        _book(ask=0.50, size=5.0),
        utc_now(),
        OrderIntent.TAKER_FOK,
    )
    assert decision.accepted is False
    assert decision.reason_code == "PAPER_DEPTH_TOO_THIN"
    assert decision.metrics["paper_available_depth_usdc"] < 10.0


def test_preflight_allows_fak_partial_depth() -> None:
    decision = _preflight().evaluate(
        _signal(order_intent=OrderIntent.TAKER_FAK),
        _book(ask=0.50, size=5.0),
        utc_now(),
        OrderIntent.TAKER_FAK,
    )
    assert decision.accepted is True
    assert decision.metrics["paper_depth_revalidated"] is True


def test_preflight_passive_gtd_does_not_require_immediate_depth() -> None:
    decision = _preflight().evaluate(
        _signal(order_intent=OrderIntent.PASSIVE_GTD, max_entry_price=0.01),
        _book(ask=0.80, size=0.1),
        utc_now(),
        OrderIntent.PASSIVE_GTD,
    )
    assert decision.accepted is True
    assert decision.metrics["paper_depth_revalidated"] is False


def test_preflight_rejects_probability_edge_vanished() -> None:
    signal = _signal(
        max_entry_price=0.80,
        metrics={"directional_probability": 0.70, "min_probability_edge": 0.05},
    )
    decision = _preflight().evaluate(signal, _book(ask=0.68, size=100.0), utc_now())
    assert decision.accepted is False
    assert decision.reason_code == "PAPER_EDGE_VANISHED"
    assert decision.metrics["paper_edge_revalidated"] is True
```

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_paper_execution_preflight.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit preflight service**

```bash
git add src/polysignal_lab/paper/preflight.py tests/test_paper_execution_preflight.py
git commit -m "feat: add paper execution preflight"
```

---

### Task 2: Wire preflight into PaperSimulator without changing fill semantics

**Files:**
- Modify: `src/polysignal_lab/paper/simulator.py:1-187`
- Modify: `tests/test_paper_simulation.py:57-129`
- Modify: `tests/test_order_intent.py:145-301`

**Interfaces:**
- Consumes: `PaperExecutionPreflight.evaluate(...)`
- Produces: `PaperOrder.metrics["paper_normalized_reason"]` and `PaperOrder.metrics["paper_original_reason"]` for every paper rejection path.
- Preserves: `PaperSimulator.process_signal(signal, orderbook) -> SimulationResult`

- [ ] **Step 1: Write simulator tests for normalized paper reject metrics**

Update the existing assertions in `tests/test_paper_simulation.py`:

```python
async def test_paper_rejects_ask_above_max(snapshot, books, settings):
    sig = (await _signal(snapshot, settings)).model_copy(update={"max_entry_price": 0.50})
    wallet = PaperWallet(starting_balance=1000)
    sim = PaperSimulator(settings.paper_trading, settings.data.polymarket, wallet)
    result = sim.process_signal(sig, books.get(sig.token_id))
    assert result.order.status == "REJECTED"
    assert result.order.reject_reason == "PAPER_ENTRY_PRICE_MOVED"
    assert result.order.metrics["paper_original_reason"] == "ASK_ABOVE_MAX_ENTRY"
    assert result.order.metrics["paper_normalized_reason"] == "PAPER_ENTRY_PRICE_MOVED"
```

Add a probability-edge regression below the existing insufficient-depth test:

```python
async def test_paper_preflight_rejects_edge_vanished(snapshot, books, settings):
    sig = (await _signal(snapshot, settings)).model_copy(
        update={
            "max_entry_price": 0.90,
            "metrics": {"directional_probability": 0.83, "min_probability_edge": 0.05},
        }
    )
    wallet = PaperWallet(starting_balance=1000)
    sim = PaperSimulator(settings.paper_trading, settings.data.polymarket, wallet)

    result = sim.process_signal(sig, books.get(sig.token_id))

    assert result.order.status == "REJECTED"
    assert result.order.reject_reason == "PAPER_EDGE_VANISHED"
    assert result.fill is None
    assert result.position is None
    assert wallet.cash_balance == 1000.0
    assert result.order.metrics["paper_edge_revalidated"] is True
```

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_paper_simulation.py::test_paper_rejects_ask_above_max tests/test_paper_simulation.py::test_paper_preflight_rejects_edge_vanished -v
```

Expected: FAIL because simulator still returns raw `ASK_ABOVE_MAX_ENTRY` and has no edge preflight.

- [ ] **Step 2: Instantiate preflight in PaperSimulator**

In `src/polysignal_lab/paper/simulator.py`, add the import:

```python
from polysignal_lab.paper.preflight import PaperExecutionPreflight, normalize_paper_reject_reason
```

In `PaperSimulator.__init__`, after `self.fill_model = ...`, add:

```python
        self.preflight = PaperExecutionPreflight(
            config.fill_model,
            data_config.max_book_staleness_ms,
            config.fixed_stake_usdc,
            registry,
        )
```

Update `_reject_order` to normalize and preserve original reasons:

```python
    def _reject_order(self, order: PaperOrder, reason: str) -> None:
        normalized = normalize_paper_reject_reason(reason)
        order.status = OrderStatus.REJECTED
        order.reject_reason = normalized
        order.metrics.setdefault("fill_decision_accepted", False)
        order.metrics["fill_decision_reason"] = normalized
        order.metrics.setdefault("paper_original_reason", reason)
        order.metrics["paper_normalized_reason"] = normalized
```

Run the two tests from Step 1 again.

Expected: edge test still FAILS because `process_signal()` has not called preflight.

- [ ] **Step 3: Run preflight before fill/enqueue dispatch**

In `PaperSimulator.process_signal()`, after `intent = signal.order_intent` and before the `PASSIVE_GTD` branch, add:

```python
        preflight = self.preflight.evaluate(signal, orderbook, order.created_at, intent)
        order.metrics.update(preflight.metrics)
        if not preflight.accepted:
            self._reject_order(order, str(preflight.metrics.get("paper_original_reason") or preflight.reason_code))
            return SimulationResult(order=order, status=OrderStatus.REJECTED)
```

Remove the old special-case missing-book block at lines 79-81 because preflight now owns it:

```python
        if orderbook is None:
            self._reject_order(order, "MISSING_ORDERBOOK")
            return SimulationResult(order=order, status=OrderStatus.REJECTED)
```

Before the FAK/FOK and default fill branches, keep a local type guard so static readers know `orderbook` is not `None` after accepted preflight:

```python
        if orderbook is None:
            self._reject_order(order, "MISSING_ORDERBOOK")
            return SimulationResult(order=order, status=OrderStatus.REJECTED)
```

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_paper_simulation.py::test_paper_rejects_ask_above_max tests/test_paper_simulation.py::test_paper_preflight_rejects_edge_vanished -v
```

Expected: PASS.

- [ ] **Step 4: Preserve raw fill behavior for accepted orders**

Update `_decision_metrics()` in `src/polysignal_lab/paper/simulator.py` so fill-model metrics do not overwrite normalized paper preflight fields:

```python
        metrics: dict[str, bool | float | str | None] = {
            "fill_decision_accepted": decision.accepted,
            "fill_decision_reason": reason,
            "fill_original_reason": decision.reason_code,
            "orderbook_token_id": orderbook.token_id,
            "orderbook_fresh": orderbook.is_fresh(self.fill_model.max_book_staleness_ms, order.created_at),
            "orderbook_staleness_ms": float(orderbook.freshness_ms(order.created_at)),
            "raw_best_ask": orderbook.best_ask,
            "available_depth_usdc": decision.available_depth_usdc,
        }
```

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_paper_simulation.py::test_accepted_signal_fills_at_best_ask_and_updates_wallet -v
```

Expected: PASS; wallet balance, fill price, and shares stay unchanged.

- [ ] **Step 5: Add intent regression tests**

Append to `tests/test_order_intent.py`:

```python

def test_simulator_fak_allows_partial_preflight(settings):
    from polysignal_lab.paper.simulator import PaperSimulator
    from polysignal_lab.paper.wallet import PaperWallet

    sig = SignalCandidate.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="s", condition_id="c",
        token_id="t-up", side=Side.UP, confidence=0.6,
        entry_reference_price=0.35, max_entry_price=0.55,
        seconds_to_close=300, data_freshness_ms=100,
        reason_codes=["TEST"], metrics={},
        order_intent=OrderIntent.TAKER_FAK,
    )
    book = OrderBook(
        token_id="t-up",
        bids=[BookLevel(price=0.30, size=100)],
        asks=[BookLevel(price=0.50, size=5)],
        received_at=utc_now(),
    )
    result = PaperSimulator(settings.paper_trading, settings.data.polymarket, PaperWallet(1000)).process_signal(sig, book)
    assert result.order.status == OrderStatus.PARTIAL
    assert result.fill is not None
    assert result.fill.fill_ratio < 1.0
    assert result.order.metrics["paper_normalized_reason"] is None


def test_simulator_passive_gtd_preflight_does_not_require_taker_depth(settings):
    from polysignal_lab.paper.simulator import PaperSimulator
    from polysignal_lab.paper.wallet import PaperWallet

    sig = SignalCandidate.build(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="mkt-1", market_slug="s", condition_id="c",
        token_id="t-up", side=Side.UP, confidence=0.6,
        entry_reference_price=0.35, max_entry_price=0.35,
        seconds_to_close=300, data_freshness_ms=100,
        reason_codes=["TEST"], metrics={},
        order_intent=OrderIntent.PASSIVE_GTD,
        expiry_seconds=200,
    )
    book = OrderBook(
        token_id="t-up",
        bids=[BookLevel(price=0.30, size=100)],
        asks=[BookLevel(price=0.80, size=1)],
        received_at=utc_now(),
    )
    result = PaperSimulator(settings.paper_trading, settings.data.polymarket, PaperWallet(1000)).process_signal(sig, book)
    assert result.order.status == OrderStatus.RESTING
    assert result.order.metrics["paper_depth_revalidated"] is False
```

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_order_intent.py::test_simulator_fak_allows_partial_preflight tests/test_order_intent.py::test_simulator_passive_gtd_preflight_does_not_require_taker_depth -v
```

Expected: PASS.

- [ ] **Step 6: Run simulator and intent regression slice**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_paper_execution_preflight.py tests/test_paper_simulation.py tests/test_order_intent.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit simulator wiring**

```bash
git add src/polysignal_lab/paper/simulator.py tests/test_paper_simulation.py tests/test_order_intent.py
git commit -m "feat: route paper simulator through preflight"
```

---

### Task 3: Daily report aggregate fields from stored paper execution metrics

**Files:**
- Modify: `src/polysignal_lab/domain/paper_result.py:51-78`
- Modify: `src/polysignal_lab/paper/report.py:1-107`
- Modify: `tests/test_reporting.py:57-109`

**Interfaces:**
- Produces defaulted fields on `DailyReport`:
  - `paper_attempts_by_intent: dict[str, int]`
  - `paper_fills_by_intent: dict[str, int]`
  - `paper_partial_fills_by_intent: dict[str, int]`
  - `paper_rejects_by_reason: dict[str, int]`
  - `paper_rejects_by_original_reason: dict[str, int]`
  - `average_execution_staleness_ms: float | None`
  - `average_executable_depth_usdc: float | None`
  - `paper_execution_assumptions: dict[str, Any]`
- Modifies: `PaperReportService.build_daily_report(..., paper_order_payloads: Iterable[dict[str, Any]] = (), paper_fill_payloads: Iterable[dict[str, Any]] = (), paper_execution_assumptions: dict[str, Any] | None = None)`

- [ ] **Step 1: Write failing report aggregate test**

Add to `tests/test_reporting.py`:

```python

def test_daily_report_aggregates_paper_execution_quality() -> None:
    order_payloads = [
        {
            "paper_order_id": "po-fill",
            "status": "FILLED",
            "order_intent": "taker_fok",
            "metrics": {
                "paper_order_intent": "taker_fok",
                "paper_orderbook_staleness_ms": 42.0,
                "paper_available_depth_usdc": 50.0,
            },
        },
        {
            "paper_order_id": "po-partial",
            "status": "PARTIAL",
            "order_intent": "taker_fak",
            "metrics": {
                "paper_order_intent": "taker_fak",
                "paper_orderbook_staleness_ms": 64.0,
                "paper_available_depth_usdc": 4.0,
            },
        },
        {
            "paper_order_id": "po-reject",
            "status": "REJECTED",
            "order_intent": None,
            "reject_reason": "PAPER_ENTRY_PRICE_MOVED",
            "metrics": {
                "paper_order_intent": None,
                "paper_normalized_reason": "PAPER_ENTRY_PRICE_MOVED",
                "paper_original_reason": "ASK_ABOVE_MAX_ENTRY",
                "paper_orderbook_staleness_ms": 20.0,
                "paper_available_depth_usdc": 100.0,
            },
        },
    ]
    fill_payloads = [
        {"paper_order_id": "po-fill", "fill_ratio": 1.0},
        {"paper_order_id": "po-partial", "fill_ratio": 0.4},
    ]

    report = PaperReportService().build_daily_report(
        report_date=date(2026, 6, 22),
        starting_equity=1000.0,
        ending_equity=1000.0,
        total_signals=3,
        paper_orders=3,
        paper_fills=2,
        rejected_paper_orders=1,
        open_positions=1,
        results=[],
        paper_order_payloads=order_payloads,
        paper_fill_payloads=fill_payloads,
        paper_execution_assumptions={"slippage_bps": 25.0, "require_depth_check": True},
    )

    assert report.paper_attempts_by_intent == {"default": 1, "taker_fak": 1, "taker_fok": 1}
    assert report.paper_fills_by_intent == {"taker_fak": 1, "taker_fok": 1}
    assert report.paper_partial_fills_by_intent == {"taker_fak": 1}
    assert report.paper_rejects_by_reason == {"PAPER_ENTRY_PRICE_MOVED": 1}
    assert report.paper_rejects_by_original_reason == {"ASK_ABOVE_MAX_ENTRY": 1}
    assert report.average_execution_staleness_ms == 42.0
    assert report.average_executable_depth_usdc == 154.0 / 3
    assert report.paper_execution_assumptions["slippage_bps"] == 25.0
```

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_reporting.py::test_daily_report_aggregates_paper_execution_quality -v
```

Expected: FAIL with unexpected `paper_order_payloads` argument.

- [ ] **Step 2: Add DailyReport fields with backwards-compatible defaults**

In `src/polysignal_lab/domain/paper_result.py`, add these fields after `stale_paper_fills`:

```python
    paper_attempts_by_intent: dict[str, int] = Field(default_factory=dict)
    paper_fills_by_intent: dict[str, int] = Field(default_factory=dict)
    paper_partial_fills_by_intent: dict[str, int] = Field(default_factory=dict)
    paper_rejects_by_reason: dict[str, int] = Field(default_factory=dict)
    paper_rejects_by_original_reason: dict[str, int] = Field(default_factory=dict)
    average_execution_staleness_ms: float | None = None
    average_executable_depth_usdc: float | None = None
    paper_execution_assumptions: dict[str, Any] = Field(default_factory=dict)
```

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_storage_reporting_publish.py::test_formatter_result_and_daily_messages_are_paper_only -v
```

Expected: PASS; old `DailyReport(...)` construction stays valid.

- [ ] **Step 3: Add report aggregate helper**

In `src/polysignal_lab/paper/report.py`, update imports:

```python
from collections import Counter, defaultdict
from typing import Any, Iterable, assert_never
```

Update `build_daily_report()` signature after `stale_paper_fills: int = 0`:

```python
        paper_order_payloads: Iterable[dict[str, Any]] = (),
        paper_fill_payloads: Iterable[dict[str, Any]] = (),
        paper_execution_assumptions: dict[str, Any] | None = None,
```

Inside `build_daily_report()`, before `return DailyReport(...)`, add:

```python
        execution_aggregates = self._paper_execution_aggregates(
            paper_order_payloads,
            paper_fill_payloads,
            paper_execution_assumptions or {},
        )
```

Pass these fields into `DailyReport(...)` after `stale_paper_fills=stale_paper_fills`:

```python
            paper_attempts_by_intent=execution_aggregates["paper_attempts_by_intent"],
            paper_fills_by_intent=execution_aggregates["paper_fills_by_intent"],
            paper_partial_fills_by_intent=execution_aggregates["paper_partial_fills_by_intent"],
            paper_rejects_by_reason=execution_aggregates["paper_rejects_by_reason"],
            paper_rejects_by_original_reason=execution_aggregates["paper_rejects_by_original_reason"],
            average_execution_staleness_ms=execution_aggregates["average_execution_staleness_ms"],
            average_executable_depth_usdc=execution_aggregates["average_executable_depth_usdc"],
            paper_execution_assumptions=execution_aggregates["paper_execution_assumptions"],
```

Add this method to `PaperReportService` before `_breakdown()`:

```python
    def _paper_execution_aggregates(
        self,
        paper_orders: Iterable[dict[str, Any]],
        paper_fills: Iterable[dict[str, Any]],
        assumptions: dict[str, Any],
    ) -> dict[str, Any]:
        orders = list(paper_orders)
        fills = list(paper_fills)
        order_intents: dict[str, str] = {}
        attempts: Counter[str] = Counter()
        rejects: Counter[str] = Counter()
        original_rejects: Counter[str] = Counter()
        staleness_values: list[float] = []
        depth_values: list[float] = []
        for order in orders:
            metrics = order.get("metrics") if isinstance(order.get("metrics"), dict) else {}
            intent = str(metrics.get("paper_order_intent") or order.get("order_intent") or "default")
            order_id = str(order.get("paper_order_id") or "")
            if order_id:
                order_intents[order_id] = intent
            attempts[intent] += 1
            staleness = _optional_float(metrics.get("paper_orderbook_staleness_ms"))
            if staleness is not None:
                staleness_values.append(staleness)
            depth = _optional_float(metrics.get("paper_available_depth_usdc"))
            if depth is not None:
                depth_values.append(depth)
            if order.get("status") == "REJECTED":
                normalized = str(metrics.get("paper_normalized_reason") or order.get("reject_reason") or "PAPER_FILL_REJECTED")
                original = str(metrics.get("paper_original_reason") or order.get("reject_reason") or "UNKNOWN")
                rejects[normalized] += 1
                original_rejects[original] += 1
        fills_by_intent: Counter[str] = Counter()
        partial_by_intent: Counter[str] = Counter()
        for fill in fills:
            order_id = str(fill.get("paper_order_id") or "")
            intent = order_intents.get(order_id, "default")
            fills_by_intent[intent] += 1
            fill_ratio = _optional_float(fill.get("fill_ratio"))
            if fill_ratio is not None and fill_ratio < 0.999:
                partial_by_intent[intent] += 1
        return {
            "paper_attempts_by_intent": dict(sorted(attempts.items())),
            "paper_fills_by_intent": dict(sorted(fills_by_intent.items())),
            "paper_partial_fills_by_intent": dict(sorted(partial_by_intent.items())),
            "paper_rejects_by_reason": dict(sorted(rejects.items())),
            "paper_rejects_by_original_reason": dict(sorted(original_rejects.items())),
            "average_execution_staleness_ms": _average(staleness_values),
            "average_executable_depth_usdc": _average(depth_values),
            "paper_execution_assumptions": dict(sorted(assumptions.items())),
        }
```

Add module helpers near `_is_closed_result()`:

```python

def _optional_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None
```

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_reporting.py::test_daily_report_aggregates_paper_execution_quality tests/test_reporting.py::test_daily_report_includes_strategy_win_rate_and_pnl -v
```

Expected: PASS.

- [ ] **Step 4: Commit report aggregates**

```bash
git add src/polysignal_lab/domain/paper_result.py src/polysignal_lab/paper/report.py tests/test_reporting.py
git commit -m "feat: aggregate paper execution report metrics"
```

---

### Task 4: Propagate aggregates through scheduler, dashboard, and Telegram report

**Files:**
- Modify: `src/polysignal_lab/app/scheduler_reporting.py:161-220`
- Modify: `src/polysignal_lab/dashboard/app.py:45-260`
- Modify: `src/polysignal_lab/signal_layer/formatter.py:57-82`
- Modify: `tests/test_scheduler_reports.py:172-225`
- Modify: `tests/test_dashboard.py`
- Modify: `tests/test_storage_reporting_publish.py:190-280`

**Interfaces:**
- Consumes: stored `paper_orders` / `paper_fills` payloads from `SQLiteStore.query_json()`.
- Produces: `/api/overview["latest_report"]` containing new aggregate fields.
- Produces: new read-only `/api/paper-orders?status=&limit=` endpoint.
- Produces: dashboard home summary showing filled/rejected/average staleness from latest report.
- Produces: daily Telegram report lines for paper orders, rejects, and average execution staleness.

- [ ] **Step 1: Update scheduler daily report test expectations**

In `tests/test_scheduler_reports.py::test_daily_report_publish_record_written`, add assertions after `assert report.stale_paper_fills == 0`:

```python
    assert report.paper_attempts_by_intent == {"default": 2}
    assert report.paper_fills_by_intent == {"default": 1}
    assert report.paper_rejects_by_reason == {"PAPER_MISSING_ORDERBOOK": 1}
    assert report.paper_rejects_by_original_reason == {"MISSING_ORDERBOOK": 1}
    assert report.average_execution_staleness_ms is not None
    assert report.average_executable_depth_usdc is not None
    assert report.paper_execution_assumptions == {
        "max_book_staleness_ms": settings.data.polymarket.max_book_staleness_ms,
        "min_fill_ratio": settings.paper_trading.fill_model.min_fill_ratio,
        "reject_if_partial": settings.paper_trading.fill_model.reject_if_partial,
        "require_depth_check": settings.paper_trading.fill_model.require_depth_check,
        "slippage_bps": settings.paper_trading.fill_model.slippage_bps,
    }
```

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_scheduler_reports.py::test_daily_report_publish_record_written -v
```

Expected: FAIL because scheduler does not pass raw order/fill payloads or assumptions.

- [ ] **Step 2: Pass raw payloads and assumptions from scheduler**

In `src/polysignal_lab/app/scheduler_reporting.py`, before `PaperReportService().build_daily_report(...)`, add:

```python
    fill_cfg = scheduler.settings.paper_trading.fill_model
    paper_execution_assumptions = {
        "max_book_staleness_ms": scheduler.settings.data.polymarket.max_book_staleness_ms,
        "min_fill_ratio": fill_cfg.min_fill_ratio,
        "reject_if_partial": fill_cfg.reject_if_partial,
        "require_depth_check": fill_cfg.require_depth_check,
        "slippage_bps": fill_cfg.slippage_bps,
    }
```

Add these arguments to `build_daily_report(...)`:

```python
            paper_order_payloads=today_orders_raw,
            paper_fill_payloads=today_fills_raw,
            paper_execution_assumptions=paper_execution_assumptions,
```

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_scheduler_reports.py::test_daily_report_publish_record_written -v
```

Expected: PASS.

- [ ] **Step 3: Add dashboard endpoint and overview/home coverage**

In `tests/test_dashboard.py`, add a test that stores a rejected paper order and a daily report, then verifies `/api/paper-orders`, `/api/overview`, and dashboard HTML:

```python

def test_dashboard_exposes_paper_execution_quality(tmp_path):
    from fastapi.testclient import TestClient
    from polysignal_lab.dashboard.app import create_dashboard_app
    from polysignal_lab.domain.enums import OrderStatus, Side
    from polysignal_lab.domain.paper_order import PaperOrder
    from polysignal_lab.domain.paper_result import DailyReport
    from polysignal_lab.storage.sqlite_store import SQLiteStore
    from datetime import date

    store = SQLiteStore(tmp_path / "db.sqlite3")
    order = PaperOrder(
        paper_order_id="po-rejected-dashboard",
        signal_id="sig-dashboard",
        asset="BTC",
        timeframe="5m",
        strategy="ptb_diff",
        market_id="mkt-1",
        market_slug="btc-updown-5m",
        token_id="token-up",
        side=Side.UP,
        limit_price=0.60,
        reference_price=0.50,
        stake_usdc=10.0,
        status=OrderStatus.REJECTED,
        reject_reason="PAPER_ENTRY_PRICE_MOVED",
        metrics={"paper_normalized_reason": "PAPER_ENTRY_PRICE_MOVED", "paper_original_reason": "ASK_ABOVE_MAX_ENTRY"},
    )
    report = DailyReport(
        report_date=date(2026, 6, 22),
        starting_equity=1000.0,
        ending_equity=1000.0,
        paper_pnl=0.0,
        paper_roi=0.0,
        total_signals=1,
        paper_orders=1,
        paper_fills=0,
        rejected_paper_orders=1,
        open_positions=0,
        closed_positions=0,
        win_count=0,
        loss_count=0,
        void_count=0,
        win_rate=0.0,
        total_pnl_usdc=0.0,
        average_roi=0.0,
        max_drawdown=0.0,
        profit_factor=None,
        paper_rejects_by_reason={"PAPER_ENTRY_PRICE_MOVED": 1},
        average_execution_staleness_ms=25.0,
    )
    store.insert_paper_order(order)
    store.insert_daily_report(report)
    client = TestClient(create_dashboard_app(store))

    orders = client.get("/api/paper-orders", params={"status": "rejected"})
    overview = client.get("/api/overview")
    html = client.get("/")

    assert orders.status_code == 200
    assert orders.json()[0]["reject_reason"] == "PAPER_ENTRY_PRICE_MOVED"
    assert overview.json()["latest_report"]["paper_rejects_by_reason"] == {"PAPER_ENTRY_PRICE_MOVED": 1}
    assert "Paper rejects" in html.text
    assert "PAPER_ENTRY_PRICE_MOVED" in html.text
```

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_dashboard.py::test_dashboard_exposes_paper_execution_quality -v
```

Expected: FAIL because `/api/paper-orders` does not exist and HTML does not show fields.

- [ ] **Step 4: Implement dashboard endpoint and summary fields**

In `src/polysignal_lab/dashboard/app.py`, add endpoint after `/api/rejected-signals`:

```python
    @app.get("/api/paper-orders", response_model=None)
    def paper_orders(status: str | None = None, limit: int = 100) -> list[dict[str, JsonValue]]:
        if status:
            return store.query_json(
                "paper_orders",
                where="WHERE status=?",
                params=(status.upper(),),
                limit=_bounded_limit(limit),
            )
        return store.query_json("paper_orders", limit=_bounded_limit(limit))
```

In `home()`, build a compact execution-quality fragment before `report_summary`:

```python
        reject_reason_rows = ""
        if report:
            rejects = report.get("paper_rejects_by_reason", {})
            if isinstance(rejects, dict) and rejects:
                reject_reason_rows = "".join(
                    f"<li><code>{_text(reason)}</code>: {_text(count)}</li>"
                    for reason, count in sorted(rejects.items())
                )
        execution_summary = (
            f"<div><dt>Paper fills</dt><dd>{_text(report.get('paper_fills', 0))}</dd></div>"
            f"<div><dt>Paper rejects</dt><dd>{_text(report.get('rejected_paper_orders', 0))}</dd></div>"
            f"<div><dt>Avg exec lag</dt><dd>{_text(report.get('average_execution_staleness_ms', 'n/a'))} ms</dd></div>"
            if report
            else ""
        )
        reject_summary = (
            f"<div><dt>Reject reasons</dt><dd><ul>{reject_reason_rows}</ul></dd></div>"
            if reject_reason_rows
            else ""
        )
```

Update `report_summary` so the `<dl class='summary'>` includes `{execution_summary}{reject_summary}` after Paper PnL:

```python
        report_summary = (
            f"<dl class='summary'><div><dt>Report date</dt><dd>{_text(report.get('report_date', ''))}</dd></div>"
            f"<div><dt>Total signals</dt><dd>{_text(report.get('total_signals', 0))}</dd></div>"
            f"<div><dt>Closed positions</dt><dd>{_text(report.get('closed_positions', 0))}</dd></div>"
            f"<div><dt>Paper PnL</dt><dd>{_fmt_money(report.get('total_pnl_usdc', 0.0))}</dd></div>"
            f"{execution_summary}{reject_summary}</dl>"
            if report
            else "<p class='muted'>No daily report has been stored yet.</p>"
        )
```

Add the endpoint link to the nav list:

```html
<li><a href="/api/paper-orders">Paper Orders JSON</a></li>
```

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_dashboard.py::test_dashboard_exposes_paper_execution_quality -v
```

Expected: PASS.

- [ ] **Step 5: Update daily Telegram report formatter**

In `tests/test_storage_reporting_publish.py::test_formatter_result_and_daily_messages_are_paper_only`, add aggregate fields to the constructed `DailyReport`:

```python
        paper_rejects_by_reason={"PAPER_ENTRY_PRICE_MOVED": 1},
        average_execution_staleness_ms=25.0,
```

Add assertions after `assert "Signals " in daily_message`:

```python
    assert "Orders  " in daily_message
    assert "Rejects " in daily_message
    assert "ExecLag " in daily_message
    assert "PAPER_ENTRY_PRICE_MOVED" in daily_message
```

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_storage_reporting_publish.py::test_formatter_result_and_daily_messages_are_paper_only -v
```

Expected: FAIL because formatter does not include execution quality lines.

In `src/polysignal_lab/signal_layer/formatter.py`, update `daily_report_message()` before `message = f"""...`:

```python
        reject_text = "none"
        if report.paper_rejects_by_reason:
            reject_text = ", ".join(
                f"{reason}:{count}" for reason, count in sorted(report.paper_rejects_by_reason.items())
            )
        exec_lag = "n/a" if report.average_execution_staleness_ms is None else f"{report.average_execution_staleness_ms:.0f} ms"
```

Add lines after `Signals {report.total_signals}`:

```python
Orders  {report.paper_orders}
Rejects {report.rejected_paper_orders} ({reject_text})
ExecLag {exec_lag}
```

Run:

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_storage_reporting_publish.py::test_formatter_result_and_daily_messages_are_paper_only tests/test_reporting.py::test_daily_report_includes_strategy_win_rate_and_pnl -v
```

Expected: PASS.

- [ ] **Step 6: Run reporting/dashboard slice**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_reporting.py tests/test_scheduler_reports.py tests/test_storage_reporting_publish.py tests/test_dashboard.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit propagation work**

```bash
git add src/polysignal_lab/app/scheduler_reporting.py src/polysignal_lab/dashboard/app.py src/polysignal_lab/signal_layer/formatter.py tests/test_scheduler_reports.py tests/test_dashboard.py tests/test_storage_reporting_publish.py
git commit -m "feat: surface paper execution quality"
```

---

### Task 5: Final verification and runtime rebuild

**Files:**
- Verify: `src/polysignal_lab/paper/preflight.py`
- Verify: `src/polysignal_lab/paper/simulator.py`
- Verify: `src/polysignal_lab/paper/report.py`
- Verify: `src/polysignal_lab/app/scheduler_reporting.py`
- Verify: `src/polysignal_lab/dashboard/app.py`
- Verify: `src/polysignal_lab/signal_layer/formatter.py`
- Verify: touched tests

**Interfaces:**
- Verifies: all added behavior and project safety gates.
- Produces: rebuilt formal Docker runtime using the new code.

- [ ] **Step 1: Run focused behavioral tests**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_paper_execution_preflight.py tests/test_paper_simulation.py tests/test_order_intent.py tests/test_reporting.py tests/test_scheduler_reports.py tests/test_storage_reporting_publish.py tests/test_dashboard.py -v
```

Expected: PASS.

- [ ] **Step 2: Run safety and full regression gates**

```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_safety.py -v
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest -v
```

Expected: PASS for safety scan and full pytest suite.

- [ ] **Step 3: Rebuild formal Docker runtime**

```bash
docker compose up -d --build --force-recreate
```

Expected: build completes and containers recreate without errors.

- [ ] **Step 4: Verify rebuilt runtime health**

```bash
docker compose ps
docker compose logs --tail=120
```

Expected: services are `Up`; logs show normal startup and no repeated stack traces. If the dashboard service is running, verify `/health` with the existing project health command or browser and confirm counts render.

- [ ] **Step 5: Confirm no unplanned file changes remain**

Task 5 is verification-only. If Docker/runtime verification creates local logs, databases, or cache files, leave them untracked and do not commit them. Expected tracked file set remains the files committed in Tasks 1-4.

---

## Self-Review

1. **Spec coverage:** Covered preflight, missing/stale/depth/max-entry/edge checks, stable `PAPER_*` reason surface, persistence via existing `paper_orders` payload JSON, daily report aggregates, dashboard payloads, and rollout tests. No live trading or authenticated CLOB path added.
2. **Current-code caveat handled:** The spec listed representative reason codes; current code also emits `MAX_OPEN_POSITIONS_REACHED`, `NO_SNAPSHOT`, `MALFORMED_ORDERBOOK`, and `GTD_EXPIRED`. Task 1 maps those so every current paper rejection has a stable report reason.
3. **Intent consistency:** Task 1 and Task 2 preserve current intent semantics: default taker uses configured slippage/depth, FAK can partial-fill, FOK requires full depth, PASSIVE_GTD does not require immediate taker depth.
4. **Type consistency:** `PaperExecutionDecision`, `PaperExecutionPreflight.evaluate()`, `normalize_paper_reject_reason()`, and new `DailyReport` fields are named consistently across tests, implementation snippets, scheduler propagation, formatter, and dashboard.
5. **No placeholder markers:** The plan contains concrete files, commands, expected outcomes, and code snippets for each implementation task.
