from __future__ import annotations
from pathlib import Path

import pytest
from pydantic import ValidationError

from polysignal_lab.config import Settings


def test_runtime_config_defaults_to_nautilus_and_stays_paper_safe() -> None:
    settings = Settings()

    assert settings.runtime.nautilus.allow_live_polymarket_execution is False
    assert settings.runtime.nautilus.execution_mode == "sandbox"


def test_nautilus_book_type_defaults_are_paper_only() -> None:
    settings = Settings()

    assert settings.runtime.nautilus.execution_mode == "sandbox"
    assert settings.runtime.nautilus.sandbox_book_type == "L2_MBP"
    assert settings.runtime.nautilus.allow_live_polymarket_execution is False


def test_nautilus_requires_nonempty_sandbox_base_currency() -> None:
    settings = Settings.model_validate(
        {"runtime": {"nautilus": {"sandbox_base_currency": " pUSD "}}}
    )

    assert settings.runtime.nautilus.sandbox_base_currency == "pUSD"
    with pytest.raises(ValidationError):
        _ = Settings.model_validate(
            {"runtime": {"nautilus": {"sandbox_base_currency": "   "}}}
        )


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

    assert settings.runtime.nautilus.execution_mode == "sandbox"
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


@pytest.mark.parametrize(
    "field",
    (
        "max_open_positions",
        "max_market_exposure_usdc",
        "max_strategy_exposure_usdc",
    ),
)
def test_removed_shadow_risk_fields_fail_fast(field: str) -> None:
    with pytest.raises(ValidationError):
        _ = Settings.model_validate({"trading": {field: 10}})


def test_native_risk_limits_are_runtime_configuration() -> None:
    settings = Settings.model_validate(
        {
            "runtime": {
                "nautilus": {
                    "risk": {
                        "max_order_submit_rate": "20/00:00:01",
                        "max_order_modify_rate": "10/00:00:01",
                        "max_notional_per_order": {
                            "123.POLYMARKET": "25.0",
                        },
                    }
                }
            }
        }
    )

    assert settings.runtime.nautilus.risk.max_order_submit_rate == "20/00:00:01"
    assert settings.runtime.nautilus.risk.max_notional_per_order == {
        "123.POLYMARKET": "25.0"
    }


def test_native_risk_config_builds_with_project_limits() -> None:
    from polysignal_lab.nautilus_runtime.live_node import build_risk_engine_config

    settings = Settings.model_validate(
        {
            "runtime": {
                "nautilus": {
                    "risk": {
                        "max_order_submit_rate": "20/00:00:01",
                        "max_order_modify_rate": "10/00:00:01",
                        "max_notional_per_order": {
                            "123.POLYMARKET": "25.0",
                        },
                    }
                }
            }
        }
    )

    built = repr(build_risk_engine_config(settings))
    assert 'max_order_submit_rate: "20/00:00:01"' in built
    assert 'max_order_modify_rate: "10/00:00:01"' in built
    assert '"123.POLYMARKET": "25.0"' in built


def test_yaml_runtime_book_type_values_are_explicit() -> None:
    production = Settings.from_yaml("config/signal_bot.yaml")
    lab = Settings.from_yaml("config/signal_bot.lab.yaml")

    assert production.runtime.nautilus.sandbox_book_type == "L2_MBP"
    assert lab.runtime.nautilus.sandbox_book_type == "L2_MBP"
    assert production.runtime.nautilus.sandbox_base_currency == "pUSD"
    assert lab.runtime.nautilus.sandbox_base_currency == "pUSD"
    assert production.runtime.nautilus.spot_data.source == "polymarket_rtds"
    assert lab.runtime.nautilus.spot_data.source == "polymarket_rtds"


def test_runtime_modes_are_explicit() -> None:
    for mode in ("sandbox", "live", "backtest"):
        values = {"execution_mode": mode}
        if mode == "live":
            values["allow_live_polymarket_execution"] = True
        settings = Settings.model_validate({"runtime": {"nautilus": values}})
        assert settings.runtime.nautilus.execution_mode == mode


def test_live_polymarket_execution_requires_live_mode() -> None:
    with pytest.raises(ValueError, match="live Polymarket execution"):
        _ = Settings.model_validate(
            {
                "runtime": {
                    "nautilus": {"allow_live_polymarket_execution": True},
                }
            }
        )


