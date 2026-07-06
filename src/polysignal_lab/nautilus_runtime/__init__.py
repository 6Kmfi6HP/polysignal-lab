"""Nautilus runtime package.

Provides lazy optional-dependency entry points for LiveNode-owned runtime wiring,
PolySignal strategy/custom-data components, cache projections, and reporting.
"""

from polysignal_lab.nautilus_runtime.node import (
    NautilusRuntimeBundle,
    build_nautilus_runtime,
    build_trading_node,
    run_nautilus_cli,
    run_nautilus_cli_async,
)

__all__ = [
    "NautilusRuntimeBundle",
    "build_nautilus_runtime",
    "build_trading_node",
    "run_nautilus_cli",
    "run_nautilus_cli_async",
]
