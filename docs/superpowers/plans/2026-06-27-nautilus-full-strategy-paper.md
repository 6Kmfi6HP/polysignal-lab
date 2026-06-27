# Nautilus Full Strategy Paper Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Polymarket strategy triggering, signal generation, order submission, paper execution, fills, positions, account state, and cache ownership into NautilusTrader while keeping PolySignal alpha algorithms as pure decision logic.

**Architecture:** Use Nautilus `TradingNode` as the default paper runtime. Polymarket market data enters Nautilus `DataEngine`; Nautilus strategy wrappers call existing PolySignal alpha cores inside Nautilus callbacks; orders are submitted through Nautilus order factory and matched by Nautilus sandbox execution. PolySignal reports, Telegram, and health become read-only projections from Nautilus cache/events.

**Tech Stack:** Python 3.11 base project, optional `nautilus_trader[polymarket]==1.229.0` for Python >= 3.12, pytest, existing PolySignal alpha core modules, Nautilus `TradingNode`, `PolymarketDataClientConfig`, `PolymarketLiveDataClientFactory`, `SandboxExecutionClientConfig`, `SandboxLiveExecClientFactory`, `Strategy`, and `StrategyConfig`.

## Global Constraints

- Default runtime must not use live Polymarket execution.
- Default runtime uses real Polymarket market data plus Nautilus sandbox/simulated execution.
- PolySignal keeps only alpha algorithm code, configuration, Telegram/health/report projections.
- NautilusTrader owns market data ingestion, strategy lifecycle, signal generation location, order submission, paper matching, fills, positions, account state, and cache.
- No new strategy algorithms.
- No second paper wallet or second position ledger.
- The default import of `polysignal_lab` must not require NautilusTrader.
- Keep `nautilus_trader[polymarket]==1.229.0; python_version >= '3.12'` in the optional `nautilus` extra unless a separate dependency review approves a version change.
- Safety checks must prove the default runtime cannot submit real Polymarket orders.

---

## File Structure

- Create `src/polysignal_lab/nautilus_runtime/native_order.py`
  - Converts approved PolySignal decisions into Nautilus-native orders and calls `submit_order()`.
  - Uses `order_spec_from_decision()` only as a validation and sizing bridge during migration; the public output is a Nautilus order object.

- Create `src/polysignal_lab/nautilus_runtime/native_strategy.py`
  - Contains Nautilus `StrategyConfig` and `Strategy` subclasses.
  - Owns `on_start`, `on_data`, and order-event callbacks.
  - Calls existing alpha cores inside Nautilus callbacks.

- Create `src/polysignal_lab/nautilus_runtime/trading_node.py`
  - Builds `TradingNodeConfig` with Polymarket data client and sandbox execution client.
  - Registers `PolymarketLiveDataClientFactory` and `SandboxLiveExecClientFactory`.
  - Refuses live Polymarket execution clients in paper mode.

- Create `src/polysignal_lab/nautilus_runtime/projections.py`
  - Reads Nautilus cache/events and exposes report/Telegram/health projection rows.
  - Does not submit orders or mutate trading state.

- Modify `src/polysignal_lab/nautilus_runtime/node.py`
  - Replace component-dict/orchestrator default path with `TradingNode` runtime path.
  - Keep CLI entrypoint names stable.

- Modify `src/polysignal_lab/nautilus_runtime/strategies/__init__.py`
  - Export native strategy builders without importing Nautilus at default package import time.

- Modify `src/polysignal_lab/nautilus_runtime/order_mapping.py`
  - Keep validation behavior but stop treating `NautilusOrderSpec` as the runtime submission contract.

- Modify `tests/test_nautilus_node.py`
  - Replace component-dict assertions with TradingNode/sandbox config assertions.

- Modify `tests/test_nautilus_strategy_base.py`
  - Add native-strategy callback tests and mark old `evaluate_all_conditions()` tests as compatibility-only until removal.

- Create `tests/test_nautilus_native_order.py`
  - Tests decision-to-Nautilus-order mapping through a fake strategy and fake order factory.

- Create `tests/test_nautilus_trading_node_runtime.py`
  - Tests `TradingNodeConfig` composition, data client factory registration, sandbox execution factory registration, and live-exec rejection.

- Create `tests/test_nautilus_projections.py`
  - Tests reports/Telegram rows are derived from fake Nautilus cache/events without `PaperWallet`.

- Modify `tests/test_nautilus_platform_boundary.py` and `tests/test_nautilus_safety_boundary.py`
  - Tighten forbidden-source checks so default runtime cannot import or configure `PolymarketExecutionClient` / `PolymarketLiveExecClientFactory`.

---

### Task 1: Nautilus-native order submission bridge

**Files:**
- Create: `src/polysignal_lab/nautilus_runtime/native_order.py`
- Test: `tests/test_nautilus_native_order.py`
- Reference: `src/polysignal_lab/nautilus_runtime/order_mapping.py`

**Interfaces:**
- Consumes: `ApprovedDecision`, `order_spec_from_decision()`, `OrderIntent`, `Side`.
- Produces: `submit_approved_decision(strategy, approved, *, fixed_stake_usdc, best_ask, available_shares, instrument_id_resolver) -> object`.

- [ ] **Step 1: Write failing tests for Nautilus order submission**

Create `tests/test_nautilus_native_order.py` with this content:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace

from polysignal_lab.alpha.types import AlphaDecision, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import ApprovedDecision
from polysignal_lab.nautilus_runtime.native_order import submit_approved_decision


@dataclass(slots=True)
class FakeOrder:
    instrument_id: str
    order_side: str
    quantity: float
    price: float
    time_in_force: str
    expire_time: object | None
    tags: list[str]


