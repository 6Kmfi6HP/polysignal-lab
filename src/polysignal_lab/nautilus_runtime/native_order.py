from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Protocol, TypeVar, cast

from nautilus_trader.core.nautilus_pyo3 import OrderSide, TimeInForce

from polysignal_lab.domain.enums import OrderIntent
from polysignal_lab.nautilus_runtime.custom_data_publisher import timestamp_ns
from polysignal_lab.nautilus_runtime.decision_policy import ApprovedDecision
from polysignal_lab.nautilus_runtime.order_mapping import order_spec_from_decision
from polysignal_lab.nautilus_runtime.order_plan import OrderSubmissionPlan
from polysignal_lab.nautilus_runtime.polymarket_adapter import PolymarketEnumParser
from polysignal_lab.nautilus_runtime.strategy.nautilus_objects import (
    _nautilus_instrument_id,
)

OrderT = TypeVar("OrderT")
OrderT_co = TypeVar("OrderT_co", covariant=True)


class NautilusOrderFactory(Protocol[OrderT_co]):
    def limit(
        self,
        *,
        instrument_id: object,
        order_side: object,
        quantity: object,
        price: object,
        time_in_force: object,
        reduce_only: bool,
        expire_time: int | None,
        tags: Sequence[str],
    ) -> OrderT_co: ...


class OrderSubmittingStrategy(Protocol[OrderT]):
    @property
    def order_factory(self) -> NautilusOrderFactory[OrderT]: ...

    def submit_order(self, order: OrderT) -> None: ...


def submit_approved_decision(
    strategy: OrderSubmittingStrategy[OrderT],
    approved: ApprovedDecision,
    *,
    fixed_stake_usdc: float,
    best_ask: float | None,
    instrument_id_resolver: Callable[[str], object],
    now: Callable[[], datetime] | None = None,
    best_bid: float | None = None,
    view_id: str = "",
    use_native_reduce_only: bool = False,
) -> OrderT:
    """Create and submit a Nautilus-native order from an approved AlphaDecision."""

    spec = order_spec_from_decision(
        approved.decision,
        fixed_stake_usdc=fixed_stake_usdc,
        best_ask=best_ask,
        best_bid=best_bid,
        view_id=view_id,
    )
    instrument = instrument_id_resolver(spec.instrument_id)
    return _submit_native_order(
        strategy,
        spec,
        instrument,
        now=now,
        use_native_reduce_only=use_native_reduce_only,
    )


def _submit_native_order(
    strategy: OrderSubmittingStrategy[OrderT],
    spec: OrderSubmissionPlan,
    instrument: object,
    *,
    now: Callable[[], datetime] | None,
    use_native_reduce_only: bool,
) -> OrderT:
    order_side = getattr(
        OrderSide,
        PolymarketEnumParser.to_nautilus_order_side(
            spec.side,
            reduce_only=spec.reduce_only,
        ).name,
    )
    time_in_force = getattr(
        TimeInForce,
        PolymarketEnumParser.to_nautilus_time_in_force(spec.intent).name,
    )
    expire_time = None
    if spec.intent == OrderIntent.PASSIVE_GTD:
        if now is None:
            raise RuntimeError("Nautilus framework clock is required for GTD expiry")
        expire_time = timestamp_ns(
            now() + timedelta(seconds=spec.expiry_seconds or 300)
        )

    native_price = _price_value(instrument, spec.price)
    _validate_entry_price_ceiling(native_price, spec.max_entry_price)
    order = strategy.order_factory.limit(
        instrument_id=_instrument_id(instrument),
        order_side=order_side,
        quantity=_quantity_value(instrument, spec.quantity),
        price=native_price,
        time_in_force=time_in_force,
        # Sandbox matching enforces reduce-only; live Polymarket does not support it.
        reduce_only=spec.reduce_only and use_native_reduce_only,
        expire_time=expire_time,
        tags=[f"{key}={value}" for key, value in sorted(spec.tags.items())],
    )
    strategy.submit_order(order)
    return order


def _instrument_id(instrument: object) -> object:
    """Coerce the instrument id into the PyO3 family the OrderFactory takes.

    Single normalization entry: nautilus_objects._nautilus_instrument_id. The
    native factory is PyO3, and the identically-named Cython `InstrumentId`
    is rejected with `'InstrumentId' object is not an instance of
    'InstrumentId'`.
    """
    return _nautilus_instrument_id(getattr(instrument, "id", instrument))


def _price_value(instrument: object, value: float) -> object:
    maker = cast(object, getattr(instrument, "make_price", None))
    if not callable(maker):
        raise ValueError("Nautilus Instrument.make_price is required")
    return cast(Callable[[float], object], maker)(value)


def _validate_entry_price_ceiling(price: object, ceiling: float | None) -> None:
    if ceiling is None:
        return
    try:
        native = Decimal(str(price))
        maximum = Decimal(str(ceiling))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(
            "Nautilus Price must be comparable to max_entry_price"
        ) from exc
    if native > maximum:
        raise ValueError(
            f"native price {native} exceeds max entry price {maximum} after quantization"
        )


def _quantity_value(instrument: object, value: float) -> object:
    maker = cast(object, getattr(instrument, "make_qty", None))
    if not callable(maker):
        raise ValueError("Nautilus Instrument.make_qty is required")
    return cast(Callable[[float], object], maker)(value)
