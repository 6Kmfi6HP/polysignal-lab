"""
Input: __future__, __future__.annotations, nautilus_trader.model.enums, nautilus_trader.model.enums.OrderSide, nautilus_trader.model.enums.TimeInForce, polysignal_lab.domain.enums, polysignal_lab.domain.enums.OrderIntent, polysignal_lab.domain.enums.Side, polysignal_lab.nautilus_runtime.polymarket_adapter, polysignal_lab.nautilus_runtime.polymarket_adapter.PolymarketEnumParser
Output: test_polymarket_enum_parser_maps_side_to_nautilus_order_side, test_polymarket_enum_parser_maps_order_intent_to_time_in_force
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""


from __future__ import annotations

from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.enums import TimeInForce

from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.nautilus_runtime.polymarket_adapter import PolymarketEnumParser


def test_polymarket_enum_parser_maps_side_to_nautilus_order_side() -> None:
    assert PolymarketEnumParser.to_nautilus_order_side(Side.UP) == OrderSide.BUY
    assert PolymarketEnumParser.to_nautilus_order_side(Side.DOWN) == OrderSide.BUY
    assert (
        PolymarketEnumParser.to_nautilus_order_side(Side.UP, reduce_only=True)
        == OrderSide.SELL
    )


def test_polymarket_enum_parser_maps_order_intent_to_time_in_force() -> None:
    assert (
        PolymarketEnumParser.to_nautilus_time_in_force(OrderIntent.PASSIVE_GTD)
        == TimeInForce.GTD
    )
    assert (
        PolymarketEnumParser.to_nautilus_time_in_force(OrderIntent.TAKER_FOK)
        == TimeInForce.FOK
    )
    assert (
        PolymarketEnumParser.to_nautilus_time_in_force(OrderIntent.TAKER_FAK)
        == TimeInForce.IOC
    )
    assert (
        PolymarketEnumParser.to_nautilus_time_in_force(OrderIntent.TAKER_IOC)
        == TimeInForce.IOC
    )