class FakeOrderFactory:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def limit(self, **kwargs):
        self.calls.append(kwargs)
        return FakeOrder(**kwargs)


class FakeStrategy:
    def __init__(self) -> None:
        self.order_factory = FakeOrderFactory()
        self.submitted: list[FakeOrder] = []

    def submit_order(self, order: FakeOrder) -> None:
        self.submitted.append(order)


def _approved(intent: OrderIntent = OrderIntent.TAKER_IOC) -> ApprovedDecision:
    signal = SignalCandidate.build(
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        token_id="up-token",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.50,
        max_entry_price=0.52,
        seconds_to_close=60,
        data_freshness_ms=20,
        reason_codes=["TEST"],
        metrics={},
        order_intent=intent,
        expiry_seconds=45 if intent == OrderIntent.PASSIVE_GTD else None,
        pair_id="pair-1",
        hedge_leg=False,
    )
    return ApprovedDecision(signal=signal)


def test_submit_approved_decision_submits_limit_order_through_strategy() -> None:
    strategy = FakeStrategy()

    order = submit_approved_decision(
        strategy,
        _approved(OrderIntent.TAKER_IOC),
        fixed_stake_usdc=10.0,
        best_ask=0.50,
        available_shares=100.0,
        instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
    )

    assert order is strategy.submitted[0]
    assert order.instrument_id == "up-token.POLYMARKET"
    assert order.order_side == "BUY"
    assert order.quantity == 20.0
    assert order.price == 0.50
    assert order.time_in_force == "IOC"
    assert order.expire_time is None
    assert "strategy=ptb_diff" in order.tags
    assert "condition_id=condition-btc-5m" in order.tags


def test_submit_approved_decision_maps_passive_gtd_expiry() -> None:
    strategy = FakeStrategy()

    order = submit_approved_decision(
        strategy,
        _approved(OrderIntent.PASSIVE_GTD),
        fixed_stake_usdc=10.0,
        best_ask=0.50,
        available_shares=100.0,
        instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
        now=lambda: datetime(2026, 6, 27, tzinfo=UTC),
    )

    assert order.time_in_force == "GTD"
    assert order.expire_time == datetime(2026, 6, 27, 0, 0, 45, tzinfo=UTC)


def test_submit_approved_decision_fok_rejects_insufficient_depth_before_submit() -> None:
    strategy = FakeStrategy()

    try:
        submit_approved_decision(
            strategy,
            _approved(OrderIntent.TAKER_FOK),
            fixed_stake_usdc=10.0,
            best_ask=0.50,
            available_shares=1.0,
            instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
        )
    except ValueError as exc:
        assert "insufficient depth" in str(exc)
    else:
        raise AssertionError("expected insufficient depth rejection")

    assert strategy.submitted == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_nautilus_native_order.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'polysignal_lab.nautilus_runtime.native_order'`.

- [ ] **Step 3: Implement minimal native order bridge**

Create `src/polysignal_lab/nautilus_runtime/native_order.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.nautilus_runtime.decision_policy import ApprovedDecision
from polysignal_lab.nautilus_runtime.order_mapping import order_spec_from_decision


def submit_approved_decision(
    strategy: Any,
    approved: ApprovedDecision,
    *,
    fixed_stake_usdc: float,
    best_ask: float | None,
    available_shares: float | None,
    instrument_id_resolver: Callable[[str], Any],
    now: Callable[[], datetime] | None = None,
) -> Any:
    """Create and submit a Nautilus-native order from an approved alpha decision."""

    spec = order_spec_from_decision(
        approved,
        fixed_stake_usdc=fixed_stake_usdc,
        best_ask=best_ask,
        available_shares=available_shares,
    )
    instrument_id = instrument_id_resolver(spec.instrument_id)
    order_side = _order_side(spec.side, reduce_only=spec.reduce_only)
    time_in_force = _time_in_force(spec.intent)
    expire_time = None
    if spec.intent == OrderIntent.PASSIVE_GTD:
        clock = now or (lambda: datetime.now(UTC))
        expire_time = clock() + timedelta(seconds=spec.expiry_seconds or 300)

    order = strategy.order_factory.limit(
        instrument_id=instrument_id,
        order_side=order_side,
        quantity=spec.quantity,
        price=spec.price,
        time_in_force=time_in_force,
        expire_time=expire_time,
        tags=[f"{key}={value}" for key, value in sorted(spec.tags.items())],
    )
    strategy.submit_order(order)
    return order


def _order_side(side: Side, *, reduce_only: bool) -> str:
    if reduce_only:
        return "SELL"
    if side in {Side.UP, Side.DOWN}:
        return "BUY"
    raise ValueError(f"unsupported side for Nautilus order: {side}")


def _time_in_force(intent: OrderIntent) -> str:
    if intent == OrderIntent.PASSIVE_GTD:
        return "GTD"
    if intent == OrderIntent.TAKER_FOK:
        return "FOK"
    return "IOC"
```

- [ ] **Step 4: Run task tests**

Run:

```bash
pytest tests/test_nautilus_native_order.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit task 1**

```bash
git add src/polysignal_lab/nautilus_runtime/native_order.py tests/test_nautilus_native_order.py
git commit -m "feat: submit alpha decisions as Nautilus orders"
```

---

### Task 2: Nautilus Strategy wrapper owns signal generation

**Files:**
- Create: `src/polysignal_lab/nautilus_runtime/native_strategy.py`
- Modify: `src/polysignal_lab/nautilus_runtime/strategies/__init__.py`
- Test: `tests/test_nautilus_strategy_base.py`

**Interfaces:**
- Consumes: `DecisionPolicyActor.evaluate(decision, view)`, `MarketViewAssembler.build(condition_id)`, `submit_approved_decision()`.
- Produces: `PolySignalNativeStrategyConfig`, `PolySignalNativeStrategy`, `build_native_strategy(...) -> PolySignalNativeStrategy`.

