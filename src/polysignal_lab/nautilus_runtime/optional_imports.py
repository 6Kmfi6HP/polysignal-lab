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
    pyo3 = load_nautilus_module("nautilus_trader.core.nautilus_pyo3")
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


def load_nautilus_module(module_path: str) -> object:
    """Single import surface for any NautilusTrader module.

    Every runtime/data/promotion module that previously did a direct
    ``from nautilus_trader.<path> import ...`` now resolves the module object
    through this entrypoint and binds attributes off it. ``import_module``
    returns the same module object a ``from`` import binds, so attribute
    identity (class objects used as bases, ``isinstance`` targets, enum
    members) is preserved exactly — this is a pure import migration with no
    runtime semantic change.

    Callers are responsible for only invoking this when Nautilus is available
    (i.e. the module is already importable in the running process). It is not
    used at ``polysignal_lab`` package import time, so the package stays
    importable without Nautilus installed.
    """
    return import_module(module_path)
