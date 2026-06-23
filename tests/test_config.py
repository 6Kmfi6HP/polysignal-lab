from __future__ import annotations

import pytest
from pydantic import ValidationError

from polysignal_lab.config import Settings, load_settings
from polysignal_lab.domain.enums import TradeResultStatus
from polysignal_lab.strategies.factory import build_strategies


def test_strategy_factory_builds_only_prd_strategies() -> None:
    from polysignal_lab.strategies.factory import build_strategy

    settings = load_settings("config/signal_bot.yaml")

    strategy_names = [strategy.name for strategy in build_strategies(settings.strategies)]
    single_strategy_names = [build_strategy(strategy_config).name for strategy_config in settings.strategies]

    assert strategy_names == ["vwap_momentum", "late_consensus", "ptb_diff"]
    assert single_strategy_names == strategy_names


def test_non_prd_strategy_config_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "strategies": {
                    "skew_mean_reversion": {
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