- [ ] **Step 1: Add failing callback-driven strategy tests**

Append these tests to `tests/test_nautilus_strategy_base.py`:

```python

def test_native_strategy_generates_signal_from_on_data_callback() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.order_factory = FakeOrderFactoryForNative()
            self.submitted = []
            self.subscriptions = []

        def submit_order(self, order):
            self.submitted.append(order)

        def subscribe_data(self, data_type):
            self.subscriptions.append(data_type)

    class FakeOrderFactoryForNative:
        def limit(self, **kwargs):
            return kwargs

    class DataEvent:
        condition_id = "condition-btc-5m"

    strategy = FakeNativeStrategy(
        core=FakeCore([_decision()]),
        assembler=FakeAssembler(_MockView()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        fixed_stake_usdc=10.0,
        instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
    )

    strategy.on_data(DataEvent())

    assert len(strategy.submitted) == 1
    assert strategy.submitted[0]["instrument_id"] == "up-token.POLYMARKET"
    assert strategy.submitted[0]["time_in_force"] == "GTD"
    assert strategy.submitted_specs == []
    assert strategy.execution_results == []


def test_native_strategy_on_start_subscribes_configured_data_names() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.subscriptions = []

        def subscribe_data(self, data_type):
            self.subscriptions.append(data_type)

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=FakeAssembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        data_names=("quote_ticks", "trade_ticks"),
    )

    strategy.on_start()

    assert strategy.subscriptions == ["quote_ticks", "trade_ticks"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_nautilus_strategy_base.py::test_native_strategy_generates_signal_from_on_data_callback tests/test_nautilus_strategy_base.py::test_native_strategy_on_start_subscribes_configured_data_names -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'polysignal_lab.nautilus_runtime.native_strategy'`.

- [ ] **Step 3: Implement callback-driven strategy wrapper**

Create `src/polysignal_lab/nautilus_runtime/native_strategy.py`:

```python
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from polysignal_lab.alpha.types import AlphaCore, MarketView
from polysignal_lab.nautilus_runtime.decision_policy import ApprovedDecision, DecisionPolicyActor, RejectedDecision
from polysignal_lab.nautilus_runtime.native_order import submit_approved_decision

DEFAULT_NATIVE_DATA_NAMES = ("quote_ticks", "trade_ticks", "order_book_deltas")


class PolySignalNativeStrategy:
    """Nautilus callback-shaped strategy wrapper around a PolySignal alpha core."""

    def __init__(
        self,
        *,
        core: AlphaCore,
        assembler: Any,
        condition_ids: Sequence[str],
        strategy_name: str,
        policy: DecisionPolicyActor | None = None,
        fixed_stake_usdc: float = 10.0,
        data_names: Sequence[str] = DEFAULT_NATIVE_DATA_NAMES,
        instrument_id_resolver: Callable[[str], Any] | None = None,
    ) -> None:
        self.core = core
        self.assembler = assembler
        self.condition_ids = tuple(condition_ids)
        self.strategy_name = strategy_name
        self.policy = policy or DecisionPolicyActor()
        self.fixed_stake_usdc = fixed_stake_usdc
        self.data_names = tuple(data_names)
        self.instrument_id_resolver = instrument_id_resolver or (lambda token_id: token_id)
        self.rejected_decisions: list[RejectedDecision] = []
        self.submitted_orders: list[Any] = []

    def on_start(self) -> None:
        for name in self.data_names:
            self.subscribe_data(name)

    def on_data(self, data: object) -> None:
        updater = getattr(self.assembler, "on_data", None) or getattr(self.assembler, "update", None)
        if callable(updater):
            updater(data)
        condition_id = getattr(data, "condition_id", None)
        if condition_id is not None:
            self.evaluate_condition(str(condition_id))
            return
        for candidate in self.condition_ids:
            self.evaluate_condition(candidate)

    def evaluate_condition(self, condition_id: str) -> None:
        view = self.assembler.build(condition_id)
        if view is None:
            return
        for decision in self.core.evaluate(view):
            policy_result = self.policy.evaluate(decision, view)
            if isinstance(policy_result, ApprovedDecision):
                order = self._submit_approved(policy_result, view=view)
                self.submitted_orders.append(order)
            else:
                self.rejected_decisions.append(policy_result)

    def _submit_approved(self, approved: ApprovedDecision, *, view: MarketView) -> Any:
        signal = approved.signal
        book = view.book_for(signal.side)
        return submit_approved_decision(
            self,
            approved,
            fixed_stake_usdc=self.fixed_stake_usdc,
            best_ask=book.best_ask,
            available_shares=_visible_ask_shares(book.ask_levels, signal.max_entry_price),
            instrument_id_resolver=self.instrument_id_resolver,
        )

    def subscribe_data(self, data_type: object) -> None:
        method = getattr(self, f"subscribe_{data_type}", None)
        if callable(method):
            for condition_id in self.condition_ids:
                method(condition_id)


def _visible_ask_shares(levels: Sequence[tuple[float, float]], limit_price: float | None) -> float | None:
    if not levels or limit_price is None:
        return None
    return sum(float(size) for price, size in levels if float(price) <= limit_price)
```

- [ ] **Step 4: Add export without forcing default Nautilus import**

Modify `src/polysignal_lab/nautilus_runtime/strategies/__init__.py` to add this import near the other runtime strategy exports:

```python
from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
```

Add `"PolySignalNativeStrategy"` to `__all__` if `__all__` exists in the file.

- [ ] **Step 5: Run task tests**

Run:

