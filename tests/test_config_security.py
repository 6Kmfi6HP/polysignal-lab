"""
Input: __future__, __future__.annotations, pytest, pydantic, pydantic.ValidationError, polysignal_lab.config, polysignal_lab.config.Settings, polysignal_lab.config.SecurityConfigError
Output: test_settings_load_without_secret_key_material, test_settings_rejects_sensitive_env_key, test_safety_flags_default_disabled, test_safety_live_market_actions_can_unlock_for_gated_live
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from polysignal_lab.config import Settings, SecurityConfigError


def test_settings_load_without_secret_key_material():
    settings = Settings()
    settings.validate_runtime_environment(environ={})
    assert settings.app.name == "PolySignal Lab"
    assert settings.safety.allow_live_market_actions is False


def test_settings_rejects_sensitive_env_key():
    settings = Settings()
    with pytest.raises(SecurityConfigError):
        settings.validate_runtime_environment(environ={"WALLET_SECRET": "x"})


def test_safety_flags_default_disabled():
    settings = Settings()
    assert settings.safety.allow_live_market_actions is False
    assert settings.safety.allow_secret_key_material is False
    assert settings.safety.allow_secure_polymarket_client is False
    assert settings.safety.allow_position_redemption is False


def test_safety_live_market_actions_can_unlock_for_gated_live():
    """Live mode requires an explicit safety unlock; config must allow setting it."""
    settings = Settings.model_validate({"safety": {"allow_live_market_actions": True}})
    assert settings.safety.allow_live_market_actions is True
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "runtime": {
                    "nautilus": {
                        "execution_mode": "sandbox",
                        "allow_live_polymarket_execution": True,
                    }
                }
            }
        )
