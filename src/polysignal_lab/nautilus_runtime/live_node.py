from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import cast

from polysignal_lab.config import Settings, load_settings
from polysignal_lab.nautilus_runtime.optional_imports import (
    load_live_runtime_symbols,
    load_nautilus_module,
)
from polysignal_lab.nautilus_runtime.polymarket_clients import (
    polymarket_rtds_data_client_name,
)

_pyo3 = load_nautilus_module("nautilus_trader.core.nautilus_pyo3")
AccountType = _pyo3.AccountType
BookType = _pyo3.BookType
OmsType = _pyo3.OmsType

SANDBOX_EXEC_CLIENT_ID = "POLYSIGNAL_PM_SANDBOX"
LIVE_EXEC_CLIENT_ID = "POLYMARKET"
POLYMARKET_CLIENT_ID = "POLYMARKET"

_symbols = load_live_runtime_symbols()
LiveNode = _symbols.live_node
TraderId = _symbols.trader_id
Environment = _symbols.environment
PolymarketDataClientFactory = _symbols.polymarket_data_factory
SandboxExecutionClientFactory = _symbols.sandbox_exec_factory
PolymarketExecutionClientFactory = _symbols.polymarket_exec_factory
Venue = _symbols.venue
Money = _symbols.money
CurrencyFromStr = _symbols.currency_from_str


def assert_no_live_polymarket_execution(config: object) -> None:
    exec_clients = getattr(config, "exec_clients", None)
    if exec_clients is None and isinstance(config, Mapping):
        exec_clients = config.get("exec_clients", {})
    if isinstance(exec_clients, Mapping) and POLYMARKET_CLIENT_ID in exec_clients:
        raise RuntimeError("sandbox runtime refuses live Polymarket execution")


def build_sandbox_live_node(
    settings: Settings | None = None,
    *,
    instrument_configs: Mapping[str, object],
) -> object:
    if settings is None:
        settings = load_settings()
    data_configs = _build_polymarket_data_configs(settings, instrument_configs)
    exec_config = build_sandbox_exec_client_config(settings)
    assert_no_live_polymarket_execution(
        {"exec_clients": {SANDBOX_EXEC_CLIENT_ID: exec_config}}
    )
    return _build_live_node(settings, data_configs, exec_config)


def build_live_execution_node(
    settings: Settings | None = None,
    *,
    instrument_configs: Mapping[str, object],
) -> object:
    if settings is None:
        settings = load_settings()
    runtime = settings.runtime.nautilus
    if runtime.execution_mode != "live":
        raise RuntimeError("live execution node requires execution_mode='live'")
    if not runtime.allow_live_polymarket_execution:
        raise RuntimeError("live execution requires allow_live_polymarket_execution")
    if not settings.safety.allow_live_market_actions:
        raise RuntimeError("live execution requires safety.allow_live_market_actions")
    data_configs = _build_polymarket_data_configs(settings, instrument_configs)
    exec_config = build_polymarket_exec_client_config(settings)
    return _build_live_node(
        settings,
        data_configs,
        exec_config,
        live=True,
    )


def build_runtime_node(
    settings: Settings | None = None,
    *,
    instrument_configs: Mapping[str, object] | None = None,
) -> object:
    if settings is None:
        settings = load_settings()
    if instrument_configs is None or not instrument_configs:
        raise RuntimeError("Polymarket instrument configs are required")
    mode = settings.runtime.nautilus.execution_mode
    if mode == "sandbox":
        return build_sandbox_live_node(
            settings,
            instrument_configs=instrument_configs,
        )
    if mode == "live":
        return build_live_execution_node(
            settings,
            instrument_configs=instrument_configs,
        )
    raise RuntimeError("live_node.build_runtime_node requires sandbox or live mode")


def _client_factories(
    *, live: bool
) -> tuple[Callable[[], object], Callable[[], object]]:
    """Resolve the pyo3 data/exec client factories, which optional_imports types as `object`.

    Both are factory classes constructed with no arguments.
    """
    data_factory = cast(
        Callable[[], object],
        _required(PolymarketDataClientFactory, "PolymarketDataClientFactory"),
    )
    exec_factory = cast(
        Callable[[], object],
        _required(
            PolymarketExecutionClientFactory if live else SandboxExecutionClientFactory,
            "PolymarketExecutionClientFactory"
            if live
            else "SandboxExecutionClientFactory",
        ),
    )
    return data_factory, exec_factory


