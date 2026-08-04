from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path
from time import time

import pytest

from polysignal_lab.nautilus_runtime import node_crash


@pytest.fixture(autouse=True)
def _restore_hooks():
    saved_excepthook = sys.excepthook
    saved_thread_hook = threading.excepthook
    yield
    sys.excepthook = saved_excepthook
    threading.excepthook = saved_thread_hook


def _boom() -> BaseException:
    try:
        raise ValueError("boom")
    except ValueError as exc:
        return exc


def test_main_thread_crash_is_logged_and_dumped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    node_crash._install_crash_logger(str(tmp_path))
    exc = _boom()

    with caplog.at_level(logging.CRITICAL, logger=node_crash.logger.name):
        sys.excepthook(type(exc), exc, exc.__traceback__)

    assert "ValueError: boom" in (tmp_path / "crash.log").read_text(encoding="utf-8")
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)


def test_worker_thread_crash_is_captured(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """
    Nautilus runs Rust and asyncio work off the main thread. sys.excepthook
    never fires for those, so a worker dying left no trace anywhere.
    """
    node_crash._install_crash_logger(str(tmp_path))
    exc = _boom()

    with caplog.at_level(logging.CRITICAL, logger=node_crash.logger.name):
        threading.excepthook(
            threading.ExceptHookArgs(
                (type(exc), exc, exc.__traceback__, threading.current_thread())
            )
        )

    assert "ValueError: boom" in (tmp_path / "crash.log").read_text(encoding="utf-8")
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)


def test_worker_thread_hook_ignores_shutdown_noise(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """threading passes exc_type=None when a thread is torn down at exit."""
    node_crash._install_crash_logger(str(tmp_path))

    with caplog.at_level(logging.CRITICAL, logger=node_crash.logger.name):
        threading.excepthook(
            threading.ExceptHookArgs((None, None, None, threading.current_thread()))
        )

    assert caplog.records == []


def test_asyncio_handler_logs_loop_exception(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    node_crash._install_crash_logger(str(tmp_path))
    handler = node_crash._asyncio_exception_handler(str(tmp_path / "crash.log"))
    exc = _boom()

    with caplog.at_level(logging.ERROR, logger=node_crash.logger.name):
        handler(object(), {"message": "task failed", "exception": exc})

    assert any("task failed" in r.getMessage() for r in caplog.records)


def test_traceback_rotates_oversized_crash_log(tmp_path: Path) -> None:
    crash_path = tmp_path / "crash.log"
    crash_path.write_text("full", encoding="utf-8")
    exc = _boom()

    node_crash._append_traceback(
        str(crash_path), type(exc), exc, exc.__traceback__, max_bytes=1
    )

    assert "ValueError: boom" in crash_path.read_text(encoding="utf-8")
    assert len(list(tmp_path.glob("crash_*_001.log"))) == 1


def test_cleanup_old_crash_logs_supports_dry_run(tmp_path: Path) -> None:
    crash_path = tmp_path / "crash_2026-01-01_001.log"
    crash_path.write_text("old", encoding="utf-8")
    active_path = tmp_path / "crash.log"
    active_path.write_text("active", encoding="utf-8")
    old = time() - 3 * 86_400
    os.utime(crash_path, (old, old))
    os.utime(active_path, (old, old))

    assert node_crash.cleanup_old_crash_logs(tmp_path, 1, dry_run=True) == 1
    assert crash_path.exists()
    assert node_crash.cleanup_old_crash_logs(tmp_path, 1) == 1
    assert not crash_path.exists()
    assert active_path.exists()


def test_concurrent_tracebacks_are_not_lost_during_rotation(tmp_path: Path) -> None:
    crash_path = tmp_path / "crash.log"
    crash_path.write_text("full", encoding="utf-8")
    exc = _boom()
    threads = [
        threading.Thread(
            target=node_crash._append_traceback,
            args=(str(crash_path), type(exc), exc, exc.__traceback__, 1),
        )
        for _ in range(2)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    text = "".join(
        path.read_text(encoding="utf-8") for path in tmp_path.glob("crash*.log")
    )
    assert text.count("ValueError: boom") == 2
