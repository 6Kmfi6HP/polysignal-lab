from __future__ import annotations

import asyncio
from types import SimpleNamespace

from polysignal_lab.config import FillModelConfig, Settings

from polysignal_lab.nautilus_runtime.node import (
    build_trading_node,
    build_control,
    build_nautilus_runtime,
    run_nautilus_cli,
    run_nautilus_cli_async,
)
from polysignal_lab.nautilus_runtime.book_data import NautilusBookDataProvider
from polysignal_lab.nautilus_runtime.matching import NautilusMatchingPaperExecutionClient


def test_build_trading_node_returns_component_dict() -> None:
    """build_trading_node returns all required components."""
    node = build_trading_node()

    assert "registry" in node
    assert "sidecar" in node
    assert "assembler" in node
    assert "group_assembler" in node
    assert "wallet" in node
    assert "paper_client" in node
    assert "policy" in node
    assert "position_policy" in node
    assert "settlement_actor" in node
    assert "observability" in node
    assert "strategies" in node
    assert "strategy_names" in node


def test_build_trading_node_wires_matching_client() -> None:
    node = build_trading_node()
    paper_client = node["paper_client"]

    assert isinstance(paper_client, NautilusMatchingPaperExecutionClient)
    assert paper_client.paper_engine == "nautilus_matching"
    assert paper_client.accuracy_mode == "depth_l2"
    assert "matching_client" not in node

def test_build_trading_node_preserves_matching_staleness_setting() -> None:
    settings = Settings()
    settings.data.polymarket.max_book_staleness_ms = 42_000

    node = build_trading_node(settings)

    assert node["paper_client"].max_book_staleness_ms == 42_000

def test_build_trading_node_strategies_is_list() -> None:
    """Strategy wrappers are a list."""
    node = build_trading_node()
    assert isinstance(node["strategies"], list)


def test_build_control_adapts_policy() -> None:
    from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor

    policy = DecisionPolicyActor()
    ctrl = build_control(policy)

    assert ctrl.is_strategy_enabled("vwap_momentum")
    ctrl.set_strategy_enabled("vwap_momentum", enabled=False)
    assert not ctrl.is_strategy_enabled("vwap_momentum")


async def test_build_nautilus_runtime_wires_real_book_provider(monkeypatch) -> None:
    async def fake_refresh(scheduler):
        scheduler.ctx.markets.upsert_many([])

    async def fake_start_websockets(scheduler):
        return []

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.scheduler_market_data.refresh_markets_once",
        fake_refresh,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.scheduler_market_data.start_websockets",
        fake_start_websockets,
    )

    bundle = await build_nautilus_runtime()

    assert isinstance(bundle.book_data_provider, NautilusBookDataProvider)
    assert bundle.components["assembler"].books is bundle.book_data_provider
    assert bundle.orchestrator is not None

    assert isinstance(bundle.paper_client, NautilusMatchingPaperExecutionClient)
    assert bundle.paper_client is bundle.components["paper_client"]
    assert bundle.orchestrator.paper_client is bundle.paper_client
    assert "matching_client" not in bundle.components

async def test_run_nautilus_cli_async_exits_on_stop_event(monkeypatch) -> None:
    class FakeOrchestrator:
        def __init__(self):
            self.stopped = False

        async def run(self, stop_event=None):
            assert stop_event is not None
            stop_event.set()

        def stop(self):
            self.stopped = True

    async def _noop(*args, **kwargs):
        pass

    fake_bundle = SimpleNamespace(
        orchestrator=FakeOrchestrator(),
        websocket_tasks=[],
        scheduler=SimpleNamespace(stop=_noop),
        observability=SimpleNamespace(notify_startup=_noop),
        components={"strategies": []},
    )

    async def fake_build(settings=None):
        return fake_bundle

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_nautilus_runtime",
        fake_build,
    )

    await run_nautilus_cli_async(stop_event=asyncio.Event())


def test_run_nautilus_cli_prints_ready(monkeypatch, capsys) -> None:
    """run_nautilus_cli returns without hanging."""
    async def fake_async(settings=None, stop_event=None):
        print("Nautilus runtime ready — 0 strategies")

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.run_nautilus_cli_async",
        fake_async,
    )

    run_nautilus_cli()

    assert "Nautilus runtime ready" in capsys.readouterr().out
