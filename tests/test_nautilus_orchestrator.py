from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from types import SimpleNamespace

from polysignal_lab.domain.enums import ExitMode, OrderIntent, OrderStatus, PositionStatus, Side, TradeResultStatus
from polysignal_lab.domain.paper_order import PaperFill, PaperOrder
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import PaperTradeResult
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import RejectedDecision
from polysignal_lab.nautilus_runtime.execution_types import PaperExecutionResult
from polysignal_lab.nautilus_runtime.orchestrator import NautilusOrchestrator
from polysignal_lab.observability.health import HealthRegistry


class FakeHealth:
    def __init__(self): self.calls = []
    def mark_ok(self, name, **metrics): self.calls.append(("ok", name, metrics))
    def mark_down(self, name, reason, **metrics): self.calls.append(("down", name, reason, metrics))
    def mark_degraded(self, name, reason, **metrics): self.calls.append(("degraded", name, reason, metrics))
    def inc_metric(self, name, metric, amount=1): self.calls.append(("inc", name, metric, amount))


class FakePublishService:
    def __init__(self):
        self.signals = []
        self.paper_results = []

    async def publish_signal(self, signal, stake_usdc):
        self.signals.append((signal, stake_usdc))
        return SimpleNamespace(as_dict=lambda: {"message_type": "signal", "status": "DRY_RUN"})

    async def publish_paper_result(self, result):
        self.paper_results.append(result)
        return SimpleNamespace(as_dict=lambda: {"message_type": "paper_result", "status": "DRY_RUN"})


class FakeScheduler:
    def __init__(self):
        self.ctx = SimpleNamespace(markets=SimpleNamespace(markets={"m1": object()}))
        self.publish_service = FakePublishService()
        self.health = FakeHealth()
        self.settings = SimpleNamespace(
            telegram=SimpleNamespace(send_signals=True, send_paper_results=True),
            paper_trading=SimpleNamespace(fixed_stake_usdc=10.0),
        )
        self.settlements_checked = 0
        self.daily_reports_checked = 0

    async def check_settlements(self):
        self.settlements_checked += 1
        return []

    async def generate_daily_report(self):
        self.daily_reports_checked += 1
        return None


class FakeObservability:
    def __init__(self):
        self.signals = []; self.rejections = []; self.orders = []; self.fills = []; self.positions = []; self.settlements = []; self.health = 0; self.shutdowns = 0
    def record_signal_from_order(self, order): self.signals.append(order)
    def record_rejected_decision(self, rejected): self.rejections.append(rejected)
    def record_order(self, result): self.orders.append(result)
    def record_fill(self, fill): self.fills.append(fill)
    def record_position(self, position): self.positions.append(position)
    def record_settlement(self, result): self.settlements.append(result)
    def record_health_snapshot(self): self.health += 1
    async def notify_order_result(self, result): pass
    async def notify_shutdown(self): self.shutdowns += 1


class FakeIngestor:
    def __init__(self, ids=("c1",)): self.ids = ids; self.calls = 0
    def sync_all(self): self.calls += 1; return self.ids


class FakeStrategy:
    strategy_name = "ptb_diff"
    def __init__(self): self.seen = []
    def evaluate_all_conditions(self, ids):
        self.seen.append(tuple(ids))
        return SimpleNamespace(strategy="ptb_diff", submitted_specs=(object(),), rejected_decisions=(), execution_results=())


class FakeSettlement:
    def __init__(self): self.markets_seen = None
    async def periodic_check(self, markets):
        self.markets_seen = markets
        return []


def _orchestrator(**overrides):
    scheduler = FakeScheduler()
    defaults = dict(
        scheduler=scheduler,
        registered_strategies=[FakeStrategy()],
        data_ingestor=FakeIngestor(),
        book_data_provider=SimpleNamespace(snapshot_for_token=lambda token_id: None),
        paper_client=SimpleNamespace(wallet=SimpleNamespace(open_positions={})),
        position_policy=SimpleNamespace(evaluate=lambda position, current_bid=None: None),
        settlement_actor=FakeSettlement(),
        observability=FakeObservability(),
        health=FakeHealth(),
        refresh_interval_sec=0.01,
    )
    defaults.update(overrides)
    return NautilusOrchestrator(**defaults)


async def test_run_once_syncs_evaluates_and_settles_real_market_registry() -> None:
    orch = _orchestrator()

    await orch.run_once()

    assert orch.data_ingestor.calls == 1
    assert orch.registered_strategies[0].seen == [("c1",)]
    assert orch.scheduler.settlements_checked == 1
    assert any(call[1] == "orchestrator" for call in orch.health.calls)
    assert orch.observability.health == 1


