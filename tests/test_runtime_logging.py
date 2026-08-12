from __future__ import annotations

import logging

import pytest

from polysignal_lab.config import AppConfig, LoggingConfig, Settings
from polysignal_lab.nautilus_runtime import runtime_logging
from polysignal_lab.nautilus_runtime.runtime_logging import _nautilus_logging_kwargs


def _settings(**logging_kwargs: object) -> Settings:
    return Settings(
        app=AppConfig(log_level="INFO"),
        logging=LoggingConfig(**logging_kwargs),  # pyright: ignore[reportArgumentType]
    )


def test_file_output_is_json_with_rotation() -> None:
    """
    User symptom: six days of runtime left under two days of logs, because
    stdout in Docker's 30MB window was the only sink. Nautilus must write
    rotating JSON files of its own.
    """
    kwargs = _nautilus_logging_kwargs(
        _settings(directory="logs/runtime", file_max_bytes=1024, file_backup_count=3)
    )

    assert kwargs["directory"] == "logs/runtime"
    assert kwargs["file_format"] == "JSON"
    assert kwargs["file_rotate"] == (1024, 3)


def test_noisy_component_is_filtered_by_default() -> None:
    """data_actor emitted 70% of all lines; it must not be at stdout level."""
    kwargs = _nautilus_logging_kwargs(_settings())

    assert kwargs["component_levels"] == {"nautilus_common::actor::data_actor": "WARN"}


def test_colors_are_off_by_default() -> None:
    """ANSI escapes in a TTY-less container only obstruct grep and agents."""
    assert _nautilus_logging_kwargs(_settings())["is_colored"] is False


def test_file_level_off_disables_all_file_arguments() -> None:
    kwargs = _nautilus_logging_kwargs(_settings(file_level="OFF"))

    assert kwargs["level_file"] is None
    assert kwargs["directory"] is None
    assert kwargs["file_format"] is None


def test_stdout_and_file_levels_are_independent() -> None:
    settings = _settings(file_level="DEBUG")
    settings.app.log_level = "WARNING"

    kwargs = _nautilus_logging_kwargs(settings)

    assert kwargs["level_stdout"] == "WARNING"
    assert kwargs["level_file"] == "DEBUG"


def test_levels_are_accepted_by_nautilus() -> None:
    """The mapped level strings must parse as real Nautilus log levels."""
    _ = pytest.importorskip("nautilus_trader")
    from nautilus_trader.core.nautilus_pyo3 import LogLevel

    kwargs = _nautilus_logging_kwargs(_settings(file_level="DEBUG"))

    # from_str exists at runtime but is absent from the shipped pyo3 stub.
    from_str = LogLevel.from_str  # pyright: ignore[reportAttributeAccessIssue]

    assert from_str(str(kwargs["level_stdout"])) == LogLevel.INFO
    assert from_str(str(kwargs["level_file"])) == LogLevel.DEBUG


def test_already_initialized_logging_does_not_stop_the_runtime(
    tmp_path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """
    Nautilus raises ValueError when a second logging system tries to take
    over. Observability setup must degrade to a warning, never take the
    trading runtime down at startup.
    """

    class _AlreadyInitialized:
        LogLevel = type("LogLevel", (), {"from_str": staticmethod(lambda _s: object())})
        TraderId = staticmethod(lambda _s: object())
        UUID4 = staticmethod(lambda: object())

        @staticmethod
        def init_logging(**_kwargs: object) -> object:
            raise ValueError(
                "attempted to set a logger after the logging system "
                "was already initialized"
            )

    monkeypatch.setattr(
        runtime_logging, "load_nautilus_module", lambda _name: _AlreadyInitialized
    )
    settings = _settings(directory=str(tmp_path))

    with caplog.at_level(logging.WARNING, logger=runtime_logging.logger.name):
        guard = runtime_logging._init_nautilus_logging(settings)

    assert guard is None
    assert any("already initialized" in r.getMessage() for r in caplog.records)
