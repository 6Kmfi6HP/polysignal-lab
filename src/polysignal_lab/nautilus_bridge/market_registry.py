from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

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

    @classmethod
    def from_metadata(cls, meta: object) -> "MarketPairMeta":
        """Build a ``MarketPairMeta`` by duck-typing a metadata object.

        Reads ``market_id, market_slug, condition_id, asset, timeframe,
        start_ts_ns, end_ts_ns, up_token_id, down_token_id`` attributes without
        importing ``nautilus_runtime`` (avoids a circular import). Nanosecond
        timestamps (int or None) are converted to UTC datetimes.
        """
        start_ts_ns = getattr(meta, "start_ts_ns", None)
        end_ts_ns = getattr(meta, "end_ts_ns", None)
        start_ts = datetime.fromtimestamp(start_ts_ns / 1e9, tz=UTC) if start_ts_ns is not None else None
        end_ts = datetime.fromtimestamp(end_ts_ns / 1e9, tz=UTC) if end_ts_ns is not None else None
        up_token_id = getattr(meta, "up_token_id")
        down_token_id = getattr(meta, "down_token_id")
        return cls(
            market_id=getattr(meta, "market_id"),
            market_slug=getattr(meta, "market_slug"),
            condition_id=getattr(meta, "condition_id"),
            asset=getattr(meta, "asset").upper(),
            timeframe=getattr(meta, "timeframe"),
            start_ts=start_ts,
            end_ts=end_ts,
            up=InstrumentTokenMeta(instrument_id=up_token_id, token_id=up_token_id, side=Side.UP),
            down=InstrumentTokenMeta(instrument_id=down_token_id, token_id=down_token_id, side=Side.DOWN),
        )


class PolymarketMarketRegistry:
    def __init__(self) -> None:
        self._by_condition: dict[str, MarketPairMeta] = {}
        self._by_token: dict[str, MarketPairMeta] = {}
        self._by_instrument: dict[str, str] = {}

    def register(self, pair: MarketPairMeta) -> None:
        self._by_condition[pair.condition_id] = pair
        self._by_token[pair.up.token_id] = pair
        self._by_token[pair.down.token_id] = pair
        self._by_instrument[str(pair.up.instrument_id)] = pair.condition_id
        self._by_instrument[str(pair.down.instrument_id)] = pair.condition_id

    def by_condition(self, condition_id: str) -> MarketPairMeta | None:
        return self._by_condition.get(condition_id)

    def by_token(self, token_id: str) -> MarketPairMeta | None:
        return self._by_token.get(token_id)

    def by_instrument(self, instrument_id: str) -> MarketPairMeta | None:
        condition_id = self._by_instrument.get(instrument_id)
        if condition_id is None:
            return None
        return self._by_condition.get(condition_id)

    def condition_id_for_instrument(self, instrument_id: str) -> str | None:
        return self._by_instrument.get(instrument_id)

    def token_id_for_instrument(self, instrument_id: str) -> str | None:
        """O(1) reverse lookup from instrument_id to token_id."""
        condition_id = self._by_instrument.get(instrument_id)
        if condition_id is None:
            return None
        pair = self._by_condition.get(condition_id)
        if pair is None:
            return None
        if str(pair.up.instrument_id) == instrument_id:
            return pair.up.token_id
        if str(pair.down.instrument_id) == instrument_id:
            return pair.down.token_id
        return None

    def token_meta(self, token_id: str) -> InstrumentTokenMeta | None:
        pair = self.by_token(token_id)
        if pair is None:
            return None
        if pair.up.token_id == token_id:
            return pair.up
        if pair.down.token_id == token_id:
            return pair.down
        return None
