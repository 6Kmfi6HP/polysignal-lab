from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import import_module
from typing import cast

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market


def _nautilus_polymarket_instrument_id(condition_id: str, token_id: str) -> object:
    """Single path: official NT get_polymarket_instrument_id (no local id formatting)."""
    try:
        helper = cast(
            Callable[[str, str], object],
            getattr(
                import_module("nautilus_trader.adapters.polymarket"),
                "get_polymarket_instrument_id",
            ),
        )
    except (ModuleNotFoundError, AttributeError) as exc:
        raise RuntimeError(
            "Nautilus Polymarket adapter is required to resolve instrument IDs"
        ) from exc
    return helper(condition_id, token_id)


@dataclass(frozen=True, slots=True)
class InstrumentTokenMeta:
    token_id: str
    side: Side
    outcome: str | None = None
    description: str | None = None
    expiry: datetime | None = None


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
            raise ValueError(
                "Only binary YES/NO markets are supported by the Nautilus runtime"
            )
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
                token_id=up_token.token_id,
                side=Side.UP,
                outcome=up_token.outcome_name,
                description=market.question,
                expiry=market.end_ts,
            ),
            down=InstrumentTokenMeta(
                token_id=down_token.token_id,
                side=Side.DOWN,
                outcome=down_token.outcome_name,
                description=market.question,
                expiry=market.end_ts,
            ),
        )

    @classmethod
    def from_metadata(cls, meta: object) -> "MarketPairMeta":
        start_ts_ns = cast(int | float | None, getattr(meta, "start_ts_ns", None))
        end_ts_ns = cast(int | float | None, getattr(meta, "end_ts_ns", None))
        start_ts = (
            datetime.fromtimestamp(start_ts_ns / 1e9, tz=UTC) if start_ts_ns else None
        )
        end_ts = datetime.fromtimestamp(end_ts_ns / 1e9, tz=UTC) if end_ts_ns else None
        asset = cast(str, getattr(meta, "asset"))
        return cls(
            market_id=cast(str, getattr(meta, "market_id")),
            market_slug=cast(str, getattr(meta, "market_slug")),
            condition_id=cast(str, getattr(meta, "condition_id")),
            asset=asset.upper(),
            timeframe=cast(str, getattr(meta, "timeframe")),
            start_ts=start_ts,
            end_ts=end_ts,
            up=InstrumentTokenMeta(
                token_id=cast(str, getattr(meta, "up_token_id")),
                side=Side.UP,
                outcome=cast(str | None, getattr(meta, "up_outcome", None)),
                description=cast(str | None, getattr(meta, "question", None)),
                expiry=end_ts,
            ),
            down=InstrumentTokenMeta(
                token_id=cast(str, getattr(meta, "down_token_id")),
                side=Side.DOWN,
                outcome=cast(str | None, getattr(meta, "down_outcome", None)),
                description=cast(str | None, getattr(meta, "question", None)),
                expiry=end_ts,
            ),
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
        # Resolution is on the market-data hot path; cache per token (issue #21).
        self._instrument_id_by_token: dict[str, str] = {}
        # Derived instrument_key → timeframe index, rebuilt after any register.
        self._timeframe_index: dict[str, str] | None = None

    def register(self, pair: MarketPairMeta) -> None:
        previous = self._by_condition.get(pair.condition_id)
        if previous is not None:
            self._condition_by_token.pop(previous.up.token_id, None)
            self._condition_by_token.pop(previous.down.token_id, None)
            self._instrument_id_by_token.pop(previous.up.token_id, None)
            self._instrument_id_by_token.pop(previous.down.token_id, None)

        self._by_condition[pair.condition_id] = pair
        self._condition_by_token[pair.up.token_id] = pair.condition_id
        self._condition_by_token[pair.down.token_id] = pair.condition_id
        self._instrument_id_by_token.pop(pair.up.token_id, None)
        self._instrument_id_by_token.pop(pair.down.token_id, None)
        # Derived index is invalidated on every structural mutation.
        self._timeframe_index = None

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
        cached = self._instrument_id_by_token.get(token_id)
        if cached is not None:
            return cached
        pair = self.by_token(token_id)
        if pair is None:
            return None
        resolver = self._instrument_id_resolver
        if resolver is not None:
            instrument_id = resolver(pair.condition_id, token_id)
        else:
            condition = pair.condition_id.strip()
            token = str(token_id).strip()
            if not condition:
                raise ValueError("condition_id must not be empty")
            if not token:
                raise ValueError("token_id must not be empty")
            instrument_id = str(_nautilus_polymarket_instrument_id(condition, token))
        if instrument_id is not None:
            self._instrument_id_by_token[token_id] = instrument_id
        return instrument_id

    def market_id_for_instrument(self, instrument_id: str) -> str | None:
        for pair in self._by_condition.values():
            for token_id in (pair.up.token_id, pair.down.token_id):
                if self.instrument_id_for_token(token_id) == instrument_id:
                    return pair.market_id
        return None

    def _build_timeframe_index(self) -> None:
        index: dict[str, str] = {}
        for pair in self._by_condition.values():
            for token_id in (pair.up.token_id, pair.down.token_id):
                instrument_id = self.instrument_id_for_token(token_id)
                if instrument_id is not None:
                    index[str(instrument_id)] = pair.timeframe
        self._timeframe_index = index

    def timeframe_for_instrument(self, instrument_id: str) -> str | None:
        """Resolve the timeframe owning an instrument id, O(1) via cache.

        Index is rebuilt lazily after any register() mutation; both up and
        down legs of a condition map to the same timeframe, so an unresolved
        key is a genuine unknown instrument.
        """
        if self._timeframe_index is None:
            self._build_timeframe_index()
        index = self._timeframe_index
        assert index is not None
        return index.get(instrument_id)
