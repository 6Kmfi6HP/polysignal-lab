from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from polysignal_lab.domain.anchor_price import AnchorPrice
from polysignal_lab.domain.market import Market


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


class AnchorPriceService:
    def __init__(self, spots, store: AnchorPriceStore, max_lag_ms: int = 2_000) -> None:
        self.spots = spots
        self.store = store
        self.max_lag_ms = max_lag_ms
        self._latest_by_key: dict[str, AnchorPrice] = {}

    def capture_for_market(self, market: Market) -> AnchorPrice | None:
        window = window_for_market(market)
        if window is None:
            return None
        samples = self._spot_history(market.asset)
        if not samples:
            return None
        best = min(
            samples,
            key=lambda spot: abs(((spot.event_time or spot.received_at) - window.window_start).total_seconds()),
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
            price=best.price if lag_ms <= self.max_lag_ms else None,
            source=source,
            verified=lag_ms <= self.max_lag_ms,
            captured_at=best.received_at,
            lag_ms=lag_ms,
        )
        self.store.upsert_anchor_price(anchor)
        self._latest_by_key[f"{anchor.asset}:{anchor.timeframe}"] = anchor
        return anchor

    def health_metrics(self) -> dict[str, dict[str, int | float | str | bool | None]]:
        return {
            key: {
                "source": anchor.source,
                "lag_ms": anchor.lag_ms,
                "verified": anchor.verified,
                "market_slug": anchor.market_slug,
            }
            for key, anchor in self._latest_by_key.items()
        }

    def _spot_history(self, asset: str):
        history = getattr(self.spots, "history", None)
        if callable(history):
            return list(history(asset))
        if isinstance(history, dict):
            return list(history.get(asset.upper(), ()))
        return []
