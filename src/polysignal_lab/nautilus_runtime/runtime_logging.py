from __future__ import annotations

import logging
from pathlib import Path

from polysignal_lab.config import Settings
from polysignal_lab.nautilus_runtime.optional_imports import load_nautilus_module
from polysignal_lab.observability.logger import configure_logging

logger = logging.getLogger("polysignal_lab.nautilus_runtime.runtime_logging")

# init_logging returns a guard that owns the logging thread; dropping it stops
# file output, so the runtime holds it for the life of the process.
_log_guard: object | None = None


def _nautilus_logging_kwargs(settings: Settings) -> dict[str, object]:
    """Map Settings onto `nautilus_pyo3.init_logging` keyword arguments.

    Kept separate from the call so the mapping can be asserted without
    initializing process-global logging state.
    """
    config = settings.logging
    file_level = config.file_level.strip().upper()
    return {
        "level_stdout": settings.app.log_level.strip().upper(),
        "level_file": None if file_level == "OFF" else file_level,
        "component_levels": dict(config.component_levels) or None,
        "directory": None if file_level == "OFF" else str(Path(config.directory)),
        "file_format": None if file_level == "OFF" else "JSON",
        "file_rotate": (config.file_max_bytes, config.file_backup_count),
        "is_colored": config.colors,
    }


def _init_nautilus_logging(settings: Settings) -> object | None:
    """Route the Nautilus Rust logger to rotating JSON files.

    Called before the node is built, so this configuration wins over the file-less
    default LiveNode would otherwise install. Nautilus refuses to re-point an
    already-initialized logging system, so whoever got there first keeps the
    sinks and this returns None — observability setup must never stop the
    runtime from trading.
    """
    pyo3 = load_nautilus_module("nautilus_trader.core.nautilus_pyo3")
    kwargs = _nautilus_logging_kwargs(settings)
    directory = kwargs["directory"]
    if isinstance(directory, str):
        Path(directory).mkdir(parents=True, exist_ok=True)
    level_file = kwargs["level_file"]
    try:
        return pyo3.init_logging(
            trader_id=pyo3.TraderId(settings.runtime.nautilus.trader_id),
            instance_id=pyo3.UUID4(),
            level_stdout=pyo3.LogLevel.from_str(kwargs["level_stdout"]),
            level_file=None
            if level_file is None
            else pyo3.LogLevel.from_str(level_file),
            component_levels=kwargs["component_levels"],
            directory=directory,
            file_format=kwargs["file_format"],
            file_rotate=kwargs["file_rotate"],
            is_colored=kwargs["is_colored"],
        )
    except (ValueError, RuntimeError):
        logger.warning(
            "Nautilus logging was already initialized; keeping the existing "
            "sinks. Nautilus output will not reach %s.",
            directory,
            exc_info=True,
        )
        return None


def configure_runtime_logging(settings: Settings) -> None:
    """Configure Python and Nautilus logging for the LiveNode runtime.

    Both write rotating JSONL into `logging.directory`, which outlives Docker's
    stdout rotation and is what a postmortem actually reads.
    """
    global _log_guard
    configure_logging(settings.app.log_level, settings.logging)
    _log_guard = _init_nautilus_logging(settings)
