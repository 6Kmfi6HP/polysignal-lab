from __future__ import annotations

from datetime import datetime, timezone

import atexit
import logging
import sys
import threading
import traceback
from collections.abc import Callable, Sequence
from pathlib import Path
from types import TracebackType
from typing import cast

UTC = timezone.utc

logger = logging.getLogger("polysignal_lab.nautilus_runtime.node_crash")


def _dump_thread_stacks(log_path: str) -> None:
    """Write all thread stack traces to a file that survives container restart."""
    try:
        _crash_dir = Path(log_path).parent
        _crash_dir.mkdir(parents=True, exist_ok=True)
        frames = sys._current_frames()  # pyright: ignore[reportPrivateUsage]
        lines: list[str] = [
            f"=== crash dump {datetime.now(UTC).isoformat()} ===",
            f"threads={len(frames)}",
        ]
        for tid, stack in frames.items():
            lines.append(f"\n--- thread {tid} ---")
            stack_summary = cast(
                Sequence[traceback.FrameSummary], traceback.extract_stack(stack)
            )
            for frame in stack_summary:
                lines.append(f"  {frame.filename}:{frame.lineno} {frame.name}")
                if frame.line:
                    lines.append(f"    {frame.line.strip()}")
        with open(log_path, "a", encoding="utf-8") as fh:
            _ = fh.write("\n".join(lines) + "\n")
    except Exception:
        pass


def _crash_log_path(log_dir: str) -> str:
    return f"{log_dir.rstrip('/')}/crash.log"


def _append_traceback(
    crash_path: str,
    typ: type[BaseException],
    val: BaseException,
    tb: TracebackType | None,
) -> None:
    try:
        # The asyncio handler can reach here before any thread dump has
        # created the directory, and file logging may be turned off entirely.
        Path(crash_path).parent.mkdir(parents=True, exist_ok=True)
        with open(crash_path, "a", encoding="utf-8") as fh:
            traceback.print_exception(typ, val, tb, file=fh)
    except Exception:
        pass


def _thread_excepthook(crash_path: str) -> Callable[[threading.ExceptHookArgs], None]:
    """Capture crashes off the main thread, which `sys.excepthook` never sees.

    Nautilus drives Rust and asyncio work on worker threads; without this an
    exception there vanished, leaving neither a log line nor a crash dump.
    """

    def hook(args: threading.ExceptHookArgs) -> None:
        typ = args.exc_type
        val = args.exc_value
        if typ is None or val is None:
            return  # Interpreter shutdown tear-down, not a crash.
        _dump_thread_stacks(crash_path)
        _append_traceback(crash_path, typ, val, args.exc_traceback)
        logger.critical(
            "Uncaught exception in thread %s",
            getattr(args.thread, "name", "unknown"),
            exc_info=(typ, val, args.exc_traceback),
        )

    return hook


def _asyncio_exception_handler(
    crash_path: str,
) -> Callable[[object, dict[str, object]], None]:
    """Surface event-loop exceptions that never reach an awaited task."""

    def handler(_loop: object, context: dict[str, object]) -> None:
        exc = context.get("exception")
        message = str(context.get("message", "asyncio exception"))
        if isinstance(exc, BaseException):
            _append_traceback(crash_path, type(exc), exc, exc.__traceback__)
            logger.error(message, exc_info=exc)
            return
        logger.error(message)

    return handler


def _install_crash_logger(log_dir: str) -> None:
    crash_path = _crash_log_path(log_dir)

    def crash_excepthook(
        typ: type[BaseException], val: BaseException, tb: TracebackType | None
    ) -> None:
        _dump_thread_stacks(crash_path)
        _append_traceback(crash_path, typ, val, tb)
        logger.critical("Uncaught exception in main thread", exc_info=(typ, val, tb))
        sys.__excepthook__(typ, val, tb)

    sys.excepthook = crash_excepthook
    threading.excepthook = _thread_excepthook(crash_path)

    def _atexit_dump() -> None:
        _dump_thread_stacks(crash_path)
        try:
            with open(crash_path, "a", encoding="utf-8") as fh:
                _ = fh.write(f"=== atexit {datetime.now(UTC).isoformat()} ===\n")
        except Exception:
            pass

    _ = atexit.register(_atexit_dump)
