from __future__ import annotations

import json
from typing import Final

from nautilus_trader.core.data import Data
from nautilus_trader.model.custom import customdataclass_pyo3
from pydantic import TypeAdapter

from polysignal_lab.alpha.types import AlphaDecision, MarketView
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import RejectedDecision
from polysignal_lab.nautilus_runtime.custom_data_types import (
    _ARROW_REGISTRATION_SCHEMA,
    _FrozenData,
    _unsupported_arrow,
    register_custom_data_type,
)


_ALPHA_DECISION_ADAPTER: Final = TypeAdapter(AlphaDecision)
_MARKET_VIEW_ADAPTER: Final = TypeAdapter(MarketView)


@customdataclass_pyo3()
class DecisionCandidateData(Data, _FrozenData):
    request_id: str = ""
    batch_id: str = ""
    batch_index: int = 0
    batch_size: int = 0
    decision_json: str = ""
    view_json: str = ""
    _schema = _ARROW_REGISTRATION_SCHEMA
    to_arrow = _unsupported_arrow
    from_arrow = classmethod(_unsupported_arrow)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_frozen", True)

    @classmethod
    def from_domain(
        cls,
        *,
        request_id: str,
        batch_id: str,
        batch_index: int,
        batch_size: int,
        decision: AlphaDecision,
        view: MarketView,
        ts_event: int,
        ts_init: int,
    ) -> DecisionCandidateData:
        return cls(
            request_id=request_id,
            batch_id=batch_id,
            batch_index=batch_index,
            batch_size=batch_size,
            decision_json=_ALPHA_DECISION_ADAPTER.dump_json(decision).decode(),
            view_json=_MARKET_VIEW_ADAPTER.dump_json(view).decode(),
            ts_event=ts_event,
            ts_init=ts_init,
        )

    def to_domain(self) -> tuple[AlphaDecision, MarketView]:
        return (
            _ALPHA_DECISION_ADAPTER.validate_json(self.decision_json),
            _MARKET_VIEW_ADAPTER.validate_json(self.view_json),
        )

@customdataclass_pyo3()
class DecisionResultData(Data, _FrozenData):
    request_id: str = ""
    approved: bool = False
    signal_json: str = ""
    reason_code: str = ""
    detail_json: str = "{}"
    _schema = _ARROW_REGISTRATION_SCHEMA
    to_arrow = _unsupported_arrow
    from_arrow = classmethod(_unsupported_arrow)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_frozen", True)

    @classmethod
    def from_approved(
        cls,
        *,
        request_id: str,
        signal: SignalCandidate,
        ts_event: int,
        ts_init: int,
    ) -> DecisionResultData:
        return cls(
            request_id=request_id,
            approved=True,
            signal_json=signal.model_dump_json(),
            reason_code="",
            detail_json="{}",
            ts_event=ts_event,
            ts_init=ts_init,
        )

    @classmethod
    def from_rejected(
        cls,
        *,
        request_id: str,
        rejected: RejectedDecision,
        ts_event: int,
        ts_init: int,
    ) -> DecisionResultData:
        return cls(
            request_id=request_id,
            approved=False,
            signal_json="",
            reason_code=rejected.reason_code,
            detail_json=json.dumps(
                dict(rejected.detail),
                sort_keys=True,
                separators=(",", ":"),
            ),
            ts_event=ts_event,
            ts_init=ts_init,
        )

    def signal(self) -> SignalCandidate | None:
        if not self.approved:
            return None
        return SignalCandidate.model_validate_json(self.signal_json)

    def detail(self) -> dict[str, object]:
        value = json.loads(self.detail_json)
        if not isinstance(value, dict):
            raise ValueError("decision result detail must be an object")
        return value



register_custom_data_type(DecisionCandidateData)
register_custom_data_type(DecisionResultData)
