"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Callable, collections.abc.Sequence, datetime, datetime.UTC, datetime.datetime, datetime.timedelta, decimal
Output: submit_approved_decision, NautilusOrderFactory, OrderSubmittingStrategy
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from typing import Protocol, TypeVar, cast

from polysignal_lab.domain.enums import OrderIntent
from polysignal_lab.nautilus_bridge.enum_parser import PolymarketEnumParser
from polysignal_lab.nautilus_runtime.decision_policy import ApprovedDecision
from polysignal_lab.nautilus_runtime.order_mapping import order_spec_from_decision

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
        expire_time: datetime | None,
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
) -> OrderT:
    """Create and submit a Nautilus-native order from an approved alpha decision."""

    spec = order_spec_from_decision(
        approved,
        fixed_stake_usdc=fixed_stake_usdc,
        best_ask=best_ask,
    )
    instrument = instrument_id_resolver(spec.instrument_id)
    order_side = PolymarketEnumParser.to_nautilus_order_side(
        spec.side,
        reduce_only=spec.reduce_only,
    )
    time_in_force = PolymarketEnumParser.to_nautilus_time_in_force(spec.intent)
    expire_time = None
    if spec.intent == OrderIntent.PASSIVE_GTD:
        clock = now or (lambda: datetime.now(UTC))
        expire_time = clock() + timedelta(seconds=spec.expiry_seconds or 300)

    order = strategy.order_factory.limit(
        instrument_id=_instrument_id(instrument),
        order_side=order_side,
        quantity=_quantity_value(instrument, spec.quantity),
        price=_price_value(instrument, spec.price),
        time_in_force=time_in_force,
        reduce_only=spec.reduce_only,
        expire_time=expire_time,
        tags=[f"{key}={value}" for key, value in sorted(spec.tags.items())],
    )
    strategy.submit_order(order)
    return order


def _instrument_id(instrument: object) -> object:
    value = cast(object, getattr(instrument, "id", instrument))
    if isinstance(value, str):
        return InstrumentId.from_str(value)
    return value


def _price_value(instrument: object, value: float) -> object:
    precision = _precision(instrument, "price_precision")
    price_text = _decimal_str(value, precision)
    maker = cast(object, getattr(instrument, "make_price", None))
    if callable(maker):
        maker_value = Decimal(price_text) if precision is not None else value
        return cast(Callable[[Decimal | float], object], maker)(maker_value)
    return Price.from_str(price_text)


def _quantity_value(instrument: object, value: float) -> object:
    precision = _precision(instrument, "size_precision")
    quantity_text = _decimal_str(value, precision)
    maker = cast(object, getattr(instrument, "make_qty", None))
    if callable(maker):
        maker_value = Decimal(quantity_text) if precision is not None else value
        return cast(Callable[[Decimal | float], object], maker)(maker_value)
    return Quantity.from_str(quantity_text)


def _precision(instrument: object, attr: str) -> int | None:
    value = cast(object, getattr(instrument, attr, None))
    return value if isinstance(value, int) else None


def _decimal_str(value: float, precision: int | None = None) -> str:
    decimal_value = Decimal(str(value))
    if precision is None:
        return format(decimal_value.normalize(), "f")
    return format(decimal_value.quantize(Decimal(1).scaleb(-precision)), f".{precision}f")