async def test_phase_health_marks_matching_engine_metadata() -> None:
    paper_client = SimpleNamespace(
        wallet=SimpleNamespace(open_positions={}),
        paper_engine="nautilus_matching",
        accuracy_mode="depth_l2",
    )
    orch = _orchestrator(paper_client=paper_client)

    orch._phase_health()

    assert (
        "ok",
        "orchestrator",
        {
            "paper_engine": "nautilus_matching",
            "accuracy_mode": "depth_l2",
            "matching_order_events": 0,
            "matching_instruments": 0,
            "matching_published_books": 0,
            "matching_trade_cache": 0,
            "ingestor_seen_matching_trades": 0,
            "vwap_trade_samples": 0,
            "vwap_seen_trade_signatures": 0,
        },
    ) in orch.health.calls


async def test_phase_health_includes_runtime_memory_debug_metrics() -> None:
    vwap_strategy = SimpleNamespace(
        strategy_name="vwap_momentum",
        core=SimpleNamespace(
            trades=SimpleNamespace(_trades={"up": [1, 2], "down": [3]}),
            _seen_trade_signatures={"up": {(1, 1, 1)}, "down": {(2, 2, 2), (3, 3, 3)}},
        ),
    )
    paper_client = SimpleNamespace(
        wallet=SimpleNamespace(open_positions={}),
        paper_engine="nautilus_matching",
        accuracy_mode="depth_l2",
        _trades={"token-up": [1, 2, 3]},
        matching_boundary=SimpleNamespace(
            _session=SimpleNamespace(order_events=[1, 2, 3, 4]),
            _instruments={"token-up": object(), "token-down": object()},
            _published_books={"token-up"},
        ),
    )
    data_ingestor = SimpleNamespace(
        _seen_matching_trades={(1,), (2,), (3,)},
        sync_all=lambda: (),
    )
    orch = _orchestrator(
        registered_strategies=[vwap_strategy],
        paper_client=paper_client,
        data_ingestor=data_ingestor,
    )

    orch._phase_health()

    assert (
        "ok",
        "orchestrator",
        {
            "paper_engine": "nautilus_matching",
            "accuracy_mode": "depth_l2",
            "matching_order_events": 4,
            "matching_instruments": 2,
            "matching_published_books": 1,
            "matching_trade_cache": 3,
            "ingestor_seen_matching_trades": 3,
            "vwap_trade_samples": 3,
            "vwap_seen_trade_signatures": 3,
        },
    ) in orch.health.calls

async def test_phase_health_resets_runtime_debug_metrics_to_zero() -> None:
    paper_client = SimpleNamespace(
        wallet=SimpleNamespace(open_positions={}),
        paper_engine="nautilus_matching",
        accuracy_mode="depth_l2",
        _trades={"token-up": [1, 2, 3]},
        matching_boundary=SimpleNamespace(
            _session=SimpleNamespace(order_events=[1, 2]),
            _instruments={"token-up": object()},
            _published_books={"token-up"},
        ),
    )
    data_ingestor = SimpleNamespace(
        _seen_matching_trades={(1,), (2,)},
        sync_all=lambda: (),
    )
    strategy = SimpleNamespace(
        core=SimpleNamespace(
            trades=SimpleNamespace(_trades={"up": [1]}),
            _seen_trade_signatures={"up": {(1, 1, 1)}},
        )
    )
    health = HealthRegistry()
    orch = _orchestrator(
        registered_strategies=[strategy],
        paper_client=paper_client,
        data_ingestor=data_ingestor,
        health=health,
    )

    orch._phase_health()
    paper_client._trades = {}
    paper_client.matching_boundary._session.order_events = []
    paper_client.matching_boundary._instruments = {}
    paper_client.matching_boundary._published_books = set()
    data_ingestor._seen_matching_trades = set()
    strategy.core.trades._trades = {}
    strategy.core._seen_trade_signatures = {}

    orch._phase_health()

    assert health.components["orchestrator"].metrics["matching_order_events"] == 0
    assert health.components["orchestrator"].metrics["matching_instruments"] == 0
    assert health.components["orchestrator"].metrics["matching_published_books"] == 0
    assert health.components["orchestrator"].metrics["matching_trade_cache"] == 0
    assert health.components["orchestrator"].metrics["ingestor_seen_matching_trades"] == 0
    assert health.components["orchestrator"].metrics["vwap_trade_samples"] == 0
    assert health.components["orchestrator"].metrics["vwap_seen_trade_signatures"] == 0

