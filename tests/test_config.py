from __future__ import annotations
from pathlib import Path

import pytest
from pydantic import ValidationError

from polysignal_lab.config import Settings, load_settings
from polysignal_lab.domain.enums import TradeResultStatus
from polysignal_lab.strategies.factory import build_strategies


def test_load_settings_records_explicit_strategy_names(tmp_path: Path) -> None:
    config_path = tmp_path / "signal_bot.yaml"
    config_path.write_text(
        """
strategies:
  late_consensus:
    enabled: true
  fibonacci_bot:
    enabled: true
    require_momentum_confirmation: false
""".strip(),
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.strategies.explicit_strategy_names() == (
        "late_consensus",
        "fibonacci_bot",
    )
    assert [strategy_config.name for strategy_config in settings.strategies] == [
        "late_consensus",
        "fibonacci_bot",
    ]


def test_settings_model_validate_has_no_explicit_strategy_names() -> None:
    settings = Settings.model_validate(
        {
            "strategies": {
                "late_consensus": {
                    "enabled": True,
                },
            },
        }
    )

    assert settings.strategies.explicit_strategy_names() == ()
    assert list(settings.strategies) == []



def test_strategy_factory_builds_default_configured_strategies() -> None:
    from polysignal_lab.strategies.factory import build_strategy

    settings = load_settings("config/signal_bot.yaml")

    strategy_names = [strategy.name for strategy in build_strategies(settings.strategies)]
    single_strategy_names = [
        build_strategy(strategy_config).name for strategy_config in settings.strategies
    ]

    assert strategy_names == ["vwap_momentum", "late_consensus", "ptb_diff"]
    assert single_strategy_names == strategy_names


def test_explicit_restored_strategy_can_be_built(tmp_path: Path) -> None:
    config_path = tmp_path / "signal_bot.yaml"
    config_path.write_text(
        """
strategies:
  fibonacci_bot:
    enabled: true
    require_momentum_confirmation: false
""".strip(),
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert [strategy.name for strategy in build_strategies(settings.strategies)] == [
        "fibonacci_bot"
    ]


def test_disabled_explicit_strategy_is_skipped(tmp_path: Path) -> None:
    config_path = tmp_path / "signal_bot.yaml"
    config_path.write_text(
        """
strategies:
  fibonacci_bot:
    enabled: false
    require_momentum_confirmation: false
  late_consensus:
    enabled: true
""".strip(),
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert [strategy.name for strategy in build_strategies(settings.strategies)] == [
        "late_consensus"
    ]


def test_unknown_strategy_config_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "strategies": {
                    "unknown_strategy": {
                        "enabled": True,
                    },
                },
            }
        )

def test_late_consensus_stop_loss_config_rejects_malformed_entry() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "strategies": {
                    "late_consensus": {
                        "stop_loss_per_coin": {
                            "BTC": {
                                "type": "trailing",
                                "value": -12.0,
                            },
                        },
                    },
                },
            }
        )


def test_prd_result_states_exclude_partial_settlement() -> None:
    result_states = {result.value for result in TradeResultStatus}

    assert result_states == {"WIN", "LOSS", "VOID", "UNKNOWN"}
