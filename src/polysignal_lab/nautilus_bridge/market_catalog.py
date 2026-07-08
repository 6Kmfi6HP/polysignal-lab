"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Callable, dataclasses, dataclasses.dataclass, datetime, datetime.UTC, datetime.datetime, typing
Output: polymarket_instrument_id, InstrumentTokenMeta, MarketPairMeta, MarketCatalog
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market


from polysignal_lab.nautilus_bridge.instrument_mapping import polymarket_instrument_id


@dataclass(frozen=True, slots=True)
class InstrumentTokenMeta:
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
    def from_market(cls, market: Market) -> "MarketPairMeta":
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
            up=InstrumentTokenMeta(token_id=up_token.token_id, side=Side.UP),
            down=InstrumentTokenMeta(token_id=down_token.token_id, side=Side.DOWN),
        )

    @classmethod
    def from_metadata(cls, meta: object) -> "MarketPairMeta":
        start_ts_ns = cast(int | float | None, getattr(meta, "start_ts_ns", None))
        end_ts_ns = cast(int | float | None, getattr(meta, "end_ts_ns", None))
        start_ts = datetime.fromtimestamp(start_ts_ns / 1e9, tz=UTC) if start_ts_ns is not None else None
        end_ts = datetime.fromtimestamp(end_ts_ns / 1e9, tz=UTC) if end_ts_ns is not None else None
        asset = cast(str, getattr(meta, "asset"))
        return cls(
            market_id=cast(str, getattr(meta, "market_id")),
            market_slug=cast(str, getattr(meta, "market_slug")),
            condition_id=cast(str, getattr(meta, "condition_id")),
            asset=asset.upper(),
            timeframe=cast(str, getattr(meta, "timeframe")),
            start_ts=start_ts,
            end_ts=end_ts,
            up=InstrumentTokenMeta(token_id=cast(str, getattr(meta, "up_token_id")), side=Side.UP),
            down=InstrumentTokenMeta(token_id=cast(str, getattr(meta, "down_token_id")), side=Side.DOWN),
        )


class MarketCatalog:
    def __init__(
        self,
        *,
        instrument_id_resolver: Callable[[str, str], str] | None = None,
    ) -> None:
        self._by_condition: dict[str, MarketPairMeta] = {}
        self._condition_by_token: dict[str, str] = {}
        self._instrument_id_resolver = instrument_id_resolver

    def register(self, pair: MarketPairMeta) -> None:
        self._by_condition[pair.condition_id] = pair
        self._condition_by_token[pair.up.token_id] = pair.condition_id
        self._condition_by_token[pair.down.token_id] = pair.condition_id

    def by_condition(self, condition_id: str) -> MarketPairMeta | None:
        return self._by_condition.get(condition_id)

    def condition_ids(self) -> tuple[str, ...]:
        return tuple(self._by_condition)

    def by_token(self, token_id: str) -> MarketPairMeta | None:
        condition_id = self._condition_by_token.get(token_id)
        if condition_id is None:
            return None
        return self._by_condition.get(condition_id)

    def token_meta(self, token_id: str) -> InstrumentTokenMeta | None:
        pair = self.by_token(token_id)
        if pair is None:
            return None
        if pair.up.token_id == token_id:
            return pair.up
        if pair.down.token_id == token_id:
            return pair.down
        return None

    def instrument_id_for_token(self, token_id: str) -> str | None:
        pair = self.by_token(token_id)
        if pair is None:
            return None
        resolver = self._instrument_id_resolver or polymarket_instrument_id
        return resolver(pair.condition_id, token_id)
