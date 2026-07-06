from __future__ import annotations

from datetime import datetime
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

from typing_extensions import final

from polysignal_lab.alpha.types import FreshnessView, MarketView, SideBookView, TradeView
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
from polysignal_lab.utils import stable_hash, utc_now

if TYPE_CHECKING:
    from polysignal_lab.nautilus_runtime.custom_data_state import CustomDataSnapshotProvider


class BookDataProvider(Protocol):
    def book_for_token(self, token_id: str) -> SideBookView | None: ...

    def trades_for_token(self, token_id: str) -> Sequence[TradeView]: ...


@final
class MarketViewAssembler:
    def __init__(
        self,
        *,
        catalog: MarketCatalog,
        books: BookDataProvider,
        custom_data: CustomDataSnapshotProvider,
    ):
        self.catalog: MarketCatalog = catalog
        self.books: BookDataProvider = books
        self.custom_data: CustomDataSnapshotProvider = custom_data

    def with_custom_data(self, custom_data: CustomDataSnapshotProvider) -> MarketViewAssembler:
        return MarketViewAssembler(
            catalog=self.catalog,
            books=self.books,
            custom_data=custom_data,
        )

    def build(self, condition_id: str, *, created_at: datetime | None = None) -> MarketView | None:
        pair = self.catalog.by_condition(condition_id)
        if pair is None:
            return None
        up_book = self.books.book_for_token(pair.up.token_id)
        down_book = self.books.book_for_token(pair.down.token_id)
        spot = self.custom_data.spot_for(pair.asset)
        ptb = self.custom_data.ptb_for(pair.condition_id)
        if up_book is None or down_book is None:
            return None

        now = created_at or utc_now()
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
            up_trades=tuple(self.books.trades_for_token(pair.up.token_id)),
            down_trades=tuple(self.books.trades_for_token(pair.down.token_id)),
            metrics=_view_metrics(pair, spot, ptb),
            freshness=_freshness_view(up_book, down_book, spot),
        )


def _seconds_to_close(end_ts: object | None, now: datetime) -> int | None:
    if end_ts is not None and hasattr(end_ts, "__sub__"):
        return max(0, int((end_ts - now).total_seconds()))
    return None


def _freshness_view(
    up_book: SideBookView,
    down_book: SideBookView,
    spot: object | None,
) -> FreshnessView:
    spot_freshness = getattr(spot, "freshness_ms", None) if spot is not None else None
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
