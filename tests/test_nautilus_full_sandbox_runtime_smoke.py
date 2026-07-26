from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from polysignal_lab.config import Settings
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.nautilus_runtime.backtest_node import build_backtest_engine
from polysignal_lab.nautilus_runtime.runtime_registration import (
    register_runtime_components,
)


def _market() -> Market:
    opened = datetime(2026, 7, 17, tzinfo=UTC)
    return Market(
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        asset="BTC",
        timeframe="5m",
        start_ts=opened,
        end_ts=opened + timedelta(minutes=5),
        outcome_tokens=[
            OutcomeToken(
                token_id="up-token",
                side=Side.UP,
                outcome_name="Up",
                market_id="btc-5m",
            ),
            OutcomeToken(
                token_id="down-token",
                side=Side.DOWN,
                outcome_name="Down",
                market_id="btc-5m",
            ),
        ],
    )


def _settings() -> Settings:
    settings = Settings()
    settings.runtime.nautilus.execution_mode = "backtest"
    settings.strategies.set_explicit_strategy_names(("one_cent_buy",))
    return settings


class _RecordingRuntime:
    def __init__(self) -> None:
        self.actors: list[object] = []
        self.strategies: list[object] = []

    def add_actor_from_config(self, config: object) -> None:
        self.actors.append(config)

    def add_strategy_from_config(self, config: object) -> None:
        self.strategies.append(config)


def test_full_backtest_runtime_materializes_native_component_graph() -> None:
    market = _market()
    engine = cast(
        Any,
        build_backtest_engine(
            _settings(),
            markets=(market,),
            condition_ids=(market.condition_id,),
        ),
    )

    try:
        assert type(engine).__name__ == "BacktestEngine"
        assert engine.cache is not None
        assert engine.portfolio is not None
        assert not hasattr(engine, "components")
        assert not hasattr(engine, "bridge_registry")
        assert not hasattr(engine, "market_universe")
    finally:
        engine.dispose()


def test_full_runtime_registration_has_one_owner_per_native_responsibility() -> None:
    runtime = _RecordingRuntime()
    market = _market()

    names = register_runtime_components(
        runtime,
        _settings(),
        markets=(market,),
        condition_ids=(market.condition_id,),
    )

    assert names == ("one_cent_buy",)
    assert [getattr(config, "actor_path") for config in runtime.actors] == [
        "polysignal_lab.nautilus_runtime.market_rotation:MarketRotationActor",
    ]
    assert [getattr(config, "strategy_path") for config in runtime.strategies] == [
        "polysignal_lab.nautilus_runtime.native_strategy:PolySignalNativeStrategy"
    ]