def _build_live_node(
    settings: Settings,
    data_configs: Mapping[str, object],
    exec_config: object,
    *,
    live: bool = False,
) -> object:
    live_node_cls = cast(type, _required(LiveNode, "LiveNode"))
    trader_id_cls = cast(Callable[[str], object], _required(TraderId, "TraderId"))
    environment = _required(Environment, "Environment")
    trader_id_text = settings.runtime.nautilus.trader_id
    trader_id = trader_id_cls(trader_id_text)
    exec_engine_config = build_exec_engine_config(reconciliation=live)
    data_factory_cls, exec_factory = _client_factories(live=live)
    execution_environment = getattr(environment, "LIVE" if live else "SANDBOX")
    builder = (
        live_node_cls.builder(trader_id_text, trader_id, execution_environment)
        .with_cache_config(build_cache_config())
        .with_data_engine_config(build_data_engine_config())
        .with_exec_engine_config(exec_engine_config)
        .with_load_state(True)
        .with_save_state(True)
    )
    for client_name, data_config in data_configs.items():
        builder = builder.add_data_client(  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
            client_name,
            data_factory_cls(),
            data_config,
        )
    with_risk = getattr(builder, "with_risk_engine_config", None)
    if not callable(with_risk):
        raise RuntimeError(
            "LiveNode builder missing with_risk_engine_config; refuse fail-open start"
        )
    builder = with_risk(build_risk_engine_config(settings))
    if live:
        builder = builder.add_exec_client(
            LIVE_EXEC_CLIENT_ID, exec_factory(), exec_config
        )
    else:
        builder = builder.add_simulated_exec_client(
            SANDBOX_EXEC_CLIENT_ID, exec_factory(), exec_config
        )
    return builder.build()


def build_cache_config() -> object:
    cache_config = _import_callable("nautilus_trader.core.nautilus_pyo3", "CacheConfig")
    return cache_config()


def build_data_engine_config() -> object:
    live_data_engine_config = _import_callable(
        "nautilus_trader.core.nautilus_pyo3", "LiveDataEngineConfig"
    )
    return live_data_engine_config(validate_data_sequence=True)


def build_exec_engine_config(*, reconciliation: bool) -> object:
    live_exec_engine_config = _import_callable(
        "nautilus_trader.core.nautilus_pyo3", "LiveExecEngineConfig"
    )
    return live_exec_engine_config(reconciliation=reconciliation)


def build_risk_engine_config(settings: Settings) -> object:
    """Fail-closed RiskEngine config: bypass is always False."""
    risk_config = _import_callable(
        "nautilus_trader.core.nautilus_pyo3", "LiveRiskEngineConfig"
    )
    configured = settings.runtime.nautilus.risk
    max_submit = getattr(configured, "max_order_submit_rate", None)
    max_modify = getattr(configured, "max_order_modify_rate", None)
    if max_submit is None or max_modify is None:
        raise RuntimeError("risk max_order_submit_rate/max_order_modify_rate required")
    return risk_config(
        bypass=False,
        max_order_submit_rate=max_submit,
        max_order_modify_rate=max_modify,
        max_notional_per_order=dict(configured.max_notional_per_order),
    )


def _build_polymarket_data_configs(
    settings: Settings,
    instrument_configs: Mapping[str, object],
) -> dict[str, object]:
    spot_source = str(settings.runtime.nautilus.spot_data.source).strip().lower()
    rtds_client_name = (
        polymarket_rtds_data_client_name(settings.markets.timeframes)
        if spot_source == "polymarket_rtds"
        else None
    )
    return {
        client_name: build_polymarket_data_client_config(
            settings,
            instrument_config=instrument_config,
            enable_rtds=client_name == rtds_client_name,
        )
        for client_name, instrument_config in instrument_configs.items()
    }


