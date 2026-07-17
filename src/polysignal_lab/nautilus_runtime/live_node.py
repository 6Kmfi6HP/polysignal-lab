"""
Input: __future__, __future__.annotations, importlib, collections.abc, typing, polysignal_lab.config
Output: assert_no_live_polymarket_execution, validate_polymarket_market_data_credentials, build_sandbox_live_node, build_cache_config, build_data_engine_config, build_exec_engine_config, build_polymarket_data_client_config, build_sandbox_exec_client_config
Pos: Application code

Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from typing import cast

from nautilus_trader.core import nautilus_pyo3 as _pyo3

from polysignal_lab.config import Settings, load_settings
from polysignal_lab.nautilus_runtime.custom_data_types import SPOT_DATA_CLIENT_ID

SANDBOX_EXEC_CLIENT_ID = "POLYSIGNAL_PM_SANDBOX"
LIVE_EXEC_CLIENT_ID = "POLYMARKET"
POLYMARKET_CLIENT_ID = "POLYMARKET"
POLYMARKET_MARKET_DATA_CREDENTIALS = (
    "POLYMARKET_" + "API_KEY",
    "POLYMARKET_" + "API_SECRET",
    "POLYMARKET_" + "PASSPHRASE",
    "POLYMARKET_" + "PK",
    "POLYMARKET_" + "FUNDER",
)

LiveNode = getattr(_pyo3, "LiveNode")
TraderId = _pyo3.TraderId
Environment = _pyo3.Environment
PolymarketDataClientFactory = getattr(_pyo3, "PolymarketDataClientFactory")
SandboxExecutionClientFactory = getattr(_pyo3, "SandboxExecutionClientFactory")
PolymarketExecutionClientFactory = getattr(_pyo3, "PolymarketExecutionClientFactory")
Venue = _pyo3.Venue
Money = _pyo3.Money
CurrencyFromStr = _pyo3.Currency.from_str

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


def validate_live_execution_credentials(
    environ: Mapping[str, str] | None = None,
) -> None:
    import os

    source = os.environ if environ is None else environ
    missing = tuple(
        name
        for name in POLYMARKET_MARKET_DATA_CREDENTIALS
        if not str(source.get(name) or "").strip()
    )
    if missing:
        raise RuntimeError(
            "live Polymarket execution requires credentials: "
            + ", ".join(missing)
        )


def assert_no_live_polymarket_execution(config: object) -> None:
    exec_clients = getattr(config, "exec_clients", None)
    if exec_clients is None and isinstance(config, Mapping):
        exec_clients = config.get("exec_clients", {})
    if isinstance(exec_clients, Mapping) and POLYMARKET_CLIENT_ID in exec_clients:
        raise RuntimeError("sandbox runtime refuses live Polymarket execution")


def build_sandbox_live_node(
    settings: Settings | None = None,
    *,
    instrument_config: object,
) -> object:
    if settings is None:
        settings = load_settings()
    _validate_real_polymarket_data_factory_credentials()
    data_config = build_polymarket_data_client_config(
        settings, instrument_config=instrument_config
    )
    exec_config = build_sandbox_exec_client_config(settings)
    assert_no_live_polymarket_execution(
        {"exec_clients": {SANDBOX_EXEC_CLIENT_ID: exec_config}}
    )
    return _build_live_node(settings, data_config, exec_config)


def build_live_execution_node(
    settings: Settings | None = None,
    *,
    instrument_config: object,
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
    validate_live_execution_credentials()
    data_config = build_polymarket_data_client_config(
        settings, instrument_config=instrument_config
    )
    exec_config = build_polymarket_exec_client_config(settings)
    return _build_live_node(
        settings,
        data_config,
        exec_config,
        live=True,
    )


def build_runtime_node(
    settings: Settings | None = None,
    *,
    instrument_config: object | None = None,
) -> object:
    if settings is None:
        settings = load_settings()
    mode = settings.runtime.nautilus.execution_mode
    if mode == "sandbox":
        return build_sandbox_live_node(settings, instrument_config=instrument_config)
    if mode == "live":
        return build_live_execution_node(settings, instrument_config=instrument_config)
    raise RuntimeError("live_node.build_runtime_node requires sandbox or live mode")


def _build_live_node(
    settings: Settings,
    data_config: object,
    exec_config: object,
    *,
    live: bool = False,
) -> object:
    live_node_cls = cast(type, _required(LiveNode, "LiveNode"))
    trader_id_cls = cast(Callable[[str], object], _required(TraderId, "TraderId"))
    environment = _required(Environment, "Environment")
    trader_id_text = settings.runtime.nautilus.trader_id
    trader_id = trader_id_cls(trader_id_text)
    load_state = False
    save_state = False
    exec_engine_config = build_exec_engine_config(reconciliation=live)
    data_factory = _required(
        PolymarketDataClientFactory, "PolymarketDataClientFactory"
    )
    exec_factory = _required(
        PolymarketExecutionClientFactory if live else SandboxExecutionClientFactory,
        "PolymarketExecutionClientFactory" if live else "SandboxExecutionClientFactory",
    )
    execution_environment = getattr(environment, "LIVE" if live else "SANDBOX")
    builder = (
        live_node_cls.builder(trader_id_text, trader_id, execution_environment)
        .with_cache_config(build_cache_config(settings))
        .with_data_engine_config(build_data_engine_config())
        .with_exec_engine_config(exec_engine_config)
        .with_load_state(load_state)
        .with_save_state(save_state)
        .add_data_client(POLYMARKET_CLIENT_ID, data_factory(), data_config)
    )
    with_risk = getattr(builder, "with_risk_engine_config", None)
    if callable(with_risk):
        builder = with_risk(build_risk_engine_config(settings))
    spot_config = _build_spot_data_client_config(settings)
    if spot_config is not None:
        builder = builder.add_data_client(
            SPOT_DATA_CLIENT_ID,
            _spot_data_client_factory(),
            spot_config,
        )
    if live:
        builder = builder.add_exec_client(LIVE_EXEC_CLIENT_ID, exec_factory(), exec_config)
    else:
        builder = builder.add_simulated_exec_client(
            SANDBOX_EXEC_CLIENT_ID, exec_factory(), exec_config
        )
    return builder.build()


def build_cache_config(settings: Settings | None = None) -> object:
    cache_config = _import_callable(
        "nautilus_trader.core.nautilus_pyo3", "CacheConfig"
    )
    if settings is not None and settings.runtime.nautilus.state_persistence.enabled:
        raise RuntimeError(
            "installed pyo3 LiveNode does not expose a configurable "
            "cache backend; state persistence cannot be enabled safely"
        )
    return cache_config()


def build_data_engine_config() -> object:
    live_data_engine_config = _import_callable(
        "nautilus_trader.core.nautilus_pyo3", "LiveDataEngineConfig"
    )
    return live_data_engine_config(
        validate_data_sequence=True,
        external_clients=[SPOT_DATA_CLIENT_ID],
    )


def build_exec_engine_config(*, reconciliation: bool) -> object:
    live_exec_engine_config = _import_callable(
        "nautilus_trader.core.nautilus_pyo3", "LiveExecEngineConfig"
    )
    return live_exec_engine_config(reconciliation=reconciliation)


def build_risk_engine_config(settings: Settings) -> object:
    risk_config = _import_callable(
        "nautilus_trader.core.nautilus_pyo3", "LiveRiskEngineConfig"
    )
    configured = settings.runtime.nautilus.risk
    return risk_config(
        bypass=False,
        max_order_submit_rate=configured.max_order_submit_rate,
        max_order_modify_rate=configured.max_order_modify_rate,
        max_notional_per_order=dict(configured.max_notional_per_order),
    )


def build_polymarket_data_client_config(
    settings: Settings,
    *,
    instrument_config: object,
) -> object:
    polymarket_data_config = _import_callable(
        "nautilus_trader.core.nautilus_pyo3",
        "PolymarketDataClientConfig",
    )
    nautilus_runtime = settings.runtime.nautilus
    polymarket = settings.data.polymarket
    spot_source = str(nautilus_runtime.spot_data.source).strip().lower()
    kwargs: dict[str, object] = {
        "instrument_config": instrument_config,
        "update_instruments_interval_mins": 0,
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
    if spot_source == "polymarket_rtds":
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
        "oms_type": "NETTING",
        "account_type": "CASH",
        "book_type": settings.runtime.nautilus.sandbox_book_type,
        "bar_execution": False,
        "trade_execution": True,
        "support_gtd_orders": True,
        "support_contingent_orders": False,
        "use_reduce_only": True,
    }
    return sandbox_exec_config(**kwargs)


def build_polymarket_exec_client_config(settings: Settings) -> object:
    config_cls = _import_callable(
        "nautilus_trader.core.nautilus_pyo3", "PolymarketExecClientConfig"
    )
    account_id_cls = _import_callable(
        "nautilus_trader.core.nautilus_pyo3", "AccountId"
    )
    runtime = settings.runtime.nautilus
    import os

    kwargs = {
        "trader_id": cast(Callable[[str], object], _required(TraderId, "TraderId"))(
            runtime.trader_id
        ),
        "account_id": account_id_cls(f"{POLYMARKET_CLIENT_ID}-001"),
        "private_key": os.environ["POLYMARKET_PK"],
        "api_key": os.environ["POLYMARKET_API_KEY"],
        "api_secret": os.environ["POLYMARKET_API_SECRET"],
        "passphrase": os.environ["POLYMARKET_PASSPHRASE"],
        "funder": os.environ["POLYMARKET_FUNDER"],
    }
    return config_cls(**kwargs)


def _build_spot_data_client_config(settings: Settings) -> object | None:
    if settings.runtime.nautilus.spot_data.source != "polymarket_rtds":
        return None
    config_cls = _import_callable(
        "polysignal_lab.nautilus_runtime.spot_data_client",
        "PolymarketRtdsSpotDataClientConfig",
    )
    polymarket = settings.data.polymarket
    return config_cls(
        rtds_ws_url=polymarket.rtds_ws_url,
        assets=polymarket.rtds_assets,
    )


def _spot_data_client_factory() -> object:
    return getattr(
        importlib.import_module("polysignal_lab.nautilus_runtime.spot_data_client"),
        "PolymarketRtdsSpotDataClientFactory",
    )


def _validate_real_polymarket_data_factory_credentials() -> None:
    factory = PolymarketDataClientFactory
    module_name = getattr(factory, "__module__", "")
    if isinstance(module_name, str) and "polymarket" in module_name:
        validate_polymarket_market_data_credentials()


def _import_callable(module_name: str, attr_name: str) -> Callable[..., object]:
    """Import a config/factory callable. Tests monkeypatch this seam."""
    module = importlib.import_module(module_name)
    return cast(Callable[..., object], getattr(module, attr_name))


def _required(value: object | None, name: str) -> object:
    if value is None:
        raise RuntimeError(f"Nautilus {name} is unavailable")
    return value
