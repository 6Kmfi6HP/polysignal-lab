from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from typing import Protocol, cast

from polysignal_lab.config import Settings, load_settings

PAPER_EXEC_CLIENT_ID = "POLYSIGNAL_PM_PAPER"
POLYMARKET_CLIENT_ID = "POLYMARKET"


class _FactoryNode(Protocol):
    def add_data_client_factory(self, name: str, factory: object) -> None: ...
    def add_exec_client_factory(self, name: str, factory: object) -> None: ...


def build_paper_trading_node_config(
    settings: Settings | None = None,
    *,
    instrument_config: object,
) -> object:
    """Build Nautilus TradingNodeConfig for Polymarket data plus sandbox execution."""

    if settings is None:
        settings = load_settings()

    cache_config = _import_callable("nautilus_trader.config", "CacheConfig")
    polymarket_data_config = _import_callable(
        "nautilus_trader.adapters.polymarket",
        "PolymarketDataClientConfig",
    )
    sandbox_exec_config = _import_callable(
        "nautilus_trader.adapters.sandbox.config",
        "SandboxExecutionClientConfig",
    )
    live_data_engine_config = _import_callable("nautilus_trader.config", "LiveDataEngineConfig")
    live_exec_engine_config = _import_callable("nautilus_trader.config", "LiveExecEngineConfig")
    logging_config = _import_callable("nautilus_trader.config", "LoggingConfig")
    trading_node_config = _import_callable("nautilus_trader.config", "TradingNodeConfig")
    routing_config = _import_callable("nautilus_trader.config", "RoutingConfig")
    trader_id = _import_callable("nautilus_trader.model.identifiers", "TraderId")

    nautilus_runtime = settings.runtime.nautilus
    config = trading_node_config(
        trader_id=trader_id("POLYSIGNAL-001"),
        logging=logging_config(log_level="INFO", use_pyo3=True),
        # Default tick_capacity=10_000 retains up to 10k quote + 10k trade
        # ticks per instrument, and market rotation subscribes ~128 new
        # instruments/hour that the cache never evicts — unbounded RSS growth
        # over hours. Strategies read cache-backed market data projections
        # instead of project-owned book/trade mirrors, so a small capacity is sufficient.
        cache=cache_config(tick_capacity=100, bar_capacity=100),
        data_engine=live_data_engine_config(
            validate_data_sequence=True,
            graceful_shutdown_on_exception=True,
        ),
        exec_engine=live_exec_engine_config(
            reconciliation=False,
            graceful_shutdown_on_exception=True,
        ),
        data_clients={
            POLYMARKET_CLIENT_ID: polymarket_data_config(
                instrument_config=instrument_config,
                ws_max_subscriptions_per_connection=nautilus_runtime.polymarket_data.ws_max_subscriptions_per_connection,
                update_instruments_interval_mins=1,
                subscribe_new_markets=nautilus_runtime.market_rotation.allow_adapter_new_market_events,
                auto_load_missing_instruments=True,
                auto_load_debounce_ms=100,
                auto_load_max_retries=12,
            ),
        },
        exec_clients={
            PAPER_EXEC_CLIENT_ID: sandbox_exec_config(
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
            ),
        },
        timeout_connection=20.0,
        timeout_reconciliation=5.0,
        timeout_portfolio=5.0,
        timeout_disconnection=5.0,
        timeout_post_stop=2.0,
    )
    assert_no_live_polymarket_execution(config)
    return config


def register_paper_factories(node: _FactoryNode) -> None:
    polymarket_factory = _import_attr(
        "nautilus_trader.adapters.polymarket",
        "PolymarketLiveDataClientFactory",
    )
    sandbox_factory = _import_attr(
        "nautilus_trader.adapters.sandbox.factory",
        "SandboxLiveExecClientFactory",
    )

    node.add_data_client_factory(POLYMARKET_CLIENT_ID, polymarket_factory)
    node.add_exec_client_factory(PAPER_EXEC_CLIENT_ID, sandbox_factory)


def assert_no_live_polymarket_execution(config: object) -> None:
    exec_clients = getattr(config, "exec_clients", {})
    if isinstance(exec_clients, Mapping) and POLYMARKET_CLIENT_ID in exec_clients:
        raise RuntimeError("default paper runtime refuses live Polymarket execution")




def _import_callable(module_name: str, attr_name: str) -> Callable[..., object]:
    return cast(Callable[..., object], _import_attr(module_name, attr_name))


def _import_attr(module_name: str, attr_name: str) -> object:
    module = importlib.import_module(module_name)
    return cast(object, getattr(module, attr_name))