```bash
pytest tests/test_nautilus_strategy_base.py::test_native_strategy_generates_signal_from_on_data_callback tests/test_nautilus_strategy_base.py::test_native_strategy_on_start_subscribes_configured_data_names tests/test_nautilus_platform_boundary.py::test_default_import_does_not_require_nautilus -q
```

Expected: PASS.

- [ ] **Step 6: Commit task 2**

```bash
git add src/polysignal_lab/nautilus_runtime/native_strategy.py src/polysignal_lab/nautilus_runtime/strategies/__init__.py tests/test_nautilus_strategy_base.py
git commit -m "feat: move signal generation into strategy callbacks"
```

---

### Task 3: TradingNode config with Polymarket data and sandbox execution

**Files:**
- Create: `src/polysignal_lab/nautilus_runtime/trading_node.py`
- Test: `tests/test_nautilus_trading_node_runtime.py`
- Modify: `tests/test_nautilus_safety_boundary.py`

**Interfaces:**
- Consumes: `Settings`, `settings.paper_trading.starting_balance_usdc`, `settings.runtime.nautilus.matching_accuracy_mode`, `settings.data.polymarket.max_book_staleness_ms`.
- Produces: `build_paper_trading_node_config(settings, *, instrument_config) -> object`, `register_paper_factories(node) -> None`, `assert_no_live_polymarket_execution(config) -> None`.

- [ ] **Step 1: Write failing TradingNode config tests**

Create `tests/test_nautilus_trading_node_runtime.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

import pytest

from polysignal_lab.config import Settings
from polysignal_lab.nautilus_runtime.trading_node import (
    PAPER_EXEC_CLIENT_ID,
    assert_no_live_polymarket_execution,
    build_paper_trading_node_config,
    register_paper_factories,
)


class FakeNode:
    def __init__(self) -> None:
        self.data_factories = []
        self.exec_factories = []

    def add_data_client_factory(self, name, factory):
        self.data_factories.append((name, factory))

    def add_exec_client_factory(self, name, factory):
        self.exec_factories.append((name, factory))


def test_build_paper_trading_node_config_uses_polymarket_data_and_sandbox_exec() -> None:
    settings = Settings()
    settings.paper_trading.starting_balance_usdc = 1234.0

    config = build_paper_trading_node_config(
        settings,
        instrument_config=SimpleNamespace(load_ids=frozenset({"up-token.POLYMARKET"})),
    )

    assert "POLYMARKET" in config.data_clients
    assert PAPER_EXEC_CLIENT_ID in config.exec_clients
    assert config.exec_clients[PAPER_EXEC_CLIENT_ID].venue == PAPER_EXEC_CLIENT_ID
    assert config.exec_clients[PAPER_EXEC_CLIENT_ID].account_type == "CASH"
    assert config.exec_clients[PAPER_EXEC_CLIENT_ID].oms_type == "NETTING"
    assert config.exec_clients[PAPER_EXEC_CLIENT_ID].starting_balances == ["1234.0 USDC"]
    assert "POLYMARKET" not in config.exec_clients


def test_register_paper_factories_registers_data_and_sandbox_exec_only() -> None:
    node = FakeNode()

    register_paper_factories(node)

    assert node.data_factories[0][0] == "POLYMARKET"
    assert node.exec_factories[0][0] == PAPER_EXEC_CLIENT_ID
    assert all(name != "POLYMARKET" for name, _factory in node.exec_factories)


def test_live_polymarket_execution_is_rejected() -> None:
    config = SimpleNamespace(exec_clients={"POLYMARKET": object()})

    with pytest.raises(RuntimeError, match="live Polymarket execution"):
        assert_no_live_polymarket_execution(config)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_nautilus_trading_node_runtime.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'polysignal_lab.nautilus_runtime.trading_node'`.

- [ ] **Step 3: Implement lazy Nautilus TradingNode helpers**

Create `src/polysignal_lab/nautilus_runtime/trading_node.py`:

```python
from __future__ import annotations

from typing import Any

from polysignal_lab.config import Settings, load_settings

PAPER_EXEC_CLIENT_ID = "POLYSIGNAL-SANDBOX"
POLYMARKET_CLIENT_ID = "POLYMARKET"


def build_paper_trading_node_config(
    settings: Settings | None = None,
    *,
    instrument_config: Any,
) -> Any:
    """Build Nautilus TradingNodeConfig for Polymarket data plus sandbox execution."""

    if settings is None:
        settings = load_settings()
    from nautilus_trader.adapters.polymarket import PolymarketDataClientConfig
    from nautilus_trader.adapters.sandbox.config import SandboxExecutionClientConfig
    from nautilus_trader.config import LiveDataEngineConfig, LiveExecEngineConfig, LoggingConfig, TradingNodeConfig
    from nautilus_trader.model.identifiers import TraderId

    config = TradingNodeConfig(
        trader_id=TraderId("POLYSIGNAL-001"),
        logging=LoggingConfig(log_level="INFO", use_pyo3=True),
        data_engine=LiveDataEngineConfig(validate_data_sequence=True),
        exec_engine=LiveExecEngineConfig(reconciliation=False),
        data_clients={
            POLYMARKET_CLIENT_ID: PolymarketDataClientConfig(
                instrument_config=instrument_config,
            ),
        },
        exec_clients={
            PAPER_EXEC_CLIENT_ID: SandboxExecutionClientConfig(
                venue=PAPER_EXEC_CLIENT_ID,
                starting_balances=[f"{float(settings.paper_trading.starting_balance_usdc)} USDC"],
                base_currency="USDC",
                oms_type="NETTING",
                account_type="CASH",
                book_type=_book_type_for(settings.runtime.nautilus.matching_accuracy_mode),
                bar_execution=False,
                trade_execution=True,
                support_gtd_orders=True,
                support_contingent_orders=False,
                use_reduce_only=False,
            ),
        },
        timeout_connection=20.0,
        timeout_reconciliation=5.0,
        timeout_portfolio=5.0,
        timeout_disconnection=5.0,
        timeout_post_stop=2.0,
    )
    assert_no_live_polymarket_execution(config)
    return config


def register_paper_factories(node: Any) -> None:
    from nautilus_trader.adapters.polymarket import PolymarketLiveDataClientFactory
    from nautilus_trader.adapters.sandbox.factory import SandboxLiveExecClientFactory

    node.add_data_client_factory(POLYMARKET_CLIENT_ID, PolymarketLiveDataClientFactory)
    node.add_exec_client_factory(PAPER_EXEC_CLIENT_ID, SandboxLiveExecClientFactory)


def assert_no_live_polymarket_execution(config: Any) -> None:
    exec_clients = dict(getattr(config, "exec_clients", {}) or {})
    if POLYMARKET_CLIENT_ID in exec_clients:
        raise RuntimeError("default paper runtime refuses live Polymarket execution")


def _book_type_for(mode: str) -> str:
    if mode == "fast_l1":
        return "L1_MBP"
    return "L2_MBP"
```

