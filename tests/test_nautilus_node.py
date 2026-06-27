from __future__ import annotations

import asyncio
from types import SimpleNamespace

from polysignal_lab.nautilus_runtime.node import (
    build_trading_node,
    build_control,
    run_nautilus_cli,
    run_nautilus_cli_async,
)


def _patch_nautilus_placeholders(monkeypatch):
    """Monkeypatch all 4 module-level nautilus placeholders so tests on py3.11
    can call build_trading_node without importing nautilus_trader."""

    class _FakeTradingNode:
        def __init__(self, config):
            self.config = config
            self.trader = SimpleNamespace(strategies=[])
            self.trader.add_strategy = self.trader.strategies.append
            self.built = False

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
            node.add_exec_client_factory("POLYSIGNAL-SANDBOX", object()),
        ),
    )
    return _FakeTradingNode


def test_build_trading_node_returns_nautilus_runtime_components(monkeypatch) -> None:
    built = {}

    class FakeTradingNode:
        def __init__(self, config):
            self.config = config
            self.trader = SimpleNamespace(strategies=[])
            self.trader.add_strategy = self.trader.strategies.append
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
            node.add_exec_client_factory("POLYSIGNAL-SANDBOX", object()),
        ),
    )

    runtime = build_trading_node(condition_ids=("condition-btc-5m",))

    assert runtime["node"] is built["node"]
    assert built["node"].built is True
    assert built["exec_factories"][0][0] != "POLYMARKET"
    assert "paper_client" not in runtime


def test_build_trading_node_uses_sandbox_execution_not_matching_client(monkeypatch) -> None:
    class FakeTradingNode:
        def __init__(self, config):
            self.config = config
            self.trader = SimpleNamespace(strategies=[])
            self.trader.add_strategy = self.trader.strategies.append

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
            node.add_exec_client_factory("POLYSIGNAL-SANDBOX", object()),
        ),
    )

    runtime = build_trading_node()

    assert runtime["node"].exec_factory_name != "POLYMARKET"
    assert "paper_client" not in runtime
    assert "matching_client" not in runtime


def test_build_trading_node_strategies_is_list(monkeypatch) -> None:
    """Strategy list is a list even when no strategies configured."""
    _patch_nautilus_placeholders(monkeypatch)

    runtime = build_trading_node()
    assert isinstance(runtime["strategies"], list)


def test_build_control_adapts_policy() -> None:
    from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor

    policy = DecisionPolicyActor()
    ctrl = build_control(policy)

    assert ctrl.is_strategy_enabled("vwap_momentum")
    ctrl.set_strategy_enabled("vwap_momentum", enabled=False)
    assert not ctrl.is_strategy_enabled("vwap_momentum")


async def test_run_nautilus_cli_async_exits_on_stop_event(monkeypatch) -> None:
    class FakeTradingNode:
        def __init__(self):
            self.running = False

        def run(self):
            self.running = True

        def dispose(self):
            pass

    async def _noop(*args, **kwargs):
        pass

    fake_bundle = SimpleNamespace(
        node=FakeTradingNode(),
        websocket_tasks=[],
        scheduler=SimpleNamespace(stop=_noop),
        data_ingestor=SimpleNamespace(sync_all=lambda: None),
        components={"strategies": []},
    )

    async def fake_build(settings=None):
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


def test_noop_matching_sink_satisfies_protocol() -> None:
    from polysignal_lab.nautilus_runtime.node import _NoopMatchingSink
    from datetime import datetime, timezone

    sink = _NoopMatchingSink()
    # Must accept real matching-sink signatures without raising.
    sink.update_book("token-up", object())
    sink.update_trade(
        "token-up",
        price=0.50,
        size=100.0,
        side="BUY",
        ts_event=datetime.now(timezone.utc),
    )
