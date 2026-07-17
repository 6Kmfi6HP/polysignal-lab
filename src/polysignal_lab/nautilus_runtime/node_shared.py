"""
Shared helpers for Nautilus runtime node files (node.py, node_lifecycle.py).

Extracted from duplicate definitions to eliminate Type-2 rename clones flagged by pyscn.

Input: signal, collections.abc
Output: _rebind_market_discovery_client, _install_sync_os_signal_handlers
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import signal
from collections.abc import Callable

from polysignal_lab.nautilus_runtime.node_signals import (
    _restore_os_signal_handlers,
    _SignalHandlerSnapshot,
)


def _install_sync_os_signal_handlers(
    request_stop: Callable[[], None],
) -> Callable[[], None]:
    previous_handlers: list[_SignalHandlerSnapshot] = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        previous_handlers.append((sig, signal.getsignal(sig)))
        _ = signal.signal(sig, lambda _signum, _frame: request_stop())
    return lambda: _restore_os_signal_handlers(previous_handlers)
