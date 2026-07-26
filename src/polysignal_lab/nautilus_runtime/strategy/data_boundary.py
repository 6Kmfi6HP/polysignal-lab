from __future__ import annotations

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


def _market_view_ready(view: object) -> bool:
    book_for = getattr(view, "book_for", None)
    if not callable(book_for):
        return False
    try:
        up_book = book_for(Side.UP)
        down_book = book_for(Side.DOWN)
    except ValueError:
        return False
    return _book_has_quote_depth(up_book) and _book_has_quote_depth(down_book)
