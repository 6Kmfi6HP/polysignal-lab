from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol, cast

from polysignal_lab.alpha.types import AlphaDecision
from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState
from polysignal_lab.nautilus_runtime.decision_policy import RejectedDecision


class _Assembler(Protocol):
    def build(self, condition_id: str, *, created_at: datetime) -> object | None: ...


class _Observability(Protocol):
    def record_decision(self, decision: AlphaDecision, accepted: bool) -> None: ...

    def record_rejected_decision(self, rejected: RejectedDecision) -> None: ...

    def record_nautilus_order_event(
        self,
        event: object,
        metrics: Mapping[str, object] | None = None,
    ) -> None: ...

    def record_nautilus_fill_event(
        self,
        event: object,
        metrics: Mapping[str, object] | None = None,
    ) -> None: ...

    def record_nautilus_position(self, position: object) -> None: ...


def _assembler_with_custom_data(
    assembler: _Assembler | None,
    custom_data: StrategyCustomDataState,
) -> _Assembler | None:
    if assembler is None:
        return None
    with_custom_data = getattr(assembler, "with_custom_data", None)
    if callable(with_custom_data):
        return cast(_Assembler, with_custom_data(custom_data))
    if hasattr(assembler, "custom_data"):
        setattr(assembler, "custom_data", custom_data)
    return assembler
