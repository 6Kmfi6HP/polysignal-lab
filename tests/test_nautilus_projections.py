from __future__ import annotations

from types import SimpleNamespace

from polysignal_lab.nautilus_runtime.projections import (
    project_fill_event,
    project_order_event,
    project_portfolio_snapshot,
    project_position,
)


class _FloatLike:
    def __init__(self, value: float) -> None:
        self.value = value

    def __float__(self) -> float:
        return self.value

    def __str__(self) -> str:
        return str(self.value)


class _MoneyLike:
    def __init__(self, value: float) -> None:
        self.value = value

    def as_double(self) -> float:
        return self.value

    def __str__(self) -> str:
        return f"{self.value} USDC"


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

    assert row["paper_order_id"] == "C-001"
    assert row["client_order_id"] == "C-001"
    assert row["instrument_id"] == "up-token.POLYMARKET"
    assert row["side"] == "BUY"
    assert row["order_type"] == "LIMIT"
    assert row["time_in_force"] == "IOC"
    assert row["order_intent"] == "default"
    assert row["quantity"] == 20.0
    assert row["price"] == 0.50
    assert row["strategy"] == "ptb_diff"
    assert row["condition_id"] == "condition-btc-5m"


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

    assert row["paper_fill_id"] == "T-001"
    assert row["paper_order_id"] == "C-001"
    assert row["client_order_id"] == "C-001"
    assert row["trade_id"] == "T-001"
    assert row["quantity"] == 12.5
    assert row["price"] == 0.50
    assert row["notional"] == 6.25


def test_project_fill_event_accepts_nautilus_price_quantity_objects() -> None:
    event = SimpleNamespace(
        client_order_id="C-002",
        instrument_id="up-token.POLYMARKET",
        trade_id="T-002",
        last_qty=_FloatLike(12.0),
        last_px=_FloatLike(0.66),
        liquidity_side="TAKER",
    )

    row = project_fill_event(event)

    assert row["quantity"] == 12.0
    assert row["price"] == 0.66
    assert row["notional"] == 7.92


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

    assert row["paper_position_id"] == "P-001"
    assert row["position_id"] == "P-001"
    assert row["instrument_id"] == "up-token.POLYMARKET"
    assert row["quantity"] == 20.0
    assert row["avg_entry_price"] == 0.50
    assert row["realized_pnl"] == 1.25
    assert row["status"] == "OPEN"
    assert row["is_closed"] is False


def test_project_portfolio_snapshot_sums_currency_equity_mapping() -> None:
    account = SimpleNamespace(id="ACCOUNT-001")

    class Portfolio:
        id = "portfolio-001"

        def equity(self, *, account_id: str) -> dict[str, _MoneyLike]:
            assert account_id == "ACCOUNT-001"
            return {"USDC": _MoneyLike(101.25), "USD": _MoneyLike(2.5)}

    row = project_portfolio_snapshot(Portfolio(), account=account)

    assert row["equity"] == 103.75