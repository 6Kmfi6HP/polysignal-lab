"""
Input: __future__, __future__.annotations, pytest, pydantic, pydantic.ValidationError, polysignal_lab.config, polysignal_lab.config.Settings, polysignal_lab.config.SecurityConfigError
Output: test_settings_load_without_secret_key_material, test_settings_rejects_sensitive_env_key, test_safety_flags_cannot_be_enabled
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


def test_safety_flags_cannot_be_enabled():
    with pytest.raises(ValidationError):
        Settings.model_validate({"safety": {"allow_live_market_actions": True}})
