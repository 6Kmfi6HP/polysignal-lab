"""
Input: __future__, __future__.annotations, datetime, datetime.UTC, datetime.datetime, types, types.SimpleNamespace, polysignal_lab.alpha.types, polysignal_lab.alpha.types.FreshnessView, polysignal_lab.alpha.types.MarketView, polysignal_lab.nautilus_runtime.decision_policy
Output: test_evaluate_condition_does_not_run_custom_exit_scan, test_native_strategy_has_no_custom_exit_evaluation_api
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from polysignal_lab.alpha.types import FreshnessView, MarketView, SideBookView
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicy
from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy


def _native_strategy() -> PolySignalNativeStrategy:
    class Core:
        def evaluate(self, view):
            return []

    class Assembler:
        def build(self, condition_id, *, created_at=None):
            _ = created_at
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
        policy=DecisionPolicy(),
        registry=Registry(),
        instrument_id_resolver=lambda value: value,
    )
    return strategy


def test_evaluate_condition_does_not_run_custom_exit_scan() -> None:
    strategy = _native_strategy()

    strategy.evaluate_condition("condition-1")

    assert list(strategy.submitted_orders) == []


def test_native_strategy_uses_exit_model_against_native_open_position() -> None:
    from datetime import timedelta

    from polysignal_lab.domain.enums import Side

    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    opened_at = now - timedelta(seconds=30)

    class Core:
        def evaluate(self, view):
            return []

    class Assembler:
        def build(self, condition_id, *, created_at=None):
            _ = condition_id, created_at
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

    class Registry:
        def by_condition(self, condition_id):
            if condition_id != "condition-1":
                return None
            return SimpleNamespace(
                asset="BTC",
                start_ts=None,
                up=SimpleNamespace(token_id="token-up", side=Side.UP),
                down=SimpleNamespace(token_id="token-down", side=Side.DOWN),
            )

        def instrument_id_for_token(self, token_id):
            return f"{token_id}.POLYMARKET"

    position = SimpleNamespace(
        id="position-1",
        instrument_id="token-up.POLYMARKET",
        signed_qty=10.0,
        avg_px_open=0.40,
        ts_opened=int(opened_at.timestamp() * 1_000_000_000),
        is_closed=False,
        realized_pnl=0.0,
    )

    class Cache:
        def positions_open(self, **kwargs):
            _ = kwargs
            return [position]

    class OrderFactory:
        def limit(self, **kwargs):
            return kwargs

    class FakeStrategy(PolySignalNativeStrategy):
        def submit_order(self, order):
            self.submitted.append(order)

    strategy = FakeStrategy(
        core=Core(),
        assembler=Assembler(),
        condition_ids=("condition-1",),
        strategy_name="ptb_diff",
        policy=DecisionPolicy(),
        registry=Registry(),
        instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
        exit_model=SimpleNamespace(
            mode="hold_to_resolution_with_optional_tp_sl",
            take_profit_enabled=True,
            stop_loss_enabled=True,
            take_profit_price=0.90,
            stop_loss_price=0.35,
            max_hold_time_sec=900,
        ),
    )
    strategy.cache = Cache()
    strategy.order_factory = OrderFactory()
    strategy.submitted = []

    strategy.evaluate_condition("condition-1", created_at=now)

    assert len(strategy.submitted) == 1
    order = strategy.submitted[0]
    assert order["reduce_only"] is True
    assert str(order["price"]) == "0.91"
    assert "exit_reason=TAKE_PROFIT" in order["tags"]
    assert "position_id=position-1" in order["tags"]


def test_native_exit_failure_falls_back_to_alpha_core() -> None:
    strategy = _native_strategy()
    expected = object()

    class Core:
        def evaluate(self, view):
            _ = view
            return [expected]

    class ExitPolicy:
        def decisions(self, **kwargs):
            _ = kwargs
            raise RuntimeError("temporary native cache failure")

    strategy.core = Core()
    strategy.exit_policy = ExitPolicy()
    view = strategy._require_assembler().build("condition-1")

    assert view is not None
    assert strategy._evaluate_decisions(view, now=view.created_at) == (expected,)


def test_native_fill_clears_exit_inflight_for_remaining_position(monkeypatch) -> None:
    import polysignal_lab.nautilus_runtime.native_strategy as native_strategy_module

    strategy = _native_strategy()
    strategy._exit_inflight.add("position-1")
    strategy._metrics_tracker = SimpleNamespace(
        metrics_for_event=lambda event: {"position_id": "position-1"}
    )
    strategy.paper_risk_gate = SimpleNamespace(release_from_event=lambda event: None)
    monkeypatch.setattr(native_strategy_module, "_handle_order_filled", lambda *_args: None)

    strategy.on_order_filled(SimpleNamespace())

    assert "position-1" not in strategy._exit_inflight


    strategy = _native_strategy()

    assert not hasattr(strategy, "evaluate_exit_positions")
    assert not hasattr(strategy, "_submit_exit_position")
