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
