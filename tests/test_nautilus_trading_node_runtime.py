from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import cast

import pytest

from polysignal_lab.config import Settings
from polysignal_lab.nautilus_runtime.trading_node import (
    PAPER_EXEC_CLIENT_ID,
    assert_no_live_polymarket_execution,
    build_paper_trading_node_config,
    register_paper_factories,
)


class FakeNode:
    def __init__(self) -> None:
        self.data_factories: list[tuple[str, object]] = []
        self.exec_factories: list[tuple[str, object]] = []

    def add_data_client_factory(self, name: str, factory: object) -> None:
        self.data_factories.append((name, factory))

    def add_exec_client_factory(self, name: str, factory: object) -> None:
        self.exec_factories.append((name, factory))


class FakeConfig:
    def __init__(self, **kwargs: object) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


class FakePolymarketLiveDataClientFactory:
    pass


class FakeSandboxLiveExecClientFactory:
    pass


def _install_fake_nautilus(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_module(name: str, **attrs: object) -> ModuleType:
        module = ModuleType(name)
        for attr_name, value in attrs.items():
            setattr(module, attr_name, value)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    _ = fake_module("nautilus_trader")
    _ = fake_module("nautilus_trader.adapters")
    _ = fake_module(
        "nautilus_trader.adapters.polymarket",
        PolymarketDataClientConfig=FakeConfig,
        PolymarketLiveDataClientFactory=FakePolymarketLiveDataClientFactory,
    )
    _ = fake_module("nautilus_trader.adapters.sandbox")
    _ = fake_module("nautilus_trader.adapters.sandbox.config", SandboxExecutionClientConfig=FakeConfig)
    _ = fake_module(
        "nautilus_trader.adapters.sandbox.factory",
        SandboxLiveExecClientFactory=FakeSandboxLiveExecClientFactory,
    )
    _ = fake_module(
        "nautilus_trader.config",
        CacheConfig=FakeConfig,
        LiveDataEngineConfig=FakeConfig,
        LiveExecEngineConfig=FakeConfig,
        LoggingConfig=FakeConfig,
        RoutingConfig=FakeConfig,
        TradingNodeConfig=FakeConfig,
    )
    _ = fake_module("nautilus_trader.model")
    _ = fake_module("nautilus_trader.model.identifiers", TraderId=str)


def _dict_attr(source: object, name: str) -> dict[str, object]:
    value = cast(object, getattr(source, name))
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def test_live_polymarket_execution_is_rejected() -> None:
    """Does NOT require nautilus_trader — tests pure Python logic."""
    config = SimpleNamespace(exec_clients={"POLYMARKET": object()})

    with pytest.raises(RuntimeError, match="live Polymarket execution"):
        assert_no_live_polymarket_execution(config)


def test_build_paper_trading_node_config_uses_polymarket_data_and_sandbox_exec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_nautilus(monkeypatch)
    settings = Settings()
    settings.paper_trading.starting_balance_usdc = 1234.0

    config = build_paper_trading_node_config(
        settings,
        instrument_config=SimpleNamespace(load_ids=frozenset({"up-token.POLYMARKET"})),
    )

    data_clients = _dict_attr(config, "data_clients")
    exec_clients = _dict_attr(config, "exec_clients")
    sandbox_config = exec_clients[PAPER_EXEC_CLIENT_ID]

    assert "POLYMARKET" in data_clients
    assert getattr(data_clients["POLYMARKET"], "venue", "POLYMARKET") == "POLYMARKET"
    assert PAPER_EXEC_CLIENT_ID in exec_clients
    assert getattr(sandbox_config, "venue") == "POLYMARKET"
    assert getattr(sandbox_config, "account_type") == "CASH"
    assert getattr(sandbox_config, "oms_type") == "NETTING"
    assert getattr(sandbox_config, "starting_balances") == ["1234.0 USDC"]
    assert "POLYMARKET" not in exec_clients


def test_build_paper_trading_node_config_enables_dynamic_instrument_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_nautilus(monkeypatch)
    settings = Settings()
    settings.runtime.nautilus.market_rotation.allow_adapter_new_market_events = True

    config = build_paper_trading_node_config(
        settings,
        instrument_config=SimpleNamespace(load_ids=frozenset({"up-token.POLYMARKET"})),
    )

    data_clients = _dict_attr(config, "data_clients")
    polymarket = data_clients["POLYMARKET"]

    assert getattr(polymarket, "auto_load_missing_instruments") is True
    assert getattr(polymarket, "auto_load_debounce_ms") == 100
    assert getattr(polymarket, "auto_load_max_retries") == 12
    assert getattr(polymarket, "subscribe_new_markets") is True
    assert getattr(polymarket, "ws_max_subscriptions_per_connection") == 200
    assert getattr(polymarket, "update_instruments_interval_mins") == 1

def test_build_paper_trading_node_config_bounds_cache_tick_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_nautilus(monkeypatch)

    config = build_paper_trading_node_config(
        Settings(),
        instrument_config=SimpleNamespace(load_ids=frozenset({"up-token.POLYMARKET"})),
    )

    cache = getattr(config, "cache")
    assert getattr(cache, "tick_capacity") == 100
    assert getattr(cache, "bar_capacity") == 100


def test_register_paper_factories_registers_data_and_sandbox_exec_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_nautilus(monkeypatch)
    node = FakeNode()

    register_paper_factories(node)

    assert node.data_factories == [("POLYMARKET", FakePolymarketLiveDataClientFactory)]
    assert node.exec_factories == [(PAPER_EXEC_CLIENT_ID, FakeSandboxLiveExecClientFactory)]
    assert all(name != "POLYMARKET" for name, _factory in node.exec_factories)
