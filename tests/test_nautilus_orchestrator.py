from __future__ import annotations

import asyncio
from types import SimpleNamespace

from polysignal_lab.nautilus_runtime.orchestrator import NautilusOrchestrator


class FakeHealth:
    def __init__(self): self.calls = []
    def mark_ok(self, name, **metrics): self.calls.append(("ok", name, metrics))
    def mark_down(self, name, reason, **metrics): self.calls.append(("down", name, reason, metrics))
    def mark_degraded(self, name, reason, **metrics): self.calls.append(("degraded", name, reason, metrics))


class FakeObservability:
    def __init__(self): self.orders = []; self.fills = []; self.positions = []; self.settlements = []; self.health = 0; self.shutdowns = 0
    def record_order(self, result): self.orders.append(result)
    def record_fill(self, fill): self.fills.append(fill)
    def record_position(self, position): self.positions.append(position)
    def record_settlement(self, result): self.settlements.append(result)
    def record_health_snapshot(self): self.health += 1
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
    scheduler = SimpleNamespace(ctx=SimpleNamespace(markets=SimpleNamespace(markets={"m1": object()})))
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
    assert orch.settlement_actor.markets_seen == {"m1": orch.scheduler.ctx.markets.markets["m1"]}
    assert any(call[1] == "orchestrator" for call in orch.health.calls)
    assert orch.observability.health == 1


async def test_phase_failure_does_not_block_settlement_or_heartbeat() -> None:
    class FailingStrategy(FakeStrategy):
        def evaluate_all_conditions(self, ids):
            raise RuntimeError("boom")

    settlement = FakeSettlement()
    observability = FakeObservability()
    orch = _orchestrator(registered_strategies=[FailingStrategy()], settlement_actor=settlement, observability=observability)

    await orch.run_once()

    assert settlement.markets_seen == orch.scheduler.ctx.markets.markets
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
