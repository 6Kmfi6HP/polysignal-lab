"""
Input: __future__, __future__.annotations, typing, typing.assert_never, nautilus_trader.model.enums, nautilus_trader.model.enums.OrderSide, nautilus_trader.model.enums.TimeInForce, polysignal_lab.domain.enums, polysignal_lab.domain.enums.OrderIntent, polysignal_lab.domain.enums.Side
Output: PolymarketEnumParser
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""


from __future__ import annotations

from typing import assert_never

from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.enums import TimeInForce

from polysignal_lab.domain.enums import OrderIntent, Side


class PolymarketEnumParser:
    """Map PolySignal domain Side/OrderIntent → Nautilus order enums.

    Order *status* is never mapped here: runtime events already carry
    Nautilus OrderStatus; string→enum remapping was a dual-path leftover.
    """

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
