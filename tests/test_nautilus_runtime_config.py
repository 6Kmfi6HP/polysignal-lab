from __future__ import annotations

import pytest

from polysignal_lab.config import Settings


def test_runtime_config_defaults_to_legacy_until_cutover() -> None:
    settings = Settings()

    assert settings.runtime.engine == "legacy"
    assert settings.runtime.nautilus.allow_live_polymarket_execution is False
    assert settings.runtime.nautilus.execution_mode == "paper_sandbox"


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
