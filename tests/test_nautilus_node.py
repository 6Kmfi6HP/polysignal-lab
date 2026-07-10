"""
Input: __future__, __future__.annotations, asyncio, logging, signal, threading, time, types, types.SimpleNamespace, typing, polysignal_lab.nautilus_runtime.market_discovery_worker
Output: test_live_engine_config_builders_import_configs_from_config_module, test_build_live_node_uses_livenode_builder, test_build_live_node_uses_configured_non_default_trader_id, test_build_live_node_returns_nautilus_runtime_components, test_build_live_node_injects_shared_projections_and_no_manual_sync_components, test_build_live_node_gives_each_strategy_own_custom_data_state, test_build_live_node_uses_static_runtime_classes, test_build_live_node_registers_market_rotation_actor, test_all_native_strategies_share_runtime_policy, test_build_live_node_uses_sandbox_execution_not_matching_client
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import asyncio
import logging
import signal
import threading
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock
import pytest

from polysignal_lab.config import Settings
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor
from polysignal_lab.nautilus_runtime.node import (
    build_live_node,
    build_control,
    run_nautilus_cli,
    run_nautilus_cli_async,
    _start_interactive_telegram_bot_thread,
    _stop_interactive_telegram_bot_thread,
)
from polysignal_lab.nautilus_runtime.live_node import PAPER_EXEC_CLIENT_ID

if TYPE_CHECKING:
    from polysignal_lab.publish.telegram_publisher import TelegramPublisher


def _fake_telegram_publisher() -> TelegramPublisher:
    return cast("TelegramPublisher", cast(object, SimpleNamespace(send=lambda *_args, **_kwargs: None)))


def _runtime_settings_stub(**kwargs):
    return SimpleNamespace(
        storage=SimpleNamespace(state_dir="/tmp/polysignal-lab-test-runtime"),
        **kwargs,
    )


def _fake_runtime_context(**overrides):
    async def _noop(*_args, **_kwargs):
        return None

    base = {
        "stop": _noop,
        "settings": _runtime_settings_stub(
            markets=SimpleNamespace(refresh_interval_sec=60),
            runtime=SimpleNamespace(
                nautilus=SimpleNamespace(
                    sandbox_book_type="L2_MBP",
                )
            ),
        ),
        "logger": logging.getLogger("test_nautilus_node"),
        "telegram_bot": None,
        "health": SimpleNamespace(),
        "persistence": SimpleNamespace(),
    }
    base.update(overrides)
    return SimpleNamespace(**base)

@pytest.fixture(autouse=True)
def _patch_live_node_config_imports(monkeypatch):
    def _fake_import_callable(module_name: str, attr_name: str):
        def _factory(**kwargs):
            return SimpleNamespace(module_name=module_name, attr_name=attr_name, **kwargs)

        return _factory

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.live_node._import_callable",
        _fake_import_callable,
    )

def test_live_engine_config_builders_import_configs_from_config_module(monkeypatch) -> None:
    from polysignal_lab.nautilus_runtime import live_node

    calls: list[tuple[str, str]] = []

    def _recording_import_callable(module_name: str, attr_name: str):
        calls.append((module_name, attr_name))

        def _factory(**kwargs):
            return SimpleNamespace(module_name=module_name, attr_name=attr_name, **kwargs)

        return _factory

    monkeypatch.setattr(live_node, "_import_callable", _recording_import_callable)

    live_node.build_data_engine_config()
    live_node.build_exec_engine_config()

    assert calls == [
        ("nautilus_trader.config", "LiveDataEngineConfig"),
        ("nautilus_trader.config", "LiveExecEngineConfig"),
    ]


def test_runtime_class_loader_requires_three_classes(monkeypatch: pytest.MonkeyPatch) -> None:
    import polysignal_lab.nautilus_runtime.node_builder as module

    monkeypatch.setattr(
        module,
        "_load_runtime_classes",
        lambda: (object, object),
    )

    with pytest.raises(ValueError, match="three runtime classes"):
        module._runtime_class_triple()


def _patch_nautilus_placeholders(monkeypatch):
    """Monkeypatch LiveNode builder placeholders so tests run without Nautilus."""

    class FakeLiveNode:
        @classmethod
        def builder(cls, trader_id_text, trader_id, environment):
            return FakeBuilder(trader_id_text, trader_id, environment)

    class FakeBuilder:
        def __init__(self, trader_id_text, trader_id, environment):
            self.trader_id_text = trader_id_text
            self.trader_id = trader_id
            self.environment = environment
            self.data_engine_config = None
            self.exec_engine_config = None
            self.cache_config = None
            self.data_clients = []
            self.exec_clients = []

        def with_data_engine_config(self, config):
            self.data_engine_config = config
            return self

        def with_exec_engine_config(self, config):
            self.exec_engine_config = config
            return self

        def with_cache_config(self, config):
            self.cache_config = config
            return self

        def add_data_client(self, name, factory, config):
            self.data_clients.append((name, factory, config))
            return self

        def add_exec_client(self, name, factory, config):
            self.exec_clients.append((name, factory, config))
            return self

        def build(self):
            return FakeBuiltNode(self)

    class FakeBuiltNode:
        def __init__(self, builder):
            self.builder = builder
            self.trader = SimpleNamespace(strategies=[], actors=[])
            self.trader.add_strategy = self.trader.strategies.append
            self.trader.add_actor = self.trader.actors.append
            self.built = False

        def build(self):
            self.built = True

    class FakeRuntimeStrategy:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.strategy_name = kwargs["strategy_name"]
            for key, value in kwargs.items():
                setattr(self, key, value)

    class FakeRuntimeActor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            for key, value in kwargs.items():
                setattr(self, key, value)


    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node.LiveNode", FakeLiveNode)
    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node_builder.LiveNode", FakeLiveNode)
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.PolymarketInstrumentProviderConfig",
        lambda *, load_ids: SimpleNamespace(load_ids=load_ids),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node_builder.PolymarketInstrumentProviderConfig",
        lambda *, load_ids: SimpleNamespace(load_ids=load_ids),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.live_node.LiveNode",
        FakeLiveNode,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.live_node.TraderId",
        lambda value: f"TraderId:{value}",
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.live_node.Environment",
        SimpleNamespace(SANDBOX="SANDBOX"),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.live_node.PolymarketLiveDataClientFactory",
        object(),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.live_node.SandboxLiveExecClientFactory",
        object(),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._load_runtime_classes",
        lambda: (FakeRuntimeStrategy, FakeRuntimeActor, DecisionPolicyActor),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node_builder._load_runtime_classes",
        lambda: (FakeRuntimeStrategy, FakeRuntimeActor, DecisionPolicyActor),
    )
    return FakeLiveNode


def test_build_live_node_uses_livenode_builder(monkeypatch) -> None:
    _patch_nautilus_placeholders(monkeypatch)

    runtime = build_live_node(condition_ids=("condition-btc-5m",))
    node = runtime["node"]
    builder = node.builder

    assert builder.trader_id_text == "PolySignal-Nautilus-001"
    assert builder.environment == "SANDBOX"
    assert builder.data_clients[0][0] == "POLYMARKET"
    assert builder.exec_clients[0][0] == PAPER_EXEC_CLIENT_ID
    assert builder.exec_clients[0][0] != "POLYMARKET"
    assert node.built is True


def test_build_live_node_uses_configured_non_default_trader_id(monkeypatch) -> None:
    _patch_nautilus_placeholders(monkeypatch)
    settings = Settings()
    settings.runtime.nautilus.trader_id = "PolySignal-Regression-Trader"

    runtime = build_live_node(settings=settings, condition_ids=("condition-btc-5m",))
    builder = runtime["node"].builder

    assert builder.trader_id_text == "PolySignal-Regression-Trader"
    assert builder.trader_id == "TraderId:PolySignal-Regression-Trader"

def test_build_live_node_returns_nautilus_runtime_components(monkeypatch) -> None:
    _patch_nautilus_placeholders(monkeypatch)

    runtime = build_live_node(condition_ids=("condition-btc-5m",))
    node = runtime["node"]

    assert node.built is True
    assert node.builder.exec_clients[0][0] != "POLYMARKET"
    assert len(node.trader.actors) == 1
    assert "paper_client" not in runtime



def test_build_live_node_injects_shared_projections_and_no_manual_sync_components(monkeypatch) -> None:
    _patch_nautilus_placeholders(monkeypatch)

    runtime = build_live_node(condition_ids=("condition-btc-5m",))
    strategies = cast(list[object], runtime["strategies"])

    assert "registry" in runtime
    assert "sidecar" not in runtime
    assert "book_data_provider" not in runtime
    assert "assembler" in runtime
    assert "market_rotation_actor" in runtime
    assert "data_ingestor" not in runtime
    assert "orchestrator" not in runtime
    assert "paper_client" not in runtime
    assert "matching_client" not in runtime
    assert strategies
    first_strategy = strategies[0]
    assert getattr(first_strategy, "registry") is runtime["registry"]
    assert getattr(first_strategy, "assembler").catalog is runtime["registry"]


def test_build_live_node_gives_each_strategy_own_custom_data_state(monkeypatch) -> None:
    from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState

    _patch_nautilus_placeholders(monkeypatch)

    runtime = build_live_node(condition_ids=("condition-btc-5m",))
    shared_assembler = runtime["assembler"]
    strategies = cast(list[object], runtime["strategies"])

    assert strategies
    for strategy in strategies:
        custom_data = getattr(strategy, "custom_data", None)
        strategy_assembler = getattr(strategy, "assembler")

        assert isinstance(custom_data, StrategyCustomDataState)
        assert strategy_assembler is not shared_assembler
        assert getattr(strategy_assembler, "custom_data") is custom_data

def test_build_live_node_uses_static_runtime_classes(monkeypatch) -> None:
    _patch_nautilus_placeholders(monkeypatch)
    captured: dict[str, object] = {}

    class FakeStaticStrategy:
        strategy_name = "vwap_momentum"

        def __init__(self, **kwargs):
            captured["strategy_kwargs"] = kwargs

    class FakeStaticActor:
        def __init__(self, **kwargs):
            captured["actor_kwargs"] = kwargs

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._load_runtime_classes",
        lambda: (FakeStaticStrategy, FakeStaticActor, DecisionPolicyActor),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node_builder._load_runtime_classes",
        lambda: (FakeStaticStrategy, FakeStaticActor, DecisionPolicyActor),
    )

    runtime = build_live_node(condition_ids=("condition-btc-5m",))

    assert runtime["strategies"][0].strategy_name == "vwap_momentum"
    assert runtime["market_rotation_actor"] is runtime["node"].trader.actors[0]
    assert "registry" in captured["strategy_kwargs"]
    assert "catalog" in captured["actor_kwargs"]


def test_build_live_node_registers_market_rotation_actor(monkeypatch) -> None:
    from polysignal_lab.nautilus_runtime.market_discovery_worker import MarketDiscoveryWorker

    _patch_nautilus_placeholders(monkeypatch)

    class FakeRotationActor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeStrategy:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.strategy_name = kwargs["strategy_name"]

    class FakeUniverse:
        def refresh_once_sync(self):
            return []


    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._load_runtime_classes",
        lambda: (FakeStrategy, FakeRotationActor, DecisionPolicyActor),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node_builder._load_runtime_classes",
        lambda: (FakeStrategy, FakeRotationActor, DecisionPolicyActor),
    )

    universe = FakeUniverse()
    health = object()
    runtime = build_live_node(
        condition_ids=("condition-btc-5m",),
        market_universe=universe,
        health=health,
    )
    node = runtime["node"]

    assert len(node.trader.actors) == 1
    assert node.trader.actors[0] is runtime["market_rotation_actor"]
    assert isinstance(runtime["market_rotation_actor"], FakeRotationActor)
    assert runtime["market_rotation_actor"].kwargs["market_universe"] is universe
    assert isinstance(
        runtime["market_rotation_actor"].kwargs["discovery_worker"],
        MarketDiscoveryWorker,
    )
    assert runtime["market_rotation_actor"].kwargs["health"] is health


def test_all_native_strategies_share_runtime_policy(monkeypatch) -> None:
    _patch_nautilus_placeholders(monkeypatch)

    from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor

    class FakeRotationActor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakePolicyActor(DecisionPolicyActor):
        def on_save(self) -> dict[str, bytes]:
            return {}

        def on_load(self, state: dict[str, bytes]) -> None:
            _ = state

    class FakeStrategy:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.strategy_name = kwargs["strategy_name"]
            self.policy = kwargs["policy"]

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._load_runtime_classes",
        lambda: (FakeStrategy, FakeRotationActor, FakePolicyActor),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node_builder._load_runtime_classes",
        lambda: (FakeStrategy, FakeRotationActor, FakePolicyActor),
    )

    settings = Settings()
    settings.strategies.set_explicit_strategy_names(("vwap_momentum", "ptb_diff"))
    settings.strategies.vwap_momentum.enabled = True
    settings.strategies.ptb_diff.enabled = True

    runtime = build_live_node(
        settings=settings,
        condition_ids=("condition-btc-5m",),
    )
    node = runtime["node"]

    assert len(node.trader.actors) == 2
    assert node.trader.actors[0] is runtime["market_rotation_actor"]
    assert node.trader.actors[1] is runtime["policy"]
    assert isinstance(runtime["policy"], FakePolicyActor)
    assert len(runtime["strategies"]) == 2
    assert all(strategy.policy is runtime["policy"] for strategy in runtime["strategies"])

def test_build_live_node_uses_sandbox_execution_not_matching_client(monkeypatch) -> None:
    _patch_nautilus_placeholders(monkeypatch)

    runtime = build_live_node()
    builder = runtime["node"].builder

    assert builder.exec_clients[0][0] != "POLYMARKET"
    assert "paper_client" not in runtime
    assert "matching_client" not in runtime


def test_build_live_node_strategies_is_list(monkeypatch) -> None:
    """Strategy list is a list even when no strategies configured."""
    _patch_nautilus_placeholders(monkeypatch)

    runtime = build_live_node()
    assert isinstance(runtime["strategies"], list)


def test_build_live_node_forwards_unsubscribe_exited_to_native_strategy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_nautilus_placeholders(monkeypatch)
    captured: dict[str, object] = {}

    class FakeRotationActor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeStrategy:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs
            self.strategy_name = kwargs["strategy_name"]

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._load_runtime_classes",
        lambda: (FakeStrategy, FakeRotationActor, DecisionPolicyActor),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node_builder._load_runtime_classes",
        lambda: (FakeStrategy, FakeRotationActor, DecisionPolicyActor),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._native_core_for",
        lambda _name, _cfg: object(),
    )

    settings = Settings()
    settings.runtime.nautilus.market_rotation.unsubscribe_exited = False
    settings.strategies.set_explicit_strategy_names(("vwap_momentum",))

    runtime = build_live_node(
        settings=settings,
        condition_ids=("condition-btc-5m",),
    )

    strategies = cast(list[object], runtime["strategies"])
    captured_kwargs = cast(dict[str, object], captured["kwargs"])

    assert len(strategies) == 1
    assert getattr(runtime["node"], "trader").strategies == strategies
    assert captured_kwargs["unsubscribe_exited"] is False
    assert captured_kwargs["strategy_name"] == "vwap_momentum"


def test_build_live_node_skips_disabled_native_strategies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_nautilus_placeholders(monkeypatch)

    class FakeRotationActor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeStrategy:
        def __init__(self, **kwargs):
            self.strategy_name = kwargs["strategy_name"]

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._load_runtime_classes",
        lambda: (FakeStrategy, FakeRotationActor, DecisionPolicyActor),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node_builder._load_runtime_classes",
        lambda: (FakeStrategy, FakeRotationActor, DecisionPolicyActor),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._native_core_for",
        lambda _name, _cfg: object(),
    )

    settings = Settings()
    settings.strategies.set_explicit_strategy_names(("vwap_momentum",))
    settings.strategies.vwap_momentum.enabled = False

    runtime = build_live_node(
        settings=settings,
        condition_ids=("condition-btc-5m",),
    )

    assert runtime["strategies"] == []
    assert getattr(runtime["node"], "trader").strategies == []



def test_build_live_node_passes_l1_snapshot_interval_to_native_strategies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_nautilus_placeholders(monkeypatch)
    captured: dict[str, object] = {}

    class FakeRotationActor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeStrategy:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs
            self.strategy_name = kwargs["strategy_name"]

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._load_runtime_classes",
        lambda: (FakeStrategy, FakeRotationActor, DecisionPolicyActor),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node_builder._load_runtime_classes",
        lambda: (FakeStrategy, FakeRotationActor, DecisionPolicyActor),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._native_core_for",
        lambda _name, _cfg: object(),
    )

    settings = Settings()
    settings.runtime.nautilus.sandbox_book_type = "L1_MBP"
    settings.runtime.nautilus.l1_book_snapshot_interval_ms = 250
    settings.strategies.set_explicit_strategy_names(("vwap_momentum",))

    runtime = build_live_node(
        settings=settings,
        condition_ids=("condition-btc-5m",),
    )

    strategies = cast(list[object], runtime["strategies"])
    captured_kwargs = cast(dict[str, object], captured["kwargs"])

    assert len(strategies) == 1
    assert getattr(runtime["node"], "trader").strategies == strategies
    assert captured_kwargs["book_type"] == "L1_MBP"
    assert captured_kwargs["l1_book_snapshot_interval_ms"] == 250


def test_build_live_node_injects_runtime_progress_callback(monkeypatch, tmp_path) -> None:
    from polysignal_lab.observability.runtime_health import read_runtime_heartbeat

    captured: dict[str, object] = {}

    class FakeStrategy:
        strategy_name = "vwap_momentum"

        def __init__(self, **kwargs):
            captured.update(kwargs)


    settings = Settings()
    settings.strategies.set_explicit_strategy_names(("vwap_momentum",))
    settings.storage.state_dir = str(tmp_path / "state")
    _patch_nautilus_placeholders(monkeypatch)
    class FakeRotationActor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._load_runtime_classes",
        lambda: (FakeStrategy, FakeRotationActor, DecisionPolicyActor),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node_builder._load_runtime_classes",
        lambda: (FakeStrategy, FakeRotationActor, DecisionPolicyActor),
    )

    runtime = build_live_node(settings=settings, condition_ids=("condition-btc-5m",))

    progress = captured["progress_callback"]
    assert callable(progress)
    progress("evaluation_heartbeat")
    heartbeat = read_runtime_heartbeat(tmp_path / "state" / "runtime_heartbeat.json")
    assert heartbeat.phase == "evaluation_heartbeat"
    assert runtime["strategies"][0].strategy_name == "vwap_momentum"

def test_runtime_progress_callback_suppresses_heartbeat_write_failures(monkeypatch, tmp_path) -> None:
    import polysignal_lab.nautilus_runtime.node_probes as probes_mod

    settings = Settings()
    settings.storage.state_dir = str(tmp_path / "state")

    def fail_write(*_args, **_kwargs):
        raise OSError("state directory unavailable")

    monkeypatch.setattr(probes_mod, "write_runtime_heartbeat", fail_write)

    from polysignal_lab.nautilus_runtime.node_probes import _runtime_progress_callback
    _runtime_progress_callback(settings)("evaluation_heartbeat")

def test_build_control_adapts_policy() -> None:
    from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor

    policy = DecisionPolicyActor()
    ctrl = build_control(policy)

    assert ctrl.is_strategy_enabled("vwap_momentum")
    ctrl.set_strategy_enabled("vwap_momentum", enabled=False)
    assert not ctrl.is_strategy_enabled("vwap_momentum")


async def test_build_nautilus_runtime_discovers_market_universe_for_trading_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod
    from polysignal_lab.domain.enums import Side
    from polysignal_lab.domain.market import Market, OutcomeToken

    market = Market(
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        asset="BTC",
        timeframe="5m",
        outcome_tokens=[
            OutcomeToken(token_id="up-token", side=Side.UP, outcome_name="Up", market_id="btc-5m"),
            OutcomeToken(token_id="down-token", side=Side.DOWN, outcome_name="Down", market_id="btc-5m"),
        ],
    )
    refresh_calls = 0
    captured: dict[str, object] = {}

    class FakePersistence:
        def insert_signal(self, payload):
            _ = payload

        def insert_rejected_signal(self, payload):
            _ = payload

        def insert_paper_trade_result(self, payload):
            _ = payload

        def insert_system_event(self, payload):
            _ = payload

        def append_log(self, stream, payload):
            _ = stream, payload

        def read_state(self, name, default=None):
            _ = name
            return default

    class FakeMarketUniverse:
        async def refresh_once(self) -> list[Market]:
            nonlocal refresh_calls
            refresh_calls += 1
            return [market]

    class FakeContext:
        def __init__(self, settings=None):
            self.settings = settings or SimpleNamespace(markets=SimpleNamespace(refresh_interval_sec=60))
            self.market_universe = FakeMarketUniverse()
            self.health = object()
            self.persistence = FakePersistence()
            self.publisher = SimpleNamespace(send=lambda *_args, **_kwargs: None)
            self.publish_service = SimpleNamespace(formatter=object(), persistence=object(), timeout_sec=10.0)
            self.logger = logging.getLogger("test")
            self.sqlite = SimpleNamespace(close=lambda: None)
            self.signal_pipeline = SimpleNamespace()
            self.strategy_schedule = []
            self.strategies = []
            self.gate = None
            self.consensus = None
            self.arbiter = None
            self.telegram_bot = None
            self.nautilus_cache = None
            self.nautilus_portfolio = None
            self.paper_execution_metadata = None
            self._running = False
            self._nautilus_runtime_owned_by_live_node = True
            self._trading_components_initialized = True

        async def stop(self) -> None:
            return None

    monkeypatch.setattr(node_mod, "build_nautilus_runtime_context", lambda settings=None: FakeContext())
    monkeypatch.setattr(node_mod, "NautilusEventStoreAdapter", lambda persistence: persistence)
    monkeypatch.setattr(node_mod, "NautilusNotifierAdapter", lambda publisher: publisher)
    cache_holder = object()
    monkeypatch.setattr(
        node_mod,
        "build_live_node",
        lambda settings=None, *, condition_ids=(), markets=(), market_universe=None, store=None, health=None, observability=None: captured.update(
            condition_ids=tuple(condition_ids),
            markets=tuple(markets),
            market_universe=market_universe,
            store=store,
            health=health,
            observability=observability,
        )
        or {
            "assembler": SimpleNamespace(books=None),
            "cache": cache_holder,
            "portfolio": cache_holder,
            "registry": object(),
            "sidecar": object(),
            "node": SimpleNamespace(),
            "strategies": [],
            "policy": DecisionPolicyActor(),
        },
    )

    bundle = await node_mod.build_nautilus_runtime(Settings())

    assert refresh_calls == 1
    assert captured["condition_ids"] == ("condition-btc-5m",)
    assert captured["markets"] == (market,)
    assert captured["market_universe"] is bundle.context.market_universe
    assert captured["health"] is bundle.context.health
    assert captured["observability"] is not None
    assert callable(getattr(captured["observability"], "accepted_signal_notifier", None))

    assert bundle.context is not None
    assert getattr(bundle.context, "nautilus_cache") is cache_holder
    assert getattr(bundle.context, "nautilus_portfolio") is cache_holder
    assert getattr(bundle.context, "paper_execution_metadata") == {
        "sandbox_book_type": "L2_MBP",
    }
    assert bundle.websocket_tasks == []


def test_publish_accepted_signal_in_background_uses_fresh_publish_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.signal_sidecar as sidecar_mod
    from polysignal_lab.domain.enums import Side
    from polysignal_lab.domain.signal import SignalCandidate

    published: list[tuple[str, float]] = []
    noted: list[dict[str, str]] = []
    closed: list[bool] = []

    class FakeTelegramPublisher:
        def __init__(self, config) -> None:
            self.config = config
            self.client = SimpleNamespace(aclose=self._aclose)

        async def _aclose(self) -> None:
            closed.append(True)

    class FakePublishService:
        def __init__(
            self,
            formatter,
            publisher,
            persistence,
            *,
            timeout_sec: float,
        ) -> None:
            assert formatter == "formatter"
            assert persistence == "persistence"
            assert timeout_sec == 7.0
            self.publisher = publisher

        async def publish_signal(self, signal, stake_usdc):
            published.append((signal.signal_id, stake_usdc))
            return SimpleNamespace(as_dict=lambda: {"status": "SENT"})

    monkeypatch.setattr(sidecar_mod, "TelegramPublisher", FakeTelegramPublisher, raising=False)
    monkeypatch.setattr(sidecar_mod, "PublishService", FakePublishService, raising=False)
    monkeypatch.setattr(
        sidecar_mod.scheduler_health,
        "note_publish_result",
        lambda _scheduler, publish: noted.append(publish),
    )
    scheduler = SimpleNamespace(
        settings=_runtime_settings_stub(telegram="telegram-config"),
        publish_service=SimpleNamespace(
            formatter="formatter",
            persistence="persistence",
            timeout_sec=7.0,
        ),
        logger=SimpleNamespace(warning=lambda *_args, **_kwargs: None),
    )
    signal = SignalCandidate.build(
        strategy="test",
        asset="BTC",
        timeframe="5m",
        market_id="m1",
        market_slug="s1",
        condition_id="c1",
        token_id="t1",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.5,
        max_entry_price=0.55,
        seconds_to_close=120,
        data_freshness_ms=100,
        reason_codes=["EDGE"],
        metrics={"edge": 0.1},
    )

    sidecar_mod._publish_accepted_signal_in_background(scheduler, signal, 10.0)

    assert published == [(signal.signal_id, 10.0)]
    assert noted == [{"status": "SENT"}]
    assert closed == [True]



def test_prepare_nautilus_runtime_context_rebinds_market_discovery_client_for_later_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod
    from polysignal_lab.domain.enums import Side
    from polysignal_lab.domain.market import Market, OutcomeToken

    market = Market(
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        asset="BTC",
        timeframe="5m",
        outcome_tokens=[
            OutcomeToken(token_id="up-token", side=Side.UP, outcome_name="Up", market_id="btc-5m"),
            OutcomeToken(token_id="down-token", side=Side.DOWN, outcome_name="Down", market_id="btc-5m"),
        ],
    )
    class LoopBoundClient:
        def __init__(self, label: str) -> None:
            self.label = label
            try:
                self.bound_loop = asyncio.get_running_loop()
            except RuntimeError:
                self.bound_loop = None
            self.closed = False

        async def get(self, _url: str, params: object | None = None) -> object:
            _ = params
            loop = asyncio.get_running_loop()
            if self.bound_loop is None:
                self.bound_loop = loop
            elif loop is not self.bound_loop:
                raise RuntimeError("client reused across event loops")
            return object()

        async def aclose(self) -> None:
            self.closed = True

    class FakeDiscovery:
        def __init__(self) -> None:
            self.client = LoopBoundClient("old")
            self.replace_calls = 0

        def replace_client(self) -> None:
            self.replace_calls += 1
            self.client = LoopBoundClient("new")

    class FakeMarketUniverse:
        def __init__(self, discovery: FakeDiscovery) -> None:
            self.discovery = discovery
            self.calls = 0

        async def refresh_once(self) -> list[Market]:
            self.calls += 1
            await self.discovery.client.get("https://example.invalid")
            return [market]

    class FakePersistence:
        def insert_signal(self, payload):
            _ = payload

        def insert_rejected_signal(self, payload):
            _ = payload

        def insert_paper_trade_result(self, payload):
            _ = payload

        def insert_system_event(self, payload):
            _ = payload

        def append_log(self, stream, payload):
            _ = stream, payload

    created: dict[str, object] = {}

    class FakeContext:
        def __init__(self, settings=None):
            self.settings = settings or SimpleNamespace(markets=SimpleNamespace(refresh_interval_sec=60))
            self.discovery = FakeDiscovery()
            created["old_client"] = self.discovery.client
            self.market_universe = FakeMarketUniverse(self.discovery)
            self.health = object()
            self.persistence = FakePersistence()
            self.publisher = SimpleNamespace(send=lambda *_args, **_kwargs: None)
            self.sqlite = SimpleNamespace()
            self.publish_service = SimpleNamespace(formatter=object(), persistence=object(), timeout_sec=10.0)
            self.signal_pipeline = SimpleNamespace()
            self.logger = logging.getLogger("test")
            self.strategy_schedule = []
            self.strategies = []
            self.gate = None
            self.consensus = None
            self.arbiter = None
            self.telegram_bot = None
            self.nautilus_cache = None
            self.nautilus_portfolio = None
            self.paper_execution_metadata = None
            self._running = False
            self._nautilus_runtime_owned_by_live_node = True
            self._trading_components_initialized = True
    monkeypatch.setattr(node_mod, "build_nautilus_runtime_context", lambda settings=None: FakeContext())
    monkeypatch.setattr(node_mod, "NautilusEventStoreAdapter", lambda persistence: persistence)
    monkeypatch.setattr(node_mod, "NautilusNotifierAdapter", lambda publisher: publisher)

    context, discovered_markets, _observability = asyncio.run(
        node_mod._prepare_nautilus_runtime_context(Settings())
    )

    assert [item.market_id for item in discovered_markets] == ["btc-5m"]
    old_client = cast(LoopBoundClient, created["old_client"])
    market_universe = cast(FakeMarketUniverse, cast(object, context.market_universe))
    discovery = cast(FakeDiscovery, cast(object, context.discovery))
    assert market_universe.calls == 1
    node_mod._rebind_market_discovery_client(context)

    refreshed_markets = asyncio.run(market_universe.refresh_once())

    assert [item.market_id for item in refreshed_markets] == ["btc-5m"]
    assert market_universe.calls == 2
    assert discovery.replace_calls == 1
    assert discovery.client is not old_client


async def test_prepare_nautilus_runtime_context_does_not_wire_shadow_wallet_mirror(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod
    from polysignal_lab.domain.enums import Side
    from polysignal_lab.domain.market import Market, OutcomeToken

    market = Market(
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="0x" + "1" * 64,
        asset="BTC",
        timeframe="5m",
        outcome_tokens=[
            OutcomeToken(token_id="up-token", side=Side.UP, outcome_name="Up", market_id="btc-5m"),
            OutcomeToken(token_id="down-token", side=Side.DOWN, outcome_name="Down", market_id="btc-5m"),
        ],
    )

    settings = Settings()
    ctx = SimpleNamespace(
        market_universe=SimpleNamespace(refresh_once=AsyncMock(return_value=[market])),
        publisher=_fake_telegram_publisher(),
        health=object(),
        persistence=SimpleNamespace(
            read_state=lambda name, default=None: [],
            insert_signal=lambda payload: None,
            insert_rejected_signal=lambda payload: None,
            upsert_market=lambda m: None,
        ),
        sqlite=SimpleNamespace(),
        publish_service=SimpleNamespace(formatter=object(), persistence=object(), timeout_sec=10.0),
        logger=logging.getLogger("test"),
        settings=settings,
    )

    monkeypatch.setattr(node_mod, "build_nautilus_runtime_context", lambda settings=None: ctx)

    sched, discovered_markets, observability = await node_mod._prepare_nautilus_runtime_context(settings)

    assert sched is ctx
    assert discovered_markets == (market,)
    assert getattr(ctx, "_nautilus_runtime_owned_by_live_node") is True


async def test_run_nautilus_housekeeping_once_skips_legacy_settlement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysignal_lab.nautilus_runtime.signal_sidecar import _run_nautilus_housekeeping_once
    import polysignal_lab.app.scheduler_shared as shared_mod

    calls: list[str] = []

    async def generate_iteration_report(_scheduler: object, last_report_date: object) -> str:
        calls.append(f"report:{last_report_date}")
        return "2026-07-05"

    monkeypatch.setattr(shared_mod, "_generate_iteration_report", generate_iteration_report)

    scheduler = SimpleNamespace(nautilus_cache=object())

    result = await _run_nautilus_housekeeping_once(scheduler, "2026-07-04")

    assert result == "2026-07-05"
    assert calls == ["report:2026-07-04"]

async def test_run_nautilus_cli_async_exits_on_stop_event(monkeypatch) -> None:
    class FakeTradingNode:
        def __init__(self):
            self.running = False

        def run(self):
            self.running = True

        def dispose(self):
            pass

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    fake_bundle = SimpleNamespace(
        node=FakeTradingNode(),
        websocket_tasks=[],
        context=_fake_runtime_context(),
        observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
        components={"strategies": []},
    )

    async def fake_build(settings=None):
        _ = settings
        return fake_bundle

    async def fake_to_thread(fn, *args):
        return fn(*args)

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_nautilus_runtime",
        fake_build,
    )
    monkeypatch.setattr(
        "asyncio.to_thread",
        fake_to_thread,
    )
    stop_event = asyncio.Event()
    stop_event.set()
    await run_nautilus_cli_async(stop_event=stop_event)

async def test_run_nautilus_cli_async_refreshes_startup_marker_before_runtime_build(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import json
    import polysignal_lab.nautilus_runtime.node as node_mod

    settings = Settings()
    settings.storage.state_dir = str(tmp_path / "state")
    old_started_at = "2026-06-30T11:00:00+00:00"
    marker = tmp_path / "state" / "runtime_startup.json"
    marker.parent.mkdir()
    marker.write_text(json.dumps({"started_at": old_started_at}), encoding="utf-8")
    observed: dict[str, object] = {}

    class FakeTradingNode:
        def run(self):
            return None

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    async def fake_build(received_settings=None):
        observed["settings"] = received_settings
        payload = json.loads(marker.read_text(encoding="utf-8"))
        assert isinstance(payload["started_at"], str)
        assert payload["started_at"] != old_started_at
        return SimpleNamespace(
            node=FakeTradingNode(),
            websocket_tasks=[],
            context=_fake_runtime_context(),
            observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
            components={"strategies": []},
        )

    monkeypatch.setattr(node_mod, "build_nautilus_runtime", fake_build)

    stop_event = asyncio.Event()
    stop_event.set()
    await run_nautilus_cli_async(settings=settings, stop_event=stop_event)

    assert observed["settings"] is settings

async def test_run_nautilus_cli_async_suppresses_probe_write_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod
    import polysignal_lab.nautilus_runtime.node_probes as probes_mod

    settings = Settings()

    class FakeTradingNode:
        def run(self):
            return None

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    async def fake_build(received_settings=None):
        assert received_settings is settings
        return SimpleNamespace(
            node=FakeTradingNode(),
            websocket_tasks=[],
            context=_fake_runtime_context(),
            observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
            components={"strategies": []},
        )

    def fail_write(*_args, **_kwargs):
        raise OSError("state directory unavailable")

    monkeypatch.setattr(node_mod, "build_nautilus_runtime", fake_build)
    monkeypatch.setattr(probes_mod, "write_runtime_startup_marker", fail_write)
    monkeypatch.setattr(probes_mod, "write_runtime_heartbeat", fail_write)

    stop_event = asyncio.Event()
    stop_event.set()
    await run_nautilus_cli_async(settings=settings, stop_event=stop_event)



async def test_run_nautilus_cli_async_does_not_install_signal_handlers_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeTradingNode:
        def run(self):
            return None

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    fake_bundle = SimpleNamespace(
        node=FakeTradingNode(),
        websocket_tasks=[],
        context=_fake_runtime_context(),
        observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
        components={"strategies": []},
    )

    async def fake_build(settings=None):
        _ = settings
        return fake_bundle

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_nautilus_runtime",
        fake_build,
    )
    monkeypatch.setattr(
        "asyncio.get_running_loop",
        lambda: SimpleNamespace(
            add_signal_handler=lambda *_args, **_kwargs: pytest.fail(
                "OS signal handlers must be opt-in"
            )
        ),
    )
    stop_event = asyncio.Event()
    stop_event.set()

    await run_nautilus_cli_async(stop_event=stop_event)


async def test_run_nautilus_cli_async_installs_signal_handlers_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed: list[tuple[object, object]] = []
    removed: list[object] = []

    class FakeTradingNode:
        def run(self):
            return None

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    fake_bundle = SimpleNamespace(
        node=FakeTradingNode(),
        websocket_tasks=[],
        context=_fake_runtime_context(
            settings=_runtime_settings_stub(
                runtime=SimpleNamespace(
                    nautilus=SimpleNamespace(
                        sandbox_book_type="L2_MBP",
                        intercept_os_signals=True,
                    )
                ),
            ),
        ),
        observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
        components={"strategies": []},
    )

    async def fake_build(settings=None):
        _ = settings
        return fake_bundle

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_nautilus_runtime",
        fake_build,
    )
    monkeypatch.setattr(
        "asyncio.get_running_loop",
        lambda: SimpleNamespace(
            add_signal_handler=lambda sig, handler: installed.append((sig, handler)),
            remove_signal_handler=lambda sig: removed.append(sig),
        ),
    )
    stop_event = asyncio.Event()
    stop_event.set()

    await run_nautilus_cli_async(stop_event=stop_event)

    assert [item[0] for item in installed] == [signal.SIGTERM, signal.SIGINT]
    assert set(removed) == {signal.SIGTERM, signal.SIGINT}


async def test_run_nautilus_cli_async_restores_signals_after_shutdown_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed: list[tuple[object, object]] = []
    removed: list[object] = []
    previous = {
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
        signal.SIGINT: signal.getsignal(signal.SIGINT),
    }


    class FakeTradingNode:
        def run(self):
            return None

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    fake_bundle = SimpleNamespace(
        node=FakeTradingNode(),
        websocket_tasks=[],
        context=_fake_runtime_context(
            settings=_runtime_settings_stub(
                runtime=SimpleNamespace(
                    nautilus=SimpleNamespace(
                        sandbox_book_type="L2_MBP",
                        intercept_os_signals=True,
                    )
                ),
            ),
        ),
        observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
        components={"strategies": []},
    )

    async def fake_build(settings=None):
        _ = settings
        return fake_bundle

    async def fail_stop(_scheduler):
        raise RuntimeError("shutdown failed")

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_nautilus_runtime",
        fake_build,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node_sidecar._stop_nautilus_services",
        fail_stop,
    )
    def add_signal_handler(sig, handler):
        installed.append((sig, handler))
        signal.signal(sig, lambda _signum, _frame: None)

    def remove_signal_handler(sig):
        removed.append(sig)

    monkeypatch.setattr(
        "asyncio.get_running_loop",
        lambda: SimpleNamespace(
            add_signal_handler=add_signal_handler,
            remove_signal_handler=remove_signal_handler,
        ),
    )
    stop_event = asyncio.Event()
    stop_event.set()

    try:
        with pytest.raises(RuntimeError, match="shutdown failed"):
            await run_nautilus_cli_async(stop_event=stop_event)

        assert signal.getsignal(signal.SIGTERM) == previous[signal.SIGTERM]
        assert signal.getsignal(signal.SIGINT) == previous[signal.SIGINT]
        assert [item[0] for item in installed] == [signal.SIGTERM, signal.SIGINT]
        assert set(removed) == {signal.SIGTERM, signal.SIGINT}
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)

async def test_run_nautilus_cli_async_surfaces_node_run_failure(monkeypatch) -> None:
    class FakeTradingNode:
        def run(self):
            raise RuntimeError("node boom")

        def dispose(self):
            pass

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    fake_bundle = SimpleNamespace(
        node=FakeTradingNode(),
        websocket_tasks=[],
        context=_fake_runtime_context(),
        observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
        components={"strategies": []},
    )

    async def fake_build(settings=None):
        _ = settings
        return fake_bundle

    async def fake_to_thread(fn, *args):
        return fn(*args)

    async def fake_report_loop(scheduler, stop_event):
        _ = scheduler
        await stop_event.wait()

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node_sidecar._run_nautilus_report_loop",
        fake_report_loop,
    )

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_nautilus_runtime",
        fake_build,
    )
    monkeypatch.setattr(
        "asyncio.to_thread",
        fake_to_thread,
    )

    with pytest.raises(RuntimeError, match="node boom"):
        await run_nautilus_cli_async()


async def test_run_nautilus_cli_async_waits_for_node_stop_instead_of_canceling_run_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_released = asyncio.Event()
    calls: list[str] = []

    class FakeTradingNode:
        def run(self):
            calls.append("run")

        def stop(self):
            calls.append("stop")
            run_released.set()

        def dispose(self):
            calls.append("dispose")

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    fake_bundle = SimpleNamespace(
        node=FakeTradingNode(),
        websocket_tasks=[],
        context=_fake_runtime_context(),
        observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
        components={"strategies": []},
    )

    async def fake_build(settings=None):
        _ = settings
        return fake_bundle

    async def fake_to_thread(fn, *args):
        if getattr(fn, "__name__", "") != "run":
            return fn(*args)
        await run_released.wait()

    async def fake_report_loop(scheduler, stop_event):
        _ = scheduler
        stop_event.set()

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node_sidecar._run_nautilus_report_loop",
        fake_report_loop,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_nautilus_runtime",
        fake_build,
    )
    monkeypatch.setattr(
        "asyncio.to_thread",
        fake_to_thread,
    )

    await run_nautilus_cli_async()

    assert calls == ["stop"]



async def test_run_nautilus_cli_async_leaves_node_disposal_to_sync_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeTradingNode:
        def run(self):
            return None

        def dispose(self):
            raise AssertionError("async runtime must not dispose node inline")

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    async def fake_report_loop(scheduler, stop_event):
        _ = scheduler
        await stop_event.wait()

    fake_bundle = SimpleNamespace(
        node=FakeTradingNode(),
        websocket_tasks=[],
        context=_fake_runtime_context(),
        observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
        components={"strategies": []},
    )

    async def fake_build(settings=None):
        _ = settings
        return fake_bundle

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node_sidecar._run_nautilus_report_loop",
        fake_report_loop,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_nautilus_runtime",
        fake_build,
    )

    node = await run_nautilus_cli_async()

    assert node is fake_bundle.node

async def test_run_nautilus_cli_async_notifies_and_starts_report_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod
    import polysignal_lab.nautilus_runtime.node_sidecar as sidecar_mod

    calls: list[tuple[object, ...]] = []

    class FakeTradingNode:
        def run(self):
            calls.append(("run",))

        def dispose(self):
            calls.append(("dispose",))

    class FakeObservability:
        async def notify_startup(self, strategy_names=(), **kwargs):
            calls.append(("startup", tuple(strategy_names), dict(kwargs)))

        async def notify_shutdown(self):
            calls.append(("shutdown",))

    async def fake_stop() -> None:
        calls.append(("scheduler_stop",))

    async def fake_build(settings=None):
        _ = settings
        return SimpleNamespace(
            node=FakeTradingNode(),
            websocket_tasks=[],
            context=_fake_runtime_context(stop=fake_stop),
            observability=FakeObservability(),
            components={"strategies": [SimpleNamespace(strategy_name="one_cent_buy")]},
        )

    async def fake_to_thread(fn, *args):
        return fn(*args)

    async def fake_report_loop(scheduler, stop_event):
        calls.append(("report_loop", scheduler))
        stop_event.set()

    monkeypatch.setattr(node_mod, "build_nautilus_runtime", fake_build)
    monkeypatch.setattr(sidecar_mod, "_run_nautilus_report_loop", fake_report_loop)
    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)

    await node_mod.run_nautilus_cli_async()

    assert any(call[0] == "startup" for call in calls)
    assert ("startup", ("one_cent_buy",), {"sandbox_book_type": "L2_MBP"}) in calls
    assert any(call[0] == "report_loop" for call in calls)
    assert any(call[0] == "shutdown" for call in calls)

async def test_run_nautilus_cli_async_tolerates_notification_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod
    import polysignal_lab.nautilus_runtime.node_sidecar as sidecar_mod

    calls: list[tuple[object, ...]] = []

    class FakeTradingNode:
        def run(self):
            calls.append(("run",))

        def dispose(self):
            calls.append(("dispose",))

    class FakeObservability:
        async def notify_startup(self, strategy_names=(), **kwargs):
            _ = strategy_names, kwargs
            raise RuntimeError("startup failed")

        async def notify_shutdown(self):
            raise RuntimeError("shutdown failed")

    class FakeLogger:
        def exception(self, message: str, *args: object) -> None:
            calls.append(("log", message, *args))

        def warning(self, message: str, *args: object) -> None:
            calls.append(("warn", message, *args))

    async def fake_stop() -> None:
        calls.append(("scheduler_stop",))

    async def fake_build(settings=None):
        _ = settings
        return SimpleNamespace(
            node=FakeTradingNode(),
            websocket_tasks=[],
            context=_fake_runtime_context(stop=fake_stop, logger=FakeLogger()),
            observability=FakeObservability(),
            components={"strategies": [SimpleNamespace(strategy_name="one_cent_buy")]},
        )

    async def fake_to_thread(fn, *args):
        return fn(*args)

    async def fake_report_loop(scheduler, stop_event):
        calls.append(("report_loop", scheduler))
        stop_event.set()

    monkeypatch.setattr(node_mod, "build_nautilus_runtime", fake_build)
    monkeypatch.setattr(sidecar_mod, "_run_nautilus_report_loop", fake_report_loop)
    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)

    await node_mod.run_nautilus_cli_async()

    assert any(call[0] == "run" for call in calls)
    assert not any(call[0] == "scheduler_stop" for call in calls)
    assert any(call[0] == "log" for call in calls)


async def test_stop_nautilus_services_skips_legacy_wallet_persist_without_wallet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod
    import polysignal_lab.nautilus_runtime.signal_sidecar as sidecar_mod

    calls: list[str] = []

    class FakeLogger:
        def warning(self, message: str, *args: object) -> None:
            calls.append(f"warn:{message}")

        def exception(self, message: str, *args: object) -> None:
            calls.append(f"exception:{message}")

    monkeypatch.setattr(
        sidecar_mod.scheduler_health,
        "persist_health_snapshot",
        lambda scheduler: calls.append("health"),
    )

    scheduler = SimpleNamespace(logger=FakeLogger())

    await node_mod._stop_nautilus_services(scheduler)

    assert calls == ["health"]

async def test_stop_nautilus_services_skips_legacy_stop_for_live_node_owned_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod
    import polysignal_lab.nautilus_runtime.signal_sidecar as sidecar_mod

    calls: list[str] = []

    monkeypatch.setattr(
        sidecar_mod.scheduler_health,
        "persist_health_snapshot",
        lambda scheduler: calls.append("health"),
    )

    async def legacy_stop() -> None:
        calls.append("legacy_stop")
        raise AssertionError("Nautilus LiveNode-owned scheduler must not call legacy stop")

    scheduler = SimpleNamespace(
        _nautilus_runtime_owned_by_live_node=True,
        wallet=object(),
        stop=legacy_stop,
    )

    await node_mod._stop_nautilus_services(scheduler)

    assert scheduler._running is False
    assert calls == ["health"]


def test_run_nautilus_cli_disposes_node_after_async_exit(monkeypatch) -> None:
    class FakeNode:
        def __init__(self) -> None:
            self.disposed = False

        def run(self) -> None:
            return None

        def dispose(self) -> None:
            self.disposed = True

    node = FakeNode()

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    async def fake_prepare(settings):
        _ = settings
        return SimpleNamespace(stop=_noop, settings=_runtime_settings_stub()), (), SimpleNamespace()

    def fake_bundle(settings, scheduler, discovered_markets, observability):
        _ = settings, scheduler, discovered_markets, observability
        return SimpleNamespace(
            node=node,
            context=_fake_runtime_context(),
            observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
            components={"strategies": []},
        )

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._prepare_nautilus_runtime_context",
        fake_prepare,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._build_nautilus_runtime_bundle",
        fake_bundle,
    )

    run_nautilus_cli()

    assert node.disposed is True




def test_run_nautilus_cli_exits_cleanly_when_live_node_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeNode:
        def run(self) -> None:
            return None

        def dispose(self) -> None:
            return None

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    async def fake_prepare(settings):
        _ = settings
        return SimpleNamespace(stop=_noop, settings=_runtime_settings_stub()), (), SimpleNamespace()

    def fake_bundle(settings, scheduler, discovered_markets, observability):
        _ = settings, scheduler, discovered_markets, observability
        return SimpleNamespace(
            node=FakeNode(),
            context=_fake_runtime_context(),
            observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
            components={"strategies": [SimpleNamespace(strategy_name="vwap_momentum")]},
        )

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._prepare_nautilus_runtime_context",
        fake_prepare,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._build_nautilus_runtime_bundle",
        fake_bundle,
    )

    # Should exit cleanly — no RuntimeError raised.
    run_nautilus_cli()


def test_run_nautilus_cli_logs_warning_on_unexpected_return(monkeypatch, tmp_path) -> None:

    class FakeNode:
        def run(self, raise_exception=False):
            return None

        def dispose(self):
            return None

    settings = Settings()
    settings.storage.state_dir = str(tmp_path / "state")
    startup_marker = tmp_path / "state" / "runtime_startup.json"
    startup_marker.parent.mkdir()
    startup_marker.write_text('{"started_at": "2026-06-30T11:00:00+00:00"}', encoding="utf-8")
    scheduler = SimpleNamespace(settings=settings, logger=SimpleNamespace(error=lambda *a, **k: None, warning=lambda *a, **k: None))
    observability = SimpleNamespace(
        notify_startup=AsyncMock(return_value=None),
        notify_shutdown=AsyncMock(return_value=None),
    )
    bundle = SimpleNamespace(
        context=scheduler,
        components={"strategies": [SimpleNamespace(strategy_name="vwap_momentum")]},
        node=FakeNode(),
        observability=observability,
    )

    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node._prepare_nautilus_runtime_context", AsyncMock(return_value=(scheduler, [], observability)))
    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node._rebind_market_discovery_client", lambda _scheduler: None)
    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node._build_nautilus_runtime_bundle", lambda *_args: bundle)
    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node._stop_nautilus_services", AsyncMock(return_value=None))

    # Should exit cleanly — no RuntimeError raised.
    run_nautilus_cli(settings)

def test_run_nautilus_cli_suppresses_heartbeat_write_failures_when_node_returns(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod
    import polysignal_lab.nautilus_runtime.node_probes as probes_mod

    class FakeNode:
        def run(self, raise_exception=False):
            return None

        def dispose(self):
            return None

    settings = Settings()
    settings.storage.state_dir = str(tmp_path / "state")
    scheduler = SimpleNamespace(settings=settings, logger=SimpleNamespace(error=lambda *a, **k: None, warning=lambda *a, **k: None))
    observability = SimpleNamespace(
        notify_startup=AsyncMock(return_value=None),
        notify_shutdown=AsyncMock(return_value=None),
    )
    bundle = SimpleNamespace(
        context=scheduler,
        components={"strategies": [SimpleNamespace(strategy_name="vwap_momentum")]},
        node=FakeNode(),
        observability=observability,
    )

    def fail_write(*_args, **_kwargs):
        raise OSError("state directory unavailable")

    monkeypatch.setattr(node_mod, "_prepare_nautilus_runtime_context", AsyncMock(return_value=(scheduler, [], observability)))
    monkeypatch.setattr(node_mod, "_rebind_market_discovery_client", lambda _scheduler: None)
    monkeypatch.setattr(node_mod, "_build_nautilus_runtime_bundle", lambda *_args: bundle)
    monkeypatch.setattr(node_mod, "_stop_nautilus_services", AsyncMock(return_value=None))
    monkeypatch.setattr(probes_mod, "write_runtime_heartbeat", fail_write)

    # Should exit cleanly — heartbeat write failures are suppressed.
    run_nautilus_cli(settings)


def test_run_nautilus_cli_does_not_install_signal_handlers_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeNode:
        def run(self) -> None:
            return None

        def dispose(self) -> None:
            return None

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    async def fake_prepare(settings):
        _ = settings
        return SimpleNamespace(stop=_noop, settings=_runtime_settings_stub()), (), SimpleNamespace()

    def fake_bundle(settings, scheduler, discovered_markets, observability):
        _ = settings, scheduler, discovered_markets, observability
        return SimpleNamespace(
            node=FakeNode(),
            context=_fake_runtime_context(),
            observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
            components={"strategies": []},
        )

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._prepare_nautilus_runtime_context",
        fake_prepare,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._build_nautilus_runtime_bundle",
        fake_bundle,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._install_sync_os_signal_handlers",
        lambda _request_stop: pytest.fail("OS signal handlers must be opt-in"),
    )

    run_nautilus_cli()


def test_run_nautilus_cli_installs_signal_handlers_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed: list[object] = []

    class FakeNode:
        def run(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def dispose(self) -> None:
            return None

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    async def fake_prepare(settings):
        _ = settings
        return SimpleNamespace(stop=_noop, settings=_runtime_settings_stub()), (), SimpleNamespace()

    def fake_bundle(settings, scheduler, discovered_markets, observability):
        _ = settings, scheduler, discovered_markets, observability
        return SimpleNamespace(
            node=FakeNode(),
            context=_fake_runtime_context(
                settings=_runtime_settings_stub(
                    runtime=SimpleNamespace(
                        nautilus=SimpleNamespace(
                            sandbox_book_type="L2_MBP",
                            intercept_os_signals=True,
                        )
                    )
                ),
            ),
            observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
            components={"strategies": []},
        )

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._prepare_nautilus_runtime_context",
        fake_prepare,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._build_nautilus_runtime_bundle",
        fake_bundle,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._install_sync_os_signal_handlers",
        lambda handler: (installed.append(handler), lambda: None)[1],
    )

    run_nautilus_cli()

    assert len(installed) == 1


def test_run_nautilus_cli_restores_opt_in_signal_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = {
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
        signal.SIGINT: signal.getsignal(signal.SIGINT),
    }

    class FakeNode:
        def run(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def dispose(self) -> None:
            return None

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    async def fake_prepare(settings):
        _ = settings
        return (
            SimpleNamespace(stop=_noop, settings=_runtime_settings_stub()),
            (),
            SimpleNamespace(),
        )

    def fake_bundle(settings, scheduler, discovered_markets, observability):
        _ = settings, scheduler, discovered_markets, observability
        return SimpleNamespace(
            node=FakeNode(),
            context=_fake_runtime_context(
                settings=_runtime_settings_stub(
                    runtime=SimpleNamespace(
                        nautilus=SimpleNamespace(
                            sandbox_book_type="L2_MBP",
                            intercept_os_signals=True,
                        )
                    )
                ),
            ),
            observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
            components={"strategies": []},
        )

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._prepare_nautilus_runtime_context",
        fake_prepare,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._build_nautilus_runtime_bundle",
        fake_bundle,
    )

    try:
        run_nautilus_cli()

        assert signal.getsignal(signal.SIGTERM) == previous[signal.SIGTERM]
        assert signal.getsignal(signal.SIGINT) == previous[signal.SIGINT]
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def test_run_nautilus_cli_restores_signal_handlers_after_dispose_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = {
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
        signal.SIGINT: signal.getsignal(signal.SIGINT),
    }

    class FakeNode:
        def run(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def dispose(self) -> None:
            raise RuntimeError("dispose failed")

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    async def fake_prepare(settings):
        _ = settings
        return (
            SimpleNamespace(stop=_noop, settings=_runtime_settings_stub()),
            (),
            SimpleNamespace(),
        )

    def fake_bundle(settings, scheduler, discovered_markets, observability):
        _ = settings, scheduler, discovered_markets, observability
        return SimpleNamespace(
            node=FakeNode(),
            context=_fake_runtime_context(
                settings=_runtime_settings_stub(
                    runtime=SimpleNamespace(
                        nautilus=SimpleNamespace(
                            sandbox_book_type="L2_MBP",
                            intercept_os_signals=True,
                        )
                    )
                ),
            ),
            observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
            components={"strategies": []},
        )

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._prepare_nautilus_runtime_context",
        fake_prepare,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._build_nautilus_runtime_bundle",
        fake_bundle,
    )

    try:
        with pytest.raises(RuntimeError, match="dispose failed"):
            run_nautilus_cli()

        assert signal.getsignal(signal.SIGTERM) == previous[signal.SIGTERM]
        assert signal.getsignal(signal.SIGINT) == previous[signal.SIGINT]
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def test_run_nautilus_cli_prints_ready(monkeypatch, capsys) -> None:
    """run_nautilus_cli returns without hanging."""

    class FakeNode:
        def run(self) -> None:
            print("Nautilus runtime ready — 0 strategies")

        def dispose(self) -> None:
            return None

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    async def fake_prepare(settings):
        _ = settings
        return SimpleNamespace(stop=_noop, settings=_runtime_settings_stub()), (), SimpleNamespace()

    def fake_bundle(settings, scheduler, discovered_markets, observability):
        _ = settings, scheduler, discovered_markets, observability
        return SimpleNamespace(
            node=FakeNode(),
            context=_fake_runtime_context(),
            observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
            components={"strategies": []},
        )

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._prepare_nautilus_runtime_context",
        fake_prepare,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._build_nautilus_runtime_bundle",
        fake_bundle,
    )

    run_nautilus_cli()

    assert "Nautilus runtime ready — 0 strategies" in capsys.readouterr().out


def test_start_interactive_telegram_bot_thread_starts_and_stops_bot() -> None:
    started = threading.Event()
    stopped = threading.Event()

    class FakeBot:
        async def start(self) -> None:
            started.set()

        async def stop(self) -> None:
            stopped.set()

    scheduler = SimpleNamespace(telegram_bot=FakeBot(), logger=SimpleNamespace(exception=print))
    handle = _start_interactive_telegram_bot_thread(cast(object, scheduler))
    assert handle is not None
    assert started.wait(timeout=5.0)
    _stop_interactive_telegram_bot_thread(handle)
    assert stopped.wait(timeout=5.0)


def test_start_interactive_telegram_bot_thread_returns_none_without_bot() -> None:
    scheduler = SimpleNamespace(telegram_bot=None)
    assert _start_interactive_telegram_bot_thread(cast(object, scheduler)) is None


def test_start_nautilus_report_loop_thread_runs_housekeeping_until_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polysignal_lab.nautilus_runtime.node import (
        _start_nautilus_report_loop_thread,
        _stop_nautilus_report_loop_thread,
    )

    calls: list[str] = []

    async def fake_housekeeping(scheduler, last_report_date):
        _ = scheduler
        calls.append("housekeeping")
        return last_report_date

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.signal_sidecar._run_nautilus_housekeeping_once",
        fake_housekeeping,
    )

    scheduler = SimpleNamespace(
        settings=SimpleNamespace(markets=SimpleNamespace(refresh_interval_sec=0.01)),
        logger=SimpleNamespace(exception=print),
    )
    handle = _start_nautilus_report_loop_thread(cast(object, scheduler))
    assert handle is not None
    deadline = time.monotonic() + 2.0
    while not calls and time.monotonic() < deadline:
        time.sleep(0.05)
    _stop_nautilus_report_loop_thread(handle)
    assert calls


def test_run_nautilus_cli_starts_report_loop_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod
    import polysignal_lab.nautilus_runtime.node_sidecar as sidecar_mod

    started = threading.Event()
    stopped = threading.Event()

    def fake_start_report_loop(scheduler):
        _ = scheduler
        started.set()
        return threading.Thread(), threading.Event()

    def fake_stop_report_loop(handle, *, timeout_sec=15.0):
        _ = handle, timeout_sec
        stopped.set()

    class FakeNode:
        def run(self) -> None:
            return None

        def dispose(self) -> None:
            return None

    async def _noop(*args, **kwargs):
        _ = args, kwargs

    async def fake_prepare(settings):
        _ = settings
        return SimpleNamespace(stop=_noop, settings=_runtime_settings_stub()), (), SimpleNamespace()

    def fake_bundle(settings, scheduler, discovered_markets, observability):
        _ = settings, scheduler, discovered_markets, observability
        return SimpleNamespace(
            node=FakeNode(),
            context=_fake_runtime_context(),
            observability=SimpleNamespace(notify_startup=_noop, notify_shutdown=_noop),
            components={"strategies": []},
        )

    monkeypatch.setattr(node_mod, "_prepare_nautilus_runtime_context", fake_prepare)
    monkeypatch.setattr(node_mod, "_rebind_market_discovery_client", lambda _scheduler: None)
    monkeypatch.setattr(node_mod, "_build_nautilus_runtime_bundle", fake_bundle)
    monkeypatch.setattr(sidecar_mod, "_start_nautilus_report_loop_thread", fake_start_report_loop)
    monkeypatch.setattr(sidecar_mod, "_stop_nautilus_report_loop_thread", fake_stop_report_loop)

    run_nautilus_cli()

    assert started.wait(timeout=5.0)
    assert stopped.is_set()
