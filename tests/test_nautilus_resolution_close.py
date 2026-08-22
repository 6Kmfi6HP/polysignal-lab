from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from polysignal_lab.alpha.types import (
    CachedOrderView,
    CachedPositionView,
    TradingStateView,
)
from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.market_catalog import (
    InstrumentTokenMeta,
    MarketCatalog,
    MarketPairMeta,
)
from polysignal_lab.nautilus_runtime.optional_imports import load_nautilus_module
from polysignal_lab.nautilus_runtime.strategy import resolution_settlement
from polysignal_lab.nautilus_runtime.strategy import subscriptions as subs
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
    MarketSubscriptionState,
)

_pyo3 = load_nautilus_module("nautilus_trader.core.nautilus_pyo3")


def _registry() -> MarketCatalog:
    registry = MarketCatalog(
        instrument_id_resolver=lambda _condition_id, token_id: f"{token_id}.POLYMARKET"
    )
    registry.register(
        MarketPairMeta(
            market_id="mkt-1",
            market_slug="btc-updown-5m",
            condition_id="condition-1",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta(token_id="token-up", side=Side.UP),
            down=InstrumentTokenMeta(token_id="token-down", side=Side.DOWN),
        )
    )
    return registry


def _position(
    *,
    instrument_id: str = "token-up.POLYMARKET",
    side: Side = Side.UP,
    position_id: str = "position-1",
    strategy: str = "test",
    market_id: str = "mkt-1",
    condition_id: str = "condition-1",
) -> CachedPositionView:
    return CachedPositionView(
        position_id=position_id,
        instrument_id=instrument_id,
        strategy=strategy,
        market_id=market_id,
        condition_id=condition_id,
        side=side,
        pair_id=None,
        quantity=10.0,
        avg_entry_price=0.40,
        opened_at=datetime(2026, 7, 6, 12, 0, tzinfo=UTC),
    )


class _Strategy:
    def __init__(
        self,
        *,
        registry: MarketCatalog,
        trading: TradingStateView,
        execution_mode: str = "sandbox",
        raw_position: object | None = None,
    ) -> None:
        self.registry = registry
        self.cache: _Cache = _Cache(raw_position)
        self.strategy_name = "test"
        self.id = "strategy-1"
        self._execution_mode = execution_mode
        self._settled_position_keys: set[tuple[str, str]] = set()
        self.progress: list[str] = []
        self.settlements: list[dict[str, object]] = []
        self.close_calls: list[tuple[object, str, dict[str, Any]]] = []
        self.trading = trading
        self.observability = SimpleNamespace(
            record_event=self._record_event,
        )  # pyright: ignore[reportCallIssue]

    def _record_event(self, table: str, payload: object) -> object:
        if table == "settlements":
            self.settlements.append(cast(dict[str, object], payload))
            return True
        return True

    def _note_runtime_progress(self, phase: str) -> None:
        self.progress.append(phase)

    def close_position(self, position: object, **kwargs: object) -> None:
        self.close_calls.append((position, "close", dict(kwargs)))


class _Cache:
    def __init__(self, raw_position: object | None) -> None:
        self.raw_position = raw_position or SimpleNamespace(is_closed=False)

    def position(self, position_id: object) -> object | None:
        if str(position_id).endswith("position-1"):
            return self.raw_position
        return None


def _close(
    *,
    instrument_id: str = "token-up.POLYMARKET",
    price: float = 1.0,
    ts_event: int = 1_700_000_000_000_000_000,
    execution_mode: str = "sandbox",
) -> _Strategy:
    registry = _registry()
    position = _position(instrument_id=instrument_id, side=Side.UP if "up" in instrument_id else Side.DOWN)
    strategy = _Strategy(
        registry=registry,
        trading=TradingStateView(positions=(position,)),
        execution_mode=execution_mode,
        raw_position=SimpleNamespace(is_closed=False),
    )
    monkeypatch = pytest.MonkeyPatch()
    # Reuse exact type identity expected by resolution_settlement while using
    # the strategy's controlled trading state.
    monkeypatch.setattr(
        resolution_settlement,
        "trading_state_from_cache",
        lambda *a, **k: strategy.trading,
    )
    try:
        resolution_settlement.handle_instrument_close(
            strategy,
            SimpleNamespace(
                instrument_id=instrument_id,
                close_price=_pyo3.Price.from_str(str(price)),
                ts_event=ts_event,
            ),
        )
    finally:
        monkeypatch.undo()
    return strategy


