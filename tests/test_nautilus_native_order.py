from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from polysignal_lab.alpha.types import AlphaDecision, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.nautilus_runtime.decision_policy import (
    ApprovedDecision,
    candidate_from_decision,
)
from polysignal_lab.nautilus_runtime.native_order import (
    OrderSubmittingStrategy,
    submit_approved_decision,
)
from factories import sample_market_view


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


class FakeInstrument:
    id: str = "up-token.POLYMARKET"

    def make_qty(self, value: float) -> float:
        return value

    def make_price(self, value: float) -> float:
        return value


class FakeStrategy:
    def __init__(self) -> None:
        self._order_factory_override: FakeOrderFactory = FakeOrderFactory()
        self.submitted: list[FakeOrder] = []
        self.submitted_orders = self.submitted

    @property
    def order_factory(self) -> FakeOrderFactory:
        return self._order_factory_override

    @property
    def cache(self) -> object:
        return self._cache_override

    def submit_order(self, order: FakeOrder) -> None:
        self.submitted.append(order)


def _approved(
    intent: OrderIntent = OrderIntent.TAKER_IOC,
    *,
    reduce_only: bool = False,
    max_entry_price: float = 0.52,
    quantity: float | None = None,
) -> ApprovedDecision:
    decision = AlphaDecision(
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
        max_entry_price=max_entry_price,
        seconds_to_close=60,
        data_freshness_ms=20,
        reason_codes=("TEST",),
        metrics={},
        order_intent=OrderIntentSpec(
            intent=intent,
            expiry_seconds=45 if intent == OrderIntent.PASSIVE_GTD else None,
            pair_id="pair-1",
            reduce_only=reduce_only,
            quantity=quantity,
        ),
        hedge_leg=False,
    )
    publish = candidate_from_decision(decision, sample_market_view())
    return ApprovedDecision(decision=decision, publish=publish)


def test_order_plan_resolves_taker_price_from_best_ask() -> None:
    from polysignal_lab.nautilus_runtime.order_plan import build_order_spec

    approved = _approved(OrderIntent.TAKER_IOC)
    spec = build_order_spec(
        approved.decision,
        fixed_stake_usdc=10.0,
        best_ask=0.50,
        view_id=approved.publish.snapshot_id or "",
    )

    assert spec.price == 0.50
    assert spec.quantity == 20.0
    assert spec.tags["time_in_force"] == "IOC"


def test_order_plan_rejects_taker_without_best_ask() -> None:
    from polysignal_lab.nautilus_runtime.order_plan import build_order_spec

    approved = _approved(OrderIntent.TAKER_FOK)

    try:
        build_order_spec(approved.decision, fixed_stake_usdc=10.0, best_ask=None)
    except ValueError as exc:
        assert "taker_fok requires best ask depth" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_submit_approved_decision_submits_limit_order_through_strategy() -> None:
    from nautilus_trader.core.nautilus_pyo3 import OrderSide, TimeInForce

    strategy = FakeStrategy()
    approved = _approved(OrderIntent.TAKER_IOC)

    order = submit_approved_decision(
        cast(OrderSubmittingStrategy[FakeOrder], strategy),
        approved,
        fixed_stake_usdc=10.0,
        best_ask=0.50,
        instrument_id_resolver=lambda _token_id: FakeInstrument(),
        view_id=approved.publish.snapshot_id or "",
    )

    assert order is strategy.submitted[0]
    assert order.instrument_id == "up-token.POLYMARKET"
    assert isinstance(order.order_side, OrderSide)
    assert order.order_side == OrderSide.BUY
    assert order.quantity == 20.0
    assert order.reduce_only is False
    assert order.price == 0.50
    assert isinstance(order.time_in_force, TimeInForce)
    assert order.time_in_force == TimeInForce.IOC
    assert order.expire_time is None
    assert "strategy=ptb_diff" in order.tags
    assert "condition_id=condition-btc-5m" in order.tags
    view_id = approved.publish.snapshot_id or ""
    assert f"signal_id={approved.decision.signal_id(view_id)}" in order.tags


