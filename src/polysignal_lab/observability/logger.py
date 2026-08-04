from __future__ import annotations

import gzip
import io
import json
import logging
import os
import re
import shutil
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import time

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


class GzipRotatingFileHandler(RotatingFileHandler):
    def rotate(self, source: str, dest: str) -> None:
        with open(source, "rb") as source_fh, gzip.open(dest, "wb") as target_fh:
            shutil.copyfileobj(source_fh, target_fh)
        os.remove(source)


def _gzip_size(path: Path) -> int:
    buffer = io.BytesIO()
    with path.open("rb") as source, gzip.GzipFile(
        fileobj=buffer, mode="wb", filename="", mtime=0
    ) as target:
        shutil.copyfileobj(source, target)
    return buffer.tell()


def cleanup_runtime_logs(
    runtime_log_dir: Path,
    archive_dir: Path,
    soft_limit: int,
    hard_limit: int,
    *,
    dry_run: bool = False,
) -> dict[str, object]:
    runtime_archive_dir = archive_dir / "runtime_logs"
    files = [path for path in runtime_log_dir.rglob("*") if path.is_file()]
    archive_files = (
        [path for path in runtime_archive_dir.glob("*.gz") if path.is_file()]
        if runtime_archive_dir.exists()
        else []
    )
    total_size = sum(path.stat().st_size for path in files)
    total_size += sum(path.stat().st_size for path in archive_files)
    compressed: list[str] = []
    deleted: list[str] = []
    summary: dict[str, object] = {
        "initial_size_bytes": total_size,
        "final_size_bytes": total_size,
        "compressed": compressed,
        "deleted": deleted,
    }
    if total_size <= soft_limit:
        return summary

    cutoff = time() - 86_400
    python_log = re.compile(r"polysignal_lab\.jsonl(?:\.\d+(?:\.gz)?)?$")
    old_jsonl = [
        path
        for path in files
        if path.suffix == ".jsonl"
        and path.stat().st_mtime < cutoff
        and not python_log.fullmatch(path.name)
    ]
    projected_archives: list[tuple[Path, int, float]] = []
    for path in sorted(old_jsonl, key=lambda item: item.stat().st_mtime):
        relative_name = "__".join(path.relative_to(runtime_log_dir).parts)
        destination = runtime_archive_dir / f"{relative_name}.gz"
        compressed.append(str(destination))
        source_size = path.stat().st_size
        if not dry_run:
            runtime_archive_dir.mkdir(parents=True, exist_ok=True)
            temporary_path = Path(f"{destination}.tmp")
            stat = path.stat()
            try:
                with path.open("rb") as source, gzip.open(
                    temporary_path, "wb"
                ) as target:
                    shutil.copyfileobj(source, target)
                temporary_path.replace(destination)
                os.utime(destination, (stat.st_atime, stat.st_mtime))
                path.unlink()
            finally:
                temporary_path.unlink(missing_ok=True)
            total_size += destination.stat().st_size - source_size
        else:
            compressed_size = _gzip_size(path)
            total_size += compressed_size - source_size
            projected_archives.append(
                (destination, compressed_size, path.stat().st_mtime)
            )

    archives = (
        [
            (path, path.stat().st_size, path.stat().st_mtime)
            for path in runtime_archive_dir.glob("*.gz")
        ]
        if runtime_archive_dir.exists()
        else []
    )
    if dry_run:
        archives.extend(projected_archives)
    if total_size > hard_limit:
        for path, archive_size, _mtime in sorted(
            archives, key=lambda item: item[2]
        ):
            if total_size <= hard_limit:
                break
            deleted.append(str(path))
            if not dry_run:
                path.unlink()
            total_size = max(0, total_size - archive_size)

    summary["final_size_bytes"] = total_size
    return summary


def _build_file_handler(config: LoggingConfig) -> logging.Handler | None:
    file_level = config.file_level.strip().upper()
    if file_level == "OFF":
        return None
    directory = Path(config.directory)
    directory.mkdir(parents=True, exist_ok=True)
    handler = GzipRotatingFileHandler(
        directory / "polysignal_lab.jsonl",
        maxBytes=config.file_max_bytes,
        backupCount=config.file_backup_count,
        encoding="utf-8",
    )
    handler.namer = lambda name: f"{name}.gz"
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
