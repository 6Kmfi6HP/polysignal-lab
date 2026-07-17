from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, cast

from polysignal_lab.alpha.types import SideBookView, TradeView
from polysignal_lab.domain.market import Market
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog, MarketPairMeta
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState

logger = logging.getLogger(__name__)


class _BookDataProvider(Protocol):
    def book_for_token(
        self,
        token_id: str,
        *,
        now: datetime | None = None,
    ) -> SideBookView | None: ...

    def trades_for_token(self, token_id: str) -> Sequence[TradeView]: ...

    def observe_book_received(
        self,
        token_id: str,
        *,
        received_at: datetime,
    ) -> None: ...


class CacheBoundBookDataProvider:
    def __init__(self, catalog: MarketCatalog) -> None:
        self._catalog = catalog
        self._provider: _BookDataProvider | None = None

    @property
    def is_bound(self) -> bool:
        return self._provider is not None

    def bind_cache(self, cache: object) -> None:
        if cache is None:
            raise RuntimeError("MarketView books require a Nautilus Cache")
        from polysignal_lab.nautilus_runtime.cache_market_data import (
            NautilusCacheMarketDataProvider,
        )

        self._provider = cast(
            _BookDataProvider,
            NautilusCacheMarketDataProvider(cache, catalog=self._catalog),
        )

    def observe_book_received(
        self,
        token_id: str,
        *,
        received_at: datetime,
    ) -> None:
        provider = self._provider
        if provider is not None:
            provider.observe_book_received(token_id, received_at=received_at)

    def book_for_token(
        self,
        token_id: str,
        *,
        now: datetime | None = None,
    ) -> SideBookView | None:
        provider = self._provider
        if provider is None:
            return None
        return provider.book_for_token(token_id, now=now)

    def trades_for_token(self, token_id: str) -> tuple[TradeView, ...]:
        provider = self._provider
        if provider is None:
            return ()
        return tuple(provider.trades_for_token(token_id))


def create_market_projection_components(
    configured_markets: Sequence[Market],
) -> tuple[MarketCatalog, MarketViewAssembler]:
    catalog = MarketCatalog()
    register_markets(catalog, configured_markets)
    assembler = MarketViewAssembler(
        catalog=catalog,
        books=CacheBoundBookDataProvider(catalog),
        custom_data=StrategyCustomDataState(),
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
            logger.debug(
                "skipping runtime market registration for %s: %s",
                market.market_id,
                exc,
            )


def instrument_load_ids(markets: Sequence[Market]) -> tuple[str, ...]:
    catalog = MarketCatalog()
    register_markets(catalog, markets)
    load_ids: set[str] = set()
    for market in markets:
        for token in market.outcome_tokens:
            if not token.token_id or not market.condition_id:
                continue
            instrument_id = catalog.instrument_id_for_token(token.token_id)
            if instrument_id is not None:
                load_ids.add(instrument_id)
    return tuple(sorted(load_ids))


def configured_condition_ids(
    condition_ids: Sequence[str],
    markets: Sequence[Market],
) -> tuple[str, ...]:
    explicit_ids = tuple(
        str(condition_id)
        for condition_id in condition_ids
        if str(condition_id)
    )
    if explicit_ids:
        return explicit_ids
    return tuple(market.condition_id for market in markets if market.condition_id)
