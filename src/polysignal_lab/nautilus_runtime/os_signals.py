from __future__ import annotations

import asyncio
import os
import signal
import threading
import time
from collections.abc import Callable, Sequence
from contextlib import suppress


_SignalHandler = signal.Handlers | int | Callable[..., object] | None
_SignalHandlerSnapshot = tuple[signal.Signals, _SignalHandler]


_stop_requested = threading.Event()
# RLock, not Lock: the main thread can legally re-enter request_process_stop()
# from its own SIGINT handler (intercept_os_signals) while a watchdog thread
# holds the lock; a plain Lock would deadlock on that re-entry.
_stop_lock = threading.RLock()

# Grace period between the SIGINT stop intent and the SIGKILL fallback. A
# healthy process exits in a second or two; only a wedged owner thread
# survives this long, so the timer only ever fires in the stuck case.
_HARD_STOP_DELAY_SEC = 20.0


def _reset_process_stop_request() -> None:
    _stop_requested.clear()


def request_process_stop() -> bool:
    """Ask the process owner to stop LiveNode without crossing PyO3 threads.

    PyO3 LiveNode is unsendable: watchdog and worker threads must not call
    node.stop() directly. The official PyO3 run() installs a SIGINT/SIGTERM
    handler that consumes a stop intent on the owner thread/event loop, so this
    helper is the process-level boundary.

    Returns True when this call newly requested stop. The check-then-set is
    guarded by a lock so concurrent callers (watchdog thread + the main thread's
    own SIGINT handler when intercept_os_signals is enabled) cannot both raise
    the stop signal.
    """
    with _stop_lock:
        if _stop_requested.is_set():
            return False
        _stop_requested.set()
    _raise_stop_signal()
    _arm_hard_stop_fallback()
    return True


def _raise_stop_signal() -> None:
    signal.raise_signal(signal.SIGINT)


def _arm_hard_stop_fallback() -> None:
    """Escape hatch when the owner thread never returns to the interpreter.

    PyO3's run() consumes the SIGINT stop intent only while the owner thread
    re-enters Python to run the pending handler. When the WS layer spins on
    reconnects with no data arriving at all, that re-entry never happens, the
    intent stays pending forever and the supervised restart silently fails —
    the container is stuck unhealthy. SIGKILL after a bounded delay is then
    the only deterministic path; a healthy process exits well before the
    timer expires. Daemon so it cannot outlive the process it kills.
    """
    def _escalate() -> None:
        time.sleep(_HARD_STOP_DELAY_SEC)
        with suppress(Exception):
            os.kill(os.getpid(), signal.SIGKILL)

    _ = threading.Thread(
        target=_escalate,
        name="process-stop-escalator",
        daemon=True,
    ).start()


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
