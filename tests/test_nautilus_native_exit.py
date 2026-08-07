from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from nautilus_trader.core import nautilus_pyo3 as pyo3

from polysignal_lab.alpha.types import (
    AlphaDecision,
    FreshnessView,
    MarketView,
    SideBookView,
)
from polysignal_lab.nautilus_runtime.decision_policy import (
    ApprovedDecision,
    BatchArbitrationResult,
    DecisionPolicy,
    candidate_from_decision,
)
from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
from polysignal_lab.nautilus_runtime.observability import ObservabilityService
from polysignal_lab.nautilus_runtime.observability_persistence import (
    NautilusEventStoreAdapter,
)
from polysignal_lab.storage.jsonl_store import JSONLStore
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.storage.state_store import StateStore
from polysignal_lab.app.services.persistence_service import PersistenceService


def _mark_condition_ready(strategy: object, condition_id: str) -> None:
    """Drive a condition into READY (feed subscription converged).

    evaluate_condition only proceeds for a READY condition; these unit tests
    exercise the exit path directly and skip the subscription flow.
    """
    from polysignal_lab.domain.enums import Side
    from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
        begin_market_book_generation,
        observe_market_book_side,
    )

    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    begin_market_book_generation(
        strategy,  # pyright: ignore[reportArgumentType]
        condition_id,
        now=now,
    )
    observe_market_book_side(
        strategy,  # pyright: ignore[reportArgumentType]
        condition_id,
        Side.UP,
        received_at=now,
        book_at=now,
    )
    observe_market_book_side(
        strategy,  # pyright: ignore[reportArgumentType]
        condition_id,
        Side.DOWN,
        received_at=now,
        book_at=now,
    )


class _Instrument:
    def __init__(self, instrument_id: pyo3.InstrumentId) -> None:
        self.id: pyo3.InstrumentId = instrument_id

    def make_price(self, value: float) -> pyo3.Price:
        return pyo3.Price.from_str(str(value))

    def make_qty(self, value: float) -> pyo3.Quantity:
        return pyo3.Quantity.from_str(str(value))


def _cached_instrument(instrument_id: object) -> _Instrument | None:
    if not isinstance(instrument_id, pyo3.InstrumentId):
        return None
    return _Instrument(instrument_id)


class _AllowAllDecisionPolicy(DecisionPolicy):
    def batch_arbitrate(
        self,
        decisions: list[tuple[AlphaDecision, MarketView]],
    ) -> BatchArbitrationResult:
        return BatchArbitrationResult(
            approvals=tuple(self.decide(decision, view) for decision, view in decisions)
        )

    def decide(
        self,
        decision: AlphaDecision,
        view: MarketView,
    ) -> ApprovedDecision:
        publish = candidate_from_decision(decision, view)
        return ApprovedDecision(decision=decision, publish=publish)


def _attach_decision_policy(
    strategy: PolySignalNativeStrategy,
) -> DecisionPolicy:
    strategy.policy = _AllowAllDecisionPolicy()
    strategy._decision_pipeline.policy = strategy.policy
    return strategy.policy


