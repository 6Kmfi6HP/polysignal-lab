"""
Input: __future__, __future__.annotations, datetime, datetime.datetime, collections.abc, collections.abc.Sequence, typing, typing.TYPE_CHECKING, typing.Protocol, typing.runtime_checkable
Output: build_alpha_snapshot, BookReceiptObserver, BookDataProvider, MarketViewAssembler
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""









from __future__ import annotations

from datetime import datetime
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from typing_extensions import final

from polysignal_lab.alpha.types import FreshnessView, MarketView, SideBookView, TradeView
from polysignal_lab.nautilus_runtime.market_catalog import MarketCatalog
from polysignal_lab.utils import stable_hash

if TYPE_CHECKING:
    from polysignal_lab.nautilus_runtime.custom_data_state import CustomDataSnapshotProvider


@runtime_checkable
class BookReceiptObserver(Protocol):
    def observe_book_received(
        self,
        token_id: str,
        *,
        received_at: datetime,
    ) -> None: ...


class BookDataProvider(Protocol):
    def book_for_token(
        self,
        token_id: str,
        *,
        now: datetime | None = None,
    ) -> SideBookView | None: ...

    def trades_for_token(self, token_id: str) -> Sequence[TradeView]: ...


@final
class MarketViewAssembler:
    """Pure alpha snapshot builder over Catalog + Cache-bound books + custom PTB/spot."""

    def __init__(
        self,
        *,
        catalog: MarketCatalog,
        books: BookDataProvider | None,
        custom_data: CustomDataSnapshotProvider,
    ):
        self.catalog: MarketCatalog = catalog
        self.books: BookDataProvider | None = books
        self.custom_data: CustomDataSnapshotProvider = custom_data

    @property
    def is_bound(self) -> bool:
        return self.books is not None

    def bind_cache(self, cache: object) -> None:
        """Attach Nautilus Cache as the sole book/trade source (no intermediate provider DI)."""
        if cache is None:
            raise RuntimeError("MarketView books require a Nautilus Cache")
        from polysignal_lab.nautilus_runtime.cache_market_data import (
            NautilusCacheMarketDataProvider,
        )

        self.books = NautilusCacheMarketDataProvider(cache, catalog=self.catalog)

    def observe_book_received(
        self,
        token_id: str,
        *,
        received_at: datetime,
    ) -> None:
        if isinstance(self.books, BookReceiptObserver):
            self.books.observe_book_received(token_id, received_at=received_at)

    def with_custom_data(self, custom_data: CustomDataSnapshotProvider) -> MarketViewAssembler:
        return MarketViewAssembler(
            catalog=self.catalog,
            books=self.books,
            custom_data=custom_data,
        )

    def build(self, condition_id: str, *, created_at: datetime) -> MarketView | None:
        return build_alpha_snapshot(self, condition_id, created_at=created_at)


def build_alpha_snapshot(
    assembler: MarketViewAssembler,
    condition_id: str,
    *,
    created_at: datetime,
) -> MarketView | None:
    """Minimal immutable alpha input from Cache books + catalog meta + PTB/spot."""
    books = assembler.books
    if books is None:
        return None
    pair = assembler.catalog.by_condition(condition_id)
    if pair is None:
        return None
    up_book = books.book_for_token(pair.up.token_id, now=created_at)
    down_book = books.book_for_token(pair.down.token_id, now=created_at)
    spot = assembler.custom_data.spot_for(pair.asset)
    ptb = assembler.custom_data.ptb_for(pair.condition_id)
    if up_book is None or down_book is None:
        return None

    now = created_at
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
        seconds_to_close=_seconds_to_close(pair.end_ts, now),
        up=up_book,
        down=down_book,
        spot=spot,
        price_to_beat=ptb.value if ptb is not None else None,
        up_trades=tuple(books.trades_for_token(pair.up.token_id)),
        down_trades=tuple(books.trades_for_token(pair.down.token_id)),
        metrics=_view_metrics(pair, spot, ptb),
        freshness=_freshness_view(up_book, down_book, spot, now=now),
    )


def _seconds_to_close(end_ts: object | None, now: datetime) -> int | None:
    if end_ts is not None and hasattr(end_ts, "__sub__"):
        return max(0, int((end_ts - now).total_seconds()))
    return None


def _freshness_view(
    up_book: SideBookView,
    down_book: SideBookView,
    spot: object | None,
    *,
    now: datetime,
) -> FreshnessView:
    dynamic_freshness = getattr(spot, "freshness_ms_at", None) if spot is not None else None
    spot_freshness = (
        dynamic_freshness(now)
        if callable(dynamic_freshness)
        else getattr(spot, "freshness_ms", None) if spot is not None else None
    )
    freshness_values = [
        value
        for value in (up_book.freshness_ms, down_book.freshness_ms, spot_freshness)
        if value is not None
    ]
    return FreshnessView(
        up_book_ms=up_book.freshness_ms,
        down_book_ms=down_book.freshness_ms,
        spot_ms=spot_freshness,
        max_ms=max(freshness_values) if freshness_values else None,
    )


def _view_metrics(pair: object, spot: object | None, ptb: object | None) -> dict[str, object]:
    metrics: dict[str, object] = {
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
    return metrics
