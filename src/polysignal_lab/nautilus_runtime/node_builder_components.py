from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Protocol

from polysignal_lab.alpha.types import TradeView
from polysignal_lab.domain.market import Market
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog, MarketPairMeta
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState
from polysignal_lab.nautilus_runtime.market_discovery_worker import MarketDiscoveryWorker

logger = logging.getLogger(__name__)


class NativeStrategyLike(Protocol):
    strategy_name: str


class EmptyBookDataProvider:
    def book_for_token(self, token_id: str) -> None:
        _ = token_id
        return None

    def trades_for_token(self, token_id: str) -> tuple[TradeView, ...]:
        _ = token_id
        return ()


class StaticMarketUniverse:
    def __init__(self, markets: tuple[Market, ...]) -> None:
        self._markets: tuple[Market, ...] = markets

    async def refresh_once(self) -> list[Market]:
        return list(self._markets)

    def refresh_once_sync(self) -> list[Market]:
        return list(self._markets)


def create_market_projection_components(
    configured_markets: Sequence[Market],
) -> tuple[MarketCatalog, MarketViewAssembler]:
    catalog = MarketCatalog()
    register_markets(catalog, configured_markets)
    custom_data = StrategyCustomDataState()
    assembler = MarketViewAssembler(
        catalog=catalog,
        books=EmptyBookDataProvider(),
        custom_data=custom_data,
    )
    return catalog, assembler


def register_markets(
    registry: MarketCatalog,
    markets: Sequence[Market],
) -> None:
    for market in markets:
        try:
            registry.register(MarketPairMeta.from_market(market))
        except (KeyError, ValueError) as exc:
            logger.debug("skipping runtime market registration for %s: %s", market.market_id, exc)


def instrument_load_ids(markets: Sequence[Market]) -> frozenset[str]:
    catalog = MarketCatalog()
    register_markets(catalog, markets)
    load_ids: set[str] = set()
    for market in markets:
        for token in market.outcome_tokens:
            if token.token_id and market.condition_id:
                instrument_id = catalog.instrument_id_for_token(token.token_id)
                if instrument_id is not None:
                    load_ids.add(instrument_id)
    return frozenset(load_ids)


def configured_condition_ids(
    condition_ids: Sequence[str],
    markets: Sequence[Market],
) -> tuple[str, ...]:
    explicit_ids = tuple(str(condition_id) for condition_id in condition_ids if str(condition_id))
    if explicit_ids:
        return explicit_ids
    return tuple(market.condition_id for market in markets if market.condition_id)


def runtime_components(
    *,
    node: object,
    config: object,
    registry: MarketCatalog,
    market_rotation_actor: object,
    assembler: MarketViewAssembler,
    policy: object,
    strategies: Sequence[NativeStrategyLike],
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


def _live_node_strategies_and_cache(
    *,
    node: object,
    settings: object,
    assembler: MarketViewAssembler,
    policy: object,
    configured_condition_ids: Sequence[str],
    registry: MarketCatalog,
    market_rotation_actor: object,
    observability: object | None,
) -> tuple[Sequence[NativeStrategyLike], object, object]:
    from polysignal_lab.nautilus_runtime.node import (
        _attach_cache_projections,
        _build_native_strategies,
        _register_runtime_trader_components,
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
    return _attach_cache_projections(node, registry, assembler, strategies) + (strategies,)


def wire_live_node_runtime(
    *,
    settings: object,
    configured_markets: Sequence[Market],
    configured_condition_ids: Sequence[str],
    runtime_market_universe: object,
    node: object,
    config: object,
    registry: MarketCatalog,
    assembler: MarketViewAssembler,
    policy: object,
    store: object | None = None,
    health: object | None = None,
    observability: object | None = None,
) -> dict[str, object]:
    from polysignal_lab.nautilus_runtime.node import _build_market_rotation_actor

    refresh_once_sync = getattr(runtime_market_universe, "refresh_once_sync")
    discovery_worker = MarketDiscoveryWorker(refresh_once_sync)

    market_rotation_actor = _build_market_rotation_actor(
        settings=settings,
        startup_markets=configured_markets,
        market_universe=runtime_market_universe,
        discovery_worker=discovery_worker,
        registry=registry,
        store=store,
        health=health,
    )
    nautilus_cache, nautilus_portfolio, strategies = _live_node_strategies_and_cache(
        node=node,
        settings=settings,
        assembler=assembler,
        policy=policy,
        configured_condition_ids=configured_condition_ids,
        registry=registry,
        market_rotation_actor=market_rotation_actor,
        observability=observability,
    )
    return runtime_components(
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
