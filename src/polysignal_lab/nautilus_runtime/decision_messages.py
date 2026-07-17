from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Final, TypedDict

from pydantic import TypeAdapter

from polysignal_lab.alpha.types import AlphaDecision, MarketView
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import RejectedDecision


_ALPHA_DECISION_ADAPTER: Final = TypeAdapter(AlphaDecision)
_MARKET_VIEW_ADAPTER: Final = TypeAdapter(MarketView)
DECISION_CANDIDATE_SIGNAL: Final = "polysignal.decision.candidate"
DECISION_RESULT_SIGNAL: Final = "polysignal.decision.result"


class _CandidateWire(TypedDict):
    request_id: str
    batch_id: str
    batch_index: int
    batch_size: int
    decision_json: str
    view_json: str
    ts_event: int
    ts_init: int


class _ResultWire(TypedDict):
    request_id: str
    approved: bool
    signal_json: str
    reason_code: str
    detail_json: str
    ts_event: int
    ts_init: int


_CANDIDATE_WIRE_ADAPTER: Final = TypeAdapter(_CandidateWire)
_RESULT_WIRE_ADAPTER: Final = TypeAdapter(_ResultWire)


@dataclass(frozen=True, slots=True)
class DecisionCandidateData:
    request_id: str
    batch_id: str
    batch_index: int
    batch_size: int
    decision_json: str
    view_json: str
    ts_event: int = 0
    ts_init: int = 0

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

    def to_json(self) -> str:
        return _CANDIDATE_WIRE_ADAPTER.dump_json(
            {
                "request_id": self.request_id,
                "batch_id": self.batch_id,
                "batch_index": self.batch_index,
                "batch_size": self.batch_size,
                "decision_json": self.decision_json,
                "view_json": self.view_json,
                "ts_event": self.ts_event,
                "ts_init": self.ts_init,
            }
        ).decode()

    @classmethod
    def from_json(cls, value: str) -> DecisionCandidateData:
        payload = _CANDIDATE_WIRE_ADAPTER.validate_json(value)
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class DecisionResultData:
    request_id: str
    approved: bool
    signal_json: str
    reason_code: str
    detail_json: str
    ts_event: int = 0
    ts_init: int = 0

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

    def to_json(self) -> str:
        return _RESULT_WIRE_ADAPTER.dump_json(
            {
                "request_id": self.request_id,
                "approved": self.approved,
                "signal_json": self.signal_json,
                "reason_code": self.reason_code,
                "detail_json": self.detail_json,
                "ts_event": self.ts_event,
                "ts_init": self.ts_init,
            }
        ).decode()

    @classmethod
    def from_json(cls, value: str) -> DecisionResultData:
        payload = _RESULT_WIRE_ADAPTER.validate_json(value)
        return cls(**payload)
