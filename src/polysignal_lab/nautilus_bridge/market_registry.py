from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market


@dataclass(frozen=True, slots=True)
class InstrumentTokenMeta:
    instrument_id: str
    token_id: str
    side: Side


@dataclass(frozen=True, slots=True)
class MarketPairMeta:
    market_id: str
    market_slug: str
    condition_id: str
    asset: str
    timeframe: str
    start_ts: datetime | None
    end_ts: datetime | None
    up: InstrumentTokenMeta
    down: InstrumentTokenMeta

    @classmethod
    def from_market(
        cls,
        market: Market,
        *,
        up_instrument_id: str | None = None,
        down_instrument_id: str | None = None,
    ) -> "MarketPairMeta":
        if len(market.outcome_tokens) != 2:
            raise ValueError("Only binary YES/NO markets are supported by the Nautilus bridge")
        up_token = market.token_for(Side.UP)
        down_token = market.token_for(Side.DOWN)
        return cls(
            market_id=market.market_id,
            market_slug=market.market_slug,
            condition_id=market.condition_id,
            asset=market.asset.upper(),
            timeframe=market.timeframe,
            start_ts=market.start_ts,
            end_ts=market.end_ts,
            up=InstrumentTokenMeta(
                instrument_id=up_instrument_id or up_token.token_id,
                token_id=up_token.token_id,
                side=Side.UP,
            ),
            down=InstrumentTokenMeta(
                instrument_id=down_instrument_id or down_token.token_id,
                token_id=down_token.token_id,
                side=Side.DOWN,
            ),
        )


class PolymarketMarketRegistry:
    def __init__(self) -> None:
        self._by_condition: dict[str, MarketPairMeta] = {}
        self._by_token: dict[str, MarketPairMeta] = {}

    def register(self, pair: MarketPairMeta) -> None:
        self._by_condition[pair.condition_id] = pair
        self._by_token[pair.up.token_id] = pair
        self._by_token[pair.down.token_id] = pair

    def by_condition(self, condition_id: str) -> MarketPairMeta | None:
        return self._by_condition.get(condition_id)

    def by_token(self, token_id: str) -> MarketPairMeta | None:
        return self._by_token.get(token_id)
