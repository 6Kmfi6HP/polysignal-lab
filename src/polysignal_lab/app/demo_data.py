from __future__ import annotations

from datetime import timedelta

from polysignal_lab.domain.enums import MarketStatus, Side
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.domain.orderbook import BookLevel, OrderBook
from polysignal_lab.domain.spot import SpotPrice
from polysignal_lab.utils import utc_now


def sample_market(asset: str = "BTC", timeframe: str = "5m", seconds_to_close: int = 120, price_to_beat: float = 100000.0) -> Market:
    now = utc_now()
    market_id = f"{asset.lower()}-{timeframe}-demo"
    return Market(
        market_id=market_id,
        market_slug=f"{asset.lower()}-updown-{timeframe}-demo",
        condition_id=f"condition-{market_id}",
        question_id=f"question-{market_id}",
        question=f"{asset} Up or Down {timeframe}? Price to beat ${price_to_beat}",
        asset=asset,
        timeframe=timeframe,
        start_ts=now - timedelta(seconds=180),
        end_ts=now + timedelta(seconds=seconds_to_close),
        status=MarketStatus.ACTIVE,
        resolution_source="demo",
        price_to_beat=price_to_beat,
        outcome_tokens=[
            OutcomeToken(token_id=f"{market_id}-UP", side=Side.UP, outcome_name="Up", market_id=market_id),
            OutcomeToken(token_id=f"{market_id}-DOWN", side=Side.DOWN, outcome_name="Down", market_id=market_id),
        ],
    )


def sample_book(token_id: str, ask: float = 0.62, bid: float | None = None, size: float = 100.0) -> OrderBook:
    if bid is None:
        bid = max(0.01, ask - 0.03)
    return OrderBook(
        market_id=token_id.rsplit("-", 1)[0],
        token_id=token_id,
        bids=[BookLevel(price=bid, size=size), BookLevel(price=max(0.01, bid - 0.01), size=size)],
        asks=[BookLevel(price=ask, size=size), BookLevel(price=min(0.99, ask + 0.02), size=size)],
        last_trade_price=(ask + bid) / 2,
        received_at=utc_now(),
    )


def sample_spot(asset: str = "BTC", price: float = 100120.0) -> SpotPrice:
    return SpotPrice(asset=asset, symbol=f"{asset}USDT", price=price, received_at=utc_now(), event_time=utc_now())
