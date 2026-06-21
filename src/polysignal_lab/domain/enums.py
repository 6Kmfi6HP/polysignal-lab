from __future__ import annotations

from enum import StrEnum


class Side(StrEnum):
    UP = "UP"
    DOWN = "DOWN"

    @property
    def opposite(self) -> "Side":
        return Side.DOWN if self == Side.UP else Side.UP


class Action(StrEnum):
    BUY = "BUY"


class MarketStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"


class PositionStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class TradeResultStatus(StrEnum):
    WIN = "WIN"
    LOSS = "LOSS"
    VOID = "VOID"
    UNKNOWN = "UNKNOWN"
    SPLIT = "SPLIT"


class ExitMode(StrEnum):
    RESOLUTION = "RESOLUTION"
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    MAX_HOLD_TIME = "MAX_HOLD_TIME"
    UNKNOWN = "UNKNOWN"
