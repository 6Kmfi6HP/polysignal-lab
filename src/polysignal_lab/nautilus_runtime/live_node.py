"""
Input: __future__, __future__.annotations, importlib, collections.abc, collections.abc.Callable, collections.abc.Mapping, typing, typing.Protocol, typing.cast, polysignal_lab.config
Output: assert_no_live_polymarket_execution, validate_polymarket_market_data_credentials, build_paper_live_node, build_cache_config, build_data_engine_config, build_exec_engine_config, build_polymarket_data_client_config, build_sandbox_exec_client_config
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import importlib
import socket
import sys
from collections.abc import Callable, Mapping
from typing import cast

from polysignal_lab.config import Settings, load_settings
from polysignal_lab.nautilus_runtime.custom_data_types import (
    SIDECAR_DATA_CLIENT_ID,
    SPOT_DATA_CLIENT_ID,
)
from polysignal_lab.nautilus_runtime.optional_imports import load_live_runtime_symbols

PAPER_EXEC_CLIENT_ID = "POLYSIGNAL_PM_PAPER"
POLYMARKET_CLIENT_ID = "POLYMARKET"
POLYMARKET_MARKET_DATA_CREDENTIALS = (
    "POLYMARKET_" + "API_KEY",
    "POLYMARKET_" + "API_SECRET",
    "POLYMARKET_" + "PASSPHRASE",
    "POLYMARKET_" + "PK",
    "POLYMARKET_" + "FUNDER",
)


def validate_polymarket_market_data_credentials(
    environ: Mapping[str, str] | None = None,
) -> None:
    """Fail before Nautilus builds its credentialed Polymarket data client."""
    import os

    source = os.environ if environ is None else environ
    missing = tuple(
        name
        for name in POLYMARKET_MARKET_DATA_CREDENTIALS
        if not str(source.get(name) or "").strip()
    )
    if missing:
        names = ", ".join(missing)
        raise RuntimeError(
            "Nautilus Polymarket market-data adapter requires credentials: "
            f"{names}"
        )


def assert_no_live_polymarket_execution(config: object) -> None:
    exec_clients = getattr(config, "exec_clients", None)
    if exec_clients is None and isinstance(config, Mapping):
        exec_clients = config.get("exec_clients", {})
    if isinstance(exec_clients, Mapping) and POLYMARKET_CLIENT_ID in exec_clients:
        raise RuntimeError("default paper runtime refuses live Polymarket execution")


def _validate_state_persistence_backend(settings: Settings) -> None:
    persistence = settings.runtime.nautilus.state_persistence
    if not persistence.enabled:
        return
    try:
        with socket.create_connection(
            (persistence.host, persistence.port),
            timeout=1.0,
        ):
            return
    except OSError as exc:
        raise RuntimeError(
            "Nautilus state persistence backend is unavailable: "
            f"{persistence.host}:{persistence.port}"
        ) from exc


# Lazy placeholders. Tests monkeypatch these module globals (and
# live_node._import_callable) so unit tests never import real Nautilus clients.
# Do not replace with import-time static nautilus_trader imports.
TradingNode: object | None = None
TradingNodeConfig: object | None = None
TraderId: Callable[[str], object] | None = None
Environment: object | None = None
PolymarketLiveDataClientFactory: object | None = None
SandboxLiveExecClientFactory: object | None = None


def build_paper_live_node(
    settings: Settings | None = None,
    *,
    instrument_config: object,
) -> object:
    if settings is None:
        settings = load_settings()
    _ensure_live_imports()
    _validate_state_persistence_backend(settings)
    _validate_real_polymarket_data_factory_credentials()
    trading_node_cls = cast(Callable[..., object], _required(TradingNode, "TradingNode"))
    trading_node_config_cls = cast(
        Callable[..., object],
        _required(TradingNodeConfig, "TradingNodeConfig"),
    )
    trader_id_cls = cast(Callable[[str], object], _required(TraderId, "TraderId"))
    environment = _required(Environment, "Environment")
    trader_id_text = settings.runtime.nautilus.trader_id
    trader_id = trader_id_cls(trader_id_text)
    data_config = build_polymarket_data_client_config(settings, instrument_config=instrument_config)
    data_clients, spot_source = _build_data_clients(settings, data_config)
    exec_config = build_sandbox_exec_client_config(settings)
    assert_no_live_polymarket_execution({"exec_clients": {PAPER_EXEC_CLIENT_ID: exec_config}})
    node_config = trading_node_config_cls(
        environment=getattr(environment, "SANDBOX"),
        trader_id=trader_id,
        cache=build_cache_config(settings),
        data_engine=build_data_engine_config(),
        exec_engine=build_exec_engine_config(),
        data_clients=data_clients,
        exec_clients={PAPER_EXEC_CLIENT_ID: exec_config},
        load_state=settings.runtime.nautilus.state_persistence.enabled,
        save_state=settings.runtime.nautilus.state_persistence.enabled,
    )
    node = trading_node_cls(config=node_config)
    _register_live_node_factories(node, spot_source)
    return node


def _register_live_node_factories(node: object, spot_source: str) -> None:
    add_data_factory = cast(
        Callable[[str, object], None], getattr(node, "add_data_client_factory")
    )
    add_exec_factory = cast(
        Callable[[str, object], None], getattr(node, "add_exec_client_factory")
    )
    add_data_factory(
        POLYMARKET_CLIENT_ID,
        _required(PolymarketLiveDataClientFactory, "PolymarketLiveDataClientFactory"),
    )
    if spot_source == "polymarket_rtds":
        add_data_factory(
            SPOT_DATA_CLIENT_ID,
            _import_callable(
                "polysignal_lab.nautilus_runtime.spot_data_client",
                "PolymarketRtdsSpotDataClientFactory",
            ),
        )
    add_exec_factory(
        PAPER_EXEC_CLIENT_ID,
        _required(SandboxLiveExecClientFactory, "SandboxLiveExecClientFactory"),
    )


def _build_data_clients(
    settings: Settings,
    data_config: object,
) -> tuple[dict[str, object], str]:
    spot_source = str(settings.runtime.nautilus.sidecar.spot_source).strip().lower()
    if spot_source not in {"disabled", "polymarket_rtds"}:
        raise RuntimeError(
            f"unsupported native spot source: {spot_source!r}; "
            "expected 'disabled' or 'polymarket_rtds'"
        )
    data_clients: dict[str, object] = {POLYMARKET_CLIENT_ID: data_config}
    if spot_source == "polymarket_rtds":
        data_clients[SPOT_DATA_CLIENT_ID] = build_polymarket_rtds_spot_data_client_config(
            settings
        )
    return data_clients, spot_source


def build_cache_config(settings: Settings | None = None) -> object:
    cache_config = _import_callable("nautilus_trader.config", "CacheConfig")
    if settings is None or not settings.runtime.nautilus.state_persistence.enabled:
        return cache_config(tick_capacity=100, bar_capacity=100)
    persistence = settings.runtime.nautilus.state_persistence
    database_config = _import_callable("nautilus_trader.config", "DatabaseConfig")
    username = _persistence_secret(persistence.username_env)
    password = _persistence_secret(persistence.password_env)
    database = database_config(
        type="redis",
        host=persistence.host,
        port=persistence.port,
        username=username,
        password=password,
        ssl=persistence.ssl,
    )
    return cache_config(
        tick_capacity=100,
        bar_capacity=100,
        database=database,
        use_trader_prefix=True,
        use_instance_id=False,
        flush_on_start=False,
    )


def _persistence_secret(env_name: str | None) -> str | None:
    if not env_name:
        return None
    import os

    value = os.environ.get(env_name)
    if value is None:
        raise RuntimeError(
            f"native state persistence requires credential environment variable {env_name!r}"
        )
    return value


def build_polymarket_rtds_spot_data_client_config(settings: Settings) -> object:
    spot_config = _import_callable(
        "polysignal_lab.nautilus_runtime.spot_data_client",
        "PolymarketRtdsSpotDataClientConfig",
    )
    polymarket = settings.data.polymarket
    return spot_config(
        rtds_ws_url=polymarket.rtds_ws_url,
        assets=tuple(polymarket.rtds_assets),
    )


def build_data_engine_config() -> object:
    from nautilus_trader.model.identifiers import ClientId

    live_data_engine_config = _import_callable("nautilus_trader.config", "LiveDataEngineConfig")
    return live_data_engine_config(
        validate_data_sequence=True,
        graceful_shutdown_on_exception=True,
        external_clients=[ClientId(SIDECAR_DATA_CLIENT_ID)],
    )


def build_exec_engine_config() -> object:
    live_exec_engine_config = _import_callable("nautilus_trader.config", "LiveExecEngineConfig")
    return live_exec_engine_config(
        reconciliation=False,
        inflight_check_interval_ms=0,
        open_check_interval_secs=None,
        position_check_interval_secs=None,
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
        update_instruments_interval_mins=0,
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
    sandbox_base_currency = settings.runtime.nautilus.sandbox_base_currency
    return sandbox_exec_config(
        venue=POLYMARKET_CLIENT_ID,
        starting_balances=[
            f"{float(settings.paper_trading.starting_balance_usdc)} {sandbox_base_currency}"
        ],
        base_currency=sandbox_base_currency,
        oms_type="NETTING",
        account_type="CASH",
        book_type=settings.runtime.nautilus.sandbox_book_type,
        bar_execution=False,
        trade_execution=True,
        support_gtd_orders=True,
        support_contingent_orders=False,
        use_reduce_only=True,
        routing=routing_config(venues=frozenset({POLYMARKET_CLIENT_ID})),
    )


def _validate_real_polymarket_data_factory_credentials() -> None:
    factory = PolymarketLiveDataClientFactory
    module_name = getattr(factory, "__module__", "")
    if isinstance(module_name, str) and module_name.startswith(
        "nautilus_trader.adapters.polymarket"
    ):
        validate_polymarket_market_data_credentials()


def _sync_live_module_globals(mod: object) -> None:
    global TradingNodeConfig, TraderId, Environment
    global PolymarketLiveDataClientFactory, SandboxLiveExecClientFactory

    TradingNodeConfig = getattr(mod, "TradingNodeConfig", TradingNodeConfig)
    TraderId = cast(Callable[[str], object] | None, getattr(mod, "TraderId", TraderId))
    Environment = getattr(mod, "Environment", Environment)
    PolymarketLiveDataClientFactory = getattr(
        mod,
        "PolymarketLiveDataClientFactory",
        PolymarketLiveDataClientFactory,
    )
    SandboxLiveExecClientFactory = getattr(
        mod,
        "SandboxLiveExecClientFactory",
        SandboxLiveExecClientFactory,
    )


def _install_live_runtime_symbols(symbols: object, mod: object | None) -> None:
    global TradingNode, TradingNodeConfig, TraderId, Environment
    global PolymarketLiveDataClientFactory, SandboxLiveExecClientFactory

    TradingNode = getattr(symbols, "trading_node")
    TradingNodeConfig = getattr(symbols, "trading_node_config")
    TraderId = cast(Callable[[str], object], getattr(symbols, "trader_id"))
    Environment = getattr(symbols, "environment")
    PolymarketLiveDataClientFactory = getattr(symbols, "polymarket_data_factory")
    SandboxLiveExecClientFactory = getattr(symbols, "sandbox_exec_factory")
    if mod is not None:
        mod.TradingNode = TradingNode
        mod.TradingNodeConfig = TradingNodeConfig
        mod.TraderId = TraderId
        mod.Environment = Environment
        mod.PolymarketLiveDataClientFactory = PolymarketLiveDataClientFactory
        mod.SandboxLiveExecClientFactory = SandboxLiveExecClientFactory


def _ensure_live_imports() -> None:
    """Lazy-import Nautilus TradingNode symbols into module globals."""
    global TradingNode

    mod = sys.modules.get(__name__)
    current_trading_node = getattr(mod, "TradingNode", None) if mod is not None else TradingNode
    if current_trading_node is not None:
        TradingNode = current_trading_node
        if mod is not None:
            _sync_live_module_globals(mod)
        return

    _install_live_runtime_symbols(load_live_runtime_symbols(), mod)


def _import_callable(module_name: str, attr_name: str) -> Callable[..., object]:
    """Import a config/factory callable. Tests monkeypatch this seam."""
    module = importlib.import_module(module_name)
    return cast(Callable[..., object], getattr(module, attr_name))


def _required(value: object | None, name: str) -> object:
    if value is None:
        raise RuntimeError(f"Nautilus {name} is unavailable")
    return value
