"""Nautilus runtime package — PolySignal-owned async orchestrator.

Wires the scheduler, bridge, book data, data ingestor, observability,
and the orchestrator loop into a single NautilusRuntimeBundle.
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
