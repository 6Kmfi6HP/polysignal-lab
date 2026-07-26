from __future__ import annotations

from datetime import timedelta

DEFAULT_NATIVE_DATA_NAMES = ("quote_ticks", "trade_ticks", "order_book_deltas")
MISSING_PROJECTIONS_ERROR = (
    "PolySignalNativeStrategy requires injected registry and assembler projections"
)
EVALUATION_HEARTBEAT_TIMER_NAME = "polysignal_evaluation_heartbeat"
EVALUATION_HEARTBEAT_INTERVAL = timedelta(seconds=10)
DEFAULT_L1_BOOK_SNAPSHOT_INTERVAL_MS = 1000
