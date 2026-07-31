from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from polysignal_lab.config import LoggingConfig
from polysignal_lab.utils import redact_text


def _redact_json_value(value: object) -> object:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {str(key): _redact_json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_redact_json_value(item) for item in value]
    return value


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))


class RedactingJsonFormatter(logging.Formatter):
    """One JSON object per line, so `jq` and agents can query the log directly.

    Values are redacted before serialization, never after: the redaction
    pattern is greedy up to whitespace and would swallow the closing `"}` of a
    serialized record, emitting unparseable JSON.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "component": record.name,
            "message": redact_text(record.getMessage()),
        }
        if record.exc_info:
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        readiness_detail = getattr(record, "readiness_detail", None)
        if isinstance(readiness_detail, dict):
            payload["readiness_detail"] = _redact_json_value(readiness_detail)
        market_detail = getattr(record, "market_detail", None)
        if isinstance(market_detail, dict):
            payload["market_detail"] = _redact_json_value(market_detail)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _build_file_handler(config: LoggingConfig) -> logging.Handler | None:
    file_level = config.file_level.strip().upper()
    if file_level == "OFF":
        return None
    directory = Path(config.directory)
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        directory / "polysignal_lab.jsonl",
        maxBytes=config.file_max_bytes,
        backupCount=config.file_backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(RedactingJsonFormatter())
    handler.setLevel(getattr(logging, file_level, logging.INFO))
    return handler


def configure_logging(level: str = "INFO", config: LoggingConfig | None = None) -> None:
    """Send human-readable text to stdout and, when configured, JSONL to disk.

    Docker's rotation is the only thing holding stdout, so file output is what
    survives long enough to investigate a failure after the fact.
    """
    stdout_handler = logging.StreamHandler()
    stdout_handler.setFormatter(
        RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    stdout_level = getattr(logging, level.upper(), logging.INFO)
    stdout_handler.setLevel(stdout_level)

    handlers: list[logging.Handler] = [stdout_handler]
    file_handler = None if config is None else _build_file_handler(config)
    if file_handler is not None:
        handlers.append(file_handler)

    root = logging.getLogger()
    root.handlers.clear()
    for handler in handlers:
        root.addHandler(handler)
    # The root threshold must clear the most verbose handler, which is the file
    # when it runs at DEBUG while stdout stays at INFO.
    root.setLevel(min(handler.level for handler in handlers))
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
