from __future__ import annotations

from datetime import datetime, timezone

import atexit
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path
from types import TracebackType
from typing import cast

UTC = timezone.utc


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


def _install_crash_logger(log_dir: str) -> None:
    crash_path = f"{log_dir.rstrip('/')}/crash.log"

    def crash_excepthook(
        typ: type[BaseException], val: BaseException, tb: TracebackType | None
    ) -> None:
        _dump_thread_stacks(crash_path)
        try:
            with open(crash_path, "a", encoding="utf-8") as fh:
                traceback.print_exception(typ, val, tb, file=fh)
        except Exception:
            pass
        sys.__excepthook__(typ, val, tb)

    sys.excepthook = crash_excepthook

    def _atexit_dump() -> None:
        _dump_thread_stacks(crash_path)
        try:
            with open(crash_path, "a", encoding="utf-8") as fh:
                _ = fh.write(f"=== atexit {datetime.now(UTC).isoformat()} ===\n")
        except Exception:
            pass

    _ = atexit.register(_atexit_dump)
