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
    assert settings.runtime.nautilus.sidecar.spot_source == "polymarket_rtds"
