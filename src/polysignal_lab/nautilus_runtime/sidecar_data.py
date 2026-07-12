"""
Input: __future__, __future__.annotations, datetime, datetime.UTC, datetime.datetime, importlib, importlib.import_module, typing, typing.Callable, typing.Protocol
Output: market_metadata, timestamp_ns, _Publisher, CustomDataPublisher
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""








from __future__ import annotations

from datetime import UTC, datetime
from importlib import import_module
from typing import Callable, Protocol, cast

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market
from polysignal_lab.nautilus_runtime.custom_data_types import (
    PolySignalMarketMetaData,
    PolySignalMarketUniverseData,
    PolySignalPriceToBeatData,
)


class _Publisher(Protocol):
    def publish_data(self, data_type: object, data: object) -> None: ...


def _data_type(payload_cls: type[object]) -> object:
    """Return ``DataType(payload_cls)`` when Nautilus is installed, else the class itself."""
    try:
        module = import_module("nautilus_trader.model.data")
    except ModuleNotFoundError:
        return payload_cls
    data_type_cls = cast(Callable[[type[object]], object], getattr(module, "DataType"))
    return data_type_cls(payload_cls)


class CustomDataPublisher:
    def __init__(self, *, publisher: _Publisher) -> None:
        self.publisher: _Publisher = publisher

    def publish_price_to_beat(
        self,
        *,
        condition_id: str,
        value: float,
        source: str,
        verified: bool,
        from_anchor_service: bool,
        anchor_source: str | None,
        anchor_lag_ms: int | None,
        ts_event: int,
        ts_init: int,
    ) -> None:
        data = PolySignalPriceToBeatData(
            condition_id=condition_id,
            value=value,
            source=source,
            verified=verified,
            from_anchor_service=from_anchor_service,
            anchor_source=anchor_source,
            anchor_lag_ms=anchor_lag_ms,
            ts_event=ts_event,
            ts_init=ts_init,
        )
        self.publisher.publish_data(_data_type(PolySignalPriceToBeatData), data)

    def publish_market_metadata(self, meta: PolySignalMarketMetaData) -> None:
        self.publisher.publish_data(_data_type(PolySignalMarketMetaData), meta)

    def publish_market_universe(self, data: PolySignalMarketUniverseData) -> None:
        self.publisher.publish_data(_data_type(PolySignalMarketUniverseData), data)


def market_metadata(
    market: Market,
    *,
    timestamp: datetime,
) -> PolySignalMarketMetaData:
    event_ns = timestamp_ns(timestamp)
    return PolySignalMarketMetaData(
        market_id=market.market_id,
        market_slug=market.market_slug,
        condition_id=market.condition_id,
        asset=market.asset,
        timeframe=market.timeframe,
        start_ts_ns=timestamp_ns(market.start_ts),
        end_ts_ns=timestamp_ns(market.end_ts),
        up_token_id=market.token_for(Side.UP).token_id,
        down_token_id=market.token_for(Side.DOWN).token_id,
        question=market.question,
        up_outcome=market.token_for(Side.UP).outcome_name,
        down_outcome=market.token_for(Side.DOWN).outcome_name,
        ts_event=event_ns,
        ts_init=event_ns,
    )


def timestamp_ns(value: datetime | None) -> int:
    if value is None:
        return 0
    current = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    delta = current.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000
