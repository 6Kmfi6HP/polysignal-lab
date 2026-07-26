from __future__ import annotations

import logging
from collections.abc import Sequence

from polysignal_lab.domain.market import Market
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog, MarketPairMeta
from polysignal_lab.nautilus_runtime.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState

logger = logging.getLogger(__name__)


def create_market_projection_components(
    configured_markets: Sequence[Market],
) -> tuple[MarketCatalog, MarketViewAssembler]:
    """Catalog + assembler; books bind to Cache on strategy start (no DI provider chain)."""
    catalog = MarketCatalog()
    register_markets(catalog, configured_markets)
    assembler = MarketViewAssembler(
        catalog=catalog,
        books=None,
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
        str(condition_id) for condition_id in condition_ids if str(condition_id)
    )
    if explicit_ids:
        return explicit_ids
    return tuple(market.condition_id for market in markets if market.condition_id)