def build_polymarket_data_client_config(
    settings: Settings,
    *,
    instrument_config: object,
    enable_rtds: bool = False,
) -> object:
    polymarket_data_config = _import_callable(
        "nautilus_trader.core.nautilus_pyo3",
        "PolymarketDataClientConfig",
    )
    nautilus_runtime = settings.runtime.nautilus
    polymarket = settings.data.polymarket
    kwargs: dict[str, object] = {
        "instrument_config": instrument_config,
        # 2.0.0rc3 defaults to SOCKUDO, but Polymarket's WS endpoint rejects
        # its subscription payload (code=1008 "invalid subscription payload"),
        # causing a 10-second reconnect loop.  TUNGSTENITE (the only option in
        # 1.x) produces a payload the server accepts.
        "transport_backend": _pyo3.TransportBackend.TUNGSTENITE,  # pyright: ignore[reportAttributeAccessIssue]
        # Locked pyo3 constructor takes a u64 minutes value (int only); keep a
        # 1-minute provider refresh budget for the adapter instrument cache.
        "update_instruments_interval_mins": 1,
        # The locked pyo3 constructor does not expose new_market_filter;
        # keep adapter-wide events disabled rather than cache every Polymarket market.
        "subscribe_new_markets": False,
        "auto_load_missing_instruments": True,
        "auto_load_debounce_ms": 100,
        "auto_load_max_retries": 12,
        "resolve_poll_enabled": True,
        "resolve_poll_interval_secs": 30,
        "resolve_poll_grace_secs": 10,
        "resolve_poll_max_wait_secs": 1800,
    }
    ws_max = nautilus_runtime.polymarket_data.ws_max_subscriptions_per_connection
    kwargs["ws_max_subscriptions"] = ws_max
    if enable_rtds:
        kwargs["base_url_rtds"] = polymarket.rtds_ws_url
    return polymarket_data_config(**kwargs)


def build_sandbox_exec_client_config(settings: Settings) -> object:
    sandbox_exec_config = _import_callable(
        "nautilus_trader.core.nautilus_pyo3",
        "SandboxExecutionClientConfig",
    )
    venue_cls = cast(Callable[[str], object], _required(Venue, "Venue"))
    money_cls = cast(Callable[..., object], _required(Money, "Money"))
    currency_from_str = cast(
        Callable[[str], object], _required(CurrencyFromStr, "Currency.from_str")
    )
    sandbox_base_currency = settings.runtime.nautilus.sandbox_base_currency
    balance = money_cls(
        float(settings.trading.starting_balance_usdc),
        currency_from_str(sandbox_base_currency),
    )
    kwargs: dict[str, object] = {
        "venue": venue_cls(POLYMARKET_CLIENT_ID),
        "starting_balances": [balance],
        "base_currency": currency_from_str(sandbox_base_currency),
        "oms_type": OmsType.NETTING,
        "account_type": AccountType.CASH,
        "book_type": getattr(BookType, settings.runtime.nautilus.sandbox_book_type),
        "bar_execution": False,
        "trade_execution": True,
        "support_gtd_orders": True,
        "support_contingent_orders": False,
        "use_reduce_only": True,
    }
    return sandbox_exec_config(**kwargs)


def build_polymarket_exec_client_config(settings: Settings) -> object:
    """Build live exec config without injecting secrets — adapter Rust resolves credentials."""
    config_cls = _import_callable(
        "nautilus_trader.core.nautilus_pyo3", "PolymarketExecClientConfig"
    )
    runtime = settings.runtime.nautilus
    kwargs = {
        # Locked pyo3 PolymarketExecClientConfig expects plain strings.
        "trader_id": runtime.trader_id,
        "account_id": f"{POLYMARKET_CLIENT_ID}-001",
        # Credential fields intentionally unset; Polymarket adapter resolves from env.
    }
    return config_cls(**kwargs)


def _import_callable(module_name: str, attr_name: str) -> Callable[..., object]:
    """Import a config/factory callable. Tests monkeypatch this seam.

    Resolves through ``load_nautilus_module`` so legacy 1.x module paths
    (``nautilus_trader.core.nautilus_pyo3``) keep working on the 2.0 wheel.
    """
    module = load_nautilus_module(module_name)
    return cast(Callable[..., object], getattr(module, attr_name))


def _required(value: object | None, name: str) -> object:
    if value is None:
        raise RuntimeError(f"Nautilus {name} is unavailable")
    return value
