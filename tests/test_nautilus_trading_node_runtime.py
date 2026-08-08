from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from polysignal_lab.config import Settings
from polysignal_lab.nautilus_runtime import live_node
from polysignal_lab.nautilus_runtime.live_node import (
    LIVE_EXEC_CLIENT_ID,
    SANDBOX_EXEC_CLIENT_ID,
    POLYMARKET_CLIENT_ID,
    assert_no_live_polymarket_execution,
    build_exec_engine_config,
    build_live_execution_node,
    build_sandbox_live_node,
    build_polymarket_data_client_config,
    build_sandbox_exec_client_config,
)
from polysignal_lab.nautilus_runtime.node import run_nautilus_cli_async


class FakeConfig:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        for key, value in kwargs.items():
            setattr(self, key, value)


class FakePolymarketDataClientFactory:
    def __call__(self) -> object:
        return self


class FakeSandboxExecutionClientFactory:
    def __call__(self) -> object:
        return self


class FakePolymarketExecutionClientFactory:
    def __call__(self) -> object:
        return self


class FakeLiveNode:
    def __init__(self, builder: FakeLiveNodeBuilder) -> None:
        self.builder = builder
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def run(self) -> None:
        self.start()


class FakeLiveNodeBuilder:
    def __init__(self, name: str, trader_id: object, environment: object) -> None:
        self.name = name
        self.trader_id = trader_id
        self.environment = environment
        self.data_clients: list[tuple[object, object, object]] = []
        self.exec_clients: list[tuple[object, object, object]] = []
        self.kwargs: dict[str, object] = {}

    def with_cache_config(self, config: object) -> FakeLiveNodeBuilder:
        self.kwargs["cache"] = config
        return self

    def with_data_engine_config(self, config: object) -> FakeLiveNodeBuilder:
        self.kwargs["data_engine"] = config
        return self

    def with_exec_engine_config(self, config: object) -> FakeLiveNodeBuilder:
        self.kwargs["exec_engine"] = config
        return self

    def with_risk_engine_config(self, config: object) -> FakeLiveNodeBuilder:
        self.kwargs["risk_engine"] = config
        return self

    def with_load_state(self, enabled: bool) -> FakeLiveNodeBuilder:
        self.kwargs["load_state"] = enabled
        return self

    def with_save_state(self, enabled: bool) -> FakeLiveNodeBuilder:
        self.kwargs["save_state"] = enabled
        return self

    def add_data_client(
        self, name: object, factory: object, config: object
    ) -> FakeLiveNodeBuilder:
        self.data_clients.append((name, factory, config))
        return self

    def add_simulated_exec_client(
        self, name: object, factory: object, config: object
    ) -> FakeLiveNodeBuilder:
        self.exec_clients.append((name, factory, config))
        return self

    def add_exec_client(
        self, name: object, factory: object, config: object
    ) -> FakeLiveNodeBuilder:
        self.exec_clients.append((name, factory, config))
        return self

    def build(self) -> FakeLiveNode:
        return FakeLiveNode(self)


class FakeLiveNodeType:
    @staticmethod
    def builder(
        name: str, trader_id: object, environment: object
    ) -> FakeLiveNodeBuilder:
        return FakeLiveNodeBuilder(name, trader_id, environment)


def _fake_import_callable(module_name: str, attr_name: str):
    def _factory(*args: object, **kwargs: object) -> FakeConfig:
        return FakeConfig(*args, module_name=module_name, attr_name=attr_name, **kwargs)

    return _factory