def _native_strategy(
    strategy_name: str = "test",
) -> PolySignalNativeStrategy:
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

    class Cache:
        def order(self, client_order_id: object) -> object | None:
            reasons = {
                "order-1": ("TAKE_PROFIT", "position-1", "10.0", "4.0"),
                "order-2": ("STOP_LOSS", "position-2", "8.0", "3.2"),
                "order-3": ("MAX_HOLD_TIME", "position-3", "5.0", "2.0"),
            }
            values = reasons.get(str(client_order_id))
            if values is None:
                return None
            reason, position_id, quantity, stake = values
            return SimpleNamespace(
                filled_qty=float(quantity),
                avg_px=0.91,
                tags=(
                    "strategy=" + strategy_name,
                    "reduce_only=true",
                    f"exit_reason={reason}",
                    f"position_id={position_id}",
                    "market_id=mkt-1",
                    "condition_id=condition-1",
                    "entry_price=0.40",
                    f"position_quantity={quantity}",
                    f"stake_usdc={stake}",
                    "side=UP",
                    "asset=BTC",
                    "timeframe=5m",
                    "market_slug=btc-updown-5m",
                    "opened_at=2026-07-06T12:00:00+00:00",
                ),
            )

        def position(self, position_id: object) -> object | None:
            if str(position_id) not in {"position-1", "position-2", "position-3"}:
                return None
            return SimpleNamespace(is_closed=True, avg_px_close=0.91)

        def orders_for_position(self, position_id: object) -> tuple[object, ...]:
            order = self.order(
                {
                    "position-1": "order-1",
                    "position-2": "order-2",
                    "position-3": "order-3",
                }[str(position_id)]
            )
            return () if order is None else (order,)

    strategy = PolySignalNativeStrategy(
        core=Core(),
        assembler=Assembler(),
        condition_ids=("condition-1",),
        strategy_name=strategy_name,
        registry=Registry(),
        instrument_id_resolver=lambda value: value,
    )
    strategy._cache_override = Cache()
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

    entry = SimpleNamespace(
        instrument_id="token-up.POLYMARKET",
        tags=(
            "strategy=ptb_diff",
            "market_id=mkt-1",
            "condition_id=condition-1",
            "position_id=position-1",
        ),
        status="FILLED",
        filled_qty=10.0,
        is_open=False,
        is_inflight=False,
    )

    class Cache:
        def instrument(self, instrument_id: object):
            return _cached_instrument(instrument_id)

        def orders(self, **kwargs: object) -> list[object]:
            _ = kwargs
            return [entry]

        def orders_for_position(self, position_id: object) -> list[object]:
            _ = position_id
            return [entry]

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
    strategy._cache_override = Cache()
    strategy._order_factory_override = OrderFactory()
    strategy.submitted = []
    _policy = _attach_decision_policy(strategy)
    _mark_condition_ready(strategy, "condition-1")

    strategy.evaluate_condition("condition-1", created_at=now)

    assert len(strategy.submitted) == 1
    order = strategy.submitted[0]
    assert order["reduce_only"] is True
    assert str(order["price"]) == "0.91"
    assert "exit_reason=TAKE_PROFIT" in order["tags"]
    assert "position_id=position-1" in order["tags"]
    assert "entry_price=0.4" in order["tags"]
    assert "position_quantity=10.0" in order["tags"]
    assert "stake_usdc=4.0" in order["tags"]
    assert f"opened_at={opened_at.isoformat()}" in order["tags"]

    from polysignal_lab.nautilus_runtime.strategy.order_events import (
        handle_order_filled,
    )

    settlements: list[dict[str, object]] = []
    strategy._cache_override = SimpleNamespace(
        order=lambda _client_order_id: SimpleNamespace(
            filled_qty=10.0,
            avg_px=0.91,
            tags=tuple(order["tags"]),
        ),
        position=lambda _position_id: SimpleNamespace(
            is_closed=True,
            avg_px_close=0.91,
        ),
        orders_for_position=lambda _position_id: (
            SimpleNamespace(
                filled_qty=10.0,
                avg_px=0.91,
                tags=tuple(order["tags"]),
            ),
        ),
    )
    strategy.observability = SimpleNamespace(
        record_event=lambda table, payload: (
            settlements.append(payload) if table == "settlements" else None
        )
    )
    strategy._record_nautilus_fill = lambda event, metrics: None
    handle_order_filled(
        strategy,
        SimpleNamespace(
            client_order_id="native-exit-order",
            instrument_id="token-up.POLYMARKET",
            last_qty=10.0,
            last_px=0.91,
            ts_event=datetime(2026, 7, 6, 12, 1, tzinfo=UTC),
            side="UP",
        ),
    )

    assert len(settlements) == 1
    assert settlements[0]["report_position_id"] == "position-1"
    assert settlements[0]["shares"] == 10.0


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


