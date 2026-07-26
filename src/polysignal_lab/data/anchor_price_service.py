"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Sequence, dataclasses, dataclasses.dataclass, datetime, datetime.datetime, datetime.timedelta, datetime.timezone
Output: window_for_market, capture_anchor_price, AnchorWindow, AnchorPriceStore
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""









from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from polysignal_lab.domain.anchor_price import AnchorPrice
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.spot import SpotPrice


@dataclass(frozen=True, slots=True)
class AnchorWindow:
    window_start: datetime
    window_end: datetime


def _timeframe_seconds(timeframe: str) -> int | None:
    if timeframe == "5m":
        return 300
    if timeframe == "15m":
        return 900
    return None


def _slug_epoch(slug: str) -> int | None:
    try:
        return int(str(slug).rsplit("-", 1)[-1])
    except (TypeError, ValueError):
        return None


def window_for_market(market: Market) -> AnchorWindow | None:
    if market.start_ts is not None and market.end_ts is not None:
        return AnchorWindow(market.start_ts, market.end_ts)
    duration = _timeframe_seconds(market.timeframe)
    epoch = _slug_epoch(market.market_slug)
    if duration is None or epoch is None:
        return None
    start = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return AnchorWindow(start, start + timedelta(seconds=duration))


class AnchorPriceStore(Protocol):
    def upsert_anchor_price(self, anchor: AnchorPrice) -> None: ...

    def get_verified_anchor_price(
        self, asset: str, timeframe: str, market_slug: str
    ) -> AnchorPrice | None: ...


def capture_anchor_price(
    spots: Sequence[SpotPrice],
    market: Market,
    store: AnchorPriceStore,
    *,
    max_lag_ms: int = 2_000,
    latest_by_key: dict[str, AnchorPrice] | None = None,
) -> AnchorPrice | None:
    window = window_for_market(market)
    if window is None or not spots:
        return None

    best = min(
        spots,
        key=lambda spot: abs(
            ((spot.event_time or spot.received_at) - window.window_start).total_seconds()
        ),
    )
    best_time = best.event_time or best.received_at
    lag_ms = int(abs((best_time - window.window_start).total_seconds()) * 1000)
    source = str(getattr(best, "source", "binance")).removesuffix("_spot")
    anchor = AnchorPrice(
        asset=market.asset.upper(),
        timeframe=market.timeframe,
        market_slug=market.market_slug,
        window_start=window.window_start,
        window_end=window.window_end,
        price=best.price if lag_ms <= max_lag_ms else None,
        source=source,
        verified=lag_ms <= max_lag_ms,
        captured_at=best.received_at,
        lag_ms=lag_ms,
    )
    if not anchor.verified:
        existing = store.get_verified_anchor_price(
            anchor.asset, anchor.timeframe, anchor.market_slug
        )
        if existing is not None:
            if latest_by_key is not None:
                latest_by_key[f"{existing.asset}:{existing.timeframe}"] = existing
            return existing
    store.upsert_anchor_price(anchor)
    if latest_by_key is not None:
        latest_by_key[f"{anchor.asset}:{anchor.timeframe}"] = anchor
    return anchor