- [ ] **Step 4: Tighten safety boundary test**

In `tests/test_nautilus_safety_boundary.py`, keep `LIVE_FORBIDDEN_TEXT` focused on default runtime code and add this exact assertion to `test_default_nautilus_source_avoids_live_execution_symbols()` after `assert findings == []`:

```python
    from polysignal_lab.nautilus_runtime.trading_node import PAPER_EXEC_CLIENT_ID

    assert PAPER_EXEC_CLIENT_ID != "POLYMARKET"
```

- [ ] **Step 5: Run task tests**

Run:

```bash
pytest tests/test_nautilus_trading_node_runtime.py tests/test_nautilus_safety_boundary.py -q
```

Expected: PASS on environments with Nautilus installed. If local Python is 3.11 without Nautilus, `tests/test_nautilus_trading_node_runtime.py::test_live_polymarket_execution_is_rejected` must still pass and Nautilus-dependent tests should be guarded with `pytest.importorskip("nautilus_trader")` at the top of those specific tests.

- [ ] **Step 6: Commit task 3**

```bash
git add src/polysignal_lab/nautilus_runtime/trading_node.py tests/test_nautilus_trading_node_runtime.py tests/test_nautilus_safety_boundary.py
git commit -m "feat: build Nautilus paper TradingNode config"
```

---

### Task 4: Replace default node runtime path with Nautilus TradingNode lifecycle

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/node.py`
- Modify: `tests/test_nautilus_node.py`

**Interfaces:**
- Consumes: `build_paper_trading_node_config()`, `register_paper_factories()`, `PolySignalNativeStrategy`.
- Produces: `NautilusRuntimeBundle.node`, `run_nautilus_cli_async()` calling `node.run()`/`node.dispose()` lifecycle.

- [ ] **Step 1: Replace node tests with TradingNode lifecycle expectations**

In `tests/test_nautilus_node.py`, replace `test_build_trading_node_returns_component_dict()` with:

```python
def test_build_trading_node_returns_nautilus_runtime_components(monkeypatch) -> None:
    built = {}

    class FakeTradingNode:
        def __init__(self, config):
            self.config = config
            self.trader = SimpleNamespace(strategies=[])
            self.built = False
            built["node"] = self

        def add_data_client_factory(self, name, factory):
            built.setdefault("data_factories", []).append((name, factory))

        def add_exec_client_factory(self, name, factory):
            built.setdefault("exec_factories", []).append((name, factory))

        def build(self):
            self.built = True

    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node.TradingNode", FakeTradingNode)

    runtime = build_trading_node(condition_ids=("condition-btc-5m",))

    assert runtime["node"] is built["node"]
    assert built["node"].built is True
    assert built["exec_factories"][0][0] != "POLYMARKET"
    assert "paper_client" not in runtime
```

Replace `test_build_trading_node_wires_matching_client()` with:

```python
def test_build_trading_node_uses_sandbox_execution_not_matching_client(monkeypatch) -> None:
    class FakeTradingNode:
        def __init__(self, config):
            self.config = config
            self.trader = SimpleNamespace(strategies=[])

        def add_data_client_factory(self, name, factory):
            pass

        def add_exec_client_factory(self, name, factory):
            self.exec_factory_name = name

        def build(self):
            pass

    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node.TradingNode", FakeTradingNode)

    runtime = build_trading_node()

    assert runtime["node"].exec_factory_name != "POLYMARKET"
    assert "paper_client" not in runtime
    assert "matching_client" not in runtime
