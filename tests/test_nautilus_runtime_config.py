from __future__ import annotations

import pytest
from pydantic import ValidationError

from polysignal_lab.config import Settings


def test_runtime_config_defaults_to_nautilus_and_stays_paper_safe() -> None:
    settings = Settings()

    assert settings.runtime.engine == "nautilus"
    assert settings.runtime.nautilus.allow_live_polymarket_execution is False
    assert settings.runtime.nautilus.execution_mode == "paper_sandbox"


def test_nautilus_matching_defaults_are_paper_only() -> None:
    settings = Settings()

    assert settings.runtime.nautilus.execution_mode == "paper_sandbox"
    assert settings.runtime.nautilus.paper_engine == "nautilus_matching"
    assert settings.runtime.nautilus.matching_accuracy_mode == "depth_l2"
    assert settings.runtime.nautilus.allow_live_polymarket_execution is False


def test_nautilus_rejects_unknown_matching_accuracy_mode() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "runtime": {
                    "nautilus": {
                        "matching_accuracy_mode": "legacy_local",
                    }
                }
            }
        )


def test_live_polymarket_execution_is_invalid_in_default_runtime() -> None:
    with pytest.raises(ValueError, match="live Polymarket execution"):
        Settings.model_validate(
            {
                "runtime": {
                    "engine": "nautilus",
                    "nautilus": {"allow_live_polymarket_execution": True},
                }
            }
        )


def test_production_yaml_declares_nautilus_runtime_section() -> None:
    settings = Settings.from_yaml("config/signal_bot.yaml")

    assert settings.runtime.nautilus.trader_id == "PolySignal-Nautilus-001"
    assert settings.runtime.nautilus.python == "3.12"
    assert settings.runtime.nautilus.matching_accuracy_mode == "fast_l1"
    assert settings.runtime.nautilus.sidecar.spot_source == "polymarket_rtds"


def test_health_config_defaults_are_conservative() -> None:
    settings = Settings()

    assert settings.health.startup_grace_sec == 180
    assert settings.health.liveness.heartbeat_max_age_sec == 120
    assert settings.health.restart_gate.enabled is True
    assert settings.health.restart_gate.critical_components == (
        "runtime",
        "scheduler",
        "sqlite",
    )
    assert settings.health.restart_gate.critical_down_sec == 300
    assert settings.health.restart_gate.min_consecutive_failures == 5
    assert (
        settings.health.restart_gate.docker_healthcheck_fails_on_restart_recommended
        is False
    )


def test_health_config_accepts_yaml_overrides(tmp_path) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text(
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
