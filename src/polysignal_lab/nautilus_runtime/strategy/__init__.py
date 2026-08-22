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
        import importlib as _importlib

        module = _importlib.import_module(
            "polysignal_lab.nautilus_runtime.native_strategy"
        )
        return getattr(module, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
