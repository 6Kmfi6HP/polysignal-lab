from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, computed_field

from polysignal_lab.domain.enums import MarketStatus, Side
from polysignal_lab.utils import parse_dt, safe_float


class OutcomeToken(BaseModel):
    token_id: str
    side: Side
    outcome_name: str
    market_id: str


class Market(BaseModel):
    schema_version: int = 1
    market_id: str
    market_slug: str
    condition_id: str
    question_id: str | None = None
    question: str | None = None
    asset: str
    timeframe: str
    start_ts: datetime | None = None
    end_ts: datetime | None = None
    status: MarketStatus = MarketStatus.UNKNOWN
    resolution_source: str | None = None
    price_to_beat: float | None = None
    resolved_outcome: Side | None = None
    outcome_tokens: list[OutcomeToken] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)

    @computed_field
    @property
    def is_active(self) -> bool:
        return self.status == MarketStatus.ACTIVE

    def token_for(self, side: Side) -> OutcomeToken:
        for token in self.outcome_tokens:
            if token.side == side:
                return token
        raise KeyError(f"No token configured for {side} in {self.market_slug}")

    @classmethod
    def from_gamma(cls, payload: dict[str, Any], asset: str, timeframe: str) -> "Market":
        market_id = str(payload.get("id") or payload.get("market") or payload.get("conditionId") or payload.get("slug"))
        condition_id = str(payload.get("conditionId") or payload.get("condition_id") or payload.get("market") or market_id)
        slug = str(payload.get("slug") or payload.get("market_slug") or market_id)
        question_id = payload.get("questionID") or payload.get("questionId") or payload.get("question_id")
        question = payload.get("question") or payload.get("title")
        start_ts = parse_dt(payload.get("startDate") or payload.get("startDateIso") or payload.get("start_ts"))
        end_ts = parse_dt(payload.get("endDate") or payload.get("endDateIso") or payload.get("end_ts"))
        closed = bool(payload.get("closed") or payload.get("archived") or payload.get("resolved"))
        active = bool(payload.get("active", not closed))
        status = MarketStatus.RESOLVED if payload.get("resolved") else (MarketStatus.ACTIVE if active and not closed else MarketStatus.CLOSED)
        ptb = safe_float(payload.get("priceToBeat") or payload.get("price_to_beat") or payload.get("strikePrice"))
        resolution_source = payload.get("resolutionSource") or payload.get("resolution_source")
        tokens: list[OutcomeToken] = []
        token_ids = payload.get("clobTokenIds") or payload.get("tokenIds") or payload.get("tokens") or []
        outcomes = payload.get("outcomes") or ["Up", "Down"]
        if isinstance(token_ids, str):
            import json
            try:
                token_ids = json.loads(token_ids)
            except Exception:
                token_ids = [token_ids]
        if isinstance(outcomes, str):
            import json
            try:
                outcomes = json.loads(outcomes)
            except Exception:
                outcomes = [outcomes]
        for idx, token_id in enumerate(token_ids):
            if isinstance(token_id, dict):
                tid = str(token_id.get("token_id") or token_id.get("id") or token_id.get("asset_id"))
                name = str(token_id.get("outcome") or token_id.get("name") or outcomes[idx] if idx < len(outcomes) else "")
            else:
                tid = str(token_id)
                name = str(outcomes[idx]) if idx < len(outcomes) else ""
            normalized = name.strip().upper()
            if "UP" in normalized or normalized in {"YES", "1"}:
                side = Side.UP
            elif "DOWN" in normalized or normalized in {"NO", "0"}:
                side = Side.DOWN
            else:
                side = Side.UP if idx == 0 else Side.DOWN
            tokens.append(OutcomeToken(token_id=tid, side=side, outcome_name=name or side.value, market_id=market_id))
        return cls(
            market_id=market_id,
            market_slug=slug,
            condition_id=condition_id,
            question_id=str(question_id) if question_id else None,
            question=str(question) if question else None,
            asset=asset.upper(),
            timeframe=timeframe,
            start_ts=start_ts,
            end_ts=end_ts,
            status=status,
            resolution_source=str(resolution_source) if resolution_source else None,
            price_to_beat=ptb,
            outcome_tokens=tokens,
            raw=payload,
        )
