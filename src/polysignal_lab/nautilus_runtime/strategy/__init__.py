"""
Input: polysignal_lab.nautilus_runtime.strategy.helpers, polysignal_lab.nautilus_runtime.strategy.helpers.(  # noqa: F401, polysignal_lab.nautilus_runtime.strategy.subscriptions, polysignal_lab.nautilus_runtime.strategy.subscriptions.(  # noqa: F401
Output: None
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from polysignal_lab.nautilus_runtime.strategy.helpers import (  # noqa: F401
    DEFAULT_L1_BOOK_SNAPSHOT_INTERVAL_MS,
    DEFAULT_NATIVE_DATA_NAMES,
    EVALUATION_HEARTBEAT_INTERVAL,
    EVALUATION_HEARTBEAT_TIMER_NAME,
    L1_RAW_DELTA_FALLBACK_PHASE,
    MISSING_PROJECTIONS_ERROR,
    DataBoundaryClassification,
    _Assembler,
    _Observability,
    classify_project_owned_data,
)
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (  # noqa: F401
    InstrumentSubscriptionManager,
    MarketSubscriptionState,
)

__all__ = [
    "DEFAULT_L1_BOOK_SNAPSHOT_INTERVAL_MS",
    "DEFAULT_NATIVE_DATA_NAMES",
    "EVALUATION_HEARTBEAT_INTERVAL",
    "EVALUATION_HEARTBEAT_TIMER_NAME",
    "L1_RAW_DELTA_FALLBACK_PHASE",
    "MISSING_PROJECTIONS_ERROR",
    "DataBoundaryClassification",
    "InstrumentSubscriptionManager",
    "MarketSubscriptionState",
    "PolySignalNativeStrategy",
    "_Assembler",
    "_Observability",
    "classify_project_owned_data",
]


def __getattr__(name: str) -> object:
    """Lazily re-export PolySignalNativeStrategy to break circular import."""
    if name == "PolySignalNativeStrategy":
        from polysignal_lab.nautilus_runtime.native_strategy import (  # noqa: PLC0415
            PolySignalNativeStrategy,
        )
        return PolySignalNativeStrategy
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