def test_submit_approved_decision_uses_instrument_value_converters() -> None:
    strategy = FakeStrategy()

    class FakeInstrument:
        id: str = "up-token.POLYMARKET"

        def make_qty(self, value: float) -> str:
            return f"qty:{value}"

        def make_price(self, value: float) -> float:
            return value

    order = submit_approved_decision(
        cast(OrderSubmittingStrategy[FakeOrder], strategy),
        _approved(OrderIntent.TAKER_IOC),
        fixed_stake_usdc=10.0,
        best_ask=0.50,
        instrument_id_resolver=lambda _token_id: FakeInstrument(),
    )

    assert order.instrument_id == "up-token.POLYMARKET"
    assert order.quantity == "qty:20.0"
    assert order.price == 0.5


def test_submit_approved_decision_delegates_price_rounding_to_instrument() -> None:
    strategy = FakeStrategy()

    class FakeInstrument:
        id: str = "up-token.POLYMARKET"
        price_precision = 2

        def make_qty(self, value: float) -> float:
            return value

        def make_price(self, value: float) -> float:
            return value

    order = submit_approved_decision(
        cast(OrderSubmittingStrategy[FakeOrder], strategy),
        _approved(OrderIntent.TAKER_IOC),
        fixed_stake_usdc=10.0,
        best_ask=0.512,
        instrument_id_resolver=lambda _token_id: FakeInstrument(),
    )

    assert order.price == 0.512


def test_submit_approved_decision_preserves_price_precision_when_price_type_available() -> (
    None
):
    strategy = FakeStrategy()

    class FakePrice:
        def __init__(self, raw: str) -> None:
            self.raw = raw
            self.precision = len(raw.partition(".")[2])

        @classmethod
        def from_str(cls, value: str) -> "FakePrice":
            return cls(value)

        def __str__(self) -> str:
            return self.raw

    class FakeInstrument:
        id: str = "up-token.POLYMARKET"
        price_precision = 3

        def make_qty(self, value: float) -> float:
            return value

        def make_price(self, value: float) -> FakePrice:
            return FakePrice(str(value))

    approved = _approved(OrderIntent.TAKER_IOC, max_entry_price=0.75)

    order = submit_approved_decision(
        cast(OrderSubmittingStrategy[FakeOrder], strategy),
        approved,
        fixed_stake_usdc=10.0,
        best_ask=0.73,
        instrument_id_resolver=lambda _token_id: FakeInstrument(),
    )

    price = cast(FakePrice, order.price)
    assert price.raw == "0.73"
    assert price.precision == 2


def test_submit_approved_decision_maps_passive_gtd_expiry() -> None:
    strategy = FakeStrategy()

    order = submit_approved_decision(
        cast(OrderSubmittingStrategy[FakeOrder], strategy),
        _approved(OrderIntent.PASSIVE_GTD),
        fixed_stake_usdc=10.0,
        best_ask=0.50,
        instrument_id_resolver=lambda token_id: FakeInstrument(),
        now=lambda: datetime(2026, 6, 27, tzinfo=UTC),
    )

    assert _enum_name(order.time_in_force) == "GTD"
    assert order.expire_time == datetime(2026, 6, 27, 0, 0, 45, tzinfo=UTC)


def test_submit_approved_decision_requires_runtime_clock_for_gtd_expiry() -> None:
    import pytest

    strategy = FakeStrategy()

    with pytest.raises(RuntimeError, match="framework clock"):
        submit_approved_decision(
            cast(OrderSubmittingStrategy[FakeOrder], strategy),
            _approved(OrderIntent.PASSIVE_GTD),
            fixed_stake_usdc=10.0,
            best_ask=0.50,
            instrument_id_resolver=lambda token_id: FakeInstrument(),
        )


def test_submit_approved_decision_passive_gtd_allows_no_immediate_visible_depth() -> (
    None
):
    strategy = FakeStrategy()

    order = submit_approved_decision(
        cast(OrderSubmittingStrategy[FakeOrder], strategy),
        _approved(OrderIntent.PASSIVE_GTD),
        fixed_stake_usdc=10.0,
        best_ask=0.50,
        instrument_id_resolver=lambda token_id: FakeInstrument(),
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
        instrument_id_resolver=lambda value: FakeInstrument(),
    )

    assert order is strategy.submitted_orders[-1]


def test_reduce_only_submission_uses_typed_decision_quantity() -> None:
    strategy = FakeStrategy()
    order = submit_approved_decision(
        cast(OrderSubmittingStrategy[FakeOrder], strategy),
        _approved(OrderIntent.TAKER_FAK, reduce_only=True, quantity=3.5),
        fixed_stake_usdc=10.0,
        best_ask=0.80,
        best_bid=0.45,
        instrument_id_resolver=lambda _value: FakeInstrument(),
        use_native_reduce_only=True,
    )

    assert order.quantity == 3.5
    assert _enum_name(order.order_side) == "SELL"
    assert order.reduce_only is True
    assert "reduce_only=true" in order.tags


