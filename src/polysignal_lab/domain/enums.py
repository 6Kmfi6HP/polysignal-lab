from __future__ import annotations

from enum import EnumMeta, StrEnum


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


class OrderIntent(StrEnum):
    PASSIVE_GTD = "passive_gtd"
    """Resting limit buy; fills when best ask <= limit price."""
    TAKER_FAK = "taker_fak"
    """Fill-and-kill: immediate execution, partial fill ok, unexecuted portion cancelled."""
    TAKER_FOK = "taker_fok"
    """Fill-or-kill: all-or-nothing; rejects if depth insufficient for full size."""
    TAKER_IOC = "taker_ioc"
    """Immediate-or-cancel: execute immediately at best available; cancel remainder."""


class PositionStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class _TradeResultStatusMeta(EnumMeta):
    def __iter__(cls):
        return (member for member in super().__iter__() if member.name != "SPLIT")


class TradeResultStatus(StrEnum, metaclass=_TradeResultStatusMeta):
    WIN = "WIN"
    LOSS = "LOSS"
    VOID = "VOID"
    SPLIT = "SPLIT"
    UNKNOWN = "UNKNOWN"


class ExitMode(StrEnum):
    RESOLUTION = "RESOLUTION"
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    MAX_HOLD_TIME = "MAX_HOLD_TIME"
    UNKNOWN = "UNKNOWN"