def _patch_live_node_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_node, "_import_callable", _fake_import_callable)
    monkeypatch.setattr(live_node, "LiveNode", FakeLiveNodeType)
    monkeypatch.setattr(live_node, "TraderId", lambda value: f"TraderId:{value}")
    monkeypatch.setattr(
        live_node,
        "Environment",
        SimpleNamespace(SANDBOX="SANDBOX", LIVE="LIVE"),
    )
    monkeypatch.setattr(
        live_node,
        "PolymarketDataClientFactory",
        FakePolymarketDataClientFactory,
    )
    monkeypatch.setattr(
        live_node,
        "SandboxExecutionClientFactory",
        FakeSandboxExecutionClientFactory,
    )
    monkeypatch.setattr(
        live_node,
        "PolymarketExecutionClientFactory",
        FakePolymarketExecutionClientFactory,
    )
    monkeypatch.setattr(live_node, "Venue", lambda value: f"Venue:{value}")
    monkeypatch.setattr(
        live_node,
        "Money",
        lambda amount, currency: f"Money:{amount}:{currency}",
    )
    monkeypatch.setattr(live_node, "CurrencyFromStr", lambda value: f"Currency:{value}")


def test_live_node_exposes_expected_client_ids() -> None:
    assert POLYMARKET_CLIENT_ID == "POLYMARKET"
    assert SANDBOX_EXEC_CLIENT_ID == "POLYSIGNAL_PM_SANDBOX"


def test_load_live_runtime_symbols_matches_livenode_api() -> None:
    pytest.importorskip("nautilus_trader")

    from nautilus_trader.core import nautilus_pyo3 as pyo3
    from polysignal_lab.nautilus_runtime.optional_imports import (
        load_live_runtime_symbols,
    )

    symbols = load_live_runtime_symbols()

    # LiveNode 运行时存在，但 pyo3 扩展模块的 stub 未导出它。
    live_node_cls: object = getattr(pyo3, "LiveNode", None)

    assert (
        symbols.live_node is live_node_cls
        or getattr(symbols.live_node, "__name__", "") == "LiveNode"
    )
    assert symbols.trader_id is pyo3.TraderId
    assert symbols.environment is pyo3.Environment


def test_live_polymarket_execution_is_rejected() -> None:
    config = SimpleNamespace(exec_clients={POLYMARKET_CLIENT_ID: object()})

    with pytest.raises(RuntimeError, match="live Polymarket execution"):
        assert_no_live_polymarket_execution(config)


def test_build_sandbox_live_node_uses_polymarket_data_and_sandbox_exec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_live_node_fakes(monkeypatch)
    settings = Settings()
    settings.trading.starting_balance_usdc = 1234.0
    instrument_config = SimpleNamespace(load_ids=frozenset({"up-token.POLYMARKET"}))

    node = build_sandbox_live_node(
        settings, instrument_configs={"POLYMARKET-5M": instrument_config}
    )

    assert isinstance(node, FakeLiveNode)
    builder = node.builder
    assert builder.name == "PolySignal-Nautilus-001"
    assert builder.trader_id == "TraderId:PolySignal-Nautilus-001"
    assert builder.environment == "SANDBOX"
    assert builder.data_clients[0][0] == "POLYMARKET-5M"
    assert builder.exec_clients[0][0] == SANDBOX_EXEC_CLIENT_ID
    assert SANDBOX_EXEC_CLIENT_ID != builder.data_clients[0][0]
    assert getattr(builder.kwargs["exec_engine"], "reconciliation") is False
    assert builder.kwargs["load_state"] is True
    assert builder.kwargs["save_state"] is True

    data_config = builder.data_clients[0][2]
    exec_config = builder.exec_clients[0][2]
    assert getattr(data_config, "instrument_config") is instrument_config
    assert str(getattr(exec_config, "venue")).endswith(POLYMARKET_CLIENT_ID)


def test_build_sandbox_live_node_uses_official_rtds_via_polymarket_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_live_node_fakes(monkeypatch)
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "polymarket_rtds"
    instrument_config = SimpleNamespace(load_ids=frozenset({"up-token.POLYMARKET"}))

    node = build_sandbox_live_node(
        settings, instrument_configs={"POLYMARKET-5M": instrument_config}
    )

    builder = cast(FakeLiveNode, node).builder
    assert [item[0] for item in builder.data_clients] == ["POLYMARKET-5M"]
    market_config = builder.data_clients[0][2]
    assert (
        getattr(market_config, "base_url_rtds") == settings.data.polymarket.rtds_ws_url
    )