```

- [ ] **Step 2: Run updated node tests to verify failure**

Run:

```bash
pytest tests/test_nautilus_node.py::test_build_trading_node_returns_nautilus_runtime_components tests/test_nautilus_node.py::test_build_trading_node_uses_sandbox_execution_not_matching_client -q
```

Expected: FAIL because `build_trading_node()` still returns `paper_client` and imports `NautilusMatchingPaperExecutionClient`.

- [ ] **Step 3: Modify `node.py` imports and runtime builder**

In `src/polysignal_lab/nautilus_runtime/node.py`:

1. Remove imports of `NautilusMatchingPaperExecutionClient`, `NautilusOrchestrator`, `PaperWallet`, `PaperExitEngine`, `PaperSettlementEngine`, and `SettlementActor` from the default path.
2. Add lazy imports inside `build_trading_node()`:

```python
from nautilus_trader.live.node import TradingNode
from nautilus_trader.adapters.polymarket.providers import PolymarketInstrumentProviderConfig
from polysignal_lab.nautilus_runtime.trading_node import (
    build_paper_trading_node_config,
    register_paper_factories,
)
```

3. Replace the body of `build_trading_node()` with this shape:

```python
def build_trading_node(
    settings: Settings | None = None,
    *,
    condition_ids: Sequence[str] = (),
    store: Any = None,
    wallet: Any = None,
) -> dict[str, Any]:
    """Build the Nautilus-owned paper runtime wiring."""
    if settings is None:
        settings = load_settings()

    instrument_config = PolymarketInstrumentProviderConfig(load_ids=frozenset())
    config = build_paper_trading_node_config(settings, instrument_config=instrument_config)
    node = TradingNode(config=config)
    register_paper_factories(node)

    registry = PolymarketMarketRegistry()
    sidecar = ExternalDataSidecar()
    assembler = MarketViewAssembler(registry=registry, books=None, sidecar=sidecar)
    policy = DecisionPolicyActor()
    strategies = _build_native_strategies(settings, assembler, policy, condition_ids)
    for strategy in strategies:
        node.trader.add_strategy(strategy)
    node.build()

    return {
        "node": node,
        "config": config,
        "registry": registry,
        "sidecar": sidecar,
        "assembler": assembler,
        "policy": policy,
        "strategies": strategies,
        "strategy_names": [strategy.strategy_name for strategy in strategies],
    }
```

4. Add `_build_native_strategies()` next to `_build_wrapper()` and have it construct `PolySignalNativeStrategy` instances using the same alpha core classes currently used by wrappers.

- [ ] **Step 4: Update CLI runtime to run Nautilus node**

In `run_nautilus_cli_async()`, replace orchestrator execution with:

```python
bundle = await build_nautilus_runtime(settings)
node = bundle.components["node"]
try:
    print(f"Nautilus runtime ready — {len(bundle.components['strategies'])} strategies")
    await asyncio.to_thread(node.run)
finally:
    dispose = getattr(node, "dispose", None)
    if callable(dispose):
        dispose()
    await bundle.scheduler.stop()
```

Keep the `stop_event` test path by checking `stop_event` before `to_thread(node.run)`:

```python
if stop_event is not None and stop_event.is_set():
    return
```

- [ ] **Step 5: Run task tests**

Run:

```bash
pytest tests/test_nautilus_node.py tests/test_nautilus_platform_boundary.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit task 4**

```bash
git add src/polysignal_lab/nautilus_runtime/node.py tests/test_nautilus_node.py
git commit -m "feat: run paper mode through Nautilus TradingNode"
```

---

### Task 5: Projections read Nautilus state instead of PaperWallet truth

**Files:**
- Create: `src/polysignal_lab/nautilus_runtime/projections.py`
- Modify: `src/polysignal_lab/nautilus_runtime/observability.py`
- Test: `tests/test_nautilus_projections.py`
- Test: `tests/test_nautilus_observability.py`

**Interfaces:**
- Consumes: Nautilus-like cache methods `orders()`, `fills()`, `positions()` or event objects with order/fill/position fields.
- Produces: `project_order_event(event) -> dict[str, object]`, `project_fill_event(event) -> dict[str, object]`, `project_position(position) -> dict[str, object]`.

- [ ] **Step 1: Write projection tests**

Create `tests/test_nautilus_projections.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

from polysignal_lab.nautilus_runtime.projections import (
    project_fill_event,
    project_order_event,
    project_position,
)


def test_project_order_event_uses_nautilus_event_fields() -> None:
    event = SimpleNamespace(
        client_order_id="C-001",
        instrument_id="up-token.POLYMARKET",
        order_side="BUY",
        order_type="LIMIT",
        time_in_force="IOC",
        quantity=20.0,
        price=0.50,
        tags=["strategy=ptb_diff", "condition_id=condition-btc-5m"],
    )

    row = project_order_event(event)

    assert row == {
        "client_order_id": "C-001",
        "instrument_id": "up-token.POLYMARKET",
        "side": "BUY",
        "order_type": "LIMIT",
        "time_in_force": "IOC",
        "quantity": 20.0,
        "price": 0.50,
        "strategy": "ptb_diff",
        "condition_id": "condition-btc-5m",
    }


def test_project_fill_event_uses_nautilus_fill_fields() -> None:
    event = SimpleNamespace(
        client_order_id="C-001",
        instrument_id="up-token.POLYMARKET",
        trade_id="T-001",
        last_qty=12.5,
        last_px=0.50,
        liquidity_side="TAKER",
    )

    row = project_fill_event(event)

    assert row["client_order_id"] == "C-001"
    assert row["trade_id"] == "T-001"
    assert row["quantity"] == 12.5
    assert row["price"] == 0.50
    assert row["notional"] == 6.25


def test_project_position_uses_nautilus_position_fields() -> None:
    position = SimpleNamespace(
        id="P-001",
        instrument_id="up-token.POLYMARKET",
        signed_qty=20.0,
        avg_px_open=0.50,
        realized_pnl=1.25,
        is_closed=False,
    )

    row = project_position(position)

    assert row == {
        "position_id": "P-001",
        "instrument_id": "up-token.POLYMARKET",
        "quantity": 20.0,
        "avg_entry_price": 0.50,
        "realized_pnl": 1.25,
        "is_closed": False,
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_nautilus_projections.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'polysignal_lab.nautilus_runtime.projections'`.

- [ ] **Step 3: Implement projection functions**

Create `src/polysignal_lab/nautilus_runtime/projections.py`:

