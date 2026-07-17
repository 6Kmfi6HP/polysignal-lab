"""
Input: __future__, asyncio, logging, collections.abc, dataclasses, nautilus_pyo3, polysignal_lab.config
Output: build_nautilus_runtime_context, build_live_node, build_nautilus_runtime, NautilusRuntimeBundle
Pos: Application code

Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple, Protocol, runtime_checkable

from nautilus_trader.core.nautilus_pyo3 import PolymarketInstrumentProviderConfig

from polysignal_lab.config import Settings, load_settings
from polysignal_lab.data.anchor_price_service import AnchorPriceStore
from polysignal_lab.domain.market import Market
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicy
from polysignal_lab.nautilus_runtime.node_builder_components import (
    NativeStrategyLike,
    StaticMarketUniverse as _StaticMarketUniverse,
    configured_condition_ids as _configured_condition_ids,
    create_market_projection_components as _create_market_projection_components,
    instrument_load_ids as _instrument_load_ids,
    wire_live_node_runtime,
)
from polysignal_lab.nautilus_runtime.observability import ObservabilityService
from polysignal_lab.nautilus_runtime.runtime_context_factory import (
    NautilusRuntimeContext,
    build_nautilus_runtime_context as build_nautilus_runtime_context,
)


@runtime_checkable
class _Disposable(Protocol):
    def dispose(self) -> None: ...


class _RuntimeBuildParts(NamedTuple):
    settings: Settings
    configured_markets: tuple[Market, ...]
    configured_condition_ids: tuple[str, ...]
    runtime_market_universe: object
    node: object
    config: object
    registry: MarketCatalog
    assembler: MarketViewAssembler
    policy: DecisionPolicy | None


logger = logging.getLogger(__name__)
_NativeStrategyLike = NativeStrategyLike


@dataclass(slots=True)
class NautilusRuntimeBundle:
    """Wired Nautilus LiveNode runtime components."""

    context: NautilusRuntimeContext
    components: dict[str, object]
    bridge_registry: MarketCatalog
    node: object
    observability: ObservabilityService
    websocket_tasks: list[asyncio.Task[object]]


def _load_runtime_classes() -> tuple[type[object], type[object], type[object]]:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
    from polysignal_lab.nautilus_runtime.market_rotation import MarketRotationActor
    from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicy

    return (
        PolySignalNativeStrategy,
        MarketRotationActor,
        DecisionPolicy,
    )


def _runtime_class_triple() -> tuple[type[object], type[object], type[object]]:
    classes = _load_runtime_classes()
    if len(classes) != 3:
        raise ValueError("_load_runtime_classes must return three runtime classes")
    strategy_cls, rotation_actor_cls, policy_actor_cls = classes
    return strategy_cls, rotation_actor_cls, policy_actor_cls


def build_runtime_node(settings: Settings, *, instrument_config: object) -> object:
    """Dispatch native node composition by configured execution mode."""
    if settings.runtime.nautilus.execution_mode == "backtest":
        from polysignal_lab.nautilus_runtime.backtest_node import build_backtest_engine

        return build_backtest_engine(settings)
    from polysignal_lab.nautilus_runtime.live_node import build_runtime_node as build

    return build(settings, instrument_config=instrument_config)


def _create_configured_live_node(
    settings: Settings,
    configured_markets: Sequence[Market],
) -> tuple[object, object]:
    instrument_config = PolymarketInstrumentProviderConfig(
        load_ids=_instrument_load_ids(configured_markets),
    )
    node = build_runtime_node(settings, instrument_config=instrument_config)
    return node, instrument_config


def _build_runtime_context(
    settings: Settings | None,
    condition_ids: Sequence[str],
    markets: Sequence[Market],
    market_universe: object | None,
) -> _RuntimeBuildParts:
    from polysignal_lab.nautilus_runtime.node import _build_policy

    if settings is None:
        settings = load_settings()
    configured_markets = tuple(markets)
    configured_condition_ids = _configured_condition_ids(condition_ids, configured_markets)
    runtime_market_universe = (
        market_universe if market_universe is not None else _StaticMarketUniverse(configured_markets)
    )
    node, config = _create_configured_live_node(settings, configured_markets)
    registry, assembler = _create_market_projection_components(configured_markets)
    kernel = getattr(node, "node", node)
    supports_importable = callable(getattr(kernel, "add_strategy_from_config", None)) and callable(
        getattr(kernel, "add_actor_from_config", None)
    )
    policy = None if supports_importable else _build_policy(
        settings,
        policy_type=_runtime_class_triple()[2],
    )
    return _RuntimeBuildParts(
        settings,
        configured_markets,
        configured_condition_ids,
        runtime_market_universe,
        node,
        config,
        registry,
        assembler,
        policy,
    )


def build_live_node(
    settings: Settings | None = None,
    *,
    condition_ids: Sequence[str] = (),
    markets: Sequence[Market] = (),
    market_universe: object | None = None,
    store: AnchorPriceStore | None = None,
    health: object | None = None,
    observability: ObservabilityService | None = None,
    reporting_services: object | None = None,
) -> dict[str, object]:
    """Build a LiveNode-based sandbox runtime wiring."""
    context = _build_runtime_context(settings, condition_ids, markets, market_universe)
    return wire_live_node_runtime(
        settings=context.settings,
        configured_markets=context.configured_markets,
        configured_condition_ids=context.configured_condition_ids,
        runtime_market_universe=context.runtime_market_universe,
        node=context.node,
        config=context.config,
        registry=context.registry,
        assembler=context.assembler,
        policy=context.policy,
        store=store,
        health=health,
        observability=observability,
        reporting_services=reporting_services,
    )


async def build_nautilus_runtime(settings: Settings | None = None) -> NautilusRuntimeBundle:
    """Build the default Nautilus runtime."""
    from polysignal_lab.nautilus_runtime.node import (
        _build_nautilus_runtime_bundle,
        _prepare_nautilus_runtime_context,
    )

    if settings is None:
        settings = load_settings()

    context, discovered_markets, observability = await _prepare_nautilus_runtime_context(settings)
    return _build_nautilus_runtime_bundle(settings, context, discovered_markets, observability)
