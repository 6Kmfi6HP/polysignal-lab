from __future__ import annotations

import asyncio
from types import SimpleNamespace
import pytest

from polysignal_lab.config import Settings
from polysignal_lab.nautilus_runtime.node import (
    build_trading_node,
    build_control,
    run_nautilus_cli,
    run_nautilus_cli_async,
)
from polysignal_lab.nautilus_runtime.trading_node import PAPER_EXEC_CLIENT_ID


def _patch_nautilus_placeholders(monkeypatch):
    """Monkeypatch all 4 module-level nautilus placeholders so tests on py3.11
    can call build_trading_node without importing nautilus_trader."""

    class _FakeTradingNode:
        def __init__(self, config):
            self.config = config
            self.trader = SimpleNamespace(strategies=[], actors=[])
            self.trader.add_strategy = self.trader.strategies.append
            self.trader.add_actor = self.trader.actors.append
            self.built = False
            self.exec_factory_name: str | None = None

        def add_data_client_factory(self, name, factory):
            pass

        def add_exec_client_factory(self, name, factory):
            self.exec_factory_name = name

        def build(self):
            self.built = True

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.TradingNode",
        _FakeTradingNode,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.PolymarketInstrumentProviderConfig",
        lambda *, load_ids: SimpleNamespace(load_ids=load_ids),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_paper_trading_node_config",
        lambda settings, **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.register_paper_factories",
        lambda node: (
            node.add_data_client_factory("POLYMARKET", object()),
            node.add_exec_client_factory(PAPER_EXEC_CLIENT_ID, object()),
        ),
    )
    return _FakeTradingNode


def test_build_trading_node_returns_nautilus_runtime_components(monkeypatch) -> None:
    built = {}

    class FakeTradingNode:
        def __init__(self, config):
            self.config = config
            self.trader = SimpleNamespace(strategies=[], actors=[])
            self.trader.add_strategy = self.trader.strategies.append
            self.trader.add_actor = self.trader.actors.append
            self.built = False
            built["node"] = self

        def add_data_client_factory(self, name, factory):
            built.setdefault("data_factories", []).append((name, factory))

        def add_exec_client_factory(self, name, factory):
            built.setdefault("exec_factories", []).append((name, factory))

        def build(self):
            self.built = True

    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node.TradingNode", FakeTradingNode)
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.PolymarketInstrumentProviderConfig",
        lambda *, load_ids: SimpleNamespace(load_ids=load_ids),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_paper_trading_node_config",
        lambda settings, **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.register_paper_factories",
        lambda node: (
            node.add_data_client_factory("POLYMARKET", object()),
            node.add_exec_client_factory(PAPER_EXEC_CLIENT_ID, object()),
        ),
    )

    runtime = build_trading_node(condition_ids=("condition-btc-5m",))

    assert runtime["node"] is built["node"]
    assert built["node"].built is True
    assert built["exec_factories"][0][0] != "POLYMARKET"
    assert len(built["node"].trader.actors) == 1
    assert "paper_client" not in runtime


def test_build_trading_node_registers_market_rotation_actor(monkeypatch) -> None:
    built = {}

    class FakeTradingNode:
        def __init__(self, config):
            self.config = config
            self.trader = SimpleNamespace(strategies=[], actors=[])
            self.trader.add_strategy = self.trader.strategies.append
            self.trader.add_actor = self.trader.actors.append
            built["node"] = self

        def add_data_client_factory(self, name, factory):
            pass

        def add_exec_client_factory(self, name, factory):
            pass

        def build(self):
            return None

    class FakeRotationActor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node.TradingNode", FakeTradingNode)
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.PolymarketInstrumentProviderConfig",
        lambda *, load_ids: SimpleNamespace(load_ids=load_ids),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_paper_trading_node_config",
        lambda settings, **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.register_paper_factories",
        lambda node: None,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.market_rotation.runtime_market_rotation_actor_type",
        lambda _base, _config: FakeRotationActor,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.sidecar_data.runtime_sidecar_actor_type",
        lambda _base, _config: pytest.fail("build_trading_node should register MarketRotationActor"),
    )

    universe = object()
    health = object()
    runtime = build_trading_node(
        condition_ids=("condition-btc-5m",),
        market_universe=universe,
        health=health,
    )

    assert len(built["node"].trader.actors) == 1
    assert built["node"].trader.actors[0] is runtime["market_rotation_actor"]
    assert isinstance(runtime["market_rotation_actor"], FakeRotationActor)
    assert runtime["market_rotation_actor"].kwargs["market_universe"] is universe
    assert runtime["market_rotation_actor"].kwargs["health"] is health

