from polysignal_lab.nautilus_runtime.strategy.constants import (  # noqa: F401
    DEFAULT_L1_BOOK_SNAPSHOT_INTERVAL_MS,
    DEFAULT_NATIVE_DATA_NAMES,
    EVALUATION_HEARTBEAT_INTERVAL,
    EVALUATION_HEARTBEAT_TIMER_NAME,
    MISSING_PROJECTIONS_ERROR,
)
from polysignal_lab.nautilus_runtime.strategy.data_boundary import (
    DataBoundaryClassification,
    classify_project_owned_data,
)
from polysignal_lab.nautilus_runtime.strategy.protocols import (
    _Assembler,
    _Observability,
)
from polysignal_lab.nautilus_runtime.strategy.subscriptions import (  # noqa: F401
    MarketSubscriptionState,
)

__all__ = [
    "DEFAULT_L1_BOOK_SNAPSHOT_INTERVAL_MS",
    "DEFAULT_NATIVE_DATA_NAMES",
    "EVALUATION_HEARTBEAT_INTERVAL",
    "EVALUATION_HEARTBEAT_TIMER_NAME",
    "MISSING_PROJECTIONS_ERROR",
    "DataBoundaryClassification",
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
