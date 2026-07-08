"""
Input: __future__, __future__.annotations, asyncio, importlib, logging, sys, collections.abc, collections.abc.Callable, collections.abc.Sequence, dataclasses
Output: build_nautilus_runtime_context, build_live_node, build_nautilus_runtime, _TraderLike, _Disposable, _NautilusNodeLike, _NativeStrategyLike, _EmptyBookDataProvider, _StaticMarketUniverse, NautilusRuntimeContext
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
from typing import Any, Protocol, cast, runtime_checkable

from polysignal_lab.alpha.types import AlphaCore, TradeView
from polysignal_lab.config import Settings, load_settings
from polysignal_lab.data.anchor_price_service import AnchorPriceStore
from polysignal_lab.domain.market import Market
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog, MarketPairMeta
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor
from polysignal_lab.nautilus_runtime.observability import ObservabilityActor
from polysignal_lab.nautilus_runtime.runtime_context_factory import (
    NautilusRuntimeContext,
    build_nautilus_runtime_context,
)


class _TraderLike(Protocol):
    def add_actor(self, actor: object) -> None: ...
    def add_strategy(self, strategy: object) -> None: ...


@runtime_checkable
class _Disposable(Protocol):
    def dispose(self) -> None: ...


class _NautilusNodeLike(Protocol):
    trader: _TraderLike

    def build(self) -> None: ...
    def run(self) -> None: ...


class _NativeStrategyLike(Protocol):
    strategy_name: str


class _EmptyBookDataProvider:
    def book_for_token(self, token_id: str) -> None:
        _ = token_id
        return None

    def trades_for_token(self, token_id: str) -> tuple[TradeView, ...]:
        _ = token_id
        return ()


# Stub placeholders -- _ensure_nautilus_imports() overwrites them at runtime.
LiveNode: object | None = None
PolymarketInstrumentProviderConfig: Callable[..., object] = SimpleNamespace
NautilusActor: type[object] | None = None
NautilusActorConfig: Callable[[], object] | None = None
NautilusStrategy: type[object] | None = None
NautilusStrategyConfig: Callable[[], object] | None = None


class _StaticMarketUniverse:
    def __init__(self, markets: tuple[Market, ...]) -> None:
        self._markets: tuple[Market, ...] = markets

    async def refresh_once(self) -> list[Market]:
        return list(self._markets)

    def refresh_once_sync(self) -> list[Market]:
        return list(self._markets)


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class NautilusRuntimeBundle:
    """Wired Nautilus LiveNode runtime components."""

    context: NautilusRuntimeContext
    components: dict[str, object]
    bridge_registry: MarketCatalog
    node: _NautilusNodeLike
    observability: ObservabilityActor
    websocket_tasks: list[asyncio.Task[object]]


def _ensure_nautilus_imports() -> None:
    """Lazy-import Nautilus LiveNode and runtime helpers into module globals.

    Uses module-level placeholders so tests on py3.11 can monkeypatch before
    the first real call triggers the import chain.  Reads the guard from
    ``sys.modules`` so a ``monkeypatch.setattr`` on the string path always
    takes effect even if this function's ``__globals__`` references a stale
    module object.
    """
    global LiveNode, PolymarketInstrumentProviderConfig, NautilusActor, NautilusStrategy
    global NautilusActorConfig, NautilusStrategyConfig

    mod = sys.modules.get(__name__)
    module_live_node = getattr(mod, "LiveNode", None) if mod is not None else None
    current_live_node = module_live_node or LiveNode
    if current_live_node is not None:
        LiveNode = current_live_node
        if mod is not None:
            PolymarketInstrumentProviderConfig = cast(Callable[..., object], getattr(mod, "PolymarketInstrumentProviderConfig", PolymarketInstrumentProviderConfig))
            NautilusActor = cast(type[object] | None, getattr(mod, "NautilusActor", NautilusActor))
            NautilusActorConfig = cast(Callable[[], object] | None, getattr(mod, "NautilusActorConfig", NautilusActorConfig))
            NautilusStrategy = cast(type[object] | None, getattr(mod, "NautilusStrategy", NautilusStrategy))
            NautilusStrategyConfig = cast(Callable[[], object] | None, getattr(mod, "NautilusStrategyConfig", NautilusStrategyConfig))
        return

    # Delegate LiveNode import to live_node's lazy-import gateway.
    from polysignal_lab.nautilus_runtime.live_node import _ensure_live_imports, LiveNode as _LiveNode

    _ensure_live_imports()
    LiveNode = _LiveNode

    provider_mod = importlib.import_module("nautilus_trader.adapters.polymarket.providers")
    actor_mod = importlib.import_module("nautilus_trader.common.actor")
    strategy_mod = importlib.import_module("nautilus_trader.trading.strategy")
    config_mod = importlib.import_module("nautilus_trader.config")

    PolymarketInstrumentProviderConfig = cast(
        Callable[..., object],
        getattr(provider_mod, "PolymarketInstrumentProviderConfig"),
    )
    NautilusActor = cast(type[object], getattr(actor_mod, "Actor"))
    NautilusActorConfig = cast(Callable[[], object], getattr(config_mod, "ActorConfig"))
    NautilusStrategy = cast(type[object], getattr(strategy_mod, "Strategy"))
    NautilusStrategyConfig = cast(Callable[[], object], getattr(config_mod, "StrategyConfig"))


def _load_runtime_classes() -> tuple[type[object], ...]:
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
    if len(classes) == 2:
        strategy_cls, rotation_actor_cls = classes
        return strategy_cls, rotation_actor_cls, DecisionPolicyActor
    if len(classes) == 3:
        strategy_cls, rotation_actor_cls, policy_actor_cls = classes
        return strategy_cls, rotation_actor_cls, policy_actor_cls
    raise RuntimeError(f"Expected 2 or 3 Nautilus runtime classes, got {len(classes)}")


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


def _create_market_projection_components(
    configured_markets: Sequence[Market],
) -> tuple[MarketCatalog, MarketViewAssembler]:
    catalog = MarketCatalog()
    _register_markets(catalog, configured_markets)
    custom_data = StrategyCustomDataState()
    assembler = MarketViewAssembler(
        catalog=catalog,
        books=_EmptyBookDataProvider(),
        custom_data=custom_data,
    )
    return catalog, assembler


def _register_markets(
    registry: MarketCatalog,
    markets: Sequence[Market],
) -> None:
    for market in markets:
        try:
            registry.register(MarketPairMeta.from_market(market))
        except (KeyError, ValueError) as exc:
            logger.debug("skipping runtime market registration for %s: %s", market.market_id, exc)


def _instrument_load_ids(markets: Sequence[Market]) -> frozenset[str]:
    from polysignal_lab.nautilus_bridge.instrument_mapping import polymarket_instrument_id

    load_ids: set[str] = set()
    for market in markets:
        for token in market.outcome_tokens:
            if token.token_id and market.condition_id:
                load_ids.add(polymarket_instrument_id(market.condition_id, token.token_id))
    return frozenset(load_ids)


def _build_runtime_context(
    settings: Settings | None,
    condition_ids: Sequence[str],
    markets: Sequence[Market],
    market_universe: object | None,
) -> tuple[object, ...]:
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
    return (
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


def _configured_condition_ids(
    condition_ids: Sequence[str],
    markets: Sequence[Market],
) -> tuple[str, ...]:
    explicit_ids = tuple(str(condition_id) for condition_id in condition_ids if str(condition_id))
    if explicit_ids:
        return explicit_ids
    return tuple(market.condition_id for market in markets if market.condition_id)


def _runtime_components(
    *,
    node: _NautilusNodeLike,
    config: object,
    registry: MarketCatalog,
    market_rotation_actor: object,
    assembler: MarketViewAssembler,
    policy: DecisionPolicyActor,
    strategies: Sequence[_NativeStrategyLike],
    cache: object,
    portfolio: object,
) -> dict[str, object]:
    return {
        "node": node,
        "config": config,
        "registry": registry,
        "market_rotation_actor": market_rotation_actor,
        "assembler": assembler,
        "policy": policy,
        "strategies": list(strategies),
        "strategy_names": [strategy.strategy_name for strategy in strategies],
        "cache": cache,
        "portfolio": portfolio,
    }


def build_live_node(
    settings: Settings | None = None,
    *,
    condition_ids: Sequence[str] = (),
    markets: Sequence[Market] = (),
    market_universe: object | None = None,
    store: AnchorPriceStore | None = None,
    health: object | None = None,
    observability: ObservabilityActor | None = None,
) -> dict[str, object]:
    """Build a LiveNode-based paper runtime wiring."""
    from polysignal_lab.nautilus_runtime.node import (
        _attach_cache_projections,
        _build_market_rotation_actor,
        _build_native_strategies,
        _register_runtime_trader_components,
    )

    context = _build_runtime_context(settings, condition_ids, markets, market_universe)
    settings, configured_markets, configured_condition_ids = context[:3]
    runtime_market_universe, node, config, registry, assembler, policy = context[3:]
    market_rotation_actor = _build_market_rotation_actor(
        settings=settings,
        startup_markets=configured_markets,
        market_universe=runtime_market_universe,
        registry=registry,
        store=store,
        health=health,
    )
    strategies = _build_native_strategies(
        settings,
        assembler,
        policy,
        configured_condition_ids,
        registry,
        observability,
    )
    _register_runtime_trader_components(node, market_rotation_actor, policy, strategies)
    nautilus_cache, nautilus_portfolio = _attach_cache_projections(node, registry, assembler, strategies)
    return _runtime_components(
        node=node,
        config=config,
        registry=registry,
        market_rotation_actor=market_rotation_actor,
        assembler=assembler,
        policy=policy,
        strategies=strategies,
        cache=nautilus_cache,
        portfolio=nautilus_portfolio,
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
