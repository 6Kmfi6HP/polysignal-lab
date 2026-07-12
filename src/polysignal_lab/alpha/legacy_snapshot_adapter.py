"""
Input: polysignal_lab.alpha.types, polysignal_lab.domain.signal, polysignal_lab.domain.snapshot
Output: market_view_from_snapshot, decision_to_signal
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from polysignal_lab.alpha.types import AlphaDecision, FreshnessView, MarketView, SideBookView, SpotView
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.domain.snapshot import MarketSnapshot


def market_view_from_snapshot(snapshot: MarketSnapshot) -> MarketView | None:
    def book_view(side: Side) -> SideBookView | None:
        book = snapshot.book_for(side)
        try:
            token = snapshot.market.token_for(side)
        except KeyError:
            return None
        return SideBookView(
            token_id=token.token_id,
            best_bid=book.best_bid if book else None,
            best_ask=book.best_ask if book else None,
            spread=book.spread if book else None,
            freshness_ms=book.freshness_ms(snapshot.created_at) if book else None,
            min_order_size=book.min_order_size if book else None,
            tick_size=book.tick_size if book else None,
            last_trade_price=book.last_trade_price if book else None,
            last_trade_size=book.last_trade_size if book else None,
            last_trade_timestamp=book.last_trade_timestamp if book else None,
            received_at=book.received_at if book else None,
            ask_levels=tuple((level.price, level.size) for level in book.asks) if book else (),
        )

    spot = None
    if snapshot.spot is not None:
        spot = SpotView(
            asset=snapshot.spot.asset,
            symbol=snapshot.spot.symbol,
            price=snapshot.spot.price,
            source=snapshot.spot.source,
            freshness_ms=snapshot.spot.freshness_ms(snapshot.created_at),
        )
    up = book_view(Side.UP)
    down = book_view(Side.DOWN)
    if up is None or down is None:
        return None

    return MarketView(
        view_id=snapshot.snapshot_id,
        market_id=snapshot.market.market_id,
        market_slug=snapshot.market.market_slug,
        condition_id=snapshot.market.condition_id,
        asset=snapshot.market.asset,
        timeframe=snapshot.market.timeframe,
        start_ts=snapshot.market.start_ts,
        end_ts=snapshot.market.end_ts,
        created_at=snapshot.created_at,
        seconds_to_close=snapshot.seconds_to_close,
        up=up,
        down=down,
        spot=spot,
        price_to_beat=snapshot.price_to_beat,
        up_trades=tuple(snapshot.metrics.get("up_trades") or ()),
        down_trades=tuple(snapshot.metrics.get("down_trades") or ()),
        metrics=snapshot.metrics,
        freshness=FreshnessView(
            up_book_ms=snapshot.freshness.up_book_ms,
            down_book_ms=snapshot.freshness.down_book_ms,
            spot_ms=snapshot.freshness.spot_ms,
            max_ms=snapshot.freshness.max_ms,
        ),
    )


def decision_to_signal(decision: AlphaDecision, snapshot_id: str | None, freshness_policy) -> SignalCandidate:
    return SignalCandidate.build(
        strategy=decision.strategy,
        asset=decision.asset,
        timeframe=decision.timeframe,
        market_id=decision.market_id,
        market_slug=decision.market_slug,
        condition_id=decision.condition_id,
        token_id=decision.token_id,
        side=decision.side,
        confidence=decision.confidence,
        entry_reference_price=decision.entry_reference_price,
        max_entry_price=decision.max_entry_price,
        seconds_to_close=decision.seconds_to_close,
        data_freshness_ms=decision.data_freshness_ms,
        freshness_policy=freshness_policy,
        reason_codes=list(decision.reason_codes),
        metrics=dict(decision.metrics),
        snapshot_id=snapshot_id,
        order_intent=decision.order_intent.intent if decision.order_intent else None,
        expiry_seconds=decision.order_intent.expiry_seconds if decision.order_intent else None,
        pair_id=decision.order_intent.pair_id if decision.order_intent else None,
        reduce_only=decision.order_intent.reduce_only if decision.order_intent else False,
        hedge_leg=decision.hedge_leg,
    )
