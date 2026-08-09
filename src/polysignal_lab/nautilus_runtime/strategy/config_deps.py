from __future__ import annotations

from collections.abc import Callable
from typing import cast

from polysignal_lab.alpha.types import AlphaCore
from polysignal_lab.config import SecurityConfigError, Settings
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.runtime_configs import PolySignalStrategyConfig
from polysignal_lab.nautilus_runtime.strategy.protocols import _Assembler


def _build_core(settings: Settings, name: str) -> AlphaCore:
    """Resolve the alpha core for a strategy name (native or external plugin)."""
    from polysignal_lab.nautilus_runtime.strategy_loader import build_external_core

    strategy_config = getattr(settings.strategies, name, None)
    if strategy_config is not None:
        if not bool(getattr(strategy_config, "enabled", False)):
            raise RuntimeError(f"PolySignalStrategyConfig alpha {name!r} is not enabled")
        from polysignal_lab.nautilus_runtime.strategy_builder import _native_core_for

        core = _native_core_for(name, strategy_config)
        if core is None:
            raise RuntimeError(
                f"PolySignalStrategyConfig has no native core for {name!r}"
            )
        return core

    plugin = settings.strategies.external_by_name(name)
    if plugin is None:
        raise RuntimeError(f"PolySignalStrategyConfig has no strategy named {name!r}")
    if not plugin.enabled:
        raise RuntimeError(
            f"PolySignalStrategyConfig external alpha {name!r} is not enabled"
        )
    if not settings.safety.allow_external_strategies:
        raise SecurityConfigError(
            f"External strategy {name!r} is disabled by "
            "safety.allow_external_strategies"
        )
    return build_external_core(plugin)


def dependencies_from_config(
    config: PolySignalStrategyConfig,
) -> tuple[AlphaCore, _Assembler, MarketCatalog, Callable[[str], object]]:
    """Build a single alpha core for this Strategy instance (no Composite)."""
    from polysignal_lab.nautilus_runtime.configured_markets import (
        create_market_projection_components,
    )
    from polysignal_lab.nautilus_runtime.strategy.catalog_lookups import (
        catalog_instrument_id_resolver,
    )

    settings = config.settings()
    registry, assembler = create_market_projection_components(config.markets())
    name = str(config.strategy_name).strip()
    if not name:
        raise RuntimeError("PolySignalStrategyConfig requires strategy_name")
    core = _build_core(settings, name)
    return (
        core,
        cast(_Assembler, assembler),
        registry,
        catalog_instrument_id_resolver(registry),
    )