async def test_daily_report_health_marks_matching_engine_metadata() -> None:
    paper_client = SimpleNamespace(
        wallet=SimpleNamespace(open_positions={}),
        paper_engine="nautilus_matching",
        accuracy_mode="queue_l2",
    )
    orch = _orchestrator(paper_client=paper_client)

    await orch._phase_daily_report()

    assert (
        "ok",
        "daily_report",
        {"paper_engine": "nautilus_matching", "accuracy_mode": "queue_l2"},
    ) in orch.health.calls
    assert orch.scheduler.paper_execution_metadata == {
        "paper_engine": "nautilus_matching",
        "accuracy_mode": "queue_l2",
    }


async def test_run_once_drains_resting_orders_and_position_exits() -> None:
    calls: list[str] = []
    position = SimpleNamespace(paper_position_id="pos-1", token_id="up-token")
    drained = PaperExecutionResult(status=OrderStatus.PENDING, reason="DRAINED")
    resting = PaperExecutionResult(status=OrderStatus.REJECTED, reason="GTD_EXPIRED")
    exited_order = PaperOrder(
        paper_order_id="exit-order",
        signal_id="signal-1",
        token_id="up-token",
        side=Side.UP,
        limit_price=0.91,
        reference_price=0.91,
        stake_usdc=9.1,
        asset="BTC",
        timeframe="5m",
        strategy="late_consensus",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        reduce_only=True,
    )
    exited = PaperExecutionResult(order=exited_order, status=OrderStatus.FILLED, reason="TAKE_PROFIT")

    class PaperClient:
        def __init__(self) -> None:
            self.wallet = SimpleNamespace(open_positions={"pos-1": position})
            self.exit_args = None
            self.drains = 0

        def drain_events(self):
            calls.append("drain")
            self.drains += 1
            return [drained] if self.drains == 1 else []

        def process_resting_orders(self):
            calls.append("resting")
            return [resting]

        def submit_exit(self, pos, bid_price, reason):
            calls.append("exit")
            self.exit_args = (pos, bid_price, reason)
            return exited

    class RecordingStrategy(FakeStrategy):
        def evaluate_all_conditions(self, ids):
            calls.append("strategy")
            return super().evaluate_all_conditions(ids)

    class PositionPolicy:
        def evaluate(self, pos, current_bid=None):
            assert pos is position
            assert current_bid == 0.91
            return SimpleNamespace(details={"exit_mode": "TAKE_PROFIT"})

    paper_client = PaperClient()
    orch = _orchestrator(
        registered_strategies=[RecordingStrategy()],
        book_data_provider=SimpleNamespace(
            snapshot_for_token=lambda token_id: SimpleNamespace(bid=0.91)
        ),
        paper_client=paper_client,
        position_policy=PositionPolicy(),
    )

    await orch.run_once()

    assert calls == ["drain", "resting", "strategy", "drain", "exit"]
    assert paper_client.exit_args == (position, 0.91, "TAKE_PROFIT")
    assert orch.observability.orders == [drained, resting, exited]
    assert orch.observability.signals == []
    assert orch.scheduler.publish_service.signals == []
    assert any(call[0] == "ok" and call[1] == "resting_orders" for call in orch.health.calls)
    assert any(call[0] == "ok" and call[1] == "position_exits" for call in orch.health.calls)


