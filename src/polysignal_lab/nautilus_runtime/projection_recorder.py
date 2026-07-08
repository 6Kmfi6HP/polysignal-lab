"""
Input: __future__, collections.abc, polysignal_lab.nautilus_runtime.projections
Output: NautilusProjectionRecorder
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from polysignal_lab.nautilus_runtime.projections import (
    project_fill_event,
    project_order_event,
    project_position,
)


class NautilusProjectionRecorder:
    """Projects Nautilus cache events into persistence-ready row payloads."""

    def __init__(self, record_event: Callable[[str, Mapping[str, object]], None]) -> None:
        self._record_event = record_event

    def record_order_event(self, event: object) -> None:
        self._record_event("nautilus_order", project_order_event(event))

    def record_fill_event(self, event: object) -> None:
        self._record_event("nautilus_fill", project_fill_event(event))

    def record_position(self, position: object) -> None:
        self._record_event("nautilus_position", project_position(position))
