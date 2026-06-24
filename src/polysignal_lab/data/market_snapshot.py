from __future__ import annotations

from polysignal_lab.data.price_to_beat_provider import PriceToBeatProvider
from polysignal_lab.data.state import OrderBookRegistry, SpotRegistry
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market
from polysignal_lab.domain.snapshot import FreshnessState, MarketSnapshot
from polysignal_lab.utils import stable_hash, utc_iso, utc_now


class MarketSnapshotBuilder:
    def __init__(self, books: OrderBookRegistry, spots: SpotRegistry, ptb_provider: PriceToBeatProvider):
        self.books = books
        self.spots = spots
        self.ptb_provider = ptb_provider

    async def build(self, market: Market) -> MarketSnapshot:
        now = utc_now()
        up_book, down_book = self.books.books_for_market(market)
        spot = self.spots.get(market.asset)
        ptb = await self.ptb_provider.get(market)
        freshness = FreshnessState(
            up_book_ms=up_book.freshness_ms(now) if up_book else None,
            down_book_ms=down_book.freshness_ms(now) if down_book else None,
            spot_ms=spot.freshness_ms(now) if spot else None,
        )
        values = [x for x in [freshness.up_book_ms, freshness.down_book_ms, freshness.spot_ms] if x is not None]
        freshness.max_ms = max(values) if values else None
        snapshot = MarketSnapshot(
            snapshot_id=f"snap_{stable_hash(market.market_id, now.isoformat())}",
            created_at=now,
            market=market,
            up_book=up_book,
            down_book=down_book,
            spot=spot,
            price_to_beat=ptb.value,
            freshness=freshness,
            metrics={
                "price_to_beat_source": ptb.source,
                "price_to_beat_verified": ptb.verified,
                "price_to_beat_from_anchor_service": ptb.from_anchor_service,
                "anchor_price_source": ptb.anchor_source,
                "anchor_price_lag_ms": ptb.anchor_lag_ms,
            },
        )
        snapshot.metrics.update(self._derived_metrics(snapshot))
        return snapshot

    def _derived_metrics(self, snapshot: MarketSnapshot) -> dict[str, float | str | None]:
        up_ask = snapshot.ask_for(Side.UP)
        down_ask = snapshot.ask_for(Side.DOWN)
        metrics: dict[str, float | str | None] = {
            "up_ask": up_ask,
            "down_ask": down_ask,
            "up_bid": snapshot.bid_for(Side.UP),
            "down_bid": snapshot.bid_for(Side.DOWN),
            "max_spread": snapshot.max_spread,
            "ask_sum": snapshot.ask_sum,
            "ask_skew": snapshot.ask_skew,
            "favorite_side": snapshot.favorite_side.value if snapshot.favorite_side else None,
            "market_status": snapshot.market.status.value,
            "resolved_outcome": snapshot.market.resolved_outcome.value if snapshot.market.resolved_outcome else None,
            "resolution_source": snapshot.market.resolution_source,
            "market_start_ts": utc_iso(snapshot.market.start_ts) if snapshot.market.start_ts else None,
            "market_end_ts": utc_iso(snapshot.market.end_ts) if snapshot.market.end_ts else None,
            "up_token_id": snapshot.market.token_for(Side.UP).token_id if any(token.side == Side.UP for token in snapshot.market.outcome_tokens) else None,
            "down_token_id": snapshot.market.token_for(Side.DOWN).token_id if any(token.side == Side.DOWN for token in snapshot.market.outcome_tokens) else None,
        }
        if snapshot.spot and snapshot.price_to_beat:
            metrics["spot_price"] = snapshot.spot.price
            metrics["price_to_beat"] = snapshot.price_to_beat
            metrics["diff_usd"] = snapshot.spot.price - snapshot.price_to_beat
        return metrics
