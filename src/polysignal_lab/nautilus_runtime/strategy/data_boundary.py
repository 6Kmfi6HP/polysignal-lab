"""
Input: __future__, enum, polysignal_lab.nautilus_runtime.custom_data_types
Output: DataBoundaryClassification, classify_project_owned_data, _Assembler, _Observability, constants
Pos: Strategy data boundary classification and shared protocols

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from datetime import timedelta
from enum import Enum
from typing import Protocol

from polysignal_lab.nautilus_runtime.custom_data_types import (
    PolySignalMarketMetaData,
    PolySignalMarketUniverseData,
    PolySignalPriceToBeatData,
    PolySignalSpotData,
)

DEFAULT_NATIVE_DATA_NAMES = ("quote_ticks", "trade_ticks", "order_book_deltas")
MISSING_PROJECTIONS_ERROR = "PolySignalNativeStrategy requires injected registry and assembler projections"
EVALUATION_HEARTBEAT_TIMER_NAME = "polysignal_evaluation_heartbeat"
EVALUATION_HEARTBEAT_INTERVAL = timedelta(seconds=10)
DEFAULT_L1_BOOK_SNAPSHOT_INTERVAL_MS = 1000
L1_RAW_DELTA_FALLBACK_PHASE = "l1_raw_delta_fallback"


class DataBoundaryClassification(Enum):
    VALID_DATA = "ValidData"
    DROPPED_FRAME = "DroppedFrame"
    RECOVERABLE_FEED_ERROR = "RecoverableFeedError"
    FATAL_FEED_ERROR = "FatalFeedError"


def classify_project_owned_data(data: object) -> DataBoundaryClassification:
    if isinstance(
        data,
        (
            PolySignalSpotData,
            PolySignalPriceToBeatData,
            PolySignalMarketMetaData,
            PolySignalMarketUniverseData,
        ),
    ):
        return DataBoundaryClassification.VALID_DATA
    if type(data).__name__ == "DataEvent" and getattr(data, "condition_id", None) is not None:
        return DataBoundaryClassification.VALID_DATA
    return DataBoundaryClassification.DROPPED_FRAME


def _book_has_quote_depth(book: object) -> bool:
    if getattr(book, "best_ask", None) is not None:
        return True
    ask_levels = getattr(book, "ask_levels", ()) or ()
    return len(ask_levels) > 0


def _market_view_ready(view: object) -> bool:
    from polysignal_lab.domain.enums import Side

    try:
        up_book = view.book_for(Side.UP)
        down_book = view.book_for(Side.DOWN)
    except (AttributeError, ValueError):
        return False
    return _book_has_quote_depth(up_book) and _book_has_quote_depth(down_book)


class _Assembler(Protocol):
    def build(self, condition_id: str) -> object | None: ...


class _Observability(Protocol):
    def record_decision(self, decision: object, accepted: bool) -> None: ...

    def record_rejected_decision(self, rejected: object) -> None: ...

    def record_nautilus_order_event(self, event: object) -> None: ...

    def record_nautilus_fill_event(self, event: object) -> None: ...

    def record_nautilus_position(self, position: object) -> None: ...