def test_reduce_only_fill_missing_economic_tags_is_quarantined() -> None:
    from polysignal_lab.nautilus_runtime.strategy.order_events import (
        handle_order_filled,
    )

    strategy = _native_strategy()
    progress: list[str] = []
    strategy._cache_override = SimpleNamespace(
        order=lambda _client_order_id: SimpleNamespace(
            tags=(
                "strategy=test",
                "reduce_only=true",
                "exit_reason=TAKE_PROFIT",
                "position_id=position-missing",
                "market_id=mkt-1",
                "condition_id=condition-1",
                "side=UP",
                "asset=BTC",
                "timeframe=5m",
                "market_slug=btc-updown-5m",
            )
        )
    )
    strategy._record_nautilus_fill = lambda event, metrics: None
    strategy._note_runtime_progress = (
        lambda phase, *, active_condition_ids=None: progress.append(phase)
    )

    handle_order_filled(
        strategy,
        SimpleNamespace(
            client_order_id="missing-economic-tags",
            instrument_id="token-up.POLYMARKET",
            last_qty=1.0,
            last_px=0.91,
            ts_event=datetime(2026, 7, 6, 12, 1, tzinfo=UTC),
            side="UP",
        ),
    )

    assert "early_exit_result_pending" in progress


def test_reduce_only_partial_fills_emit_one_result_after_position_closes() -> None:
    from polysignal_lab.nautilus_runtime.strategy.order_events import (
        handle_order_filled,
    )

    position_id = pyo3.PositionId.from_str("position-partial")
    tags = (
        "strategy=test",
        "reduce_only=true",
        "exit_reason=TAKE_PROFIT",
        "position_id=position-partial",
        "entry_price=0.4",
        "position_quantity=10.0",
        "stake_usdc=4.0",
        "market_id=mkt-1",
        "condition_id=condition-1",
        "side=UP",
        "asset=BTC",
        "timeframe=5m",
        "market_slug=btc-updown-5m",
    )
    order = SimpleNamespace(
        tags=tags,
        filled_qty=pyo3.Quantity.from_str("2.5"),
        avg_px=pyo3.Price.from_str("0.90"),
    )
    cached_position = SimpleNamespace(is_closed=False, avg_px_close=None)
    strategy = _native_strategy()
    results: list[dict[str, object]] = []
    progress: list[str] = []

    def cached_position_for_id(cache_position_id: object) -> object:
        assert isinstance(cache_position_id, pyo3.PositionId)
        assert cache_position_id == position_id
        return cached_position

    def orders_for_position(cache_position_id: object) -> tuple[object, ...]:
        assert isinstance(cache_position_id, pyo3.PositionId)
        assert cache_position_id == position_id
        return (order,)

    strategy._cache_override = SimpleNamespace(
        order=lambda _client_order_id: order,
        position=cached_position_for_id,
        orders_for_position=orders_for_position,
    )
    strategy.observability = SimpleNamespace(
        record_event=lambda table, payload: (
            results.append(payload) if table == "settlements" else None
        )
    )
    strategy._record_nautilus_fill = lambda event, metrics: None
    strategy._note_runtime_progress = (
        lambda phase, *, active_condition_ids=None: progress.append(phase)
    )

    first = SimpleNamespace(
        client_order_id="partial-exit",
        instrument_id="token-up.POLYMARKET",
        last_qty=2.5,
        last_px=0.90,
        ts_event=datetime(2026, 7, 6, 12, 1, tzinfo=UTC),
        side="UP",
    )
    handle_order_filled(strategy, first)

    assert results == []
    assert "early_exit_result_pending" in progress

    order.filled_qty = pyo3.Quantity.from_str("10")
    order.avg_px = pyo3.Price.from_str("0.91")
    cached_position.is_closed = True
    cached_position.avg_px_close = 0.91
    second = SimpleNamespace(
        client_order_id="partial-exit",
        instrument_id="token-up.POLYMARKET",
        last_qty=7.5,
        last_px=0.9133333333333333,
        ts_event=datetime(2026, 7, 6, 12, 2, tzinfo=UTC),
        side="UP",
    )
    handle_order_filled(strategy, second)
    handle_order_filled(strategy, second)

    assert len(results) == 1
    assert results[0]["shares"] == 10.0
    assert results[0]["stake_usdc"] == 4.0
    outcome_value = results[0]["outcome_value"]
    assert isinstance(outcome_value, float)
    assert abs(outcome_value - 0.91) < 1e-12
    assert "early_exit_result_duplicate" in progress


