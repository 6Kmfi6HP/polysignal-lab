from __future__ import annotations

import asyncio
import signal
import threading
from collections.abc import Callable, Sequence
from contextlib import suppress


_SignalHandler = signal.Handlers | int | Callable[..., object] | None
_SignalHandlerSnapshot = tuple[signal.Signals, _SignalHandler]


_stop_requested = threading.Event()


def _reset_process_stop_request() -> None:
    _stop_requested.clear()


def request_process_stop() -> bool:
    """Ask the process owner to stop LiveNode without crossing PyO3 threads.

    PyO3 LiveNode is unsendable: watchdog and worker threads must not call
    node.stop() directly. The official PyO3 run() installs a SIGINT/SIGTERM
    handler that consumes a stop intent on the owner thread/event loop, so this
    helper is the process-level boundary.

    Returns True when this call newly requested stop. Subsequent calls while
    the request is pending do not raise again, avoiding recursive signal
    handlers when intercept_os_signals is enabled.
    """
    if _stop_requested.is_set():
        return False
    _stop_requested.set()
    _raise_stop_signal()
    return True


def _raise_stop_signal() -> None:
    signal.raise_signal(signal.SIGINT)


def _consume_process_stop_request() -> bool:
    return _stop_requested.is_set()


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


def _install_sync_os_signal_handlers(
    _request_stop: Callable[[], None],
) -> Callable[[], None]:
    previous_handlers: list[_SignalHandlerSnapshot] = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        previous_handlers.append((sig, signal.getsignal(sig)))
        _ = signal.signal(sig, lambda _signum, _frame: request_process_stop())
    return lambda: _restore_os_signal_handlers(previous_handlers)


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
            _ = signal.signal(sig, lambda _signum, _frame: request_process_stop())
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
