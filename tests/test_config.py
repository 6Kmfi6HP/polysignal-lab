"""
Input: __future__, __future__.annotations, pathlib, pathlib.Path, pytest, pydantic, pydantic.ValidationError, polysignal_lab.config, polysignal_lab.config.Settings, polysignal_lab.config.load_settings
Output: test_load_settings_records_explicit_strategy_names, test_settings_model_validate_has_no_explicit_strategy_names, test_default_rtds_assets_cover_default_market_assets, test_strategy_factory_builds_default_configured_strategies, test_explicit_restored_strategy_can_be_built, test_disabled_explicit_strategy_is_skipped, test_unknown_strategy_config_rejected, test_late_consensus_stop_loss_config_rejects_malformed_entry, test_late_consensus_policy_uses_model_defaults_when_yaml_omits_fields, test_ptb_diff_policy_uses_exit_lag_default_when_yaml_omits_fields
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations
from pathlib import Path

import pytest
from pydantic import ValidationError

from polysignal_lab.config import Settings, load_settings
from polysignal_lab.domain.enums import TradeResultStatus
from polysignal_lab.nautilus_runtime.strategy_builder import _build_nautilus_config_strategy_schedule


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



def test_default_rtds_assets_cover_default_market_assets() -> None:
    settings = Settings()

    assert set(settings.markets.assets).issubset(settings.data.polymarket.rtds_assets)


def _enabled_strategy_names(settings: Settings) -> list[str]:
    return [entry.name for entry in _build_nautilus_config_strategy_schedule(settings)]


def test_strategy_schedule_builds_default_configured_strategies() -> None:
    settings = load_settings("config/signal_bot.yaml")

    assert _enabled_strategy_names(settings) == [
        "vwap_momentum",
        "late_consensus",
        "ptb_diff",
    ]


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

    assert _enabled_strategy_names(settings) == [
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

    assert _enabled_strategy_names(settings) == [
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



def test_late_consensus_policy_uses_model_defaults_when_yaml_omits_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "signal_bot.yaml"
    config_path.write_text(
        """
strategies:
  late_consensus:
    enabled: true
""".strip(),
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert _enabled_strategy_names(settings) == ["late_consensus"]
    assert settings.strategies.late_consensus.max_orderbook_staleness_ms == 1_500
    assert settings.strategies.late_consensus.max_spot_staleness_ms == 1_500


def test_ptb_diff_policy_uses_exit_lag_default_when_yaml_omits_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "signal_bot.yaml"
    config_path.write_text(
        """
strategies:
  ptb_diff:
    enabled: true
""".strip(),
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert _enabled_strategy_names(settings) == ["ptb_diff"]
    assert settings.strategies.ptb_diff.exit_config.market_data_max_lag_sec == 1.0


def test_ptb_diff_anchor_required_mode_loads_from_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "signal_bot.yaml"
    config_path.write_text(
        """
strategies:
  ptb_diff:
    enabled: true
    require_anchor_price_source: true
""".strip(),
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.strategies.ptb_diff.require_anchor_price_source is True


def test_prd_result_states_exclude_partial_settlement() -> None:
    result_states = {result.value for result in TradeResultStatus}

    assert result_states == {"WIN", "LOSS", "VOID", "UNKNOWN"}


def test_production_config_uses_reviewed_strategy_subset() -> None:
    settings = Settings.from_yaml("config/signal_bot.yaml")
    names = _enabled_strategy_names(settings)

    assert names == ["vwap_momentum", "late_consensus", "ptb_diff"]


def test_lab_config_preserves_experimental_strategy_breadth() -> None:
    settings = Settings.from_yaml("config/signal_bot.lab.yaml")
    names = set(_enabled_strategy_names(settings))

    assert names == {
        "vwap_momentum",
        "late_consensus",
        "ptb_diff",
        "binary_momentum",
        "cross_market_bot",
        "dump_hedge",
        "fibonacci_bot",
        "low_side_dual_reversion",
        "mid_price_sizing",
        "ninety_nine_cent_sniper",
        "one_cent_buy",
        "pre_order_market",
        "skew_mean_reversion",
    }
