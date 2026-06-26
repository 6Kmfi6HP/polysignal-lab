from __future__ import annotations

import asyncio
from types import SimpleNamespace

from polysignal_lab.domain.enums import OrderStatus, Side
from polysignal_lab.domain.paper_order import PaperOrder
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import RejectedDecision
from polysignal_lab.nautilus_runtime.execution import PaperExecutionResult
from polysignal_lab.nautilus_runtime.orchestrator import NautilusOrchestrator


class FakeHealth:
    def __init__(self): self.calls = []
    def mark_ok(self, name, **metrics): self.calls.append(("ok", name, metrics))
    def mark_down(self, name, reason, **metrics): self.calls.append(("down", name, reason, metrics))
    def mark_degraded(self, name, reason, **metrics): self.calls.append(("degraded", name, reason, metrics))


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
        self.settings = SimpleNamespace(
            telegram=SimpleNamespace(send_signals=True),
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
