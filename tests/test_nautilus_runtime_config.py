"""
Input: __future__, __future__.annotations, pathlib, pathlib.Path, pytest, pydantic, pydantic.ValidationError, polysignal_lab.config, polysignal_lab.config.Settings
Output: test_runtime_config_defaults_to_nautilus_and_stays_paper_safe, test_nautilus_book_type_defaults_are_paper_only, test_nautilus_rejects_unknown_sandbox_book_type, test_nautilus_runtime_uses_sandbox_book_type_not_matching_engine, test_removed_nautilus_matching_keys_fail_fast, test_yaml_runtime_book_type_values_are_explicit, test_live_polymarket_execution_is_invalid_in_default_runtime, test_production_yaml_declares_nautilus_runtime_section, test_health_config_defaults_are_conservative, test_health_config_accepts_yaml_overrides
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations
from pathlib import Path

import pytest
from pydantic import ValidationError

from polysignal_lab.config import Settings


def test_runtime_config_defaults_to_nautilus_and_stays_paper_safe() -> None:
    settings = Settings()

    assert settings.runtime.nautilus.allow_live_polymarket_execution is False
    assert settings.runtime.nautilus.execution_mode == "paper_sandbox"


def test_nautilus_book_type_defaults_are_paper_only() -> None:
    settings = Settings()

    assert settings.runtime.nautilus.execution_mode == "paper_sandbox"
    assert settings.runtime.nautilus.sandbox_book_type == "L2_MBP"
    assert settings.runtime.nautilus.allow_live_polymarket_execution is False


def test_nautilus_rejects_unknown_sandbox_book_type() -> None:
    with pytest.raises(ValidationError):
        _ = Settings.model_validate(
            {
                "runtime": {
                    "nautilus": {
                        "sandbox_book_type": "legacy_local",
                    }
                }
            }
        )


def test_nautilus_runtime_uses_sandbox_book_type_not_matching_engine() -> None:
    settings = Settings()

    assert settings.runtime.nautilus.execution_mode == "paper_sandbox"
    assert settings.runtime.nautilus.sandbox_book_type == "L2_MBP"
    assert not hasattr(settings.runtime.nautilus, "paper_engine")
    assert not hasattr(settings.runtime.nautilus, "matching_accuracy_mode")


def test_removed_nautilus_matching_keys_fail_fast() -> None:
    with pytest.raises(ValidationError):
        _ = Settings.model_validate(
            {
                "runtime": {
                    "nautilus": {
                        "paper_engine": "nautilus_matching",
                    }
                }
            }
        )

    with pytest.raises(ValidationError):
        _ = Settings.model_validate(
            {
                "runtime": {
                    "nautilus": {
                        "matching_accuracy_mode": "depth_l2",
                    }
                }
            }
        )


def test_yaml_runtime_book_type_values_are_explicit() -> None:
    production = Settings.from_yaml("config/signal_bot.yaml")
    lab = Settings.from_yaml("config/signal_bot.lab.yaml")

    assert production.runtime.nautilus.sandbox_book_type == "L2_MBP"
    assert lab.runtime.nautilus.sandbox_book_type == "L2_MBP"
    assert production.runtime.nautilus.sidecar.spot_source == "polymarket_rtds"
    assert lab.runtime.nautilus.sidecar.spot_source == "polymarket_rtds"


def test_live_polymarket_execution_is_invalid_in_default_runtime() -> None:
    with pytest.raises(ValueError, match="live Polymarket execution"):
        _ = Settings.model_validate(
            {
                "runtime": {
                    "nautilus": {"allow_live_polymarket_execution": True},
                }
            }
        )


def test_production_yaml_declares_nautilus_runtime_section() -> None:
    settings = Settings.from_yaml("config/signal_bot.yaml")

    assert settings.runtime.nautilus.trader_id == "PolySignal-Nautilus-001"
    assert settings.runtime.nautilus.python == "3.12"
    assert settings.runtime.nautilus.sandbox_book_type == "L2_MBP"
    assert settings.runtime.nautilus.sidecar.spot_source == "polymarket_rtds"


def test_health_config_defaults_are_conservative() -> None:
    settings = Settings()

    assert settings.health.startup_grace_sec == 180
    assert settings.health.liveness.heartbeat_max_age_sec == 120
    assert settings.health.restart_gate.enabled is True
    assert settings.health.restart_gate.critical_components == (
        "runtime",
        "sqlite",
    )
    assert settings.health.restart_gate.critical_down_sec == 300
    assert settings.health.restart_gate.min_consecutive_failures == 5
    assert (
        settings.health.restart_gate.docker_healthcheck_fails_on_restart_recommended
        is False
    )


def test_health_config_accepts_yaml_overrides(tmp_path: Path) -> None:
    path = tmp_path / "settings.yaml"
    _ = path.write_text(
        "\n".join(
            [
                "health:",
                "  startup_grace_sec: 240",
                "  liveness:",
                "    heartbeat_max_age_sec: 90",
                "  restart_gate:",
                "    enabled: true",
                "    critical_components:",
                "      - runtime",
                "      - sqlite",
                "    critical_down_sec: 600",
                "    min_consecutive_failures: 7",
                "    docker_healthcheck_fails_on_restart_recommended: true",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings.from_yaml(path)

    assert settings.health.startup_grace_sec == 240
    assert settings.health.liveness.heartbeat_max_age_sec == 90
    assert settings.health.restart_gate.critical_components == ("runtime", "sqlite")
    assert settings.health.restart_gate.critical_down_sec == 600
    assert settings.health.restart_gate.min_consecutive_failures == 7
    assert settings.health.restart_gate.docker_healthcheck_fails_on_restart_recommended is True

def test_nautilus_market_rotation_defaults_are_enabled() -> None:
    settings = Settings()

    cfg = settings.runtime.nautilus.market_rotation
    assert cfg.enabled is True
    assert cfg.interval_sec == 10
    assert cfg.include_next_periods == 1
    assert cfg.stale_grace_sec == 5
    assert cfg.unsubscribe_exited is True
    assert cfg.allow_adapter_new_market_events is False


def test_production_yaml_declares_market_rotation_section() -> None:
    settings = Settings.from_yaml("config/signal_bot.yaml")

    cfg = settings.runtime.nautilus.market_rotation
    assert cfg.enabled is True
    assert cfg.interval_sec == 10
    assert cfg.include_next_periods == 1
    assert cfg.stale_grace_sec == 5
    assert cfg.unsubscribe_exited is True
