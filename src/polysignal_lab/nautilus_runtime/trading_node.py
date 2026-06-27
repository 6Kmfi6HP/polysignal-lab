from __future__ import annotations

from typing import Any

from polysignal_lab.config import Settings, load_settings

PAPER_EXEC_CLIENT_ID = "POLYSIGNAL-SANDBOX"
POLYMARKET_CLIENT_ID = "POLYMARKET"


def build_paper_trading_node_config(
    settings: Settings | None = None,
    *,
    instrument_config: Any,
) -> Any:
    """Build Nautilus TradingNodeConfig for Polymarket data plus sandbox execution."""

    if settings is None:
        settings = load_settings()
    from nautilus_trader.adapters.polymarket import PolymarketDataClientConfig
    from nautilus_trader.adapters.sandbox.config import SandboxExecutionClientConfig
    from nautilus_trader.config import LiveDataEngineConfig, LiveExecEngineConfig, LoggingConfig, TradingNodeConfig
    from nautilus_trader.model.identifiers import TraderId

    config = TradingNodeConfig(
        trader_id=TraderId("POLYSIGNAL-001"),
        logging=LoggingConfig(log_level="INFO", use_pyo3=True),
        data_engine=LiveDataEngineConfig(validate_data_sequence=True),
        exec_engine=LiveExecEngineConfig(reconciliation=False),
        data_clients={
            POLYMARKET_CLIENT_ID: PolymarketDataClientConfig(
                instrument_config=instrument_config,
            ),
        },
        exec_clients={
            PAPER_EXEC_CLIENT_ID: SandboxExecutionClientConfig(
                venue=PAPER_EXEC_CLIENT_ID,
                starting_balances=[f"{float(settings.paper_trading.starting_balance_usdc)} USDC"],
                base_currency="USDC",
                oms_type="NETTING",
                account_type="CASH",
                book_type=_book_type_for(settings.runtime.nautilus.matching_accuracy_mode),
                bar_execution=False,
                trade_execution=True,
                support_gtd_orders=True,
                support_contingent_orders=False,
                use_reduce_only=False,
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


def register_paper_factories(node: Any) -> None:
    from nautilus_trader.adapters.polymarket import PolymarketLiveDataClientFactory
    from nautilus_trader.adapters.sandbox.factory import SandboxLiveExecClientFactory

    node.add_data_client_factory(POLYMARKET_CLIENT_ID, PolymarketLiveDataClientFactory)
    node.add_exec_client_factory(PAPER_EXEC_CLIENT_ID, SandboxLiveExecClientFactory)


def assert_no_live_polymarket_execution(config: Any) -> None:
    exec_clients = dict(getattr(config, "exec_clients", {}) or {})
    if POLYMARKET_CLIENT_ID in exec_clients:
        raise RuntimeError("default paper runtime refuses live Polymarket execution")


def _book_type_for(mode: str) -> str:
    if mode == "fast_l1":
        return "L1_MBP"
    return "L2_MBP"
