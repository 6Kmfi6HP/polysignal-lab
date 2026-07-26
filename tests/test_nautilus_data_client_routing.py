from __future__ import annotations

from dataclasses import dataclass
from typing import cast, final

import pytest
from polysignal_lab.config import Settings
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.nautilus_runtime import node_builder
from polysignal_lab.nautilus_runtime.polymarket_clients import (
    polymarket_data_client_id,
    polymarket_data_client_name,
)


@dataclass(frozen=True, slots=True)
class _SlugConfig:
    assets: list[str]
    interval_mins: int
    periods: int
    start_offset_periods: int


@final
class _Config:
    kwargs: dict[str, object]

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


def _market(timeframe: str, suffix: str) -> Market:
    condition_id = f"condition{suffix}"
    return Market(
        market_id=f"market{suffix}",
        market_slug=f"btc-updown-{timeframe}-{suffix}",
        condition_id=condition_id,
        asset="BTC",
        timeframe=timeframe,
        outcome_tokens=[
            OutcomeToken(
                token_id=f"up{suffix}",
                side=Side.UP,
                outcome_name="Up",
                market_id=f"market{suffix}",
            ),
            OutcomeToken(
                token_id=f"down{suffix}",
                side=Side.DOWN,
                outcome_name="Down",
                market_id=f"market{suffix}",
            ),
        ],
    )


def test_data_client_ids_are_stable_per_timeframe() -> None:
    assert polymarket_data_client_name("5m") == "POLYMARKET-5M"
    assert polymarket_data_client_name("15m") == "POLYMARKET-15M"
    assert str(polymarket_data_client_id("5m")) == "POLYMARKET-5M"
    assert str(polymarket_data_client_id("15m")) == "POLYMARKET-15M"


def test_market_timeframes_are_canonicalized_before_client_routing() -> None:
    settings = Settings.model_validate({"markets": {"timeframes": [" 5M ", "15m"]}})

    assert settings.markets.timeframes == ["5m", "15m"]


def test_market_timeframes_reject_duplicate_client_routes() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        _ = Settings.model_validate({"markets": {"timeframes": ["5m", "5M"]}})


def test_rtds_data_client_is_primary_timeframe() -> None:
    from polysignal_lab.nautilus_runtime.polymarket_clients import (
        polymarket_rtds_data_client_id,
        polymarket_rtds_data_client_name,
    )

    assert polymarket_rtds_data_client_name(["5m", "15m"]) == "POLYMARKET-5M"
    assert str(polymarket_rtds_data_client_id(["15m", "5m"])) == "POLYMARKET-15M"


def test_default_timeframes_build_distinct_dynamic_provider_configs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builders: list[_SlugConfig] = []

    def build_slug_config(**kwargs: object) -> _SlugConfig:
        config = _SlugConfig(
            assets=cast(list[str], kwargs["assets"]),
            interval_mins=cast(int, kwargs["interval_mins"]),
            periods=cast(int, kwargs["periods"]),
            start_offset_periods=cast(int, kwargs["start_offset_periods"]),
        )
        builders.append(config)
        return config

    monkeypatch.setattr(
        node_builder, "PolymarketUpDownEventSlugConfig", build_slug_config
    )
    monkeypatch.setattr(node_builder, "PolymarketInstrumentProviderConfig", _Config)

    configs = node_builder._polymarket_instrument_configs(  # pyright: ignore[reportPrivateUsage]
        Settings(),
        (),
    )

    typed_configs = tuple(cast(_Config, config) for config in configs.values())
    assert tuple(configs) == ("POLYMARKET-5M", "POLYMARKET-15M")
    assert [builder.interval_mins for builder in builders] == [5, 15]
    assert all("event_slug_builder" in config.kwargs for config in typed_configs)
    assert all("event_slugs" not in config.kwargs for config in typed_configs)


def test_startup_load_ids_are_partitioned_by_timeframe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def build_slug_config(**kwargs: object) -> dict[str, object]:
        return kwargs

    monkeypatch.setattr(
        node_builder,
        "PolymarketUpDownEventSlugConfig",
        build_slug_config,
    )
    monkeypatch.setattr(node_builder, "PolymarketInstrumentProviderConfig", _Config)

    configs = node_builder._polymarket_instrument_configs(  # pyright: ignore[reportPrivateUsage]
        Settings(),
        (_market("5m", "5"), _market("15m", "15")),
    )

    five_minute = cast(_Config, configs["POLYMARKET-5M"])
    fifteen_minute = cast(_Config, configs["POLYMARKET-15M"])
    assert {
        str(item) for item in cast(list[object], five_minute.kwargs["load_ids"])
    } == {
        "condition5-down5.POLYMARKET",
        "condition5-up5.POLYMARKET",
    }
    assert {
        str(item) for item in cast(list[object], fifteen_minute.kwargs["load_ids"])
    } == {
        "condition15-down15.POLYMARKET",
        "condition15-up15.POLYMARKET",
    }