async def test_position_exit_phase_persists_matching_trade_result() -> None:
    opened_at = datetime(2026, 1, 1, tzinfo=UTC)
    closed_at = datetime(2026, 1, 1, 0, 5, tzinfo=UTC)
    position = PaperPosition(
        paper_position_id="position-1",
        signal_id="signal-1",
        paper_order_id="entry-order",
        paper_fill_id="entry-fill",
        strategy="late_consensus",
        asset="BTC",
        timeframe="5m",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        token_id="up-token",
        side=Side.UP,
        entry_price=0.82,
        shares=10.0,
        stake_usdc=8.2,
        opened_at=opened_at,
    )
    trade = PaperTradeResult(
        signal_id=position.signal_id,
        paper_position_id=position.paper_position_id,
        strategy=position.strategy,
        asset=position.asset,
        timeframe=position.timeframe,
        market_id=position.market_id,
        market_slug=position.market_slug,
        side=position.side,
        entry_price=position.entry_price,
        shares=position.shares,
        stake_usdc=position.stake_usdc,
        exit_mode=ExitMode.TAKE_PROFIT,
        outcome_value=0.85,
        settlement_value=8.5,
        pnl_usdc=0.3,
        roi=0.3 / 8.2,
        result=TradeResultStatus.WIN,
        opened_at=opened_at,
        closed_at=closed_at,
    )
    exit_order = PaperOrder(
        paper_order_id="exit-order",
        signal_id=position.signal_id,
        token_id=position.token_id,
        side=position.side,
        limit_price=0.85,
        reference_price=0.85,
        stake_usdc=8.5,
        asset=position.asset,
        timeframe=position.timeframe,
        strategy=position.strategy,
        market_id=position.market_id,
        market_slug=position.market_slug,
        reduce_only=True,
    )
    result = PaperExecutionResult(
        order=exit_order,
        positions=[position],
        status=OrderStatus.FILLED,
        trade_results=[trade],
    )

    class RecordingPersistence:
        def __init__(self):
            self.trade_results = []
            self.positions = []
            self.logs = []

        def insert_paper_trade_result(self, value):
            self.trade_results.append(value)

        def upsert_paper_position(self, value):
            self.positions.append(value)

        def append_log(self, table, value):
            self.logs.append((table, value))

    class SchedulerWithPersistence(FakeScheduler):
        def __init__(self):
            super().__init__()
            self.persistence = RecordingPersistence()
            self.health = FakeHealth()
            self.logger = logging.getLogger("test")

    class PaperClient:
        def __init__(self):
            self.wallet = SimpleNamespace(open_positions={"position-1": position})

        def submit_exit(self, pos, bid_price, reason):
            assert pos is position
            assert bid_price == 0.85
            assert reason == "TAKE_PROFIT"
            position.status = PositionStatus.CLOSED
            position.closed_at = closed_at
            self.wallet.open_positions.clear()
            return result

    scheduler = SchedulerWithPersistence()
    orch = _orchestrator(
        scheduler=scheduler,
        book_data_provider=SimpleNamespace(snapshot_for_token=lambda token_id: SimpleNamespace(bid=0.85)),
        paper_client=PaperClient(),
        position_policy=SimpleNamespace(evaluate=lambda position, current_bid=None: SimpleNamespace(details={"exit_mode": "TAKE_PROFIT"})),
    )

    await orch._phase_position_exits()

    assert scheduler.persistence.trade_results == [trade]
    assert scheduler.persistence.positions == [position]
    assert scheduler.persistence.logs == [("paper_trade_results", trade)]
    assert scheduler.publish_service.paper_results == [trade]
    assert position.status == PositionStatus.CLOSED


async def test_resting_order_terminal_update_does_not_republish_signal() -> None:
    order = PaperOrder(
        paper_order_id="passive-order",
        signal_id="signal-1",
        token_id="up-token",
        side=Side.UP,
        limit_price=0.83,
        reference_price=0.84,
        stake_usdc=8.3,
        shares=10.0,
        asset="BTC",
        timeframe="5m",
        strategy="late_consensus",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        order_intent=OrderIntent.PASSIVE_GTD,
        metrics={
            "condition_id": "condition-btc-5m",
            "confidence": "0.8",
            "entry_reference_price": "0.84",
            "max_entry_price": "0.83",
        },
    )
    fill = PaperFill(
        paper_fill_id="fill-1",
        paper_order_id=order.paper_order_id,
        signal_id=order.signal_id,
        token_id=order.token_id,
        side=order.side,
        raw_best_ask=0.82,
        slippage_bps=0.0,
        fill_price=0.82,
        stake_usdc=8.2,
        shares=10.0,
        depth_checked=True,
    )
    position = PaperPosition(
        paper_position_id="position-1",
        signal_id=order.signal_id,
        paper_order_id=order.paper_order_id,
        paper_fill_id=fill.paper_fill_id,
        strategy=order.strategy,
        asset=order.asset,
        timeframe=order.timeframe,
        market_id=order.market_id,
        market_slug=order.market_slug,
        token_id=order.token_id,
        side=order.side,
        entry_price=fill.fill_price,
        shares=fill.shares,
        stake_usdc=fill.stake_usdc,
    )
    terminal = PaperExecutionResult(
        order=order,
        fills=[fill],
        positions=[position],
        status=OrderStatus.FILLED,
    )

    class PaperClient:
        wallet = SimpleNamespace(open_positions={})

        def process_resting_orders(self):
            return [terminal]

    orch = _orchestrator(
        registered_strategies=[],
        paper_client=PaperClient(),
    )

    await orch._record_execution_result(PaperExecutionResult(order=order, status=OrderStatus.RESTING))
    await orch._phase_resting_orders()

    assert len(orch.scheduler.publish_service.signals) == 1
    assert orch.observability.signals == [order]
    assert orch.observability.orders == [
        PaperExecutionResult(order=order, status=OrderStatus.RESTING),
        terminal,
    ]
    assert orch.observability.fills == [fill]
    assert orch.observability.positions == [position]


