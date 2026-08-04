from __future__ import annotations

import gzip
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from time import time

import pytest

from polysignal_lab.config import LoggingConfig
from polysignal_lab.observability.logger import (
    RedactingFormatter,
    RedactingJsonFormatter,
    cleanup_runtime_logs,
    configure_logging,
)


@pytest.fixture(autouse=True)
def _restore_root_logger():
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield
    for handler in root.handlers:
        handler.close()
    root.handlers = saved_handlers
    root.setLevel(saved_level)


def _log_file(directory: Path) -> Path:
    files = sorted(directory.glob("*.jsonl"))
    assert len(files) == 1, f"expected one log file, got {files}"
    return files[0]


def _records(directory: Path) -> list[dict[str, object]]:
    text = _log_file(directory).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_file_handler_writes_one_json_object_per_line(tmp_path: Path) -> None:
    """
    User symptom: a container failure could not be investigated because the
    only application log was unstructured text on stdout, inside Docker's
    rotation window. Logs must land on disk as machine-queryable JSONL.
    """
    configure_logging("INFO", LoggingConfig(directory=str(tmp_path)))

    logging.getLogger("polysignal_lab.probe").warning("market feed stalled")

    records = _records(tmp_path)
    assert len(records) == 1
    assert {k: v for k, v in records[0].items() if k != "timestamp"} == {
        "level": "WARNING",
        "component": "polysignal_lab.probe",
        "message": "market feed stalled",
    }
    # ISO-8601 with offset, so `jq` can sort a whole directory by time.
    assert datetime.strptime(str(records[0]["timestamp"]), "%Y-%m-%dT%H:%M:%S%z")


def test_file_handler_redacts_secrets(tmp_path: Path) -> None:
    configure_logging("INFO", LoggingConfig(directory=str(tmp_path)))

    logging.getLogger("polysignal_lab.probe").error(
        "auth failed token=8badf00d-supersecret-value-goes-here"
    )

    message = _records(tmp_path)[0]["message"]
    assert "supersecret" not in str(message)
    assert "token=***" in str(message)