def test_live_submission_does_not_send_unsupported_native_reduce_only() -> None:
    strategy = FakeStrategy()

    order = submit_approved_decision(
        cast(OrderSubmittingStrategy[FakeOrder], strategy),
        _approved(OrderIntent.TAKER_FAK, reduce_only=True, quantity=3.5),
        fixed_stake_usdc=10.0,
        best_ask=0.80,
        best_bid=0.45,
        instrument_id_resolver=lambda _value: FakeInstrument(),
        use_native_reduce_only=False,
    )

    assert order.reduce_only is False
    assert "reduce_only=true" in order.tags


def test_reduce_only_submission_rejects_missing_typed_quantity() -> None:
    import pytest

    strategy = FakeStrategy()

    with pytest.raises(
        ValueError, match="reduce-only decision requires explicit quantity"
    ):
        submit_approved_decision(
            cast(OrderSubmittingStrategy[FakeOrder], strategy),
            _approved(OrderIntent.TAKER_FAK, reduce_only=True),
            fixed_stake_usdc=10.0,
            best_ask=0.80,
            best_bid=0.45,
            instrument_id_resolver=lambda _value: FakeInstrument(),
        )


def test_submit_approved_decision_uses_native_pyo3_instrument_converters() -> None:
    from nautilus_trader.core import nautilus_pyo3 as pyo3

    price_increment = pyo3.Price.from_str("0.01")
    size_increment = pyo3.Quantity.from_str("0.01")
    instrument = pyo3.BinaryOption(
        instrument_id=pyo3.InstrumentId.from_str("up-token.POLYMARKET"),
        raw_symbol=pyo3.Symbol("up-token"),
        asset_class=pyo3.AssetClass.ALTERNATIVE,
        currency=pyo3.Currency.from_str("USDC"),
        price_precision=price_increment.precision,
        size_precision=size_increment.precision,
        price_increment=price_increment,
        size_increment=size_increment,
        activation_ns=0,
        expiration_ns=10_000_000_000,
        ts_event=0,
        ts_init=0,
        min_quantity=size_increment,
        outcome="Yes",
    )
    strategy = FakeStrategy()

    order = submit_approved_decision(
        cast(OrderSubmittingStrategy[FakeOrder], strategy),
        _approved(OrderIntent.TAKER_IOC),
        fixed_stake_usdc=10.0,
        best_ask=0.505,
        instrument_id_resolver=lambda _token_id: instrument,
    )

    expected_price = instrument.make_price(0.505)
    expected_quantity = instrument.make_qty(10.0 / 0.505)
    assert order.price == expected_price
    assert order.quantity == expected_quantity
    assert order.price.precision == instrument.price_precision
    assert order.quantity.precision == instrument.size_precision


def test_native_price_quantization_cannot_exceed_entry_ceiling() -> None:
    import pytest
    from nautilus_trader.core import nautilus_pyo3 as pyo3

    price_increment = pyo3.Price.from_str("0.01")
    size_increment = pyo3.Quantity.from_str("0.01")
    instrument = pyo3.BinaryOption(
        instrument_id=pyo3.InstrumentId.from_str("up-token.POLYMARKET"),
        raw_symbol=pyo3.Symbol("up-token"),
        asset_class=pyo3.AssetClass.ALTERNATIVE,
        currency=pyo3.Currency.from_str("USDC"),
        price_precision=price_increment.precision,
        size_precision=size_increment.precision,
        price_increment=price_increment,
        size_increment=size_increment,
        activation_ns=0,
        expiration_ns=10_000_000_000,
        ts_event=0,
        ts_init=0,
        min_quantity=size_increment,
        outcome="Yes",
    )
    strategy = FakeStrategy()

    with pytest.raises(ValueError, match="exceeds max entry price"):
        submit_approved_decision(
            cast(OrderSubmittingStrategy[FakeOrder], strategy),
            _approved(OrderIntent.TAKER_IOC, max_entry_price=0.509),
            fixed_stake_usdc=10.0,
            best_ask=0.509,
            instrument_id_resolver=lambda _token_id: instrument,
        )

    assert strategy.submitted == []