def test_reduce_only_exit_uses_position_average_when_order_price_is_missing() -> None:
    from polysignal_lab.nautilus_runtime.strategy.order_events import (
        handle_order_filled,
    )

    position_id = pyo3.PositionId.from_str("position-multi")
    tags = (
        "strategy=test",
        "reduce_only=true",
        "exit_reason=TAKE_PROFIT",
        "position_id=position-multi",
        "entry_price=0.4",
        "position_quantity=10.0",
        "stake_usdc=4.0",
        "market_id=mkt-1",
        "condition_id=condition-1",
        "side=UP",
        "asset=BTC",
        "timeframe=5m",
        "market_slug=btc-updown-5m",
    )
    current_order = SimpleNamespace(
        tags=tags,
        filled_qty=pyo3.Quantity.from_str("5"),
        avg_px=pyo3.Price.from_str("0.8"),
    )
    missing_price_order = SimpleNamespace(
        tags=tags,
        filled_qty=pyo3.Quantity.from_str("5"),
        avg_px=None,
    )
    position = SimpleNamespace(is_closed=True, avg_px_close=0.9)
    results: list[dict[str, object]] = []
    strategy = _native_strategy()
    strategy._cache_override = SimpleNamespace(
        order=lambda _client_order_id: current_order,
        position=lambda cache_position_id: (
            position if cache_position_id == position_id else None
        ),
        orders_for_position=lambda cache_position_id: (
            (
                current_order,
                missing_price_order,
            )
            if cache_position_id == position_id
            else ()
        ),
    )
    strategy.observability = SimpleNamespace(
        record_event=lambda table, payload: (
            results.append(payload) if table == "settlements" else None
        )
    )
    strategy._record_nautilus_fill = lambda event, metrics: None
    strategy._note_runtime_progress = lambda phase, *, active_condition_ids=None: None

    handle_order_filled(
        strategy,
        SimpleNamespace(
            client_order_id="multi-exit",
            instrument_id="token-up.POLYMARKET",
            last_qty=5.0,
            last_px=0.8,
            ts_event=datetime(2026, 7, 6, 12, 2, tzinfo=UTC),
            side="UP",
        ),
    )

    assert len(results) == 1
    assert results[0]["shares"] == 10.0
    assert results[0]["outcome_value"] == 0.9


def test_reduce_only_replay_after_restart_is_durably_idempotent(
    tmp_path: Path,
) -> None:
    from polysignal_lab.nautilus_runtime.strategy.order_events import (
        handle_order_filled,
    )

    persistence = PersistenceService(
        JSONLStore(tmp_path / "logs"),
        SQLiteStore(tmp_path / "runtime.sqlite3"),
        StateStore(tmp_path / "state"),
    )
    notifications: list[dict[str, object]] = []
    event = SimpleNamespace(
        client_order_id="order-1",
        instrument_id="token-up.POLYMARKET",
        last_qty=10.0,
        last_px=0.91,
        ts_event=datetime(2026, 7, 6, 12, 2, tzinfo=UTC),
        side="UP",
    )

    for _ in range(2):
        strategy = _native_strategy()
        strategy.observability = ObservabilityService(
            store=NautilusEventStoreAdapter(persistence),
            report_result_notifier=lambda result: notifications.append(dict(result)),
        )
        strategy._record_nautilus_fill = lambda event, metrics: None
        strategy._note_runtime_progress = lambda phase, *, active_condition_ids=None: None
        handle_order_filled(strategy, event)

    results = persistence.sqlite.query_json("report_results")
    assert len(results) == 1
    assert len(notifications) == 1
    persistence.close()


