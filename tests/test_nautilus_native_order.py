"""
Input: __future__, __future__.annotations, sys, collections.abc, collections.abc.Sequence, dataclasses, dataclasses.dataclass, datetime, datetime.UTC, datetime.datetime
Output: test_order_plan_resolves_taker_price_from_best_ask, test_order_plan_rejects_taker_without_best_ask, test_submit_approved_decision_submits_limit_order_through_strategy, test_submit_approved_decision_uses_instrument_value_converters, test_submit_approved_decision_quantizes_price_before_instrument_converter, test_submit_approved_decision_preserves_price_precision_when_price_type_available, test_submit_approved_decision_maps_passive_gtd_expiry, test_submit_approved_decision_passive_gtd_allows_no_immediate_visible_depth, test_submit_approved_decision_does_not_require_available_shares, test_static_native_strategy_initializes_nautilus_base
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

import sys

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import import_module
from types import ModuleType
from typing import cast

import pytest

from polysignal_lab.alpha.types import AlphaCore
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import ApprovedDecision
from polysignal_lab.nautilus_runtime.native_order import OrderSubmittingStrategy, submit_approved_decision


@dataclass(slots=True)
class FakeOrder:
    instrument_id: str
    order_side: object
    quantity: object
    price: object
    time_in_force: object
    reduce_only: bool
    expire_time: object | None
    tags: list[str]

def _enum_name(value: object) -> object:
    return getattr(value, "name", value)


class FakeOrderFactory:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def limit(
        self,
        *,
        instrument_id: object,
        order_side: object,
        quantity: object,
        price: object,
        time_in_force: object,
        reduce_only: bool,
        expire_time: datetime | None,
        tags: Sequence[str],
    ) -> FakeOrder:
        call = {
            "instrument_id": instrument_id,
            "order_side": order_side,
            "quantity": quantity,
            "price": price,
            "time_in_force": time_in_force,
            "expire_time": expire_time,
            "reduce_only": reduce_only,
            "tags": list(tags),
        }
        self.calls.append(call)
        return FakeOrder(
            instrument_id=str(instrument_id),
            order_side=order_side,
            quantity=quantity,
            price=price,
            time_in_force=time_in_force,
            reduce_only=reduce_only,
            expire_time=expire_time,
            tags=list(tags),
        )


class FakeStrategy:
    def __init__(self) -> None:
        self.order_factory: FakeOrderFactory = FakeOrderFactory()
        self.submitted: list[FakeOrder] = []
        self.submitted_orders = self.submitted

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

def test_order_plan_resolves_taker_price_from_best_ask() -> None:
    from polysignal_lab.nautilus_runtime.order_plan import build_order_spec

    spec = build_order_spec(
        _approved(OrderIntent.TAKER_IOC).signal,
        fixed_stake_usdc=10.0,
        best_ask=0.50,
    )

    assert spec.price == 0.50
    assert spec.quantity == 20.0
    assert spec.tags["time_in_force"] == "IOC"


def test_order_plan_rejects_taker_without_best_ask() -> None:
    from polysignal_lab.nautilus_runtime.order_plan import build_order_spec

    approved = _approved(OrderIntent.TAKER_FOK)

    try:
        build_order_spec(approved.signal, fixed_stake_usdc=10.0, best_ask=None)
    except ValueError as exc:
        assert "taker_fok requires best ask depth" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_submit_approved_decision_submits_limit_order_through_strategy() -> None:
    strategy = FakeStrategy()

    order = submit_approved_decision(
        cast(OrderSubmittingStrategy[FakeOrder], strategy),
        _approved(OrderIntent.TAKER_IOC),
        fixed_stake_usdc=10.0,
        best_ask=0.50,
        instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
    )

    assert order is strategy.submitted[0]
    assert order.instrument_id == "up-token.POLYMARKET"
    assert _enum_name(order.order_side) == "BUY"
    assert order.quantity == 20.0
    assert order.reduce_only is False
    assert order.price == 0.50
    assert _enum_name(order.time_in_force) == "IOC"
    assert order.expire_time is None
    assert "strategy=ptb_diff" in order.tags
    assert "condition_id=condition-btc-5m" in order.tags



def test_submit_approved_decision_uses_instrument_value_converters() -> None:
    strategy = FakeStrategy()

    class FakeInstrument:
        id: str = "up-token.POLYMARKET"

        def make_qty(self, value: float) -> str:
            return f"qty:{value}"

        def make_price(self, value: float) -> str:
            return f"price:{value}"

    order = submit_approved_decision(
        cast(OrderSubmittingStrategy[FakeOrder], strategy),
        _approved(OrderIntent.TAKER_IOC),
        fixed_stake_usdc=10.0,
        best_ask=0.50,
        instrument_id_resolver=lambda _token_id: FakeInstrument(),
    )

    assert order.instrument_id == "up-token.POLYMARKET"
    assert order.quantity == "qty:20.0"
    assert order.price == "price:0.5"



def test_submit_approved_decision_quantizes_price_before_instrument_converter() -> None:
    strategy = FakeStrategy()

    class FakeInstrument:
        id: str = "up-token.POLYMARKET"
        price_precision = 2

        def make_price(self, value: float) -> str:
            return f"price:{value:.3f}"

    order = submit_approved_decision(
        cast(OrderSubmittingStrategy[FakeOrder], strategy),
        _approved(OrderIntent.TAKER_IOC),
        fixed_stake_usdc=10.0,
        best_ask=0.512,
        instrument_id_resolver=lambda _token_id: FakeInstrument(),
    )

    assert order.price == "price:0.510"



def test_submit_approved_decision_preserves_price_precision_when_price_type_available(
    monkeypatch,
) -> None:
    import polysignal_lab.nautilus_runtime.native_order as native_order

    strategy = FakeStrategy()

    class FakePrice:
        def __init__(self, raw: str) -> None:
            self.raw = raw
            self.precision = len(raw.partition(".")[2])

        @classmethod
        def from_str(cls, value: str) -> "FakePrice":
            return cls(value)

    class FakeInstrument:
        id: str = "up-token.POLYMARKET"
        price_precision = 3

        def make_price(self, value: float) -> FakePrice:
            return FakePrice(str(value))

    def fake_optional_attr(module_name: str, attr_name: str) -> object | None:
        if attr_name == "Price":
            return FakePrice
        return None

    monkeypatch.setattr(native_order, "_optional_nautilus_attr", fake_optional_attr)

    approved = _approved(OrderIntent.TAKER_IOC)
    approved = ApprovedDecision(
        signal=approved.signal.model_copy(update={"max_entry_price": 0.75}),
    )

    order = submit_approved_decision(
        cast(OrderSubmittingStrategy[FakeOrder], strategy),
        approved,
        fixed_stake_usdc=10.0,
        best_ask=0.73,
        instrument_id_resolver=lambda _token_id: FakeInstrument(),
    )

    assert order.price.raw == "0.730"
    assert order.price.precision == 3



def test_submit_approved_decision_maps_passive_gtd_expiry() -> None:
    strategy = FakeStrategy()

    order = submit_approved_decision(
        cast(OrderSubmittingStrategy[FakeOrder], strategy),
        _approved(OrderIntent.PASSIVE_GTD),
        fixed_stake_usdc=10.0,
        best_ask=0.50,
        instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
        now=lambda: datetime(2026, 6, 27, tzinfo=UTC),
    )

    assert _enum_name(order.time_in_force) == "GTD"
    assert order.expire_time == datetime(2026, 6, 27, 0, 0, 45, tzinfo=UTC)

def test_submit_approved_decision_passive_gtd_allows_no_immediate_visible_depth() -> None:
    strategy = FakeStrategy()

    order = submit_approved_decision(
        cast(OrderSubmittingStrategy[FakeOrder], strategy),
        _approved(OrderIntent.PASSIVE_GTD),
        fixed_stake_usdc=10.0,
        best_ask=0.50,
        instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
        now=lambda: datetime(2026, 6, 27, tzinfo=UTC),
    )

    assert _enum_name(order.time_in_force) == "GTD"
    assert strategy.submitted == [order]


def test_submit_approved_decision_does_not_require_available_shares() -> None:
    strategy = FakeStrategy()
    approved = _approved(OrderIntent.TAKER_FOK)

    order = submit_approved_decision(
        cast(OrderSubmittingStrategy[FakeOrder], strategy),
        approved,
        fixed_stake_usdc=10.0,
        best_ask=0.50,
        instrument_id_resolver=lambda value: value,
    )

    assert order is strategy.submitted_orders[-1]


def _load_static_native_strategy(
    monkeypatch: pytest.MonkeyPatch,
    strategy_base: type[object],
    strategy_config: object,
) -> type[object]:
    runtime_module_name = "polysignal_lab.nautilus_runtime.runtime_classes"
    missing = object()
    previous_runtime_module = sys.modules.get(runtime_module_name, missing)
    _ = sys.modules.pop(runtime_module_name, None)

    nautilus_module = ModuleType("nautilus_trader")
    common_module = ModuleType("nautilus_trader.common")
    actor_module = ModuleType("nautilus_trader.common.actor")
    config_module = ModuleType("nautilus_trader.config")
    strategy_module = ModuleType("nautilus_trader.trading.strategy")
    trading_module = ModuleType("nautilus_trader.trading")

    class FakeActor:
        def __init__(self, *, config: object) -> None:
            self.actor_config = config

    actor_module.Actor = FakeActor
    config_module.ActorConfig = lambda: "actor-config"
    config_module.StrategyConfig = lambda: strategy_config
    strategy_module.Strategy = strategy_base

    nautilus_module.common = common_module
    nautilus_module.config = config_module
    nautilus_module.trading = trading_module
    common_module.actor = actor_module
    trading_module.strategy = strategy_module

    monkeypatch.setitem(sys.modules, "nautilus_trader", nautilus_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.common", common_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.common.actor", actor_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.config", config_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.trading", trading_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.trading.strategy", strategy_module)

    try:
        module = import_module(runtime_module_name)
        return cast(type[object], module.PolySignalNativeStrategy)
    finally:
        if previous_runtime_module is missing:
            _ = sys.modules.pop(runtime_module_name, None)
        else:
            sys.modules[runtime_module_name] = previous_runtime_module


def test_static_native_strategy_initializes_nautilus_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeNautilusBase:
        def __init__(self, *, config: object) -> None:
            self.nautilus_config: object = config

    class FakeRegistry:
        def by_condition(self, _condition_id: str) -> None:
            return None

    strategy_type = _load_static_native_strategy(
        monkeypatch,
        FakeNautilusBase,
        "strategy-config",
    )
    strategy = strategy_type(
        core=cast(AlphaCore, object()),
        assembler=FakeAssemblerForRuntimeType(),
        condition_ids=(),
        strategy_name="ptb_diff",
        registry=FakeRegistry(),
    )

    assert getattr(strategy, "nautilus_config") == "strategy-config"


class FakeAssemblerForRuntimeType:
    def build(self, condition_id: str) -> None:
        _ = condition_id
        return None
