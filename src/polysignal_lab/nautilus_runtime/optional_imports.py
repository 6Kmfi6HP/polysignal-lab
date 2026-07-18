"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Callable, dataclasses, dataclasses.dataclass, importlib, importlib.import_module
Output: load_live_runtime_symbols, LiveRuntimeSymbols
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""


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


def load_live_runtime_symbols() -> LiveRuntimeSymbols:
    """Single load surface for pyo3 LiveNode + factory symbols used by live_node."""
    pyo3 = import_module("nautilus_trader.core.nautilus_pyo3")
    return LiveRuntimeSymbols(
        live_node=pyo3.LiveNode,
        trader_id=pyo3.TraderId,
        environment=pyo3.Environment,
        polymarket_data_factory=pyo3.PolymarketDataClientFactory,
        sandbox_exec_factory=pyo3.SandboxExecutionClientFactory,
        polymarket_exec_factory=pyo3.PolymarketExecutionClientFactory,
        venue=pyo3.Venue,
        money=pyo3.Money,
        currency_from_str=pyo3.Currency.from_str,
    )