def test_reduce_only_fill_records_early_exit_paper_result() -> None:
    from polysignal_lab.domain.enums import Side
    from polysignal_lab.nautilus_runtime.strategy.order_events import (
        handle_order_filled,
    )
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

    strategy = _native_strategy("ptb_diff")
    strategy._metrics_tracker = Tracker()
    strategy.observability = SimpleNamespace(
        record_event=lambda table, data: recorded.append((table, data)),
        record_nautilus_fill_event=lambda event: None,
    )
    strategy._record_nautilus_fill = lambda event, metrics: None
    strategy._note_runtime_progress = lambda phase, *, active_condition_ids=None: None

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
                "entry_price=0.40",
                "position_quantity=10.0",
                "stake_usdc=4.0",
                "side=UP",
                "asset=BTC",
                "timeframe=5m",
                "market_slug=btc-updown-5m",
                "opened_at=2026-07-06T12:00:00+00:00",
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
    from polysignal_lab.nautilus_runtime.strategy.order_events import (
        handle_order_filled,
    )

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

    strategy = _native_strategy("ptb_diff")
    strategy._metrics_tracker = Tracker()
    strategy.observability = SimpleNamespace(
        record_event=lambda table, data: recorded.append((table, data)),
        notify_report_result=lambda result: notified.append(result),
        record_nautilus_fill_event=lambda event: None,
    )
    strategy._record_nautilus_fill = lambda event, metrics: None
    strategy._note_runtime_progress = lambda phase, *, active_condition_ids=None: None

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
                "entry_price=0.40",
                "position_quantity=8.0",
                "stake_usdc=3.2",
                "side=UP",
                "asset=BTC",
                "timeframe=5m",
                "market_slug=btc-updown-5m",
                "opened_at=2026-07-06T12:00:00+00:00",
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
    from polysignal_lab.nautilus_runtime.strategy.order_events import (
        handle_order_filled,
    )

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

    strategy = _native_strategy("late_consensus")
    strategy._metrics_tracker = Tracker()
    strategy.observability = SimpleNamespace(
        record_event=lambda table, data: recorded.append((table, data)),
        notify_report_result=lambda _result: (_ for _ in ()).throw(
            RuntimeError("tg down")
        ),
        record_nautilus_fill_event=lambda event: None,
    )
    strategy._record_nautilus_fill = lambda event, metrics: None
    strategy._note_runtime_progress = (
        lambda phase, *, active_condition_ids=None: progress.append(phase)
    )

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
                "entry_price=0.40",
                "position_quantity=5.0",
                "stake_usdc=2.0",
                "side=UP",
                "asset=BTC",
                "timeframe=5m",
                "market_slug=btc-updown-5m",
                "opened_at=2026-07-06T12:00:00+00:00",
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
        def instrument(self, instrument_id: object):
            return _cached_instrument(instrument_id)

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
    strategy._cache_override = Cache()
    strategy._order_factory_override = OrderFactory()
    strategy.submitted = []
    _policy = _attach_decision_policy(strategy)
    _mark_condition_ready(strategy, "condition-1")
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
        def instrument(self, instrument_id: object):
            return _cached_instrument(instrument_id)

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
    strategy._cache_override = Cache()
    strategy._order_factory_override = OrderFactory()
    strategy.submitted = []
    _policy = _attach_decision_policy(strategy)
    _mark_condition_ready(strategy, "condition-1")
    strategy.evaluate_condition("condition-1", created_at=now)

    assert len(strategy.submitted) == 1
    assert "exit_reason=STOP_LOSS" in strategy.submitted[0]["tags"]
