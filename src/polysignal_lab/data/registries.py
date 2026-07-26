from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from polysignal_lab.domain.market import Market
from polysignal_lab.domain.spot import SpotPrice

SPOT_HISTORY_LIMIT = 512


def parse_source_timestamp(ts_val: Any) -> datetime | None:
    if not ts_val:
        return None
    try:
        val = float(ts_val)
        if val > 1e11:
            val = val / 1000.0
        return datetime.fromtimestamp(val, tz=timezone.utc)
    except (ValueError, TypeError, OverflowError):
        try:
            return datetime.fromisoformat(str(ts_val).replace("Z", "+00:00"))
        except ValueError:
            return None


def append_spot_history(
    history_by_asset: dict[str, list[SpotPrice]],
    spot: SpotPrice,
    *,
    limit: int = SPOT_HISTORY_LIMIT,
) -> list[SpotPrice]:
    """Append a spot sample and truncate to the shared history window."""
    asset = spot.asset.upper()
    history = history_by_asset.setdefault(asset, [])
    history.append(spot)
    del history[:-limit]
    return history


@dataclass
class MarketRegistry:
    """Read-only market projection for reporting/Telegram.

    Trading active-set authority is MarketRotationActor CustomData; this
    registry is updated via ``project_active`` from that Actor.
    """

    markets: dict[str, Market] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def upsert_many(self, markets: list[Market]) -> None:
        with self._lock:
            for market in markets:
                self.markets[market.market_id] = market

    def project_active(self, markets: list[Market]) -> None:
        """Replace contents with the Actor's current active set."""
        with self._lock:
            self.markets = {market.market_id: market for market in markets}

    def active(self) -> list[Market]:
        with self._lock:
            return [m for m in self.markets.values() if m.is_active]

    def get(self, market_id: str) -> Market | None:
        with self._lock:
            return self.markets.get(market_id)

    def for_token(self, token_id: str) -> Market | None:
        with self._lock:
            return next(
                (
                    market
                    for market in self.markets.values()
                    if any(
                        token.token_id == token_id for token in market.outcome_tokens
                    )
                ),
                None,
            )


@dataclass
class SpotRegistry:
    """Thread-safe spot history for AnchorPriceService / reporting paths.

    Runtime trading anchor capture uses ``SpotAnchorState`` with the same
    ``append_spot_history`` helper so history truncation stays single-source.
    """

    spots: dict[str, SpotPrice] = field(default_factory=dict)
    history: dict[str, list[SpotPrice]] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def update(self, spot: SpotPrice) -> None:
        asset = spot.asset.upper()
        with self._lock:
            self.spots[asset] = spot
            append_spot_history(self.history, spot)

    def get(self, asset: str) -> SpotPrice | None:
        with self._lock:
            return self.spots.get(asset.upper())

    def movement_pct(self, asset: str, lookback: int = 5) -> float | None:
        with self._lock:
            hist = self.history.get(asset.upper(), [])
            if len(hist) <= lookback:
                return None
            old = hist[-lookback - 1].price
            new = hist[-1].price
            return (new - old) / old if old else None
