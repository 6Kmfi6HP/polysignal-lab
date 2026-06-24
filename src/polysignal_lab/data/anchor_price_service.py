from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

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
