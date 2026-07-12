"""
Input: __future__, __future__.annotations, asyncio, types, types.SimpleNamespace, pytest, polysignal_lab.config, polysignal_lab.config.Settings, polysignal_lab.nautilus_runtime, polysignal_lab.nautilus_runtime.live_node
Output: test_trading_node_exposes_expected_client_ids, test_load_live_runtime_symbols_matches_nautilus_1229_api, test_live_polymarket_execution_is_rejected, test_polymarket_market_data_credentials_fail_closed, test_polymarket_market_data_credentials_accept_nonempty_values, test_build_paper_live_node_uses_polymarket_data_and_sandbox_exec, test_build_polymarket_data_client_config_enables_dynamic_instrument_loading, test_build_paper_live_node_bounds_cache_tick_capacity, test_build_sandbox_exec_client_config_uses_paper_venue_and_routes_to_polymarket, test_build_exec_engine_config_disables_unsupported_sandbox_reconciliation, test_run_nautilus_cli_async_starts_and_stops_observability_writer, FakeConfig, FakePolymarketLiveDataClientFactory, FakeSandboxLiveExecClientFactory
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
    build_cache_config,
    build_exec_engine_config,
    build_paper_live_node,
    build_polymarket_data_client_config,
    build_sandbox_exec_client_config,
)
from polysignal_lab.nautilus_runtime.node import run_nautilus_cli_async
from polysignal_lab.nautilus_runtime.live_node import (
    PAPER_EXEC_CLIENT_ID,
    POLYMARKET_CLIENT_ID,
    assert_no_live_polymarket_execution,
    validate_polymarket_market_data_credentials,
)
from polysignal_lab.nautilus_runtime.custom_data_types import SPOT_DATA_CLIENT_ID


class FakeConfig:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        for key, value in kwargs.items():
            setattr(self, key, value)


class FakePolymarketLiveDataClientFactory:
    pass


class FakeSandboxLiveExecClientFactory:
    pass


class FakeTradingNode:
    def __init__(self, *, config: FakeConfig) -> None:
        self.config = config
        self.data_client_factories: list[tuple[str, object]] = []
        self.exec_client_factories: list[tuple[str, object]] = []

    def add_data_client_factory(self, name: str, factory: object) -> None:
        self.data_client_factories.append((name, factory))

    def add_exec_client_factory(self, name: str, factory: object) -> None:
        self.exec_client_factories.append((name, factory))


def _fake_import_callable(module_name: str, attr_name: str):
    def _factory(*args: object, **kwargs: object) -> FakeConfig:
        return FakeConfig(*args, module_name=module_name, attr_name=attr_name, **kwargs)

    return _factory


def _patch_live_node_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_node, "_import_callable", _fake_import_callable)
    monkeypatch.setattr(live_node, "TradingNode", FakeTradingNode)
    monkeypatch.setattr(live_node, "TradingNodeConfig", FakeConfig)
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


def test_load_live_runtime_symbols_matches_nautilus_1229_api() -> None:
    pytest.importorskip("nautilus_trader")

    from nautilus_trader.common import Environment
    from nautilus_trader.config import TradingNodeConfig
    from nautilus_trader.live.node import TradingNode
    from nautilus_trader.model.identifiers import TraderId
    from polysignal_lab.nautilus_runtime.optional_imports import load_live_runtime_symbols

    symbols = load_live_runtime_symbols()

    assert symbols.trading_node is TradingNode
    assert symbols.trading_node_config is TradingNodeConfig
    assert symbols.trader_id is TraderId
    assert symbols.environment is Environment


def test_live_polymarket_execution_is_rejected() -> None:
    """Does NOT require nautilus_trader — tests pure Python logic."""
    config = SimpleNamespace(exec_clients={POLYMARKET_CLIENT_ID: object()})

    with pytest.raises(RuntimeError, match="live Polymarket execution"):
        assert_no_live_polymarket_execution(config)


def test_polymarket_market_data_credentials_fail_closed() -> None:
    with pytest.raises(RuntimeError, match="POLYMARKET_API_KEY") as exc_info:
        validate_polymarket_market_data_credentials({})

    message = str(exc_info.value)
    assert "POLYMARKET_API_SECRET" in message
    assert "POLYMARKET_PASSPHRASE" in message
    assert "POLYMARKET_PK" in message
    assert "POLYMARKET_FUNDER" in message
    assert "secret-value" not in message


def test_polymarket_market_data_credentials_accept_nonempty_values() -> None:
    validate_polymarket_market_data_credentials(
        {
            "POLYMARKET_API_KEY": "key",
            "POLYMARKET_API_SECRET": "secret",
            "POLYMARKET_PASSPHRASE": "passphrase",
            "POLYMARKET_PK": "private-key",
            "POLYMARKET_FUNDER": "funder",
        }
    )


def test_build_paper_live_node_rejects_real_polymarket_factory_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_live_node_fakes(monkeypatch)

    class RealLikePolymarketFactory:
        pass

    RealLikePolymarketFactory.__module__ = "nautilus_trader.adapters.polymarket.data"
    monkeypatch.setattr(
        live_node,
        "PolymarketLiveDataClientFactory",
        RealLikePolymarketFactory,
    )
    for name in live_node.POLYMARKET_MARKET_DATA_CREDENTIALS:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match="POLYMARKET_API_KEY"):
        build_paper_live_node(
            Settings(),
            instrument_config=SimpleNamespace(load_ids=frozenset()),
        )


def test_build_paper_live_node_uses_polymarket_data_and_sandbox_exec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_live_node_fakes(monkeypatch)
    settings = Settings()
    settings.paper_trading.starting_balance_usdc = 1234.0
    instrument_config = SimpleNamespace(load_ids=frozenset({"up-token.POLYMARKET"}))

    node = build_paper_live_node(settings, instrument_config=instrument_config)

    config = node.config
    assert getattr(config, "trader_id") == "TraderId:PolySignal-Nautilus-001"
    assert getattr(config, "environment") == "SANDBOX"
    assert getattr(config, "data_clients")[POLYMARKET_CLIENT_ID] is not None
    assert getattr(config, "exec_clients")[PAPER_EXEC_CLIENT_ID] is not None
    assert node.data_client_factories == [
        (POLYMARKET_CLIENT_ID, FakePolymarketLiveDataClientFactory),
    ]
    assert node.exec_client_factories == [
        (PAPER_EXEC_CLIENT_ID, FakeSandboxLiveExecClientFactory),
    ]
    assert PAPER_EXEC_CLIENT_ID != POLYMARKET_CLIENT_ID

    data_config = config.data_clients[POLYMARKET_CLIENT_ID]
    exec_config = config.exec_clients[PAPER_EXEC_CLIENT_ID]
    assert getattr(data_config, "instrument_config") is instrument_config
    assert getattr(exec_config, "venue") == POLYMARKET_CLIENT_ID
    assert getattr(exec_config, "account_type") == "CASH"
    assert getattr(exec_config, "oms_type") == "NETTING"
    assert getattr(exec_config, "starting_balances") == ["1234.0 USDC"]


def test_build_paper_live_node_registers_managed_rtds_spot_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_live_node_fakes(monkeypatch)
    settings = Settings()
    settings.runtime.nautilus.sidecar.spot_source = "polymarket_rtds"
    settings.data.polymarket.rtds_assets = ("BTC", "ETH")
    instrument_config = SimpleNamespace(load_ids=frozenset({"up-token.POLYMARKET"}))

    node = build_paper_live_node(settings, instrument_config=instrument_config)

    assert set(node.config.data_clients) == {
        POLYMARKET_CLIENT_ID,
        SPOT_DATA_CLIENT_ID,
    }
    assert node.data_client_factories[0][0] == POLYMARKET_CLIENT_ID
    assert node.data_client_factories[1][0] == SPOT_DATA_CLIENT_ID
    spot_config = node.config.data_clients[SPOT_DATA_CLIENT_ID]
    assert getattr(spot_config, "rtds_ws_url") == settings.data.polymarket.rtds_ws_url
    assert getattr(spot_config, "assets") == ("BTC", "ETH")


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

    cache = node.config.cache
    assert getattr(cache, "tick_capacity") == 100
    assert getattr(cache, "bar_capacity") == 100


def test_build_cache_config_wires_opt_in_redis_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_live_node_fakes(monkeypatch)
    settings = Settings()
    settings.runtime.nautilus.state_persistence.enabled = True
    settings.runtime.nautilus.state_persistence.password_env = "REDIS_PASSWORD"
    monkeypatch.setenv("REDIS_PASSWORD", "test-only-placeholder")

    cache = build_cache_config(settings)

    database = getattr(cache, "database")
    assert getattr(database, "type") == "redis"
    assert getattr(database, "host") == "127.0.0.1"
    assert getattr(database, "password") == "test-only-placeholder"
    assert getattr(cache, "use_instance_id") is False
    assert getattr(cache, "flush_on_start") is False
def test_build_cache_config_requires_opt_in_redis_password_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_live_node_fakes(monkeypatch)
    settings = Settings()
    settings.runtime.nautilus.state_persistence.enabled = True
    settings.runtime.nautilus.state_persistence.password_env = "MISSING_REDIS_PASSWORD"
    monkeypatch.delenv("MISSING_REDIS_PASSWORD", raising=False)

    with pytest.raises(RuntimeError, match="MISSING_REDIS_PASSWORD"):
        build_cache_config(settings)


def test_state_persistence_backend_fails_fast_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings()
    settings.runtime.nautilus.state_persistence.enabled = True

    def unavailable(*args, **kwargs):
        _ = args, kwargs
        raise OSError("connection refused")

    monkeypatch.setattr(live_node.socket, "create_connection", unavailable)

    with pytest.raises(RuntimeError, match="state persistence backend is unavailable"):
        live_node._validate_state_persistence_backend(settings)


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
    assert getattr(sandbox_config, "use_reduce_only") is True
    routing = getattr(sandbox_config, "routing")
    assert getattr(routing, "venues") == frozenset({POLYMARKET_CLIENT_ID})


def test_build_exec_engine_config_disables_unsupported_sandbox_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_live_node_fakes(monkeypatch)

    config = build_exec_engine_config()

    assert getattr(config, "reconciliation") is False
    assert getattr(config, "inflight_check_interval_ms") == 0
    assert getattr(config, "open_check_interval_secs") is None
    assert getattr(config, "position_check_interval_secs") is None
    assert getattr(config, "graceful_shutdown_on_exception") is True


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
            context=SimpleNamespace(settings=settings, telegram_bot=None),
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