def test_build_polymarket_data_client_config_subscribes_to_future_markets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_live_node_fakes(monkeypatch)
    settings = Settings()
    instrument_config = SimpleNamespace(load_ids=frozenset({"up-token.POLYMARKET"}))

    polymarket = build_polymarket_data_client_config(
        settings, instrument_config=instrument_config
    )

    assert getattr(polymarket, "instrument_config") is instrument_config
    assert getattr(polymarket, "auto_load_missing_instruments") is True
    assert getattr(polymarket, "auto_load_debounce_ms") == 100
    assert getattr(polymarket, "auto_load_max_retries") == 12
    assert getattr(polymarket, "subscribe_new_markets") is False
    assert getattr(polymarket, "update_instruments_interval_mins") == 1


def test_build_sandbox_live_node_bounds_cache_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_live_node_fakes(monkeypatch)

    node = build_sandbox_live_node(
        Settings(),
        instrument_configs={
            "POLYMARKET-5M": SimpleNamespace(
                load_ids=frozenset({"up-token.POLYMARKET"})
            )
        },
    )

    builder = cast(FakeLiveNode, node).builder
    cache = builder.kwargs["cache"]
    assert getattr(cache, "attr_name") == "CacheConfig"


def test_build_sandbox_exec_client_config_uses_paper_venue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_live_node_fakes(monkeypatch)
    settings = Settings()
    settings.trading.starting_balance_usdc = 4321.0
    settings.runtime.nautilus.sandbox_base_currency = "USDC"

    sandbox_config = build_sandbox_exec_client_config(settings)

    assert str(getattr(sandbox_config, "venue")).endswith(POLYMARKET_CLIENT_ID)
    assert str(cast(object, getattr(sandbox_config, "account_type"))) == "CASH"
    assert str(cast(object, getattr(sandbox_config, "oms_type"))) == "NETTING"
    assert str(cast(object, getattr(sandbox_config, "book_type"))) == "L2_MBP"
    assert "4321.0" in str(getattr(sandbox_config, "starting_balances"))
    assert "USDC" in str(getattr(sandbox_config, "base_currency"))


def test_build_exec_engine_config_disables_reconciliation_for_sandbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_live_node_fakes(monkeypatch)

    config = build_exec_engine_config(reconciliation=False)

    assert getattr(config, "reconciliation") is False


def test_build_exec_engine_config_enables_reconciliation_for_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_live_node_fakes(monkeypatch)

    config = build_exec_engine_config(reconciliation=True)

    assert getattr(config, "reconciliation") is True


def test_live_execution_node_fails_closed_without_safety_unlock() -> None:
    settings = Settings.model_validate(
        {
            "runtime": {
                "nautilus": {
                    "execution_mode": "live",
                    "allow_live_polymarket_execution": True,
                }
            }
        }
    )

    with pytest.raises(RuntimeError, match="safety.allow_live_market_actions"):
        _ = build_live_execution_node(
            settings,
            instrument_configs={"POLYMARKET-5M": SimpleNamespace()},
        )


def test_live_execution_node_fails_closed_without_live_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_live_node_fakes(monkeypatch)
    settings = Settings()
    settings.runtime.nautilus.execution_mode = "live"
    settings.runtime.nautilus.allow_live_polymarket_execution = False
    settings.safety.allow_live_market_actions = True

    with pytest.raises(RuntimeError, match="allow_live_polymarket_execution"):
        _ = build_live_execution_node(
            settings,
            instrument_configs={
                "POLYMARKET-5M": SimpleNamespace(load_ids=frozenset()),
            },
        )


