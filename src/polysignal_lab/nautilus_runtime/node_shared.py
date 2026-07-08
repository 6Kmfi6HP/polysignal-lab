"""
Shared helpers for Nautilus runtime node files (node.py, node_sidecar.py).

Extracted from duplicate definitions to eliminate Type-2 rename clones flagged by pyscn.

Input: signal, collections.abc
Output: _rebind_market_discovery_client, _install_sync_os_signal_handlers
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import signal
from collections.abc import Callable

from polysignal_lab.nautilus_runtime.node_builder import NautilusRuntimeContext
from polysignal_lab.nautilus_runtime.node_signals import (
    _restore_os_signal_handlers,
    _SignalHandlerSnapshot,
)


def _rebind_market_discovery_client(context: NautilusRuntimeContext) -> None:
    """Replace the startup-phase HTTP client with a fresh connection for live runtime."""
    if context.market_universe is None:
        return
    discovery = getattr(context.market_universe, "discovery", None)
    if discovery is None:
        return
    replace_client = getattr(discovery, "replace_client", None)
    if callable(replace_client):
        _ = replace_client()
        return
    try:
        import httpx

        discovery.client = httpx.AsyncClient(timeout=15.0)
    except Exception:
        context.logger.warning(
            "Failed to replace startup market discovery client before live runtime handoff",
            exc_info=True,
        )


def _install_sync_os_signal_handlers(
    request_stop: Callable[[], None],
) -> Callable[[], None]:
    previous_handlers: list[_SignalHandlerSnapshot] = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        previous_handlers.append((sig, signal.getsignal(sig)))
        _ = signal.signal(sig, lambda _signum, _frame: request_stop())
    return lambda: _restore_os_signal_handlers(previous_handlers)
