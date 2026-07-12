"""
Input: __future__, __future__.annotations, asyncio, importlib, logging, sys, collections.abc, collections.abc.Callable, collections.abc.Sequence, dataclasses
Output: build_nautilus_runtime_context, build_live_node, build_nautilus_runtime, _TraderLike, _Disposable, _NautilusNodeLike, _NativeStrategyLike, CacheBoundBookDataProvider, _StaticMarketUniverse, NautilusRuntimeContext
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

import asyncio
import importlib
import logging
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from typing import NamedTuple, Protocol, cast, runtime_checkable

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


class _TraderLike(Protocol):
    def add_actor(self, _: object) -> None: ...
    def add_strategy(self, strategy: object) -> None: ...


@runtime_checkable
class _Disposable(Protocol):
    def dispose(self) -> None: ...


class _NautilusNodeLike(Protocol):
    trader: _TraderLike

    def build(self) -> None: ...
    def run(self, raise_exception: bool = False) -> None: ...
    async def run_async(self) -> None: ...
    def stop(self) -> None: ...
    async def stop_async(self) -> None: ...


class _RuntimeBuildParts(NamedTuple):
    settings: Settings
    configured_markets: tuple[Market, ...]
    configured_condition_ids: tuple[str, ...]
    runtime_market_universe: object
    node: _NautilusNodeLike
    config: object
    registry: MarketCatalog
    assembler: MarketViewAssembler
    policy: DecisionPolicy


# Stub placeholder -- _ensure_nautilus_imports() overwrites it at runtime.
# Do not expand this gateway with import-time static Nautilus imports.
PolymarketInstrumentProviderConfig: Callable[..., object] = SimpleNamespace


logger = logging.getLogger(__name__)
_NativeStrategyLike = NativeStrategyLike


@dataclass(slots=True)
class NautilusRuntimeBundle:
    """Wired Nautilus TradingNode runtime components."""

    context: NautilusRuntimeContext
    components: dict[str, object]
    bridge_registry: MarketCatalog
    node: _NautilusNodeLike
    observability: ObservabilityService
    websocket_tasks: list[asyncio.Task[object]]


def _ensure_nautilus_imports() -> None:
    """Lazy-import the Nautilus instrument provider configuration."""
    global PolymarketInstrumentProviderConfig

    mod = sys.modules.get(__name__)
    module_provider = getattr(mod, "PolymarketInstrumentProviderConfig", None) if mod is not None else None
    if module_provider is not None and module_provider is not SimpleNamespace:
        PolymarketInstrumentProviderConfig = cast(Callable[..., object], module_provider)
        return

    provider_mod = importlib.import_module("nautilus_trader.adapters.polymarket.providers")
    PolymarketInstrumentProviderConfig = cast(
        Callable[..., object],
        provider_mod.PolymarketInstrumentProviderConfig,
    )
    if mod is not None:
        mod.PolymarketInstrumentProviderConfig = PolymarketInstrumentProviderConfig


def _load_runtime_classes() -> tuple[type[object], type[object], type[object]]:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
    from polysignal_lab.nautilus_runtime.market_rotation import MarketRotationActor
    from polysignal_lab.nautilus_runtime.decision_policy_actor import NautilusDecisionPolicyActor

    return (
        PolySignalNativeStrategy,
        MarketRotationActor,
        NautilusDecisionPolicyActor,
    )


def _runtime_class_triple() -> tuple[type[object], type[object], type[object]]:
    classes = _load_runtime_classes()
    if len(classes) != 3:
        raise ValueError("_load_runtime_classes must return three runtime classes")
    strategy_cls, rotation_actor_cls, policy_actor_cls = classes
    return strategy_cls, rotation_actor_cls, policy_actor_cls


def _create_configured_live_node(
    settings: Settings,
    configured_markets: Sequence[Market],
) -> tuple[_NautilusNodeLike, object]:
    _ensure_nautilus_imports()
    if PolymarketInstrumentProviderConfig is None:
        raise RuntimeError("Nautilus PolymarketInstrumentProviderConfig is unavailable")
    instrument_config = PolymarketInstrumentProviderConfig(
        load_ids=_instrument_load_ids(configured_markets),
    )
    from polysignal_lab.nautilus_runtime.live_node import build_paper_live_node

    node = build_paper_live_node(settings, instrument_config=instrument_config)
    return cast(_NautilusNodeLike, node), instrument_config


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
    policy = _build_policy(settings, policy_type=_runtime_class_triple()[2])
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
) -> dict[str, object]:
    """Build a TradingNode-based paper runtime wiring."""
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