def test_instrument_close_records_resolution_and_requests_sandbox_close() -> None:
    strategy = _close(price=1.0)
    assert len(strategy.settlements) == 1
    row = strategy.settlements[0]
    assert row["exit_mode"] == "RESOLUTION"
    assert row["outcome_value"] == 1.0
    assert row["result"] == "WIN"
    assert row["report_position_id"] == "position-1"
    assert len(strategy.close_calls) == 1
    assert strategy.close_calls[0][0] is strategy.cache.raw_position
    kwargs = strategy.close_calls[0][2]
    assert kwargs["reduce_only"] is True
    assert "resolution_settlement_close=true" in kwargs["tags"]
    assert ("test", "position-1") in strategy._settled_position_keys


def test_instrument_close_loss_records_zero_settlement_and_closes() -> None:
    strategy = _close(price=0.0)
    assert len(strategy.settlements) == 1
    assert strategy.settlements[0]["outcome_value"] == 0.0
    assert strategy.settlements[0]["result"] == "LOSS"
    assert strategy.settlements[0]["settlement_value"] == 0.0
    assert len(strategy.close_calls) == 1


def test_backtest_skips_resolution_settlement() -> None:
    strategy = _close(execution_mode="backtest")
    assert strategy.settlements == []
    assert strategy.close_calls == []
    assert strategy._settled_position_keys == set()


def test_resolution_settlement_is_idempotent() -> None:
    registry = _registry()
    position = _position()
    strategy = _Strategy(
        registry=registry,
        trading=TradingStateView(positions=(position,)),
        raw_position=SimpleNamespace(is_closed=False),
    )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        resolution_settlement,
        "trading_state_from_cache",
        lambda *a, **k: strategy.trading,
    )
    try:
        close = SimpleNamespace(
            instrument_id="token-up.POLYMARKET",
            close_price=_pyo3.Price.from_str("1.0"),
            ts_event=1_700_000_000_000_000_000,
        )
        resolution_settlement.handle_instrument_close(strategy, close)
        resolution_settlement.handle_instrument_close(strategy, close)
    finally:
        monkeypatch.undo()

    assert len(strategy.settlements) == 1
    assert len(strategy.close_calls) == 1
    assert "resolution_result_duplicate" in strategy.progress


def test_exit_order_pending_skips_resolution() -> None:
    registry = _registry()
    position = _position()
    pending_order = CachedOrderView(
        client_order_id="exit-order",
        instrument_id="token-up.POLYMARKET",
        strategy="test",
        market_id="mkt-1",
        condition_id="condition-1",
        side=Side.UP,
        pair_id=None,
        position_id="position-1",
        status="ACCEPTED",
        price=0.90,
        filled_quantity=0.0,
        average_fill_price=None,
        ts_event=None,
        hedge_leg=False,
        reduce_only=True,
        is_open=True,
        is_inflight=True,
        take_profit_price=None,
        stop_loss_price=None,
    )
    strategy = _Strategy(
        registry=registry,
        trading=TradingStateView(orders=(pending_order,), positions=(position,)),
        raw_position=SimpleNamespace(is_closed=False),
    )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        resolution_settlement,
        "trading_state_from_cache",
        lambda *a, **k: strategy.trading,
    )
    try:
        resolution_settlement.handle_instrument_close(
            strategy,
            SimpleNamespace(
                instrument_id="token-up.POLYMARKET",
                close_price=_pyo3.Price.from_str("1.0"),
                ts_event=1_700_000_000_000_000_000,
            ),
        )
    finally:
        monkeypatch.undo()

    assert strategy.settlements == []
    assert strategy.close_calls == []
    assert "resolution_exit_order_pending" in strategy.progress


def test_market_subscription_does_not_wire_instrument_close() -> None:
    calls: list[str] = []

    class Subscriber:
        book_type = "L2_MBP"

        def subscribe_quotes(self, instrument_id, *, client_id=None): calls.append("quotes")

        def subscribe_trades(self, instrument_id, *, client_id=None): calls.append("trades")

        def subscribe_book_deltas(self, instrument_id, *, book_type=None, client_id=None, managed=False):
            calls.append("deltas")

    subs._dispatch_market_subscriptions(Subscriber(), "token-up.POLYMARKET", None)
    assert "close" not in calls


def test_market_unsubscription_does_not_wire_instrument_close() -> None:
    calls: list[str] = []

    class Subscriber:
        def unsubscribe_quotes(self, instrument_id, *, client_id=None): calls.append("quotes")

        def unsubscribe_trades(self, instrument_id, *, client_id=None): calls.append("trades")

        def unsubscribe_book_deltas(self, instrument_id, *, client_id=None): calls.append("deltas")

    strategy = Subscriber()
    strategy.registry = _registry()
    strategy._subscription_state = MarketSubscriptionState()
    strategy._subscription_state.subscribed_instrument_ids.add("token-up.POLYMARKET")

    subs.unsubscribe_market_instrument(strategy, "token-up.POLYMARKET")  # type: ignore[arg-type, call-arg]

    assert "close" not in calls


