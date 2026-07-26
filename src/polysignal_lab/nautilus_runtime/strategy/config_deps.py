from __future__ import annotations

from collections.abc import Callable
from typing import cast

from polysignal_lab.alpha.types import AlphaCore
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.runtime_configs import PolySignalStrategyConfig
from polysignal_lab.nautilus_runtime.strategy.protocols import _Assembler


def dependencies_from_config(
    config: PolySignalStrategyConfig,
) -> tuple[AlphaCore, _Assembler, MarketCatalog, Callable[[str], object]]:
    """Build a single alpha core for this Strategy instance (no Composite)."""
    from polysignal_lab.nautilus_runtime.configured_markets import (
        create_market_projection_components,
    )
    from polysignal_lab.nautilus_runtime.strategy_builder import _native_core_for

    settings = config.settings()
    registry, assembler = create_market_projection_components(config.markets())
    name = str(config.strategy_name).strip()
    if not name:
        raise RuntimeError("PolySignalStrategyConfig requires strategy_name")
    strategy_config = getattr(settings.strategies, name, None)
    if strategy_config is None or not bool(getattr(strategy_config, "enabled", False)):
        raise RuntimeError(f"PolySignalStrategyConfig alpha {name!r} is not enabled")
    core = _native_core_for(name, strategy_config)
    if core is None:
        raise RuntimeError(f"PolySignalStrategyConfig has no native core for {name!r}")

    from polysignal_lab.nautilus_runtime.strategy.catalog_lookups import (
        catalog_instrument_id_resolver,
    )

    return (
        core,
        cast(_Assembler, assembler),
        registry,
        catalog_instrument_id_resolver(registry),
    )