async def test_strategy_eval_records_signal_and_rejection_batch_events() -> None:
    signal = SignalCandidate.build(
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        token_id="up-token",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.5,
        max_entry_price=0.55,
        seconds_to_close=60,
        data_freshness_ms=20,
        reason_codes=["TEST"],
        metrics={},
    )
    order = PaperOrder(
        paper_order_id="order-1",
        signal_id=signal.signal_id,
        token_id=signal.token_id,
        side=signal.side,
        limit_price=0.5,
        reference_price=0.5,
        stake_usdc=10.0,
        asset=signal.asset,
        timeframe=signal.timeframe,
        strategy=signal.strategy,
        market_id=signal.market_id,
        market_slug=signal.market_slug,
    )

    class RecordingStrategy(FakeStrategy):
        def evaluate_all_conditions(self, ids):
            self.seen.append(tuple(ids))
            return SimpleNamespace(
                strategy="ptb_diff",
                submitted_specs=(),
                rejected_decisions=(RejectedDecision("TEST_REJECT", {}, signal),),
                execution_results=(PaperExecutionResult(order=order, status=OrderStatus.FILLED),),
            )

    observability = FakeObservability()
    orch = _orchestrator(registered_strategies=[RecordingStrategy()], observability=observability)

    await orch.run_once()

    assert observability.signals == [order]
    assert observability.rejections[0].candidate == signal
    assert observability.orders[0].order == order
    assert orch.scheduler.publish_service.signals[0][0].signal_id == signal.signal_id
    assert orch.scheduler.publish_service.signals[0][0].asset == "BTC"
    assert orch.scheduler.publish_service.signals[0][1] == 10.0


async def test_strategy_rejections_are_persisted_without_channel_publish() -> None:
    signal = SignalCandidate.build(
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        token_id="up-token",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.5,
        max_entry_price=0.55,
        seconds_to_close=60,
        data_freshness_ms=20,
        reason_codes=["TEST"],
        metrics={},
    )

    class RejectingStrategy(FakeStrategy):
        def evaluate_all_conditions(self, ids):
            self.seen.append(tuple(ids))
            return SimpleNamespace(
                strategy="ptb_diff",
                submitted_specs=(),
                rejected_decisions=(RejectedDecision("TEST_REJECT", {}, signal),),
                execution_results=(),
            )

    observability = FakeObservability()
    orch = _orchestrator(registered_strategies=[RejectingStrategy()], observability=observability)

    await orch.run_once()

    assert observability.rejections[0].candidate == signal
    assert orch.scheduler.publish_service.signals == []


async def test_settlement_phase_uses_scheduler_reporting_pipeline() -> None:
    class SchedulerWithSettlement(FakeScheduler):
        async def check_settlements(self):
            self.settlements_checked += 1
            return [SimpleNamespace(paper_trade_id="trade-1")]

    settlement = FakeSettlement()
    orch = _orchestrator(scheduler=SchedulerWithSettlement(), settlement_actor=settlement)

    await orch.run_once()

    assert orch.scheduler.settlements_checked == 1
    assert settlement.markets_seen is None
    assert orch.observability.settlements == []


async def test_phase_failure_does_not_block_settlement_or_heartbeat() -> None:
    class FailingStrategy(FakeStrategy):
        def evaluate_all_conditions(self, ids):
            raise RuntimeError("boom")

    settlement = FakeSettlement()
    observability = FakeObservability()
    orch = _orchestrator(registered_strategies=[FailingStrategy()], settlement_actor=settlement, observability=observability)

    await orch.run_once()

    assert settlement.markets_seen is None
    assert observability.health == 1
    assert any(call[0] == "degraded" and call[1] == "strategy_ptb_diff" for call in orch.health.calls)


async def test_stop_event_ends_run_without_full_interval() -> None:
    orch = _orchestrator(refresh_interval_sec=60.0)
    stop = asyncio.Event()
    task = asyncio.create_task(orch.run(stop))
    await asyncio.sleep(0)
    stop.set()
    await asyncio.wait_for(task, timeout=1.0)

    assert orch.observability.shutdowns == 1


async def test_orchestrator_never_submits_specs_outside_strategy_submitter() -> None:
    class PaperClient:
        wallet = SimpleNamespace(open_positions={})
        def submit_spec(self, spec):
            raise AssertionError("orchestrator must not submit specs")

    orch = _orchestrator(paper_client=PaperClient())

    await orch.run_once()

    assert orch.registered_strategies[0].seen == [("c1",)]
