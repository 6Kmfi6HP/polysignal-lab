"""
Input: __future__, __future__.annotations, importlib, collections.abc, collections.abc.Callable, collections.abc.Mapping, typing, typing.Protocol, typing.cast, polysignal_lab.config
Output: assert_no_live_polymarket_execution, build_paper_live_node, build_cache_config, build_data_engine_config, build_exec_engine_config, build_polymarket_data_client_config, build_sandbox_exec_client_config, _Builder
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from typing import Protocol, cast

from polysignal_lab.config import Settings, load_settings

PAPER_EXEC_CLIENT_ID = "POLYSIGNAL_PM_PAPER"
POLYMARKET_CLIENT_ID = "POLYMARKET"


def assert_no_live_polymarket_execution(config: object) -> None:
    exec_clients = getattr(config, "exec_clients", None)
    if exec_clients is None and isinstance(config, Mapping):
        exec_clients = config.get("exec_clients", {})
    if isinstance(exec_clients, Mapping) and POLYMARKET_CLIENT_ID in exec_clients:
        raise RuntimeError("default paper runtime refuses live Polymarket execution")


LiveNode: object | None = None
TraderId: Callable[[str], object] | None = None
Environment: object | None = None
PolymarketLiveDataClientFactory: object | None = None
SandboxLiveExecClientFactory: object | None = None


class _Builder(Protocol):
    def with_data_engine_config(self, config: object) -> "_Builder": ...
    def with_exec_engine_config(self, config: object) -> "_Builder": ...
    def with_cache_config(self, config: object) -> "_Builder": ...
    def add_data_client(self, name: str | None, factory: object, config: object) -> "_Builder": ...
    def add_exec_client(self, name: str | None, factory: object, config: object) -> "_Builder": ...
    def build(self) -> object: ...


def build_paper_live_node(
    settings: Settings | None = None,
    *,
    instrument_config: object,
) -> object:
    if settings is None:
        settings = load_settings()
    _ensure_live_imports()
    live_node = _required(LiveNode, "LiveNode")
    trader_id_cls = cast(Callable[[str], object], _required(TraderId, "TraderId"))
    environment = _required(Environment, "Environment")
    trader_id_text = settings.runtime.nautilus.trader_id
    trader_id = trader_id_cls(trader_id_text)
    builder_factory = cast(object, live_node)
    builder = cast(
        _Builder,
        getattr(builder_factory, "builder")(
            trader_id_text,
            trader_id,
            getattr(environment, "SANDBOX"),
        ),
    )
    data_config = build_polymarket_data_client_config(settings, instrument_config=instrument_config)
    exec_config = build_sandbox_exec_client_config(settings)
    assert_no_live_polymarket_execution({"exec_clients": {PAPER_EXEC_CLIENT_ID: exec_config}})
    node = (
        builder.with_cache_config(build_cache_config())
        .with_data_engine_config(build_data_engine_config())
        .with_exec_engine_config(build_exec_engine_config())
        .add_data_client(
            POLYMARKET_CLIENT_ID,
            _required(PolymarketLiveDataClientFactory, "PolymarketLiveDataClientFactory"),
            data_config,
        )
        .add_exec_client(
            PAPER_EXEC_CLIENT_ID,
            _required(SandboxLiveExecClientFactory, "SandboxLiveExecClientFactory"),
            exec_config,
        )
        .build()
    )
    return node


def build_cache_config() -> object:
    cache_config = _import_callable("nautilus_trader.config", "CacheConfig")
    return cache_config(tick_capacity=100, bar_capacity=100)


def build_data_engine_config() -> object:
    live_data_engine_config = _import_callable("nautilus_trader.config", "LiveDataEngineConfig")
    return live_data_engine_config(
        validate_data_sequence=True,
        graceful_shutdown_on_exception=True,
    )


def build_exec_engine_config() -> object:
    live_exec_engine_config = _import_callable("nautilus_trader.config", "LiveExecEngineConfig")
    return live_exec_engine_config(
        reconciliation=False,
        graceful_shutdown_on_exception=True,
    )


def build_polymarket_data_client_config(
    settings: Settings,
    *,
    instrument_config: object,
) -> object:
    polymarket_data_config = _import_callable(
        "nautilus_trader.adapters.polymarket",
        "PolymarketDataClientConfig",
    )
    nautilus_runtime = settings.runtime.nautilus
    return polymarket_data_config(
        instrument_config=instrument_config,
        ws_max_subscriptions_per_connection=nautilus_runtime.polymarket_data.ws_max_subscriptions_per_connection,
        update_instruments_interval_mins=1,
        subscribe_new_markets=nautilus_runtime.market_rotation.allow_adapter_new_market_events,
        auto_load_missing_instruments=True,
        auto_load_debounce_ms=100,
        auto_load_max_retries=12,
    )


def build_sandbox_exec_client_config(settings: Settings) -> object:
    sandbox_exec_config = _import_callable(
        "nautilus_trader.adapters.sandbox.config",
        "SandboxExecutionClientConfig",
    )
    routing_config = _import_callable("nautilus_trader.config", "RoutingConfig")
    return sandbox_exec_config(
        venue=POLYMARKET_CLIENT_ID,
        starting_balances=[f"{float(settings.paper_trading.starting_balance_usdc)} USDC"],
        base_currency="USDC",
        oms_type="NETTING",
        account_type="CASH",
        book_type=settings.runtime.nautilus.sandbox_book_type,
        bar_execution=False,
        trade_execution=True,
        support_gtd_orders=True,
        support_contingent_orders=False,
        use_reduce_only=False,
        routing=routing_config(venues=frozenset({POLYMARKET_CLIENT_ID})),
    )


def _ensure_live_imports() -> None:
    global LiveNode, TraderId, Environment, PolymarketLiveDataClientFactory, SandboxLiveExecClientFactory
    if LiveNode is not None:
        return
    live_mod = importlib.import_module("nautilus_trader.live")
    common_mod = importlib.import_module("nautilus_trader.common")
    identifiers_mod = importlib.import_module("nautilus_trader.model.identifiers")
    polymarket_mod = importlib.import_module("nautilus_trader.adapters.polymarket")
    sandbox_factory_mod = importlib.import_module("nautilus_trader.adapters.sandbox.factory")
    LiveNode = getattr(live_mod, "LiveNode")
    Environment = getattr(common_mod, "Environment")
    TraderId = cast(Callable[[str], object], getattr(identifiers_mod, "TraderId"))
    PolymarketLiveDataClientFactory = getattr(polymarket_mod, "PolymarketLiveDataClientFactory")
    SandboxLiveExecClientFactory = getattr(sandbox_factory_mod, "SandboxLiveExecClientFactory")


def _import_callable(module_name: str, attr_name: str) -> Callable[..., object]:
    module = importlib.import_module(module_name)
    return cast(Callable[..., object], getattr(module, attr_name))


def _required(value: object | None, name: str) -> object:
    if value is None:
        raise RuntimeError(f"Nautilus {name} is unavailable")
    return value