```python
from __future__ import annotations

from typing import Any


def project_order_event(event: Any) -> dict[str, object]:
    tags = _tags(getattr(event, "tags", None))
    return {
        "client_order_id": str(getattr(event, "client_order_id", "")),
        "instrument_id": str(getattr(event, "instrument_id", "")),
        "side": str(getattr(event, "order_side", "")),
        "order_type": str(getattr(event, "order_type", "")),
        "time_in_force": str(getattr(event, "time_in_force", "")),
        "quantity": float(getattr(event, "quantity", 0.0) or 0.0),
        "price": float(getattr(event, "price", 0.0) or 0.0),
        "strategy": tags.get("strategy", ""),
        "condition_id": tags.get("condition_id", ""),
    }


def project_fill_event(event: Any) -> dict[str, object]:
    quantity = float(getattr(event, "last_qty", 0.0) or 0.0)
    price = float(getattr(event, "last_px", 0.0) or 0.0)
    return {
        "client_order_id": str(getattr(event, "client_order_id", "")),
        "instrument_id": str(getattr(event, "instrument_id", "")),
        "trade_id": str(getattr(event, "trade_id", "")),
        "quantity": quantity,
        "price": price,
        "notional": quantity * price,
        "liquidity_side": str(getattr(event, "liquidity_side", "")),
    }


def project_position(position: Any) -> dict[str, object]:
    return {
        "position_id": str(getattr(position, "id", "")),
        "instrument_id": str(getattr(position, "instrument_id", "")),
        "quantity": float(getattr(position, "signed_qty", 0.0) or 0.0),
        "avg_entry_price": float(getattr(position, "avg_px_open", 0.0) or 0.0),
        "realized_pnl": float(getattr(position, "realized_pnl", 0.0) or 0.0),
        "is_closed": bool(getattr(position, "is_closed", False)),
    }


def _tags(raw: object) -> dict[str, str]:
    if isinstance(raw, dict):
        return {str(key): str(value) for key, value in raw.items()}
    parsed: dict[str, str] = {}
    for item in raw or ():
        text = str(item)
        if "=" not in text:
            continue
        key, value = text.split("=", 1)
        parsed[key] = value
    return parsed
```

- [ ] **Step 4: Wire observability to projection helpers**

In `src/polysignal_lab/nautilus_runtime/observability.py`, add imports:

```python
from polysignal_lab.nautilus_runtime.projections import project_fill_event, project_order_event, project_position
```

Where observability currently records `PaperExecutionResult`, add new methods without removing old compatibility methods:

```python
    def record_nautilus_order_event(self, event: object) -> None:
        self.record_event("nautilus_order", project_order_event(event))

    def record_nautilus_fill_event(self, event: object) -> None:
        self.record_event("nautilus_fill", project_fill_event(event))

    def record_nautilus_position(self, position: object) -> None:
        self.record_event("nautilus_position", project_position(position))
```

If `record_event()` does not exist, use the existing store adapter method already used by `record_order()` and keep the event names above.

- [ ] **Step 5: Run projection and observability tests**

Run:

```bash
pytest tests/test_nautilus_projections.py tests/test_nautilus_observability.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit task 5**

```bash
git add src/polysignal_lab/nautilus_runtime/projections.py src/polysignal_lab/nautilus_runtime/observability.py tests/test_nautilus_projections.py tests/test_nautilus_observability.py
git commit -m "feat: project reports from Nautilus events"
```

---

### Task 6: Remove default custom paper truth source

**Files:**
- Modify: `src/polysignal_lab/nautilus_runtime/node.py`
- Modify: `src/polysignal_lab/nautilus_runtime/strategies/base.py`
- Modify: `tests/test_nautilus_platform_boundary.py`
- Modify: `tests/test_nautilus_safety_boundary.py`
- Modify: `tests/test_nautilus_strategy_base.py`

**Interfaces:**
- Consumes: `PolySignalNativeStrategy` and projections from earlier tasks.
- Produces: default runtime path without `PaperWallet`, `PaperExecutionResult`, or `NautilusMatchingPaperExecutionClient` as truth sources.

- [ ] **Step 1: Add safety tests that fail on old truth sources**

In `tests/test_nautilus_platform_boundary.py`, add:

```python
def test_default_nautilus_runtime_does_not_use_custom_paper_truth_sources() -> None:
    forbidden = (
        "NautilusMatchingPaperExecutionClient(",
        "PaperWallet(",
        "PaperExecutionResult(",
        "evaluate_all_conditions(",
    )
    findings: list[str] = []
    for path in Path("src/polysignal_lab/nautilus_runtime").rglob("*.py"):
        if path.name in {"matching.py", "execution_types.py"}:
            continue
        text = path.read_text(encoding="utf-8")
        findings.extend(f"{path}:{token}" for token in forbidden if token in text)

    assert findings == []
```

- [ ] **Step 2: Run safety test to verify failure**

Run:

```bash
pytest tests/test_nautilus_platform_boundary.py::test_default_nautilus_runtime_does_not_use_custom_paper_truth_sources -q
```

Expected: FAIL while `node.py` or default strategy path still references old custom paper truth sources.

- [ ] **Step 3: Isolate compatibility classes**

In `src/polysignal_lab/nautilus_runtime/strategies/base.py`, add this module-level constant:

```python
COMPATIBILITY_ONLY = True
```

Add this docstring sentence to `PolySignalNautilusStrategy`:

```python
"""Compatibility wrapper for pre-TradingNode tests; default runtime uses PolySignalNativeStrategy."""
```

Do not import this compatibility wrapper from the default `node.py` path.

- [ ] **Step 4: Remove old paper truth source imports from default runtime**

In `src/polysignal_lab/nautilus_runtime/node.py`, ensure these names do not appear outside comments or compatibility tests:

```text
NautilusMatchingPaperExecutionClient
PaperWallet
PaperExecutionResult
NautilusOrchestrator
SettlementActor
PaperSettlementEngine
PaperExitEngine
```

If `NautilusRuntimeBundle` still has `paper_client` or `orchestrator` fields, replace them with:

```python
node: Any
components: dict[str, Any]
bridge_registry: PolymarketMarketRegistry
sidecar: ExternalDataSidecar
book_data_provider: NautilusBookDataProvider | None
observability: ObservabilityActor
websocket_tasks: list[asyncio.Task]
```

- [ ] **Step 5: Run focused safety and node tests**

Run:

```bash
pytest tests/test_nautilus_platform_boundary.py tests/test_nautilus_safety_boundary.py tests/test_nautilus_node.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit task 6**