def test_live_mode_requires_explicit_execution_switch() -> None:
    with pytest.raises(ValueError, match="allow_live_polymarket_execution"):
        _ = Settings.model_validate(
            {"runtime": {"nautilus": {"execution_mode": "live"}}}
        )


def test_live_safety_flag_is_settable() -> None:
    settings = Settings.model_validate(
        {
            "safety": {"allow_live_market_actions": True},
            "runtime": {
                "nautilus": {
                    "execution_mode": "live",
                    "allow_live_polymarket_execution": True,
                }
            },
        }
    )
    assert settings.safety.allow_live_market_actions is True


def test_production_yaml_declares_nautilus_runtime_section() -> None:
    settings = Settings.from_yaml("config/signal_bot.yaml")

    assert settings.runtime.nautilus.trader_id == "PolySignal-Nautilus-001"
    assert settings.runtime.nautilus.python == "3.12"
    assert settings.runtime.nautilus.sandbox_book_type == "L2_MBP"
    assert settings.runtime.nautilus.spot_data.source == "polymarket_rtds"


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
    assert (
        settings.health.restart_gate.docker_healthcheck_fails_on_restart_recommended
        is True
    )


def test_nautilus_market_rotation_defaults_are_enabled() -> None:
    settings = Settings()

    cfg = settings.runtime.nautilus.market_rotation
    assert cfg.enabled is True
    assert cfg.interval_sec == 10
    assert cfg.include_next_periods == 1
    assert cfg.stale_grace_sec == 5
    assert cfg.unsubscribe_exited is True
    assert not hasattr(cfg, "allow_adapter_new_market_events")


def test_production_yaml_declares_market_rotation_section() -> None:
    settings = Settings.from_yaml("config/signal_bot.yaml")

    cfg = settings.runtime.nautilus.market_rotation
    assert cfg.enabled is True
    assert cfg.interval_sec == 10
    assert cfg.include_next_periods == 1
    assert cfg.stale_grace_sec == 5
    assert cfg.unsubscribe_exited is True


def test_polysignal_strategy_config_extends_nautilus_strategy_config() -> None:
    from nautilus_trader.trading.config import StrategyConfig

    from polysignal_lab.nautilus_runtime.runtime_configs import PolySignalStrategyConfig

    settings = Settings()
    config = PolySignalStrategyConfig.build(
        settings, (), (), strategy_name="one_cent_buy"
    )

    assert isinstance(config, StrategyConfig)
    assert config.strategy_id == "PolySignal-one_cent_buy"
    assert config.order_id_tag == "onecentbuy"
    assert config.strategy_name == "one_cent_buy"
    assert config.strategy_names == ("one_cent_buy",)
    reconstructed: PolySignalStrategyConfig = PolySignalStrategyConfig.parse(
        config.json()
    )
    assert reconstructed.settings_json == config.settings_json
    assert tuple(reconstructed.condition_ids) == tuple(config.condition_ids)
    assert reconstructed.strategy_name == "one_cent_buy"


def test_all_production_strategy_configs_expose_subscription_scope() -> None:
    from nautilus_optional import require_nautilus

    require_nautilus()

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
    from polysignal_lab.nautilus_runtime.runtime_configs import (
        PolySignalStrategyConfig,
    )

    settings = Settings.from_yaml("config/signal_bot.yaml")
    for name in settings.strategies.explicit_strategy_names():
        strategy = PolySignalNativeStrategy(
            PolySignalStrategyConfig.build(settings, (), (), strategy_name=name)
        )
        assert strategy._subscription_assets  # pyright: ignore[reportUnknownMemberType]
        assert strategy._subscription_timeframes  # pyright: ignore[reportUnknownMemberType]


def test_market_rotation_actor_config_extends_nautilus_actor_config() -> None:
    from nautilus_trader.common.config import ActorConfig

    from polysignal_lab.nautilus_runtime.runtime_configs import (
        MarketRotationActorConfig,
    )

    config = MarketRotationActorConfig.build(Settings(), ())

    assert isinstance(config, ActorConfig)
    assert config.actor_id == "PolySignal-MarketRotation"
    assert str(config.component_id) == "PolySignal-MarketRotation"


def test_decision_policy_from_settings_is_strategy_owned_factory() -> None:
    from polysignal_lab.nautilus_runtime.decision_policy import (
        DecisionPolicy,
        decision_policy_from_settings,
    )

    policy = decision_policy_from_settings(Settings())
    assert isinstance(policy, DecisionPolicy)
    assert callable(policy.decide)
    assert callable(policy.batch_arbitrate)
