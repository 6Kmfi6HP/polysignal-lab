"""
Input: __future__, __future__.annotations, asyncio, signal, collections.abc, collections.abc.Callable, collections.abc.Sequence, contextlib, contextlib.suppress
Output: None
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""









from __future__ import annotations

import asyncio
import signal
from collections.abc import Callable, Sequence
from contextlib import suppress


_SignalHandler = signal.Handlers | int | Callable[..., object] | None
_SignalHandlerSnapshot = tuple[signal.Signals, _SignalHandler]


def _runtime_intercepts_os_signals(settings: object | None) -> bool:
    runtime_settings = getattr(settings, "runtime", None)
    nautilus_settings = getattr(runtime_settings, "nautilus", None)
    return bool(getattr(nautilus_settings, "intercept_os_signals", False))


def _restore_os_signal_handlers(
    previous_handlers: Sequence[_SignalHandlerSnapshot],
) -> None:
    for sig, previous in reversed(previous_handlers):
        with suppress(ValueError, OSError, RuntimeError):
            _ = signal.signal(sig, previous)


def _install_async_os_signal_handlers(
    loop: asyncio.AbstractEventLoop,
    request_stop: Callable[[], None],
) -> Callable[[], None]:
    loop_handlers: list[_SignalHandlerSnapshot] = []
    sync_handlers: list[_SignalHandlerSnapshot] = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        previous = signal.getsignal(sig)
        try:
            loop.add_signal_handler(sig, request_stop)
        except (NotImplementedError, RuntimeError):
            _ = signal.signal(sig, lambda _signum, _frame: request_stop())
            sync_handlers.append((sig, previous))
        else:
            loop_handlers.append((sig, previous))

    def cleanup() -> None:
        for sig, previous in reversed(loop_handlers):
            with suppress(NotImplementedError, RuntimeError):
                _ = loop.remove_signal_handler(sig)
            _restore_os_signal_handlers(((sig, previous),))
        _restore_os_signal_handlers(sync_handlers)

    return cleanup