def test_build_trading_node_uses_sandbox_execution_not_matching_client(monkeypatch) -> None:
    class FakeTradingNode:
        def __init__(self, config):
            self.config = config
            self.trader = SimpleNamespace(strategies=[], actors=[])
            self.trader.add_strategy = self.trader.strategies.append
            self.trader.add_actor = self.trader.actors.append
            self.exec_factory_name: str | None = None

        def add_data_client_factory(self, name, factory):
            pass

        def add_exec_client_factory(self, name, factory):
            self.exec_factory_name = name

        def build(self):
            pass

    monkeypatch.setattr("polysignal_lab.nautilus_runtime.node.TradingNode", FakeTradingNode)
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.PolymarketInstrumentProviderConfig",
        lambda *, load_ids: SimpleNamespace(load_ids=load_ids),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.build_paper_trading_node_config",
        lambda settings, **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node.register_paper_factories",
        lambda node: (
            node.add_data_client_factory("POLYMARKET", object()),
            node.add_exec_client_factory(PAPER_EXEC_CLIENT_ID, object()),
        ),
    )

    runtime = build_trading_node()

    assert getattr(runtime["node"], "exec_factory_name") != "POLYMARKET"
    assert "paper_client" not in runtime
    assert "matching_client" not in runtime


def test_build_trading_node_strategies_is_list(monkeypatch) -> None:
    """Strategy list is a list even when no strategies configured."""
    _patch_nautilus_placeholders(monkeypatch)

    runtime = build_trading_node()
    assert isinstance(runtime["strategies"], list)


