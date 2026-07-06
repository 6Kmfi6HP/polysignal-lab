from __future__ import annotations

from datetime import UTC, datetime

from polysignal_lab.nautilus_runtime.exit_policy import ExitReason, NautilusExitDecision
from polysignal_lab.nautilus_runtime.native_exit import submit_exit_decision


class FakeOrderFactory:
    def limit(self, **kwargs):
        return kwargs


class FakeStrategy:
    def __init__(self) -> None:
        self.order_factory = FakeOrderFactory()
        self.submitted_orders = []

    def submit_order(self, order):
        self.submitted_orders.append(order)


def test_submit_exit_decision_submits_reduce_only_sell_order() -> None:
    strategy = FakeStrategy()
    decision = NautilusExitDecision(
        reason=ExitReason.TAKE_PROFIT,
        position_id="pos-1",
        instrument_id="token-up.POLYMARKET",
        quantity=20.0,
        limit_price=0.91,
        ts_event=datetime(2026, 7, 6, tzinfo=UTC),
    )

    order = submit_exit_decision(
        strategy,
        decision,
        instrument_id_resolver=lambda value: value,
    )

    assert order is strategy.submitted_orders[-1]
    assert order["instrument_id"] == "token-up.POLYMARKET"
    assert order["reduce_only"] is True
    assert "exit_reason=take_profit" in order["tags"]


def test_evaluate_condition_submits_exit_order_for_qualifying_position(monkeypatch) -> None:
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from polysignal_lab.alpha.types import FreshnessView, MarketView, SideBookView
    from polysignal_lab.config import ExitModelConfig
    from polysignal_lab.domain.enums import Side
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    submitted = []

    class Core:
        def evaluate(self, view):
            return []

    class Assembler:
        def build(self, condition_id):
            now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
            up = SideBookView(
                token_id="token-up",
                best_bid=0.91,
                best_ask=0.92,
                spread=0.01,
                freshness_ms=100,
            )
            down = SideBookView(
                token_id="token-down",
                best_bid=0.10,
                best_ask=0.11,
                spread=0.01,
                freshness_ms=100,
            )
            return MarketView(
                view_id="view-1",
                market_id="mkt-1",
                market_slug="slug",
                condition_id=condition_id,
                asset="BTC",
                timeframe="5m",
                start_ts=None,
                end_ts=None,
                created_at=now,
                seconds_to_close=300,
                up=up,
                down=down,
                spot=None,
                price_to_beat=None,
                up_trades=(),
                down_trades=(),
                metrics={},
                freshness=FreshnessView(100, 100, None, 100),
            )

    class Registry:
        def by_condition(self, condition_id):
            return None

    strategy = PolySignalNativeStrategy(
        core=Core(),
        assembler=Assembler(),
        condition_ids=("condition-1",),
        strategy_name="test",
        registry=Registry(),
        exit_model=ExitModelConfig(),
        instrument_id_resolver=lambda value: value,
    )
    strategy.cache_reader = SimpleNamespace(
        read_positions=lambda: [
            {
                "position_id": "pos-1",
                "condition_id": "condition-1",
                "instrument_id": "token-up.POLYMARKET",
                "token_id": "token-up",
                "quantity": 20.0,
                "avg_entry_price": 0.50,
                "opened_at": "2026-07-06T12:00:00+00:00",
                "is_closed": False,
            }
        ]
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.native_exit.submit_exit_decision",
        lambda _strategy, decision, **_kwargs: submitted.append(decision),
    )

    strategy.evaluate_condition("condition-1")

    assert len(submitted) == 1
    assert submitted[0].position_id == "pos-1"


def _exit_evaluation_fixtures():
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from polysignal_lab.alpha.types import FreshnessView, MarketView, SideBookView
    from polysignal_lab.config import ExitModelConfig
    from polysignal_lab.domain.enums import Side
    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class Core:
        def evaluate(self, view):
            return []

    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    up = SideBookView(
        token_id="token-up",
        best_bid=0.91,
        best_ask=0.92,
        spread=0.01,
        freshness_ms=100,
    )
    down = SideBookView(
        token_id="token-down",
        best_bid=0.10,
        best_ask=0.11,
        spread=0.01,
        freshness_ms=100,
    )
    view = MarketView(
        view_id="view-1",
        market_id="mkt-1",
        market_slug="slug",
        condition_id="condition-1",
        asset="BTC",
        timeframe="5m",
        start_ts=None,
        end_ts=None,
        created_at=now,
        seconds_to_close=300,
        up=up,
        down=down,
        spot=None,
        price_to_beat=None,
        up_trades=(),
        down_trades=(),
        metrics={},
        freshness=FreshnessView(100, 100, None, 100),
    )
    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="mkt-1",
            market_slug="slug",
            condition_id="condition-1",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("token-up.POLYMARKET", "token-up", Side.UP),
            down=InstrumentTokenMeta("token-down.POLYMARKET", "token-down", Side.DOWN),
        )
    )
    strategy = PolySignalNativeStrategy(
        core=Core(),
        assembler=SimpleNamespace(),
        condition_ids=("condition-1",),
        strategy_name="test",
        registry=registry,
        exit_model=ExitModelConfig(),
        instrument_id_resolver=lambda value: value,
    )
    strategy.cache_reader = SimpleNamespace(
        read_positions=lambda: [
            {
                "position_id": "pos-1",
                "instrument_id": "token-up.POLYMARKET",
                "quantity": 20.0,
                "avg_entry_price": 0.50,
                "ts": now.isoformat(),
                "is_closed": False,
            }
        ]
    )
    return strategy, view


def test_evaluate_exit_positions_resolves_condition_and_token_from_registry(monkeypatch) -> None:
    submitted = []
    strategy, view = _exit_evaluation_fixtures()
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.native_exit.submit_exit_decision",
        lambda _strategy, decision, **_kwargs: submitted.append(decision),
    )

    strategy.evaluate_exit_positions("condition-1", view)

    assert len(submitted) == 1
    assert submitted[0].position_id == "pos-1"
    assert "pos-1" in strategy._pending_exit_position_ids


def test_evaluate_exit_positions_dedupes_pending_position_ids(monkeypatch) -> None:
    submitted = []
    strategy, view = _exit_evaluation_fixtures()
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.native_exit.submit_exit_decision",
        lambda _strategy, decision, **_kwargs: submitted.append(decision),
    )

    strategy.evaluate_exit_positions("condition-1", view)
    strategy.evaluate_exit_positions("condition-1", view)

    assert len(submitted) == 1
