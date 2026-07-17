from __future__ import annotations

import pytest
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.enums import OrderStatus as NautilusOrderStatus
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


def test_polymarket_enum_parser_maps_order_status_to_nautilus_status() -> None:
    assert (
        PolymarketEnumParser.to_nautilus_order_status("PENDING")
        == NautilusOrderStatus.SUBMITTED
    )
    assert (
        PolymarketEnumParser.to_nautilus_order_status("RESTING")
        == NautilusOrderStatus.ACCEPTED
    )
    assert (
        PolymarketEnumParser.to_nautilus_order_status("PARTIAL")
        == NautilusOrderStatus.PARTIALLY_FILLED
    )
    assert (
        PolymarketEnumParser.to_nautilus_order_status("cancelled")
        == NautilusOrderStatus.CANCELED
    )


def test_polymarket_enum_parser_rejects_unknown_order_status() -> None:
    with pytest.raises(ValueError, match="unsupported Polymarket order status"):
        PolymarketEnumParser.to_nautilus_order_status("stale")