@pytest.mark.parametrize(
    "token",
    ["x", "123:short", "1234567890:abcdefghijklmnopqrstuvwxyz_ABC-123"],
)
def test_telegram_url_token_is_redacted_from_text_and_json(token: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    record = logging.LogRecord(
        "httpx",
        logging.ERROR,
        __file__,
        1,
        "request failed: %s",
        (url,),
        None,
    )

    text = RedactingFormatter("%(message)s").format(record)
    payload = json.loads(RedactingJsonFormatter().format(record))

    assert f"/bot{token}/" not in text
    assert f"/bot{token}/" not in str(payload)
    assert "/bot***/sendMessage" in text


def test_telegram_url_token_is_redacted_from_exception() -> None:
    token = "arbitrary-length-token:with_symbols-123"
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    formatter = RedactingJsonFormatter()

    try:
        raise RuntimeError(f"HTTP request failed for {url}")
    except RuntimeError:
        record = logging.LogRecord(
            "httpcore",
            logging.ERROR,
            __file__,
            1,
            "transport error",
            (),
            exc_info=__import__("sys").exc_info(),
        )

    payload = json.loads(formatter.format(record))
    assert token not in str(payload)
    assert "/bot***/getUpdates" in str(payload)


def test_http_client_loggers_default_to_warning(tmp_path: Path) -> None:
    configure_logging("DEBUG", LoggingConfig(directory=str(tmp_path)))

    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


def test_file_handler_records_tracebacks(tmp_path: Path) -> None:
    configure_logging("INFO", LoggingConfig(directory=str(tmp_path)))

    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("polysignal_lab.probe").exception("strategy crashed")

    record = _records(tmp_path)[0]
    assert "ValueError: boom" in str(record["exception"])


def test_file_handler_records_redacted_market_detail(tmp_path: Path) -> None:
    configure_logging("INFO", LoggingConfig(directory=str(tmp_path)))

    logging.getLogger("polysignal_lab.probe").info(
        "market_untraditable",
        extra={
            "market_detail": {
                "condition": "btc-5m",
                "missing_sides": ["UP"],
                "credential": "token=8badf00d-supersecret-value-goes-here",
            }
        },
    )

    record = _records(tmp_path)[0]
    assert record["market_detail"] == {
        "condition": "btc-5m",
        "missing_sides": ["UP"],
        "credential": "token=***",
    }


def test_file_level_off_disables_file_output(tmp_path: Path) -> None:
    configure_logging("INFO", LoggingConfig(directory=str(tmp_path), file_level="OFF"))

    logging.getLogger("polysignal_lab.probe").error("no file please")

    assert list(tmp_path.glob("*.jsonl")) == []


def test_file_level_is_independent_of_stdout_level(tmp_path: Path) -> None:
    """DEBUG detail can be kept on disk while stdout stays quiet."""
    configure_logging(
        "WARNING", LoggingConfig(directory=str(tmp_path), file_level="DEBUG")
    )

    logging.getLogger("polysignal_lab.probe").debug("subscription detail")

    assert [r["message"] for r in _records(tmp_path)] == ["subscription detail"]


def test_stdout_stays_human_readable(tmp_path: Path, capsys) -> None:
    """`docker logs` remains the live human view; only the file is JSON."""
    configure_logging("INFO", LoggingConfig(directory=str(tmp_path)))

    logging.getLogger("polysignal_lab.probe").info("runtime ready")

    stderr = capsys.readouterr().err
    assert "INFO polysignal_lab.probe runtime ready" in stderr
    assert not stderr.lstrip().startswith("{")


def test_configure_logging_without_config_writes_no_file(tmp_path: Path) -> None:
    """Callers that only want stdout (dashboard, smoke) keep the old behaviour."""
    configure_logging("INFO")

    logging.getLogger("polysignal_lab.probe").info("stdout only")

    assert list(tmp_path.glob("*.jsonl")) == []


def test_rotated_python_logs_are_gzipped(tmp_path: Path) -> None:
    configure_logging(
        "INFO",
        LoggingConfig(directory=str(tmp_path), file_max_bytes=20, file_backup_count=2),
    )

    logging.getLogger("polysignal_lab.probe").info("first record")
    logging.getLogger("polysignal_lab.probe").info("second record")

    rotated = tmp_path / "polysignal_lab.jsonl.1.gz"
    assert rotated.exists()
    with gzip.open(rotated, "rt", encoding="utf-8") as fh:
        assert "first record" in fh.read()


def test_runtime_log_cleanup_archives_only_inactive_old_jsonl(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    active = runtime_dir / "polysignal_lab.jsonl"
    active.write_text("active", encoding="utf-8")
    inactive = runtime_dir / "nautilus-2026-08-01.jsonl"
    inactive.write_text("old runtime log", encoding="utf-8")
    old = time() - 2 * 86_400
    os.utime(inactive, (old, old))

    summary = cleanup_runtime_logs(
        runtime_dir,
        tmp_path / "archive",
        soft_limit=1,
        hard_limit=1_000_000,
    )

    assert active.exists()
    assert not inactive.exists()
    compressed = summary["compressed"]
    assert isinstance(compressed, list)
    assert len(compressed) == 1
    assert list((tmp_path / "archive" / "runtime_logs").glob("*.gz"))


def test_runtime_log_cleanup_evicts_rotated_gzip_at_hard_limit(
    tmp_path: Path,
) -> None:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    active = runtime_dir / "polysignal_lab.jsonl"
    active.write_bytes(b"active")
    rotated = runtime_dir / "polysignal_lab.jsonl.1.gz"
    rotated.write_bytes(b"rotated-log")
    old = time() - 2 * 86_400
    os.utime(rotated, (old, old))

    summary = cleanup_runtime_logs(
        runtime_dir,
        tmp_path / "archive",
        soft_limit=1,
        hard_limit=active.stat().st_size,
    )

    assert not rotated.exists()
    assert active.exists()
    assert summary["deleted"] == [str(rotated)]
