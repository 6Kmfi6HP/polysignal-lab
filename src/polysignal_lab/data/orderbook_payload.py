"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Mapping, dataclasses, dataclasses.dataclass, datetime, datetime.datetime, typing, typing.Final, typing.TypeAlias, pydantic, pydantic.JsonValue, pydantic.TypeAdapter, typing_extensions, typing_extensions.override, polysignal_lab.domain.orderbook, polysignal_lab.domain.orderbook.BookLevel, polysignal_lab.domain.orderbook.OrderBook, polysignal_lab.utils
Output: InvalidOrderBookPayload, parse_order_book_payload
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""








from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final, TypeAlias

from pydantic import JsonValue, TypeAdapter
from typing_extensions import override

from polysignal_lab.domain.orderbook import BookLevel, OrderBook
from polysignal_lab.utils import safe_float, utc_now

JsonObject: TypeAlias = Mapping[str, JsonValue]
JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


@dataclass(frozen=True, slots=True)
class InvalidOrderBookPayload(ValueError):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


def parse_order_book_payload(
    payload: JsonObject,
    received_at: datetime | None = None,
) -> OrderBook:
    return OrderBook(
        market_id=_optional_text(payload.get("market")),
        token_id=_token_id(payload),
        bids=sorted(_levels(payload.get("bids")), key=lambda level: level.price, reverse=True),
        asks=sorted(_levels(payload.get("asks")), key=lambda level: level.price),
        last_trade_price=safe_float(payload.get("last_trade_price") or payload.get("lastTradePrice")),
        last_trade_size=safe_float(
            payload.get("last_trade_size") or payload.get("lastTradeSize") or payload.get("size")
        ),
        last_trade_side=_optional_text(payload.get("side")),
        last_trade_timestamp=_optional_text(payload.get("last_trade_timestamp") or payload.get("timestamp")),
        min_order_size=safe_float(payload.get("min_order_size")),
        tick_size=safe_float(payload.get("tick_size")),
        source_timestamp=_optional_text(payload.get("timestamp")),
        hash=_optional_text(payload.get("hash")),
        received_at=received_at or utc_now(),
    )


def json_object(value: JsonValue) -> JsonObject:
    validated = JSON_VALUE_ADAPTER.validate_python(value)
    if isinstance(validated, dict):
        return {str(key): item for key, item in validated.items()}
    raise InvalidOrderBookPayload("order book payload must be a JSON object")


def _levels(raw: JsonValue | None) -> list[BookLevel]:
    if not isinstance(raw, list):
        return []
    levels: list[BookLevel] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        level = json_object(item)
        price = safe_float(level.get("price"))
        size = safe_float(level.get("size"))
        if price is None or size is None or price <= 0 or size <= 0:
            continue
        levels.append(
            BookLevel(
                price=price,
                size=size,
            )
        )
    return levels


def _token_id(payload: JsonObject) -> str:
    raw = payload.get("asset_id") or payload.get("token_id") or payload.get("assetId")
    if raw in (None, ""):
        raise InvalidOrderBookPayload("order book payload missing token id")
    return str(raw)


def _optional_text(value: JsonValue | None) -> str | None:
    return str(value) if value is not None else None