```bash
git add src/polysignal_lab/nautilus_runtime/node.py src/polysignal_lab/nautilus_runtime/strategies/base.py tests/test_nautilus_platform_boundary.py tests/test_nautilus_safety_boundary.py tests/test_nautilus_strategy_base.py
git commit -m "refactor: remove default custom paper truth source"
```

---

### Task 7: Integration smoke path and final verification

**Files:**
- Create: `tests/test_nautilus_full_paper_runtime_smoke.py`
- Modify: `tests/test_nautilus_runtime_config.py`
- Modify: `docs/superpowers/specs/2026-06-27-nautilus-full-strategy-paper-design.md` only if implementation reveals a spec mismatch that the user approves.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: smoke proof that default paper mode uses Nautilus strategy callbacks and sandbox execution wiring.

- [ ] **Step 1: Add smoke test for complete default paper path**

Create `tests/test_nautilus_full_paper_runtime_smoke.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

from polysignal_lab.config import Settings
from polysignal_lab.nautilus_runtime.node import build_trading_node


def test_full_paper_runtime_builds_node_without_live_execution(monkeypatch) -> None:
    built = {}

    class FakeTrader:
        def __init__(self) -> None:
            self.strategies = []

        def add_strategy(self, strategy):
            self.strategies.append(strategy)

    class FakeTradingNode:
        def __init__(self, config):
            self.config = config
            self.trader = FakeTrader()
            built["node"] = self

        def add_data_client_factory(self, name, factory):
            built.setdefault("data_factories", []).append(name)

        def add_exec_client_factory(self, name, factory):
            built.setdefault("exec_factories", []).append(name)

        def build(self):
            built["built"] = True

    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node.TradingNode", FakeTradingNode)

    runtime = build_trading_node(Settings(), condition_ids=("condition-btc-5m",))

    assert runtime["node"] is built["node"]
    assert "POLYMARKET" in built["data_factories"]
    assert "POLYMARKET" not in built["exec_factories"]
    assert built["built"] is True
```

- [ ] **Step 2: Run smoke test**

Run:

```bash
pytest tests/test_nautilus_full_paper_runtime_smoke.py -q
```

Expected: PASS.

- [ ] **Step 3: Run focused Nautilus suite**

Run:

```bash
pytest tests/test_nautilus_native_order.py tests/test_nautilus_strategy_base.py tests/test_nautilus_trading_node_runtime.py tests/test_nautilus_node.py tests/test_nautilus_projections.py tests/test_nautilus_platform_boundary.py tests/test_nautilus_safety_boundary.py tests/test_nautilus_full_paper_runtime_smoke.py -q
```

Expected: PASS.

- [ ] **Step 4: Run type/lint checks for changed source**

Run:

```bash
basedpyright src/polysignal_lab/nautilus_runtime tests/test_nautilus_native_order.py tests/test_nautilus_trading_node_runtime.py tests/test_nautilus_projections.py tests/test_nautilus_full_paper_runtime_smoke.py
```

Expected: zero errors in changed files.

- [ ] **Step 5: Inspect final source for forbidden runtime ownership regressions**

Run:

```bash
pytest tests/test_nautilus_platform_boundary.py::test_default_nautilus_runtime_does_not_use_custom_paper_truth_sources tests/test_nautilus_safety_boundary.py::test_default_nautilus_source_avoids_live_execution_symbols -q
```

Expected: PASS.

- [ ] **Step 6: Commit task 7**

```bash
git add tests/test_nautilus_full_paper_runtime_smoke.py tests/test_nautilus_runtime_config.py docs/superpowers/specs/2026-06-27-nautilus-full-strategy-paper-design.md
git commit -m "test: cover Nautilus full paper runtime path"
```

If `tests/test_nautilus_runtime_config.py` or the spec file did not change, omit them from `git add` and commit only the smoke test.

---

## Self-Review

### Spec coverage

- Nautilus owns market data ingestion: Task 3 and Task 4 build Polymarket data client into `TradingNode`.
- Nautilus owns strategy lifecycle and signal generation location: Task 2 moves signal generation into `on_data`; Task 4 registers strategies on `node.trader`.
- Nautilus owns order submission: Task 1 submits through `strategy.submit_order()`; Task 2 calls it from callback execution.
- Nautilus owns paper matching/fills/positions/account/cache: Task 3 uses `SandboxExecutionClientConfig`; Task 5 projects from Nautilus event/cache-shaped objects; Task 6 removes old truth sources from default runtime.
- Default runtime cannot use live Polymarket execution: Task 3 and Task 6 add runtime and source safety checks.
- PolySignal keeps alpha/config/projections only: Task 2 preserves alpha cores; Task 5 keeps projections; Task 6 removes custom paper state from default path.

### Placeholder scan

This plan contains no open-ended placeholder steps. Each task names files, tests, commands, and expected outcomes.

### Type consistency

- `submit_approved_decision()` is introduced in Task 1 and consumed by `PolySignalNativeStrategy` in Task 2.
- `build_paper_trading_node_config()`, `register_paper_factories()`, and `PAPER_EXEC_CLIENT_ID` are introduced in Task 3 and consumed by `node.py` in Task 4.
- Projection function names introduced in Task 5 are the same names used by the observability wiring.