def test_build_trading_node_forwards_unsubscribe_exited_to_native_strategy(
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
        "polysignal_lab.nautilus_runtime.market_rotation.runtime_market_rotation_actor_type",
        lambda _base, _config: FakeRotationActor,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.native_strategy.runtime_native_strategy_type",
        lambda _base, _config: FakeStrategy,
    )
    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._native_core_for",
        lambda _name, _cfg: object(),
    )

    settings = Settings()
    settings.runtime.nautilus.market_rotation.unsubscribe_exited = False
    settings.strategies.set_explicit_strategy_names(("vwap_momentum",))

    runtime = build_trading_node(
        settings=settings,
        condition_ids=("condition-btc-5m",),
    )

    assert len(runtime["strategies"]) == 1
    assert runtime["node"].trader.strategies == runtime["strategies"]
    assert captured["kwargs"]["unsubscribe_exited"] is False
    assert captured["kwargs"]["strategy_name"] == "vwap_momentum"

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

        def upsert_paper_order(self, payload):
            _ = payload

        def insert_paper_fill(self, payload):
            _ = payload

        def upsert_paper_position(self, payload):
            _ = payload

        def insert_paper_trade_result(self, payload):
            _ = payload

        def insert_system_event(self, payload):
            _ = payload

        def append_log(self, stream, payload):
            _ = stream, payload

    class FakeMarketUniverse:
        async def refresh_once(self) -> list[Market]:
            nonlocal refresh_calls
            refresh_calls += 1
            return [market]

    class FakeScheduler:
        def __init__(self, settings=None):
            self.settings = settings or SimpleNamespace(markets=SimpleNamespace(refresh_interval_sec=60))
            self.market_universe = FakeMarketUniverse()
            self.health = object()
            self.persistence = FakePersistence()
            self.publisher = SimpleNamespace(send=lambda *_args, **_kwargs: None)

        async def stop(self) -> None:
            return None

    monkeypatch.setattr(node_mod, "PolySignalScheduler", FakeScheduler)
    monkeypatch.setattr(node_mod, "_initialize_nautilus_scheduler_components", lambda _scheduler: None)
    monkeypatch.setattr(node_mod, "NautilusEventStoreAdapter", lambda persistence: persistence)
    monkeypatch.setattr(node_mod, "NautilusNotifierAdapter", lambda publisher: publisher)
    monkeypatch.setattr(node_mod, "ObservabilityActor", lambda **kwargs: SimpleNamespace(**kwargs))
    cache_reader = object()
    monkeypatch.setattr(
        node_mod,
        "build_trading_node",
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
            "cache_reader": cache_reader,
            "registry": object(),
            "sidecar": object(),
            "node": SimpleNamespace(),
            "strategies": [],
        },
    )

    bundle = await node_mod.build_nautilus_runtime()

    assert refresh_calls == 1
    assert captured["condition_ids"] == ("condition-btc-5m",)
    assert captured["markets"] == (market,)
    assert captured["market_universe"] is bundle.scheduler.market_universe
    assert captured["health"] is bundle.scheduler.health
    assert captured["observability"] is not None
    assert bundle.scheduler is not None
    assert getattr(bundle.scheduler, "nautilus_cache_reader") is cache_reader
    assert getattr(bundle.scheduler, "paper_execution_metadata") == {
        "paper_engine": "nautilus_matching",
        "accuracy_mode": "depth_l2",
    }
    assert bundle.websocket_tasks == []


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
        scheduler=SimpleNamespace(
            stop=_noop,
            settings=SimpleNamespace(
                markets=SimpleNamespace(refresh_interval_sec=60),
                runtime=SimpleNamespace(
                    nautilus=SimpleNamespace(
                        paper_engine="nautilus_matching",
                        matching_accuracy_mode="depth_l2",
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

    async def fake_to_thread(fn):
        return fn()

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
        scheduler=SimpleNamespace(
            stop=_noop,
            settings=SimpleNamespace(
                markets=SimpleNamespace(refresh_interval_sec=60),
                runtime=SimpleNamespace(
                    nautilus=SimpleNamespace(
                        paper_engine="nautilus_matching",
                        matching_accuracy_mode="depth_l2",
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

    async def fake_to_thread(fn):
        return fn()

    async def fake_report_loop(scheduler, stop_event):
        _ = scheduler
        await stop_event.wait()

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._run_nautilus_report_loop",
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
        scheduler=SimpleNamespace(
            stop=_noop,
            settings=SimpleNamespace(
                markets=SimpleNamespace(refresh_interval_sec=60),
                runtime=SimpleNamespace(
                    nautilus=SimpleNamespace(
                        paper_engine="nautilus_matching",
                        matching_accuracy_mode="depth_l2",
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

    async def fake_to_thread(fn):
        if getattr(fn, "__name__", "") == "dispose":
            fn()
            return None
        await run_released.wait()

    async def fake_report_loop(scheduler, stop_event):
        _ = scheduler
        stop_event.set()

    monkeypatch.setattr(
        "polysignal_lab.nautilus_runtime.node._run_nautilus_report_loop",
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
        scheduler=SimpleNamespace(
            stop=_noop,
            settings=SimpleNamespace(
                markets=SimpleNamespace(refresh_interval_sec=60),
                runtime=SimpleNamespace(
                    nautilus=SimpleNamespace(
                        paper_engine="nautilus_matching",
                        matching_accuracy_mode="depth_l2",
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
        "polysignal_lab.nautilus_runtime.node._run_nautilus_report_loop",
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
            scheduler=SimpleNamespace(
                stop=fake_stop,
                settings=SimpleNamespace(
                    runtime=SimpleNamespace(
                        nautilus=SimpleNamespace(
                            paper_engine="nautilus_matching",
                            matching_accuracy_mode="depth_l2",
                        )
                    )
                ),
            ),
            observability=FakeObservability(),
            components={"strategies": [SimpleNamespace(strategy_name="one_cent_buy")]},
        )

    async def fake_to_thread(fn):
        return fn()

    async def fake_report_loop(scheduler, stop_event):
        calls.append(("report_loop", scheduler))
        stop_event.set()

    monkeypatch.setattr(node_mod, "build_nautilus_runtime", fake_build)
    monkeypatch.setattr(node_mod, "_run_nautilus_report_loop", fake_report_loop, raising=False)
    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)

    await node_mod.run_nautilus_cli_async()

    assert any(call[0] == "startup" for call in calls)
    assert any(call[0] == "report_loop" for call in calls)
    assert any(call[0] == "shutdown" for call in calls)

async def test_run_nautilus_cli_async_tolerates_notification_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod

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
            scheduler=SimpleNamespace(
                stop=fake_stop,
                logger=FakeLogger(),
                settings=SimpleNamespace(
                    markets=SimpleNamespace(refresh_interval_sec=60),
                    runtime=SimpleNamespace(
                        nautilus=SimpleNamespace(
                            paper_engine="nautilus_matching",
                            matching_accuracy_mode="depth_l2",
                        )
                    ),
                ),
            ),
            observability=FakeObservability(),
            components={"strategies": [SimpleNamespace(strategy_name="one_cent_buy")]},
        )

    async def fake_to_thread(fn):
        return fn()

    async def fake_report_loop(scheduler, stop_event):
        calls.append(("report_loop", scheduler))
        stop_event.set()

    monkeypatch.setattr(node_mod, "build_nautilus_runtime", fake_build)
    monkeypatch.setattr(node_mod, "_run_nautilus_report_loop", fake_report_loop, raising=False)
    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)

    await node_mod.run_nautilus_cli_async()

    assert any(call[0] == "run" for call in calls)
    assert not any(call[0] == "scheduler_stop" for call in calls)
    assert any(call[0] == "log" for call in calls)


async def test_stop_nautilus_scheduler_skips_legacy_wallet_persist_without_wallet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod

    calls: list[str] = []

    class FakeLogger:
        def warning(self, message: str, *args: object) -> None:
            calls.append(f"warn:{message}")

        def exception(self, message: str, *args: object) -> None:
            calls.append(f"exception:{message}")

    monkeypatch.setattr(
        node_mod.scheduler_health,
        "persist_health_snapshot",
        lambda scheduler: calls.append("health"),
    )

    scheduler = SimpleNamespace(logger=FakeLogger())

    await node_mod._stop_nautilus_scheduler(scheduler)

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
        return SimpleNamespace(stop=_noop, settings=SimpleNamespace()), (), SimpleNamespace()

    def fake_bundle(settings, scheduler, discovered_markets, observability):
        _ = settings, scheduler, discovered_markets, observability
        return SimpleNamespace(
            node=node,
            scheduler=SimpleNamespace(
                stop=_noop,
                settings=SimpleNamespace(
                    runtime=SimpleNamespace(
                        nautilus=SimpleNamespace(
                            paper_engine="nautilus_matching",
                            matching_accuracy_mode="depth_l2",
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

    run_nautilus_cli()

    assert node.disposed is True


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
        return SimpleNamespace(stop=_noop, settings=SimpleNamespace()), (), SimpleNamespace()

    def fake_bundle(settings, scheduler, discovered_markets, observability):
        _ = settings, scheduler, discovered_markets, observability
        return SimpleNamespace(
            node=FakeNode(),
            scheduler=SimpleNamespace(
                stop=_noop,
                settings=SimpleNamespace(
                    runtime=SimpleNamespace(
                        nautilus=SimpleNamespace(
                            paper_engine="nautilus_matching",
                            matching_accuracy_mode="depth_l2",
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

    run_nautilus_cli()

    assert "Nautilus runtime ready — 0 strategies" in capsys.readouterr().out
