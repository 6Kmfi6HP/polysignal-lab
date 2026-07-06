from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from polysignal_lab.nautilus_runtime.exit_policy import NautilusExitDecision
from polysignal_lab.nautilus_runtime.native_order import (
    OrderSubmittingStrategy,
    _enum_member,
    _instrument_id,
    _price_value,
    _quantity_value,
)

OrderT = TypeVar("OrderT")


def submit_exit_decision(
    strategy: OrderSubmittingStrategy[OrderT],
    decision: NautilusExitDecision,
    *,
    instrument_id_resolver: Callable[[str], object],
) -> OrderT:
    instrument = instrument_id_resolver(decision.instrument_id)
    order = strategy.order_factory.limit(
        instrument_id=_instrument_id(instrument),
        order_side=_enum_member("OrderSide", "SELL", "SELL"),
        quantity=_quantity_value(instrument, decision.quantity),
        price=_price_value(instrument, decision.limit_price),
        time_in_force=_enum_member("TimeInForce", "IOC", "IOC"),
        reduce_only=True,
        expire_time=None,
        tags=[
            f"exit_reason={decision.reason.value}",
            f"position_id={decision.position_id}",
        ],
    )
    strategy.submit_order(order)
    return order
