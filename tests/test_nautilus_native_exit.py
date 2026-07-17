"""
Input: __future__, __future__.annotations, datetime, datetime.UTC, datetime.datetime, types, types.SimpleNamespace, polysignal_lab.alpha.types, polysignal_lab.alpha.types.FreshnessView, polysignal_lab.alpha.types.MarketView, polysignal_lab.domain.freshness, polysignal_lab.nautilus_runtime.decision_policy
Output: test_evaluate_condition_does_not_run_custom_exit_scan, test_native_exit_runs_when_opposite_book_exceeds_trade_freshness, test_native_strategy_has_no_custom_exit_evaluation_api, test_reduce_only_fill_records_early_exit_paper_result
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from polysignal_lab.alpha.types import FreshnessView, MarketView, SideBookView
from polysignal_lab.domain.freshness import FreshnessPolicy
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


def test_native_exit_runs_when_opposite_book_exceeds_trade_freshness() -> None:
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
                freshness_ms=50_000,
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
                market_id="mkt-1",
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
        policy=DecisionPolicy(
            strategy_freshness_policies={
                "ptb_diff": FreshnessPolicy(max_orderbook_staleness_ms=30_000)
            }
        ),
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


def test_native_strategy_has_no_custom_exit_evaluation_api() -> None:
    strategy = _native_strategy()

    assert not hasattr(strategy, "evaluate_exit_positions")
    assert not hasattr(strategy, "_submit_exit_position")


def test_reduce_only_fill_records_early_exit_paper_result() -> None:
    from polysignal_lab.domain.enums import Side
    from polysignal_lab.nautilus_runtime.strategy.order_events import handle_order_filled
    from polysignal_lab.reporting.exit_result import FEE_MODEL_IGNORED_V1

    recorded: list[tuple[str, object]] = []

    class Tracker:
        def metrics_for_event(self, event):
            _ = event
            return {
                "reduce_only": True,
                "exit_reason": "TAKE_PROFIT",
                "position_id": "position-1",
                "entry_price": 0.40,
                "position_quantity": 10.0,
                "stake_usdc": 4.0,
                "side": Side.UP.value,
                "asset": "BTC",
                "timeframe": "5m",
                "market_id": "mkt-1",
                "market_slug": "btc-updown-5m",
                "opened_at": "2026-07-06T12:00:00+00:00",
            }

        def forget(self, event, order):
            _ = event, order

    strategy = _native_strategy()
    strategy.strategy_name = "ptb_diff"
    strategy._metrics_tracker = Tracker()
    strategy.observability = SimpleNamespace(
        record_event=lambda table, data: recorded.append((table, data)),
        record_nautilus_fill_event=lambda event: None,
    )
    strategy._record_nautilus_fill = lambda event, metrics: None
    strategy._note_runtime_progress = lambda phase: None

    handle_order_filled(
        strategy,
        SimpleNamespace(
            id="fill-1",
            client_order_id="order-1",
            instrument_id="token-up.POLYMARKET",
            last_qty=10.0,
            last_px=0.91,
            price=0.91,
            quantity=10.0,
            tags=(
                "reduce_only=true",
                "exit_reason=TAKE_PROFIT",
                "position_id=position-1",
                "market_id=mkt-1",
                "condition_id=condition-1",
            ),
            ts_event=datetime(2026, 7, 6, 12, 1, tzinfo=UTC),
            side=Side.UP,
        ),
    )

    assert len(recorded) == 1
    table, payload = recorded[0]
    assert table == "settlements"
    assert isinstance(payload, dict)
    assert payload["exit_mode"] == "TAKE_PROFIT"
    assert payload["fee_model"] == FEE_MODEL_IGNORED_V1
    assert payload["strategy"] == "ptb_diff"
    assert payload["report_position_id"] == "position-1"


def test_reduce_only_fill_notifies_paper_result_after_durable_record() -> None:
    from polysignal_lab.domain.enums import Side
    from polysignal_lab.nautilus_runtime.strategy.order_events import handle_order_filled

    recorded: list[tuple[str, object]] = []
    notified: list[object] = []

    class Tracker:
        def metrics_for_event(self, event):
            _ = event
            return {
                "reduce_only": True,
                "exit_reason": "STOP_LOSS",
                "position_id": "position-2",
                "entry_price": 0.50,
                "position_quantity": 8.0,
                "stake_usdc": 4.0,
                "side": Side.UP.value,
                "asset": "BTC",
                "timeframe": "5m",
                "market_id": "mkt-1",
                "market_slug": "btc-updown-5m",
                "opened_at": "2026-07-06T12:00:00+00:00",
            }

        def forget(self, event, order):
            _ = event, order

    strategy = _native_strategy()
    strategy.strategy_name = "ptb_diff"
    strategy._metrics_tracker = Tracker()
    strategy.observability = SimpleNamespace(
        record_event=lambda table, data: recorded.append((table, data)),
        notify_report_result=lambda result: notified.append(result),
        record_nautilus_fill_event=lambda event: None,
    )
    strategy._record_nautilus_fill = lambda event, metrics: None
    strategy._note_runtime_progress = lambda phase: None

    handle_order_filled(
        strategy,
        SimpleNamespace(
            id="fill-2",
            client_order_id="order-2",
            instrument_id="token-up.POLYMARKET",
            last_qty=8.0,
            last_px=0.30,
            price=0.30,
            quantity=8.0,
            tags=(
                "reduce_only=true",
                "exit_reason=STOP_LOSS",
                "position_id=position-2",
                "market_id=mkt-1",
                "condition_id=condition-1",
            ),
            ts_event=datetime(2026, 7, 6, 12, 2, tzinfo=UTC),
            side=Side.UP,
        ),
    )

    assert len(recorded) == 1
    assert len(notified) == 1
    assert notified[0] is recorded[0][1]


def test_reduce_only_fill_durable_when_report_result_notifier_raises() -> None:
    from polysignal_lab.domain.enums import Side
    from polysignal_lab.nautilus_runtime.strategy.order_events import handle_order_filled

    recorded: list[tuple[str, object]] = []
    progress: list[str] = []

    class Tracker:
        def metrics_for_event(self, event):
            _ = event
            return {
                "reduce_only": True,
                "exit_reason": "MAX_HOLD_TIME",
                "position_id": "position-3",
                "entry_price": 0.45,
                "position_quantity": 5.0,
                "stake_usdc": 2.25,
                "side": Side.UP.value,
                "asset": "BTC",
                "timeframe": "5m",
                "market_id": "mkt-1",
                "market_slug": "btc-updown-5m",
                "opened_at": "2026-07-06T12:00:00+00:00",
            }

        def forget(self, event, order):
            _ = event, order

    strategy = _native_strategy()
    strategy.strategy_name = "late_consensus"
    strategy._metrics_tracker = Tracker()
    strategy.observability = SimpleNamespace(
        record_event=lambda table, data: recorded.append((table, data)),
        notify_report_result=lambda _result: (_ for _ in ()).throw(RuntimeError("tg down")),
        record_nautilus_fill_event=lambda event: None,
    )
    strategy._record_nautilus_fill = lambda event, metrics: None
    strategy._note_runtime_progress = lambda phase: progress.append(phase)

    handle_order_filled(
        strategy,
        SimpleNamespace(
            id="fill-3",
            client_order_id="order-3",
            instrument_id="token-up.POLYMARKET",
            last_qty=5.0,
            last_px=0.50,
            price=0.50,
            quantity=5.0,
            tags=(
                "reduce_only=true",
                "exit_reason=MAX_HOLD_TIME",
                "position_id=position-3",
                "market_id=mkt-1",
                "condition_id=condition-1",
            ),
            ts_event=datetime(2026, 7, 6, 12, 5, tzinfo=UTC),
            side=Side.UP,
        ),
    )

    assert len(recorded) == 1
    assert "early_exit_result" in progress
    assert "early_exit_result_publish_failed" in progress


def test_native_exit_uses_per_position_take_profit_threshold() -> None:
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
                best_bid=0.78,
                best_ask=0.79,
                spread=0.01,
                freshness_ms=100,
            )
            down = SideBookView(
                token_id="token-down",
                best_bid=0.20,
                best_ask=0.21,
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
                market_id="mkt-1",
                asset="BTC",
                start_ts=None,
                up=SimpleNamespace(token_id="token-up", side=Side.UP),
                down=SimpleNamespace(token_id="token-down", side=Side.DOWN),
            )

        def instrument_id_for_token(self, token_id):
            return f"{token_id}.POLYMARKET"

    position = SimpleNamespace(
        id="position-ptb",
        instrument_id="token-up.POLYMARKET",
        signed_qty=10.0,
        avg_px_open=0.40,
        ts_opened=int(opened_at.timestamp() * 1_000_000_000),
        is_closed=False,
        realized_pnl=0.0,
    )
    entry_order = SimpleNamespace(
        client_order_id="entry-ptb",
        instrument_id="token-up.POLYMARKET",
        tags=(
            "strategy=ptb_diff",
            "market_id=mkt-1",
            "condition_id=condition-1",
            "exit_tp_price=0.75",
            "exit_stop_price=0.42",
        ),
        status="FILLED",
        price=0.40,
        filled_qty=10.0,
        avg_px=0.40,
        ts_last=int(opened_at.timestamp() * 1_000_000_000),
        is_open=False,
        is_inflight=False,
    )

    class Cache:
        def orders(self, **kwargs):
            _ = kwargs
            return [entry_order]

        def positions_open(self, **kwargs):
            _ = kwargs
            return [position]

        def orders_for_position(self, position_id):
            _ = position_id
            return [entry_order]

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
    assert "exit_reason=TAKE_PROFIT" in order["tags"]


def test_native_exit_flip_stop_uses_stamped_stop_price() -> None:
    from datetime import timedelta

    from polysignal_lab.domain.enums import Side
    from polysignal_lab.nautilus_runtime.native_strategy_exit import (
        thresholds_from_metrics,
    )

    stamped = thresholds_from_metrics(
        {"flip_stop_enabled": True, "flip_stop_price": 0.48}
    )
    assert stamped is not None
    assert stamped.stop_loss_price == 0.48

    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    opened_at = now - timedelta(seconds=10)

    class Core:
        def evaluate(self, view):
            return []

    class Assembler:
        def build(self, condition_id, *, created_at=None):
            _ = condition_id, created_at
            up = SideBookView(
                token_id="token-up",
                best_bid=0.47,
                best_ask=0.48,
                spread=0.01,
                freshness_ms=100,
            )
            down = SideBookView(
                token_id="token-down",
                best_bid=0.50,
                best_ask=0.51,
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
                market_id="mkt-1",
                asset="BTC",
                start_ts=None,
                up=SimpleNamespace(token_id="token-up", side=Side.UP),
                down=SimpleNamespace(token_id="token-down", side=Side.DOWN),
            )

        def instrument_id_for_token(self, token_id):
            return f"{token_id}.POLYMARKET"

    position = SimpleNamespace(
        id="position-lc",
        instrument_id="token-up.POLYMARKET",
        signed_qty=5.0,
        avg_px_open=0.55,
        ts_opened=int(opened_at.timestamp() * 1_000_000_000),
        is_closed=False,
        realized_pnl=0.0,
    )
    entry_order = SimpleNamespace(
        client_order_id="entry-lc",
        instrument_id="token-up.POLYMARKET",
        tags=(
            "strategy=late_consensus",
            "market_id=mkt-1",
            "condition_id=condition-1",
            "exit_stop_price=0.48",
        ),
        status="FILLED",
        price=0.55,
        filled_qty=5.0,
        avg_px=0.55,
        ts_last=int(opened_at.timestamp() * 1_000_000_000),
        is_open=False,
        is_inflight=False,
    )

    class Cache:
        def orders(self, **kwargs):
            _ = kwargs
            return [entry_order]

        def positions_open(self, **kwargs):
            _ = kwargs
            return [position]

        def orders_for_position(self, position_id):
            _ = position_id
            return [entry_order]

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
        strategy_name="late_consensus",
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
    assert "exit_reason=STOP_LOSS" in strategy.submitted[0]["tags"]
