from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import cast

from nautilus_trader.core import nautilus_pyo3

from polysignal_lab.config import Settings
from polysignal_lab.domain.market import Market
from polysignal_lab.nautilus_runtime.decision_policy_actor import (
    DecisionPolicyActor,
    DecisionPolicyActorConfig,
)
from polysignal_lab.nautilus_runtime.market_rotation import MarketRotationActor
from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
from polysignal_lab.nautilus_runtime.runtime_configs import (
    MarketRotationActorConfig,
    PolySignalStrategyConfig,
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
    configured_condition_ids = tuple(condition_ids)

    rotation_config = MarketRotationActorConfig.build(settings, configured_markets)
    add_actor(
        _importable_actor_config(
            actor_path=_fqn(MarketRotationActor),
            config_path=_fqn(MarketRotationActorConfig),
            config=rotation_config.importable_dict(),
        )
    )

    policy_config = DecisionPolicyActorConfig.build(settings)
    add_actor(
        _importable_actor_config(
            actor_path=_fqn(DecisionPolicyActor),
            config_path=_fqn(DecisionPolicyActorConfig),
            config=policy_config.importable_dict(),
        )
    )

    strategy_names = enabled_strategy_names(settings)
    if strategy_names:
        strategy_config = PolySignalStrategyConfig.build(
            settings,
            configured_markets,
            configured_condition_ids,
        )
        add_strategy(
            _importable_strategy_config(
                strategy_path=_fqn(PolySignalNativeStrategy),
                config_path=_fqn(PolySignalStrategyConfig),
                config=strategy_config.importable_dict(),
            )
        )
    return strategy_names
