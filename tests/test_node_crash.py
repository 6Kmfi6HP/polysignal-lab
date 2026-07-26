from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

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
