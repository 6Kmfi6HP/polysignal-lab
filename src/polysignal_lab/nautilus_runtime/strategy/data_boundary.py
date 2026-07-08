"""
Input: __future__, polysignal_lab.nautilus_runtime.strategy.helpers
Output: DataBoundaryClassification, classify_project_owned_data, _Assembler, _Observability, constants
Pos: Strategy data boundary classification and shared protocols

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from polysignal_lab.nautilus_runtime.strategy.helpers import (
    DEFAULT_L1_BOOK_SNAPSHOT_INTERVAL_MS,
    DEFAULT_NATIVE_DATA_NAMES,
    EVALUATION_HEARTBEAT_INTERVAL,
    EVALUATION_HEARTBEAT_TIMER_NAME,
    L1_RAW_DELTA_FALLBACK_PHASE,
    MISSING_PROJECTIONS_ERROR,
    DataBoundaryClassification,
    _Assembler,  # pyright: ignore[reportPrivateUsage]
    _Observability,  # pyright: ignore[reportPrivateUsage]
    classify_project_owned_data,
)

__all__ = [
    "DEFAULT_L1_BOOK_SNAPSHOT_INTERVAL_MS",
    "DEFAULT_NATIVE_DATA_NAMES",
    "EVALUATION_HEARTBEAT_INTERVAL",
    "EVALUATION_HEARTBEAT_TIMER_NAME",
    "L1_RAW_DELTA_FALLBACK_PHASE",
    "MISSING_PROJECTIONS_ERROR",
    "DataBoundaryClassification",
    "_Assembler",
    "_Observability",
    "classify_project_owned_data",
]