def test_live_execution_node_registers_official_factory_only_after_all_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_live_node_fakes(monkeypatch)
    settings = Settings.model_validate(
        {
            "safety": {"allow_live_market_actions": True},
            "runtime": {
                "nautilus": {
                    "execution_mode": "live",
                    "allow_live_polymarket_execution": True,
                }
            },
        }
    )
    credentials = {
        "POLYMARKET_API_KEY": "key",
        "POLYMARKET_API_SECRET": "secret",
        "POLYMARKET_PASSPHRASE": "passphrase",
        "POLYMARKET_PK": "private-key",
        "POLYMARKET_FUNDER": "funder",
    }
    for name, value in credentials.items():
        monkeypatch.setenv(name, value)

    node = build_live_execution_node(
        settings,
        instrument_configs={"POLYMARKET-5M": SimpleNamespace(load_ids=frozenset())},
    )

    builder = cast(FakeLiveNode, node).builder
    assert [item[0] for item in builder.exec_clients] == [LIVE_EXEC_CLIENT_ID]
    assert getattr(builder.kwargs["exec_engine"], "reconciliation") is True
    assert isinstance(builder.exec_clients[0][1], FakePolymarketExecutionClientFactory)


def test_locked_pyo3_composition_has_no_signature_fallbacks() -> None:
    source = live_node.__file__
    assert source is not None
    text = Path(source).read_text(encoding="utf-8")

    assert "except TypeError" not in text


def test_real_pyo3_execution_configs_match_locked_constructor_types() -> None:
    from nautilus_trader.core import nautilus_pyo3 as pyo3

    sandbox = build_sandbox_exec_client_config(Settings())
    assert getattr(sandbox, "oms_type") is pyo3.OmsType.NETTING
    assert getattr(sandbox, "account_type") is pyo3.AccountType.CASH
    assert getattr(sandbox, "book_type") is pyo3.BookType.L2_MBP

    live = live_node.build_polymarket_exec_client_config(Settings())
    assert 'trader_id: "PolySignal-Nautilus-001"' in str(live)
    assert 'account_id: "POLYMARKET-001"' in str(live)


def test_sandbox_book_type_uses_pyo3_enum_attribute_not_from_str() -> None:
    """Match backtest_node: getattr(BookType, name). Stubs omit BookType.from_str."""
    from nautilus_trader.core import nautilus_pyo3 as pyo3

    source = live_node.__file__
    assert source is not None
    text = Path(source).read_text(encoding="utf-8")
    assert "BookType.from_str" not in text

    settings = Settings()
    settings.runtime.nautilus.sandbox_book_type = "L1_MBP"
    sandbox = build_sandbox_exec_client_config(settings)
    assert getattr(sandbox, "book_type") is pyo3.BookType.L1_MBP


def test_build_sandbox_live_node_enables_rtds_only_on_primary_data_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_live_node_fakes(monkeypatch)
    settings = Settings()
    settings.runtime.nautilus.spot_data.source = "polymarket_rtds"
    instrument_configs = {
        "POLYMARKET-5M": SimpleNamespace(load_ids=frozenset({"up-5.POLYMARKET"})),
        "POLYMARKET-15M": SimpleNamespace(load_ids=frozenset({"up-15.POLYMARKET"})),
    }

    node = build_sandbox_live_node(settings, instrument_configs=instrument_configs)

    builder = cast(FakeLiveNode, node).builder
    by_name = {str(name): config for name, _factory, config in builder.data_clients}
    assert getattr(by_name["POLYMARKET-5M"], "base_url_rtds") == (
        settings.data.polymarket.rtds_ws_url
    )
    assert not hasattr(by_name["POLYMARKET-15M"], "base_url_rtds")


async def test_run_nautilus_cli_async_starts_and_stops_observability_writer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    settings = Settings()
    settings.storage.state_dir = str(tmp_path / "state")
    settings.logging.directory = str(tmp_path / "logs")

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

    class FakeNode:
        def run(self):
            return None

    async def fake_build(settings=None):
        _ = settings
        return SimpleNamespace(
            node=FakeNode(),
            context=SimpleNamespace(settings=settings),
            observability=FakeObservability(),
            strategy_names=(),
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


def test_build_risk_engine_config_is_fail_closed() -> None:
    from polysignal_lab.config import Settings
    from polysignal_lab.nautilus_runtime.live_node import build_risk_engine_config

    settings = Settings()
    cfg = build_risk_engine_config(settings)
    # pyo3 LiveRiskEngineConfig exposes fields via Debug, not Python attrs.
    text = str(cfg).lower()
    assert "bypass: false" in text
    assert "max_order_submit_rate" in text
