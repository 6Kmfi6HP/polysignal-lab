from __future__ import annotations

import logging
from datetime import UTC, datetime

from polysignal_lab.alpha.types import SpotView
from polysignal_lab.data.price_to_beat_provider import PriceToBeatProvider
from polysignal_lab.data.state import MarketRegistry, OrderBookRegistry, SpotRegistry
from polysignal_lab.domain.market import Market
from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
from polysignal_lab.nautilus_bridge.market_registry import MarketPairMeta, PolymarketMarketRegistry
from polysignal_lab.nautilus_runtime.book_data import NautilusBookDataProvider
from polysignal_lab.nautilus_runtime.execution import PolySignalPaperExecutionClient


class NautilusDataIngestor:
    def __init__(
        self,
        *,
        markets: MarketRegistry,
        books: OrderBookRegistry,
        spots: SpotRegistry,
        bridge_registry: PolymarketMarketRegistry,
        sidecar: ExternalDataSidecar,
        book_data_provider: NautilusBookDataProvider,
        paper_client: PolySignalPaperExecutionClient,
        price_to_beat_provider: PriceToBeatProvider | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.markets = markets
        self.books = books
        self.spots = spots
        self.bridge_registry = bridge_registry
        self.sidecar = sidecar
        self.book_data_provider = book_data_provider
        self.paper_client = paper_client
        self.price_to_beat_provider = price_to_beat_provider
        self.logger = logger or logging.getLogger(__name__)

    def active_condition_ids(self) -> tuple[str, ...]:
        return tuple(m.condition_id for m in self.markets.active() if m.condition_id)

    def sync_all(self) -> tuple[str, ...]:
        ids = self.sync_markets()
        self.sync_orderbooks()
        self.sync_spots()
        self.sync_price_to_beat()
        return ids

    def sync_markets(self) -> tuple[str, ...]:
        condition_ids: list[str] = []
        for market in self.markets.active():
            try:
                self.bridge_registry.register(MarketPairMeta.from_market(market))
            except (KeyError, ValueError) as exc:
                self.logger.debug("skipping market %s for bridge sync: %s", market.market_id, exc)
                continue
            condition_ids.append(market.condition_id)
        return tuple(condition_ids)

    def sync_orderbooks(self) -> None:
        for token_id, book in self.books.books.items():
            self.book_data_provider.update_book(token_id, book)
            self.paper_client.update_book(token_id, book)

    def sync_spots(self) -> None:
        now = datetime.now(UTC)
        for spot in self.spots.spots.values():
            freshness_ms = max(0, int((now - spot.received_at).total_seconds() * 1000)) if spot.received_at else None
            self.sidecar.update_spot(
                SpotView(
                    asset=spot.asset,
                    symbol=spot.symbol,
                    price=spot.price,
                    source=spot.source,
                    freshness_ms=freshness_ms,
                )
            )

    def sync_price_to_beat(self) -> None:
        for market in self.markets.active():
            value, source, verified, anchor_source, anchor_lag_ms, from_anchor = self._ptb_for_market(market)
            if value is None:
                continue
            self.sidecar.update_price_to_beat(
                condition_id=market.condition_id,
                value=value,
                source=source,
                verified=verified,
                from_anchor_service=from_anchor,
                anchor_source=anchor_source,
                anchor_lag_ms=anchor_lag_ms,
            )

    def _ptb_for_market(self, market: Market) -> tuple[float | None, str, bool, str | None, int | None, bool]:
        anchor_store = getattr(self.price_to_beat_provider, "anchor_store", None) if self.price_to_beat_provider is not None else None
        if anchor_store is not None:
            anchor = anchor_store.get_verified_anchor_price(market.asset, market.timeframe, market.market_slug)
            if anchor is not None and anchor.price is not None:
                return anchor.price, f"anchor_service:{anchor.source}", True, anchor.source, anchor.lag_ms, True
        if market.price_to_beat is not None:
            return market.price_to_beat, "market_metadata", True, None, None, False
        return None, "unavailable", False, None, None, False
