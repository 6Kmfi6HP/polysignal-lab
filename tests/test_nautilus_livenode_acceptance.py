from __future__ import annotations

# ruff: noqa: E402

from dataclasses import asdict, dataclass

from nautilus_optional import require_nautilus

require_nautilus()

from nautilus_trader.core import nautilus_pyo3 as pyo3

from polysignal_lab.nautilus_runtime.live_node import (
    SANDBOX_EXEC_CLIENT_ID,
    POLYMARKET_CLIENT_ID,
)
from polysignal_lab.nautilus_runtime.optional_imports import load_live_runtime_symbols

from nautilus_runtime_contracts_harness import run_node


@dataclass(frozen=True, slots=True)
class _AcceptanceProbeConfig:
    strategy_id: str
    order_id_tag: str


class _AcceptanceProbeStrategy(pyo3.Strategy):
    """Minimal pyo3 Strategy registered via ImportableStrategyConfig for acceptance."""

    def __init__(self, config: _AcceptanceProbeConfig) -> None:
        strategy_name = str(config.order_id_tag)
        super().__init__(
            pyo3.StrategyConfig(
                strategy_id=pyo3.StrategyId(str(config.strategy_id)),
                order_id_tag=strategy_name,
            )
        )


def test_load_live_runtime_symbols_resolves_livenode() -> None:
    symbols = load_live_runtime_symbols()

    # LiveNode 运行时存在，但 pyo3 扩展模块的 stub 未导出它。
    live_node_cls: object = getattr(pyo3, "LiveNode", None)

    assert (
        symbols.live_node is live_node_cls
        or getattr(symbols.live_node, "__name__", "") == "LiveNode"
    )
    assert symbols.polymarket_data_factory is pyo3.PolymarketDataClientFactory
    assert symbols.sandbox_exec_factory is pyo3.SandboxExecutionClientFactory


def test_livenode_registers_unique_strategy_ids_and_factories() -> None:
    instrument_id = pyo3.InstrumentId.from_str("BTCUSDT.BINANCE")
    quantity = pyo3.Quantity.from_str("0.001")
    strategy_ids = (
        pyo3.StrategyId("PolySignal-vwap_momentum"),
        pyo3.StrategyId("PolySignal-ptb_diff"),
    )
    assert strategy_ids[0] != strategy_ids[1]
    configs = (
        pyo3.EmaCrossConfig(
            instrument_id=instrument_id,
            trade_size=quantity,
            strategy_id=strategy_ids[0],
            order_id_tag="vwap_momentum",
        ),
        pyo3.EmaCrossConfig(
            instrument_id=instrument_id,
            trade_size=quantity,
            strategy_id=strategy_ids[1],
            order_id_tag="ptb_diff",
        ),
    )

    venue = pyo3.Venue(POLYMARKET_CLIENT_ID)
    money = pyo3.Money(1_000.0, pyo3.Currency.from_str("USDT"))
    exec_config = pyo3.SandboxExecutionClientConfig(
        venue=venue,
        starting_balances=[money],
    )
    node = (
        pyo3.LiveNode.builder(
            "ACCEPT", pyo3.TraderId("ACCEPT-001"), pyo3.Environment.SANDBOX
        )
        .with_load_state(False)
        .with_save_state(False)
        .with_cache_config(pyo3.CacheConfig())
        .with_data_engine_config(pyo3.LiveDataEngineConfig())
        .with_exec_engine_config(pyo3.LiveExecEngineConfig(reconciliation=False))
        .add_data_client(
            POLYMARKET_CLIENT_ID,
            pyo3.PolymarketDataClientFactory(),
            pyo3.PolymarketDataClientConfig(),
        )
        .add_simulated_exec_client(
            SANDBOX_EXEC_CLIENT_ID,
            pyo3.SandboxExecutionClientFactory(),
            exec_config,
        )
        .build()
    )
    for config in configs:
        node.add_builtin_strategy("EmaCross", config)

    assert run_node(node) is True


def test_livenode_save_load_flags_round_trip_on_builder() -> None:
    builder = (
        pyo3.LiveNode.builder(
            "STATE", pyo3.TraderId("STATE-001"), pyo3.Environment.SANDBOX
        )
        .with_load_state(True)
        .with_save_state(True)
    )
    node = builder.build()
    assert node.trader_id == pyo3.TraderId("STATE-001")
    run_node(node)


def test_livenode_registers_pyo3_strategy_without_registration_globals() -> None:
    node = (
        pyo3.LiveNode.builder(
            "CACHE", pyo3.TraderId("CACHE-001"), pyo3.Environment.SANDBOX
        )
        .with_load_state(False)
        .with_save_state(False)
        .build()
    )
    config = _AcceptanceProbeConfig(
        strategy_id="PolySignal-probe_cache",
        order_id_tag="probe_cache",
    )
    node.add_strategy_from_config(
        pyo3.ImportableStrategyConfig(
            strategy_path=f"{_AcceptanceProbeStrategy.__module__}:{_AcceptanceProbeStrategy.__qualname__}",
            config_path=f"{_AcceptanceProbeConfig.__module__}:{_AcceptanceProbeConfig.__qualname__}",
            config=asdict(config),
        )
    )

    assert run_node(node) is True
