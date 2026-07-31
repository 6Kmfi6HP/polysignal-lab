from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from polysignal_lab.domain.enums import Side
from polysignal_lab.nautilus_runtime.custom_data_types import (
    PolySignalMarketMetaData,
    PolySignalMarketUniverseData,
    PolySignalPriceToBeatData,
    is_polymarket_rtds_crypto_price,
)


class DataBoundaryClassification(Enum):
    VALID_DATA = "ValidData"
    DROPPED_FRAME = "DroppedFrame"
    RECOVERABLE_FEED_ERROR = "RecoverableFeedError"
    FATAL_FEED_ERROR = "FatalFeedError"


class MarketViewState(Enum):
    INVALID = "invalid"
    UNTRADABLE = "untradable"
    TRADABLE = "tradable"


@dataclass(frozen=True, slots=True)
class MarketViewClassification:
    state: MarketViewState
    missing_quote_depth_sides: tuple[Side, ...] = ()


def classify_project_owned_data(data: object) -> DataBoundaryClassification:
    if is_polymarket_rtds_crypto_price(data) or isinstance(
        data,
        (
            PolySignalPriceToBeatData,
            PolySignalMarketMetaData,
            PolySignalMarketUniverseData,
        ),
    ):
        return DataBoundaryClassification.VALID_DATA
    if (
        type(data).__name__ == "DataEvent"
        and getattr(data, "condition_id", None) is not None
    ):
        return DataBoundaryClassification.VALID_DATA
    return DataBoundaryClassification.DROPPED_FRAME


def _book_has_quote_depth(book: object) -> bool:
    if getattr(book, "best_ask", None) is not None:
        return True
    ask_levels = getattr(book, "ask_levels", ()) or ()
    return len(ask_levels) > 0


def classify_market_view(view: object) -> MarketViewClassification:
    book_for = getattr(view, "book_for", None)
    if not callable(book_for):
        return MarketViewClassification(MarketViewState.INVALID)
    try:
        books = {side: book_for(side) for side in (Side.UP, Side.DOWN)}
    except (AttributeError, KeyError, TypeError, ValueError):
        return MarketViewClassification(MarketViewState.INVALID)
    missing_sides = tuple(
        side for side, book in books.items() if not _book_has_quote_depth(book)
    )
    if missing_sides:
        return MarketViewClassification(
            MarketViewState.UNTRADABLE,
            missing_quote_depth_sides=missing_sides,
        )
    return MarketViewClassification(MarketViewState.TRADABLE)
