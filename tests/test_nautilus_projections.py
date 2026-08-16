from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from types import SimpleNamespace

import pytest

from nautilus_optional import require_nautilus
from polysignal_lab.nautilus_runtime.strategy import event_projection
from polysignal_lab.nautilus_runtime.projections import (
    project_fill_event,
    project_order_event,
    project_portfolio_snapshot,
    project_position,
)


def test_project_order_event_converts_nautilus_nanoseconds_to_utc() -> None:
    event = SimpleNamespace(ts_event=1_788_451_200_123_456_789, side="UP")

    projected = event_projection.project_order_metrics(
        event,
        registry=None,
        strategy_name="alpha",
    )

    assert projected["ts_event"] == datetime.fromtimestamp(1_788_451_200.1234567, UTC)


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
    event = SimpleNamespace(
        ts_event=datetime(2026, 1, 1, tzinfo=_BadTimezone()), side="UP"
    )

    with pytest.raises(ValueError, match="ts_event datetime"):
        event_projection.project_order_metrics(
            event,
            registry=None,
            strategy_name="alpha",
        )


def test_project_order_event_normalizes_runtime_timezone_error() -> None:
    event = SimpleNamespace(
        ts_event=datetime(2026, 1, 1, tzinfo=_RuntimeErrorTimezone()),
        side="UP",
    )

    with pytest.raises(ValueError, match="ts_event datetime"):
        event_projection.project_order_metrics(
            event,
            registry=None,
            strategy_name="alpha",
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
    event = SimpleNamespace(ts_event=timestamp, side="UP")

    with pytest.raises(ValueError, match="ts_event"):
        event_projection.project_order_metrics(
            event,
            registry=None,
            strategy_name="alpha",
        )


def test_project_order_event_rejects_missing_event_time() -> None:
    with pytest.raises(ValueError, match="ts_event"):
        event_projection.project_order_metrics(
            SimpleNamespace(side="UP"),
            registry=None,
            strategy_name="alpha",
        )


def test_project_order_event_normalizes_timezone_aware_test_double() -> None:
    event = SimpleNamespace(
        ts_event=datetime(2026, 1, 1, 12, tzinfo=timezone(timedelta(hours=-5))),
        side="UP",
    )

    projected = event_projection.project_order_metrics(
        event,
        registry=None,
        strategy_name="alpha",
    )

    assert projected["ts_event"] == datetime(2026, 1, 1, 17, tzinfo=UTC)


def test_fill_without_cache_order_is_quarantined() -> None:
    """Production path no longer routes AlphaFillEvent into core.on_order_filled."""

    class Strategy:
        registry = None
        strategy_name = "alpha"
        _active_condition_ids = {"condition-btc-5m"}
        observability = None

        def __init__(self) -> None:
            self.core = SimpleNamespace()
            self.recorded: list[object] = []
            self.progress: list[str] = []

        def _note_runtime_progress(
        self,
        phase: str,
        *,
        active_condition_ids=None,
    ) -> None:
            self.progress.append(phase)

        def _record_nautilus_fill(self, event: object, metrics: object) -> None:
            _ = event
            self.recorded.append(metrics)

        def _require_assembler(self) -> object:
            raise AssertionError("no core follow-up")

        def _handle_decision(self, decision: object, view: object) -> None:
            raise AssertionError("no core follow-up")

    from polysignal_lab.nautilus_runtime.strategy.order_events import (
        handle_order_filled,
    )

    strategy = Strategy()
    handle_order_filled(
        strategy,
        SimpleNamespace(
            ts_event=1_788_451_200_123_456_789,
            last_px=0.5,
            last_qty=1.0,
            side="UP",
            tags=["strategy=alpha", "condition_id=condition-btc-5m"],
        ),
    )

    assert strategy.recorded == []
    assert "order_event_unresolved" in strategy.progress
    assert "fill_event_quarantined" in strategy.progress


def test_fill_recovers_association_tags_from_cache_order() -> None:
    from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
    from polysignal_lab.nautilus_runtime.strategy.order_events import (
        handle_order_filled,
    )

    order = SimpleNamespace(
        tags=(
            "strategy=alpha",
            "condition_id=condition-btc-5m",
            "reduce_only=true",
            "exit_reason=TAKE_PROFIT",
            "position_id=position-1",
        )
    )

    class Cache:
        def order(self, client_order_id: object) -> object:
            assert str(client_order_id) == "client-order-1"
            return order

    class Strategy:
        registry: MarketCatalog | None = None
        strategy_name: str = "alpha"
        _active_condition_ids: set[str] = {"condition-btc-5m"}
        observability: object | None = None

        def __init__(self) -> None:
            self.cache: object = Cache()
            self.core: object = SimpleNamespace()
            self.recorded: list[dict[str, object]] = []
            self._settled_position_keys: set[tuple[str, str]] = set()

        def _note_runtime_progress(
        self,
        phase: str,
        *,
        active_condition_ids=None,
    ) -> None:
            _ = phase

        def _record_nautilus_fill(
            self,
            event: object,
            metrics: Mapping[str, object],
        ) -> None:
            _ = event
            self.recorded.append(dict(metrics))

        def _record_nautilus_order(
            self,
            event: object,
            metrics: Mapping[str, object],
        ) -> None:
            _ = event, metrics

        def _record_nautilus_position(self, position: object) -> None:
            _ = position

        def _require_assembler(self) -> object:
            return object()

        def _handle_decision(self, decision: object, view: object) -> None:
            _ = decision, view

    strategy = Strategy()
    handle_order_filled(
        strategy,
        SimpleNamespace(
            client_order_id="client-order-1",
            instrument_id="up-token.POLYMARKET",
            last_px=0.5,
            last_qty=1.0,
            side="UP",
            ts_event=1_788_451_200_123_456_789,
        ),
    )

    assert strategy.recorded[0]["reduce_only"] is True
    assert strategy.recorded[0]["exit_reason"] == "TAKE_PROFIT"
    assert strategy.recorded[0]["position_id"] == "position-1"


def test_order_event_merges_partial_event_tags_with_cache_order() -> None:
    from polysignal_lab.nautilus_runtime.strategy.order_events import (
        handle_order_lifecycle_event,
    )

    order = SimpleNamespace(
        tags=(
            "strategy=alpha",
            "market_id=market-1",
            "condition_id=condition-1",
            "token_id=token-up",
        )
    )

    class Cache:
        def order(self, client_order_id: object) -> object:
            _ = client_order_id
            return order

    class Strategy:
        registry = None
        strategy_name = "alpha"
        cache: object = Cache()

        def __init__(self) -> None:
            self.recorded: list[dict[str, object]] = []
            self.progress: list[str] = []

        def _note_runtime_progress(
        self,
        phase: str,
        *,
        active_condition_ids=None,
    ) -> None:
            self.progress.append(phase)

        def _record_nautilus_order(
            self, event: object, metrics: Mapping[str, object]
        ) -> None:
            _ = event
            self.recorded.append(dict(metrics))

    strategy = Strategy()
    handle_order_lifecycle_event(  # pyright: ignore[reportArgumentType]
        strategy,  # pyright: ignore[reportArgumentType]
        "on_order_updated",
        SimpleNamespace(
            client_order_id="client-order-1",
            instrument_id="token-up.POLYMARKET",
            tags=("strategy=alpha", "condition_id="),
            side="UP",
            ts_event=1_788_451_200_123_456_789,
        ),
    )

    assert strategy.recorded[0]["condition_id"] == "condition-1"
    assert strategy.recorded[0]["market_id"] == "market-1"


def test_order_event_quarantines_cache_order_without_project_identity() -> None:
    from polysignal_lab.nautilus_runtime.strategy.order_events import (
        handle_order_lifecycle_event,
    )

    class Cache:
        def __init__(self) -> None:
            self.order_tags: tuple[str, ...] = ("foo=bar",)

        def order(self, client_order_id: object) -> object:
            _ = client_order_id
            return SimpleNamespace(tags=self.order_tags)

    class Strategy:
        registry = None
        strategy_name = "alpha"
        cache = Cache()

        def __init__(self) -> None:
            self.recorded: list[dict[str, object]] = []
            self.progress: list[str] = []

        def _note_runtime_progress(
        self,
        phase: str,
        *,
        active_condition_ids=None,
    ) -> None:
            self.progress.append(phase)

        def _record_nautilus_order(
            self, event: object, metrics: Mapping[str, object]
        ) -> None:
            _ = event
            self.recorded.append(dict(metrics))

    strategy = Strategy()
    event = SimpleNamespace(
        client_order_id="client-order-1",
        instrument_id="token-up.POLYMARKET",
        side="UP",
        ts_event=1_788_451_200_123_456_789,
    )

    handle_order_lifecycle_event(  # pyright: ignore[reportArgumentType]
        strategy,  # pyright: ignore[reportArgumentType]
        "on_order_accepted",
        event,
    )
    strategy.cache.order_tags = ("strategy=", "condition_id=condition-1")
    handle_order_lifecycle_event(  # pyright: ignore[reportArgumentType]
        strategy,  # pyright: ignore[reportArgumentType]
        "on_order_accepted",
        event,
    )

    assert strategy.recorded == []
    assert strategy.progress.count("order_event_unresolved") == 2


def test_tagless_cache_miss_fill_is_quarantined() -> None:
    from polysignal_lab.nautilus_runtime.strategy.order_events import (
        handle_order_filled,
    )

    class Cache:
        def order(self, client_order_id: object) -> None:
            _ = client_order_id
            return None

    class Strategy:
        registry = None
        strategy_name = "alpha"
        observability = None
        cache: object = Cache()
        core: object = SimpleNamespace()

        def __init__(self) -> None:
            self.progress: list[str] = []
            self.recorded: list[object] = []

        def _note_runtime_progress(
        self,
        phase: str,
        *,
        active_condition_ids=None,
    ) -> None:
            self.progress.append(phase)

        def _record_nautilus_fill(
            self, event: object, metrics: Mapping[str, object]
        ) -> None:
            _ = event
            self.recorded.append(metrics)

    strategy = Strategy()
    handle_order_filled(
        strategy,  # pyright: ignore[reportArgumentType]
        SimpleNamespace(
            client_order_id="missing",
            instrument_id="token-up.POLYMARKET",
            tags=(),
            last_px=0.5,
            last_qty=1.0,
        ),
    )

    assert strategy.recorded == []
    assert "order_event_unresolved" in strategy.progress
    assert "fill_event_quarantined" in strategy.progress


def test_project_fill_metrics_raises_on_missing_shares() -> None:
    event = SimpleNamespace(
        ts_event=1_788_451_200_123_456_789,
        side="UP",
        last_px=0.5,
    )

    with pytest.raises(ValueError, match="shares"):
        event_projection.project_fill_metrics(
            event,
            registry=None,
            strategy_name="alpha",
        )


def test_project_fill_metrics_raises_on_zero_shares() -> None:
    event = SimpleNamespace(
        ts_event=1_788_451_200_123_456_789,
        side="UP",
        last_px=0.5,
        last_qty=0.0,
    )

    with pytest.raises(ValueError, match="shares"):
        event_projection.project_fill_metrics(
            event,
            registry=None,
            strategy_name="alpha",
        )

def test_project_fill_metrics_raises_on_non_finite_shares() -> None:
    event = SimpleNamespace(
        ts_event=1_788_451_200_123_456_789,
        side="UP",
        last_px=0.5,
        last_qty=float("nan"),
    )

    with pytest.raises(ValueError, match="shares"):
        event_projection.project_fill_metrics(
            event,
            registry=None,
            strategy_name="alpha",
        )


def test_project_fill_metrics_raises_on_missing_fill_price() -> None:
    event = SimpleNamespace(
        ts_event=1_788_451_200_123_456_789,
        side="UP",
        last_qty=1.0,
    )

    with pytest.raises(ValueError, match="fill_price"):
        event_projection.project_fill_metrics(
            event,
            registry=None,
            strategy_name="alpha",
        )


def test_fill_with_missing_quantity_is_quarantined() -> None:
    from polysignal_lab.nautilus_runtime.strategy.order_events import (
        handle_order_filled,
    )

    order = SimpleNamespace(
        tags=(
            "strategy=alpha",
            "condition_id=condition-btc-5m",
        )
    )

    class Cache:
        def order(self, client_order_id: object) -> object:
            _ = client_order_id
            return order

    class Strategy:
        registry = None
        strategy_name = "alpha"
        _active_condition_ids = {"condition-btc-5m"}
        observability = None
        cache: object = Cache()
        core: object = SimpleNamespace()

        def __init__(self) -> None:
            self.recorded: list[object] = []
            self.progress: list[str] = []

        def _note_runtime_progress(
        self,
        phase: str,
        *,
        active_condition_ids=None,
    ) -> None:
            self.progress.append(phase)

        def _record_nautilus_fill(
            self, event: object, metrics: Mapping[str, object]
        ) -> None:
            _ = event, metrics
            self.recorded.append(metrics)

    strategy = Strategy()
    handle_order_filled(
        strategy,  # pyright: ignore[reportArgumentType]
        SimpleNamespace(
            client_order_id="client-order-1",
            instrument_id="up-token.POLYMARKET",
            ts_event=1_788_451_200_123_456_789,
            last_px=0.5,
            side="UP",
        ),
    )

    assert strategy.recorded == []
    assert "fill_event_quarantined" in strategy.progress


def test_fill_notify_receives_projected_shares() -> None:
    from polysignal_lab.nautilus_runtime.strategy.order_events import (
        handle_order_filled,
    )

    order = SimpleNamespace(
        tags=(
            "strategy=alpha",
            "condition_id=condition-btc-5m",
        )
    )

    class Cache:
        def order(self, client_order_id: object) -> object:
            _ = client_order_id
            return order

    class Strategy:
        registry = None
        strategy_name = "alpha"
        _active_condition_ids = {"condition-btc-5m"}
        observability = None
        cache: object = Cache()

        def __init__(self) -> None:
            self.recorded: list[dict[str, object]] = []
            self.notified: list[float] = []
            self.core: object = SimpleNamespace(
                on_notify_fill=lambda market_id, side, shares: self.notified.append(
                    shares
                )
            )

        def _note_runtime_progress(
        self,
        phase: str,
        *,
        active_condition_ids=None,
    ) -> None:
            _ = phase, active_condition_ids

        def _record_nautilus_fill(
            self, event: object, metrics: Mapping[str, object]
        ) -> None:
            _ = event
            self.recorded.append(dict(metrics))

        def _record_nautilus_order(
            self, event: object, metrics: Mapping[str, object]
        ) -> None:
            _ = event, metrics

        def _record_nautilus_position(self, position: object) -> None:
            _ = position

        def _require_assembler(self) -> object:
            return object()

        def _handle_decision(self, decision: object, view: object) -> None:
            _ = decision, view

    strategy = Strategy()
    handle_order_filled(
        strategy,  # pyright: ignore[reportArgumentType]
        SimpleNamespace(
            client_order_id="client-order-1",
            instrument_id="up-token.POLYMARKET",
            ts_event=1_788_451_200_123_456_789,
            last_px=0.5,
            last_qty=10.0,
            side="UP",
        ),
    )

    assert strategy.notified == [10.0]
    assert strategy.recorded[0]["shares"] == 10.0


class _FloatLike:
    def __init__(self, value: float) -> None:
        self.value = value

    def __float__(self) -> float:
        return self.value

    def __str__(self) -> str:
        return str(self.value)


class _CurrencyLike:
    def __init__(self, code: str) -> None:
        self.code = code

    def __str__(self) -> str:
        return self.code


class _MoneyLike:
    def __init__(self, value: float) -> None:
        self.value = value

    def as_double(self) -> float:
        return self.value

    def __str__(self) -> str:
        return f"{self.value} USDC"


def test_project_order_event_uses_nautilus_event_fields() -> None:
    """`OrderUpdated` is the one order event carrying its own economics, so its
    quantity/price win; business metadata still arrives via metrics."""
    require_nautilus()
    from nautilus_trader.test_kit.rust.events_pyo3 import TestEventsProviderPyo3

    event = TestEventsProviderPyo3.order_updated()

    row = project_order_event(
        event,
        metrics={
            "strategy": "ptb_diff",
            "condition_id": "condition-btc-5m",
            "signal_id": "sig-001",
        },
    )

    assert row["report_order_id"] == str(event.client_order_id)
    assert row["client_order_id"] == str(event.client_order_id)
    assert row["instrument_id"] == str(event.instrument_id)
    assert row["status"] == "UPDATED"
    assert row["order_intent"] == "default"
    assert row["quantity"] == 1.5
    assert row["price"] == 1500.0
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

    assert row["report_fill_id"] == "T-001"
    assert row["report_order_id"] == "C-001"
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
        metrics={"signal_id": "sig-002"},
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

    assert row["report_position_id"] == "P-001"
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


def test_project_portfolio_snapshot_selects_currency_equity_mapping() -> None:
    account = SimpleNamespace(id="ACCOUNT-001")

    class Portfolio:
        id = "portfolio-001"

        def equity(self, *, account_id: str) -> dict[_CurrencyLike, _MoneyLike]:
            assert account_id == "ACCOUNT-001"
            return {
                _CurrencyLike("pUSD"): _MoneyLike(200.0),
                _CurrencyLike("USDC"): _MoneyLike(100.0),
            }

    row = project_portfolio_snapshot(
        Portfolio(),
        account=account,
        currency="pUSD",
    )

    assert row["equity"] == 200.0


def test_project_portfolio_snapshot_sums_currency_equity_mapping() -> None:
    account = SimpleNamespace(id="ACCOUNT-001")

    class Portfolio:
        id = "portfolio-001"

        def equity(self, *, account_id: str) -> dict[str, _MoneyLike]:
            assert account_id == "ACCOUNT-001"
            return {"USDC": _MoneyLike(101.25), "USD": _MoneyLike(2.5)}

    row = project_portfolio_snapshot(Portfolio(), account=account)

    assert row["equity"] == 103.75


def test_project_portfolio_snapshot_without_account_reports_no_equity() -> None:
    """`Portfolio.equity(venue=None, account_id=None)` needs an account to scope
    the total; with none available we report nothing rather than guess."""

    class Portfolio:
        id: str = "portfolio-001"

        def equity(
            self, venue: object = None, account_id: object = None
        ) -> dict[str, _MoneyLike]:
            _ = venue, account_id
            raise AssertionError("must not ask for a venue-wide equity total")

    row = project_portfolio_snapshot(Portfolio(), account=None, currency="USDC")

    assert row["portfolio_id"] == "portfolio-001"
    assert row["equity"] is None
