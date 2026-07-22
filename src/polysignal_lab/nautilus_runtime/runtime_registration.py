"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Callable, collections.abc.Sequence, typing, typing.cast, nautilus_trader.core, nautilus_trader.core.nautilus_pyo3, polysignal_lab.config
Output: enabled_strategy_names, register_runtime_components
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""


from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import cast

from nautilus_trader.core import nautilus_pyo3

from polysignal_lab.config import Settings
from polysignal_lab.domain.market import Market
from polysignal_lab.nautilus_runtime.market_rotation import MarketRotationActor
from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
from polysignal_lab.nautilus_runtime.recorded_market_data import (
    RecordedMarketDataActor,
    RecordedMarketDataActorConfig,
)
from polysignal_lab.nautilus_runtime.runtime_configs import (
    MarketRotationActorConfig,
    PolySignalStrategyConfig,
    importable_config_dict,
)

_importable_actor_config = cast(
    Callable[..., object],
    getattr(nautilus_pyo3, "ImportableActorConfig"),
)
_importable_strategy_config = cast(
    Callable[..., object],
    getattr(nautilus_pyo3, "ImportableStrategyConfig"),
)


def _fqn(component: type[object]) -> str:
    return f"{component.__module__}:{component.__qualname__}"


def enabled_strategy_names(settings: Settings) -> tuple[str, ...]:
    return tuple(
        name
        for name in settings.strategies.explicit_strategy_names()
        if bool(getattr(settings.strategies, name).enabled)
    )


def register_runtime_components(
    runtime: object,
    settings: Settings,
    *,
    markets: Sequence[Market] = (),
    condition_ids: Sequence[str] = (),
) -> tuple[str, ...]:
    add_actor = getattr(runtime, "add_actor_from_config")
    add_strategy = getattr(runtime, "add_strategy_from_config")
    configured_markets = tuple(markets)
    _ = condition_ids  # MarketRotationActor universe events are the sole active-set SoT.
    strategy_names = enabled_strategy_names(settings)

    rotation_config = MarketRotationActorConfig.build(settings, configured_markets)
    add_actor(
        _importable_actor_config(
            actor_path=_fqn(MarketRotationActor),
            config_path=_fqn(MarketRotationActorConfig),
            config=rotation_config.importable_dict(),
        )
    )
    if settings.runtime.nautilus.execution_mode == "sandbox":
        recorder_config = RecordedMarketDataActorConfig.build(settings)
        add_actor(
            _importable_actor_config(
                actor_path=_fqn(RecordedMarketDataActor),
                config_path=_fqn(RecordedMarketDataActorConfig),
                config=importable_config_dict(recorder_config),
            )
        )

    for name in strategy_names:
        strategy_config = PolySignalStrategyConfig.build(
            settings,
            configured_markets,
            (),
            strategy_name=name,
        )
        add_strategy(
            _importable_strategy_config(
                strategy_path=_fqn(PolySignalNativeStrategy),
                config_path=_fqn(PolySignalStrategyConfig),
                config=strategy_config.importable_dict(),
            )
        )
    return strategy_names
