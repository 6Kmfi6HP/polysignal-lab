from __future__ import annotations

from datetime import datetime
from typing import Protocol, Sequence

from polysignal_lab.alpha.types import FreshnessView, MarketView, SideBookView, TradeView
from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
from polysignal_lab.nautilus_bridge.market_registry import PolymarketMarketRegistry
from polysignal_lab.utils import stable_hash, utc_now


class BookDataProvider(Protocol):
    def book_for_token(self, token_id: str, *, now: datetime | None = None) -> SideBookView | None: ...

    def trades_for_token(self, token_id: str) -> Sequence[TradeView]: ...


class MarketViewAssembler:
    def __init__(self, *, registry: PolymarketMarketRegistry, books: BookDataProvider, sidecar: ExternalDataSidecar):
        self.registry = registry
        self.books = books
        self.sidecar = sidecar

    def build(self, condition_id: str, *, created_at: datetime | None = None) -> MarketView | None:
        pair = self.registry.by_condition(condition_id)
        if pair is None:
            return None
        now = created_at or utc_now()
        up_book = self.books.book_for_token(pair.up.token_id, now=now)
        down_book = self.books.book_for_token(pair.down.token_id, now=now)
        spot = self.sidecar.spot_for(pair.asset)
        ptb = self.sidecar.ptb_for(pair.condition_id)
        if up_book is None or down_book is None:
            return None

        seconds_to_close = None
        if pair.end_ts is not None and hasattr(pair.end_ts, "__sub__"):
            seconds_to_close = max(0, int((pair.end_ts - now).total_seconds()))
        freshness_values = [
            value
            for value in (
                up_book.freshness_ms,
                down_book.freshness_ms,
                spot.freshness_ms if spot is not None else None,
            )
            if value is not None
        ]
        freshness = FreshnessView(
            up_book_ms=up_book.freshness_ms,
            down_book_ms=down_book.freshness_ms,
            spot_ms=spot.freshness_ms if spot is not None else None,
            max_ms=max(freshness_values) if freshness_values else None,
        )
        metrics = {
            "up_token_id": pair.up.token_id,
            "down_token_id": pair.down.token_id,
        }
        if ptb is not None:
            metrics.update(
                {
                    "price_to_beat_source": ptb.source,
                    "price_to_beat_verified": ptb.verified,
                    "price_to_beat_from_anchor_service": ptb.from_anchor_service,
                    "anchor_price_source": ptb.anchor_source,
                    "anchor_price_lag_ms": ptb.anchor_lag_ms,
                }
            )
        if spot is not None:
            metrics["spot_source"] = spot.source
        return MarketView(
            view_id=f"view_{stable_hash(pair.condition_id, now.isoformat())}",
            market_id=pair.market_id,
            market_slug=pair.market_slug,
            condition_id=pair.condition_id,
            asset=pair.asset,
            timeframe=pair.timeframe,
            start_ts=pair.start_ts,
            end_ts=pair.end_ts,
            created_at=now,
            seconds_to_close=seconds_to_close,
            up=up_book,
            down=down_book,
            spot=spot,
            price_to_beat=ptb.value if ptb is not None else None,
            up_trades=tuple(self.books.trades_for_token(pair.up.token_id)),
            down_trades=tuple(self.books.trades_for_token(pair.down.token_id)),
            metrics=metrics,
            freshness=freshness,
        )
