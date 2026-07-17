from __future__ import annotations

from typing import assert_never

from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.enums import OrderStatus as NautilusOrderStatus
from nautilus_trader.model.enums import TimeInForce

from polysignal_lab.domain.enums import OrderIntent, Side


class PolymarketEnumParser:
    @staticmethod
    def to_nautilus_order_side(side: Side, *, reduce_only: bool = False) -> OrderSide:
        if reduce_only:
            return OrderSide.SELL
        match side:
            case Side.UP | Side.DOWN:
                return OrderSide.BUY
            case unreachable:
                assert_never(unreachable)

    @staticmethod
    def to_nautilus_time_in_force(intent: OrderIntent) -> TimeInForce:
        match intent:
            case OrderIntent.PASSIVE_GTD:
                return TimeInForce.GTD
            case OrderIntent.TAKER_FOK:
                return TimeInForce.FOK
            case OrderIntent.TAKER_FAK | OrderIntent.TAKER_IOC:
                return TimeInForce.IOC
            case unreachable:
                assert_never(unreachable)

    @staticmethod
    def to_nautilus_order_status(status: str) -> NautilusOrderStatus:
        match status.upper():
            case "PENDING":
                return NautilusOrderStatus.SUBMITTED
            case "RESTING" | "ACCEPTED":
                return NautilusOrderStatus.ACCEPTED
            case "REJECTED":
                return NautilusOrderStatus.REJECTED
            case "CANCELLED" | "CANCELED":
                return NautilusOrderStatus.CANCELED
            case "FILLED":
                return NautilusOrderStatus.FILLED
            case "PARTIAL" | "PARTIALLY_FILLED":
                return NautilusOrderStatus.PARTIALLY_FILLED
            case "EXPIRED":
                return NautilusOrderStatus.EXPIRED
            case _:
                raise ValueError(f"unsupported Polymarket order status: {status}")
