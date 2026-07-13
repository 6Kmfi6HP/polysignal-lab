"""
Input: __future__, __future__.annotations, types, types.SimpleNamespace, polysignal_lab.nautilus_runtime.projections, polysignal_lab.nautilus_runtime.projections.(
Output: test_project_order_event_uses_nautilus_event_fields, test_project_fill_event_uses_nautilus_fill_fields, test_project_fill_event_accepts_nautilus_price_quantity_objects, test_project_position_uses_nautilus_position_fields, test_project_closed_position_uses_close_time_for_lifecycle_ordering, test_project_position_leaves_missing_money_unknown, test_project_portfolio_snapshot_sums_currency_equity_mapping, _FloatLike, _MoneyLike
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone, tzinfo
from types import SimpleNamespace

import pytest

from polysignal_lab.nautilus_runtime.strategy import event_projection
from polysignal_lab.nautilus_runtime.projections import (
    project_fill_event,
    project_order_event,
    project_portfolio_snapshot,
    project_position,
)


def test_project_order_event_converts_nautilus_nanoseconds_to_utc() -> None:
    event = SimpleNamespace(ts_event=1_788_451_200_123_456_789)

    projected = event_projection.project_order_event(
        event,
        registry=None,
        strategy_name="alpha",
        metrics_lookup=lambda _: {},
    )

    assert projected.ts_event == datetime.fromtimestamp(1_788_451_200.1234567, UTC)


class _NaiveTimezone(tzinfo):
    def utcoffset(self, dt: datetime | None) -> None:
        return None

    def dst(self, dt: datetime | None) -> None:
        return None


class _BadTimezone(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta:
        raise TypeError("malformed timezone")

    def dst(self, dt: datetime | None) -> None:
        return None


class _RuntimeErrorTimezone(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta:
        raise RuntimeError("malformed timezone")

    def dst(self, dt: datetime | None) -> None:
        return None


def test_project_order_event_normalizes_malformed_timezone_error() -> None:
    event = SimpleNamespace(ts_event=datetime(2026, 1, 1, tzinfo=_BadTimezone()))

    with pytest.raises(ValueError, match="ts_event datetime"):
        event_projection.project_order_event(
            event,
            registry=None,
            strategy_name="alpha",
            metrics_lookup=lambda _: {},
        )


def test_project_order_event_normalizes_runtime_timezone_error() -> None:
    event = SimpleNamespace(ts_event=datetime(2026, 1, 1, tzinfo=_RuntimeErrorTimezone()))

    with pytest.raises(ValueError, match="ts_event datetime"):
        event_projection.project_order_event(
            event,
            registry=None,
            strategy_name="alpha",
            metrics_lookup=lambda _: {},
        )


@pytest.mark.parametrize(
    "timestamp",
    (
        0,
        -1,
        True,
        1.0,
        "1",
        None,
        datetime(2026, 1, 1),
        datetime(2026, 1, 1, tzinfo=_NaiveTimezone()),
        10**100,
    ),
)
def test_project_order_event_rejects_invalid_event_time(timestamp: object) -> None:
    event = SimpleNamespace(ts_event=timestamp)

    with pytest.raises(ValueError, match="ts_event"):
        event_projection.project_order_event(
            event,
            registry=None,
            strategy_name="alpha",
            metrics_lookup=lambda _: {},
        )


def test_project_order_event_rejects_missing_event_time() -> None:
    with pytest.raises(ValueError, match="ts_event"):
        event_projection.project_order_event(
            SimpleNamespace(),
            registry=None,
            strategy_name="alpha",
            metrics_lookup=lambda _: {},
        )


def test_project_order_event_normalizes_timezone_aware_test_double() -> None:
    event = SimpleNamespace(
        ts_event=datetime(2026, 1, 1, 12, tzinfo=timezone(timedelta(hours=-5)))
    )

    projected = event_projection.project_order_event(
        event,
        registry=None,
        strategy_name="alpha",
        metrics_lookup=lambda _: {},
    )

    assert projected.ts_event == datetime(2026, 1, 1, 17, tzinfo=UTC)


def test_fill_follow_up_builds_view_at_event_time() -> None:
    created_at = datetime.fromtimestamp(1_788_451_200.1234567, UTC)
    decision = SimpleNamespace(condition_id="condition-btc-5m")

    class MetricsTracker:
        def metrics_for_event(self, event: object) -> dict[str, object]:
            _ = event
            return {}

        def forget(self, event: object, order: object) -> None:
            _ = event, order

    class Assembler:
        def __init__(self) -> None:
            self.created_at: datetime | None = None

        def build(
            self, condition_id: str, *, created_at: datetime | None = None
        ) -> object:
            assert condition_id == "condition-btc-5m"
            self.created_at = created_at
            return object()

    class Core:
        def on_order_filled(self, event: object) -> tuple[object, ...]:
            _ = event
            return (decision,)

    class Strategy:
        registry = None
        strategy_name = "alpha"
        _active_condition_ids = {"condition-btc-5m"}
        _metrics_tracker = MetricsTracker()

        def __init__(self) -> None:
            self.core = Core()
            self.assembler = Assembler()
            self.handled: list[tuple[object, object]] = []

        def _note_runtime_progress(self, phase: str) -> None:
            _ = phase

        def _record_nautilus_fill(
            self, event: object, metrics: object
        ) -> None:
            _ = event, metrics

        def _require_assembler(self) -> Assembler:
            return self.assembler

        def _handle_decision(self, decision: object, view: object) -> None:
            self.handled.append((decision, view))

    from polysignal_lab.nautilus_runtime.strategy.order_events import handle_order_filled

    strategy = Strategy()
    handle_order_filled(
        strategy,
        SimpleNamespace(
            ts_event=1_788_451_200_123_456_789,
            last_px=0.5,
            last_qty=1.0,
        ),
    )

    assert strategy.assembler.created_at == created_at
    assert len(strategy.handled) == 1


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
        tags=["strategy=ptb_diff", "condition_id=condition-btc-5m", "signal_id=sig-001"],
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
    assert row["signal_id"] == "sig-001"


def test_project_fill_event_uses_nautilus_fill_fields() -> None:
    event = SimpleNamespace(
        client_order_id="C-001",
        instrument_id="up-token.POLYMARKET",
        trade_id="T-001",
        last_qty=12.5,
        last_px=0.50,
        liquidity_side="TAKER",
        metrics={"signal_id": "sig-001"},
    )

    row = project_fill_event(event)

    assert row["paper_fill_id"] == "T-001"
    assert row["paper_order_id"] == "C-001"
    assert row["client_order_id"] == "C-001"
    assert row["trade_id"] == "T-001"
    assert row["quantity"] == 12.5
    assert row["price"] == 0.50
    assert row["notional"] == 6.25
    assert row["signal_id"] == "sig-001"


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
        ts_opened=1_788_451_200_123_456_789,
        ts_closed=1_788_451_201_123_456_789,
        is_closed=False,
    )

    row = project_position(position)

    assert row["paper_position_id"] == "P-001"
    assert row["position_id"] == "P-001"
    assert row["instrument_id"] == "up-token.POLYMARKET"
    assert row["quantity"] == 20.0
    assert row["avg_entry_price"] == 0.50
    assert row["stake_usdc"] == 10.0
    assert row["realized_pnl"] == 1.25
    assert row["status"] == "OPEN"
    assert row["is_closed"] is False
    assert row["opened_at"] == "2026-09-03T16:00:00.123457Z"
    assert row["closed_at"] == "2026-09-03T16:00:01.123457Z"
    assert row["ts"] == "2026-09-03T16:00:00.123457Z"


def test_project_closed_position_uses_close_time_for_lifecycle_ordering() -> None:
    opened_at = 1_788_451_200_123_456_789
    closed_at = 1_788_451_201_123_456_789
    row = project_position(
        SimpleNamespace(
            id="P-closed",
            ts_opened=opened_at,
            ts_closed=closed_at,
            is_closed=True,
        )
    )

    assert row["ts"] == "2026-09-03T16:00:01.123457Z"


def test_project_position_leaves_missing_money_unknown() -> None:
    position = SimpleNamespace(
        id="P-missing-money",
        instrument_id="up-token.POLYMARKET",
        is_closed=False,
    )

    row = project_position(position)

    assert row["quantity"] is None
    assert row["avg_entry_price"] is None
    assert row["stake_usdc"] is None


def test_project_portfolio_snapshot_sums_currency_equity_mapping() -> None:
    account = SimpleNamespace(id="ACCOUNT-001")

    class Portfolio:
        id = "portfolio-001"

        def equity(self, *, account_id: str) -> dict[str, _MoneyLike]:
            assert account_id == "ACCOUNT-001"
            return {"USDC": _MoneyLike(101.25), "USD": _MoneyLike(2.5)}

    row = project_portfolio_snapshot(Portfolio(), account=account)

    assert row["equity"] == 103.75
