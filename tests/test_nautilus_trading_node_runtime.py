"""
Input: __future__, __future__.annotations, asyncio, types, types.SimpleNamespace, pytest, polysignal_lab.config, polysignal_lab.config.Settings, polysignal_lab.nautilus_runtime, polysignal_lab.nautilus_runtime.live_node
Output: test_trading_node_exposes_expected_client_ids, test_live_polymarket_execution_is_rejected, test_build_paper_live_node_uses_polymarket_data_and_sandbox_exec, test_build_polymarket_data_client_config_enables_dynamic_instrument_loading, test_build_paper_live_node_bounds_cache_tick_capacity, test_build_sandbox_exec_client_config_uses_paper_venue_and_routes_to_polymarket, test_run_nautilus_cli_async_starts_and_stops_observability_writer, FakeConfig, FakePolymarketLiveDataClientFactory, FakeSandboxLiveExecClientFactory
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from polysignal_lab.config import Settings
from polysignal_lab.nautilus_runtime import live_node
from polysignal_lab.nautilus_runtime.live_node import (
    build_paper_live_node,
    build_polymarket_data_client_config,
    build_sandbox_exec_client_config,
)
from polysignal_lab.nautilus_runtime.node import run_nautilus_cli_async
from polysignal_lab.nautilus_runtime.live_node import (
    PAPER_EXEC_CLIENT_ID,
    POLYMARKET_CLIENT_ID,
    assert_no_live_polymarket_execution,
)


class FakeConfig:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        for key, value in kwargs.items():
            setattr(self, key, value)


class FakePolymarketLiveDataClientFactory:
    pass


class FakeSandboxLiveExecClientFactory:
    pass


class FakeBuiltLiveNode:
    def __init__(self, builder: "FakeBuilder") -> None:
        self.builder = builder


class FakeBuilder:
    def __init__(self, trader_id_text: str, trader_id: object, environment: object) -> None:
        self.trader_id_text = trader_id_text
        self.trader_id = trader_id
        self.environment = environment
        self.cache_config: object | None = None
        self.data_engine_config: object | None = None
        self.exec_engine_config: object | None = None
        self.data_clients: list[tuple[str | None, object, object]] = []
        self.exec_clients: list[tuple[str | None, object, object]] = []

    def with_cache_config(self, config: object) -> "FakeBuilder":
        self.cache_config = config
        return self

    def with_data_engine_config(self, config: object) -> "FakeBuilder":
        self.data_engine_config = config
        return self

    def with_exec_engine_config(self, config: object) -> "FakeBuilder":
        self.exec_engine_config = config
        return self

    def add_data_client(self, name: str | None, factory: object, config: object) -> "FakeBuilder":
        self.data_clients.append((name, factory, config))
        return self

    def add_exec_client(self, name: str | None, factory: object, config: object) -> "FakeBuilder":
        self.exec_clients.append((name, factory, config))
        return self

    def build(self) -> FakeBuiltLiveNode:
        return FakeBuiltLiveNode(self)


class FakeLiveNode:
    @classmethod
    def builder(cls, trader_id_text: str, trader_id: object, environment: object) -> FakeBuilder:
        return FakeBuilder(trader_id_text, trader_id, environment)


def _fake_import_callable(module_name: str, attr_name: str):
    def _factory(*args: object, **kwargs: object) -> FakeConfig:
        return FakeConfig(*args, module_name=module_name, attr_name=attr_name, **kwargs)

    return _factory


def _patch_live_node_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_node, "_import_callable", _fake_import_callable)
    monkeypatch.setattr(live_node, "LiveNode", FakeLiveNode)
    monkeypatch.setattr(live_node, "TraderId", lambda value: f"TraderId:{value}")
    monkeypatch.setattr(live_node, "Environment", SimpleNamespace(SANDBOX="SANDBOX"))
    monkeypatch.setattr(
        live_node,
        "PolymarketLiveDataClientFactory",
        FakePolymarketLiveDataClientFactory,
    )
    monkeypatch.setattr(
        live_node,
        "SandboxLiveExecClientFactory",
        FakeSandboxLiveExecClientFactory,
    )


def test_trading_node_exposes_expected_client_ids() -> None:
    assert POLYMARKET_CLIENT_ID == "POLYMARKET"
    assert PAPER_EXEC_CLIENT_ID == "POLYSIGNAL_PM_PAPER"


def test_live_polymarket_execution_is_rejected() -> None:
    """Does NOT require nautilus_trader — tests pure Python logic."""
    config = SimpleNamespace(exec_clients={POLYMARKET_CLIENT_ID: object()})

    with pytest.raises(RuntimeError, match="live Polymarket execution"):
        assert_no_live_polymarket_execution(config)


def test_build_paper_live_node_uses_polymarket_data_and_sandbox_exec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_live_node_fakes(monkeypatch)
    settings = Settings()
    settings.paper_trading.starting_balance_usdc = 1234.0
    instrument_config = SimpleNamespace(load_ids=frozenset({"up-token.POLYMARKET"}))

    node = build_paper_live_node(settings, instrument_config=instrument_config)

    builder = node.builder
    assert builder.trader_id_text == "PolySignal-Nautilus-001"
    assert builder.trader_id == "TraderId:PolySignal-Nautilus-001"
    assert builder.environment == "SANDBOX"
    assert builder.data_clients[0][0] == POLYMARKET_CLIENT_ID
    assert builder.data_clients[0][1] is FakePolymarketLiveDataClientFactory
    assert builder.exec_clients[0][0] == PAPER_EXEC_CLIENT_ID
    assert builder.exec_clients[0][1] is FakeSandboxLiveExecClientFactory
    assert builder.exec_clients[0][0] != POLYMARKET_CLIENT_ID

    data_config = builder.data_clients[0][2]
    exec_config = builder.exec_clients[0][2]
    assert getattr(data_config, "instrument_config") is instrument_config
    assert getattr(exec_config, "venue") == POLYMARKET_CLIENT_ID
    assert getattr(exec_config, "account_type") == "CASH"
    assert getattr(exec_config, "oms_type") == "NETTING"
    assert getattr(exec_config, "starting_balances") == ["1234.0 USDC"]


def test_build_polymarket_data_client_config_enables_dynamic_instrument_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_live_node_fakes(monkeypatch)
    settings = Settings()
    settings.runtime.nautilus.market_rotation.allow_adapter_new_market_events = True
    instrument_config = SimpleNamespace(load_ids=frozenset({"up-token.POLYMARKET"}))

    polymarket = build_polymarket_data_client_config(settings, instrument_config=instrument_config)

    assert getattr(polymarket, "instrument_config") is instrument_config
    assert getattr(polymarket, "auto_load_missing_instruments") is True
    assert getattr(polymarket, "auto_load_debounce_ms") == 100
    assert getattr(polymarket, "auto_load_max_retries") == 12
    assert getattr(polymarket, "subscribe_new_markets") is True
    assert getattr(polymarket, "ws_max_subscriptions_per_connection") == 200
    assert getattr(polymarket, "update_instruments_interval_mins") == 1


def test_build_paper_live_node_bounds_cache_tick_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_live_node_fakes(monkeypatch)

    node = build_paper_live_node(
        Settings(),
        instrument_config=SimpleNamespace(load_ids=frozenset({"up-token.POLYMARKET"})),
    )

    cache = node.builder.cache_config
    assert getattr(cache, "tick_capacity") == 100
    assert getattr(cache, "bar_capacity") == 100


def test_build_sandbox_exec_client_config_uses_paper_venue_and_routes_to_polymarket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_live_node_fakes(monkeypatch)
    settings = Settings()
    settings.paper_trading.starting_balance_usdc = 4321.0

    sandbox_config = build_sandbox_exec_client_config(settings)

    assert getattr(sandbox_config, "venue") == POLYMARKET_CLIENT_ID
    assert getattr(sandbox_config, "account_type") == "CASH"
    assert getattr(sandbox_config, "oms_type") == "NETTING"
    assert getattr(sandbox_config, "starting_balances") == ["4321.0 USDC"]
    assert getattr(sandbox_config, "book_type") == settings.runtime.nautilus.sandbox_book_type
    routing = getattr(sandbox_config, "routing")
    assert getattr(routing, "venues") == frozenset({POLYMARKET_CLIENT_ID})

async def test_run_nautilus_cli_async_starts_and_stops_observability_writer(monkeypatch, tmp_path) -> None:
    calls: list[str] = []
    settings = Settings()
    settings.storage.state_dir = str(tmp_path / "state")

    class FakeObservability:
        def start(self) -> None:
            calls.append("start")

        def stop(self) -> None:
            calls.append("stop")

        async def notify_startup(self, strategy_names=(), **kwargs):
            _ = strategy_names, kwargs
            calls.append("startup")

        async def notify_shutdown(self):
            calls.append("shutdown")

    class FakeTradingNode:
        def run(self):
            return None

    async def _stop_scheduler(*args, **kwargs):
        _ = args, kwargs
        calls.append("scheduler_stop")

    async def fake_build(settings=None):
        _ = settings
        return SimpleNamespace(
            node=FakeTradingNode(),
            websocket_tasks=[],
            scheduler=SimpleNamespace(
                stop=_stop_scheduler,
                settings=settings,
                wallet=object(),
            ),
            observability=FakeObservability(),
            components={"strategies": []},
        )

    async def fake_to_thread(fn, *args):
        return fn(*args)

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_nautilus_runtime",
        fake_build,
    )
    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)

    stop_event = asyncio.Event()
    stop_event.set()

    await run_nautilus_cli_async(settings=settings, stop_event=stop_event)

    assert calls[0] == "start"
    assert "stop" in calls
    assert calls.index("stop") > calls.index("start")
