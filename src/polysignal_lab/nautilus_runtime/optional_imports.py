from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module


@dataclass(frozen=True, slots=True)
class LiveRuntimeSymbols:
    live_node: object
    trader_id: Callable[[str], object]
    environment: object
    polymarket_data_factory: object
    sandbox_exec_factory: object
    polymarket_exec_factory: object
    venue: Callable[[str], object]
    money: Callable[..., object]
    currency_from_str: Callable[[str], object]


def _load_live_node_cls() -> object:
    return import_module("nautilus_trader.core.nautilus_pyo3").LiveNode


def load_live_runtime_symbols() -> LiveRuntimeSymbols:
    pyo3 = import_module("nautilus_trader.core.nautilus_pyo3")
    return LiveRuntimeSymbols(
        live_node=_load_live_node_cls(),
        trader_id=pyo3.TraderId,
        environment=pyo3.Environment,
        polymarket_data_factory=pyo3.PolymarketDataClientFactory,
        sandbox_exec_factory=pyo3.SandboxExecutionClientFactory,
        polymarket_exec_factory=pyo3.PolymarketExecutionClientFactory,
        venue=pyo3.Venue,
        money=pyo3.Money,
        currency_from_str=pyo3.Currency.from_str,
    )
