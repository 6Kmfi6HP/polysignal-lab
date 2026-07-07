"""
Input: __future__, __future__.annotations, datetime, datetime.datetime, typing, typing.Final, pydantic, pydantic.BaseModel, pydantic.Field, pydantic.JsonValue
Output: OutcomeToken, Market
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

from datetime import datetime
from typing import Final

from pydantic import BaseModel, Field, JsonValue, TypeAdapter, ValidationError, computed_field

from polysignal_lab.domain.enums import MarketStatus, Side
from polysignal_lab.utils import parse_dt, safe_float

JsonObject = dict[str, JsonValue]
JSON_LIST_ADAPTER: Final = TypeAdapter(list[JsonValue])
PTB_KEYS: Final = (
    "priceToBeat",
    "price_to_beat",
    "priceToBeatValue",
    "strikePrice",
    "targetPrice",
)
OUTCOME_KEYS: Final = (
    "winning_outcome",
    "winningOutcome",
    "resolved_outcome",
    "resolvedOutcome",
    "resolution_outcome",
    "resolutionOutcome",
    "winner",
    "result",
)
WINNING_TOKEN_KEYS: Final = (
    "winning_asset_id",
    "winningAssetId",
    "winning_token_id",
    "winningTokenId",
)
VOID_OUTCOMES: Final = {"VOID", "CANCELLED", "CANCELED", "TIE", "DRAW", "NO CONTEST"}


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
    raw: JsonObject = Field(default_factory=dict)

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
    def from_gamma(cls, payload: JsonObject, asset: str, timeframe: str) -> "Market":
        market_id = str(payload.get("id") or payload.get("market") or payload.get("conditionId") or payload.get("slug"))
        condition_id = str(payload.get("conditionId") or payload.get("condition_id") or payload.get("market") or market_id)
        slug = str(payload.get("slug") or payload.get("market_slug") or market_id)
        question_id = payload.get("questionID") or payload.get("questionId") or payload.get("question_id")
        question = payload.get("question") or payload.get("title")
        start_ts = parse_dt(_first_text(payload, ("eventStartTime", "startTime", "startDate", "startDateIso", "start_ts", "start_date")))
        end_ts = parse_dt(_first_text(payload, ("endDate", "endDateIso", "end_ts", "end_date")))
        ptb = _first_float(payload, PTB_KEYS)
        resolution_source = payload.get("resolutionSource") or payload.get("resolution_source")
        tokens: list[OutcomeToken] = []
        token_ids = _json_list(
            payload.get("clobTokenIds")
            or payload.get("clob_token_ids")
            or payload.get("tokenIds")
            or payload.get("tokens")
        )
        outcomes = _json_list(payload.get("outcomes") or payload.get("shortOutcomes")) or ["Up", "Down"]
        for idx, token_id in enumerate(token_ids):
            if isinstance(token_id, dict):
                raw_tid = token_id.get("token_id") or token_id.get("id") or token_id.get("asset_id")
                name = str(token_id.get("outcome") or token_id.get("name") or _list_text(outcomes, idx) or "")
            else:
                raw_tid = token_id
                name = _list_text(outcomes, idx) or ""
            if raw_tid is None:
                continue
            tid = str(raw_tid)
            side = _side_from_text(name) or (Side.UP if idx == 0 else Side.DOWN)
            tokens.append(OutcomeToken(token_id=tid, side=side, outcome_name=name or side.value, market_id=market_id))
        resolved_outcome = _resolved_outcome_from_gamma(payload, tokens)
        status = _status_from_gamma(payload)
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
            resolved_outcome=resolved_outcome,
            outcome_tokens=tokens,
            raw=payload,
        )


def _first_text(payload: JsonObject, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _first_float(payload: JsonObject, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = safe_float(payload.get(key))
        if value is not None:
            return value
    return None


def _json_list(raw: JsonValue | None) -> list[JsonValue]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            return JSON_LIST_ADAPTER.validate_json(raw)
        except ValidationError:
            return [raw] if raw else []
    if isinstance(raw, dict):
        return [raw]
    if raw is None:
        return []
    return [raw]


def _list_text(items: list[JsonValue], index: int) -> str | None:
    if index >= len(items):
        return None
    value = items[index]
    return str(value) if value is not None else None


def _side_from_text(value: str) -> Side | None:
    normalized = value.strip().upper()
    if normalized in {"UP", "YES", "ABOVE", "1"} or " UP" in f" {normalized} ":
        return Side.UP
    if normalized in {"DOWN", "NO", "BELOW", "0"} or " DOWN" in f" {normalized} ":
        return Side.DOWN
    return None


def _bool_value(value: JsonValue | None, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    if isinstance(value, int | float):
        return value != 0
    return default


def _has_void_resolution(payload: JsonObject) -> bool:
    outcome = _first_text(payload, OUTCOME_KEYS)
    return outcome is not None and outcome.strip().upper() in VOID_OUTCOMES



def _outcome_prices_from_gamma(payload: JsonObject) -> list[float]:
    prices = _json_list(payload.get("outcomePrices") or payload.get("outcome_prices"))
    parsed: list[float] = []
    for price in prices:
        value = safe_float(price)
        if value is None:
            return []
        parsed.append(value)
    return parsed

def _status_from_gamma(payload: JsonObject) -> MarketStatus:
    if _bool_value(payload.get("cancelled")) or _bool_value(payload.get("canceled")) or _has_void_resolution(payload):
        return MarketStatus.CANCELLED
    uma_status = payload.get("umaResolutionStatus")
    if isinstance(uma_status, str) and uma_status.strip().lower() == "resolved":
        prices = _outcome_prices_from_gamma(payload)
        if prices or _first_text(payload, WINNING_TOKEN_KEYS) or _first_text(payload, OUTCOME_KEYS):
            return MarketStatus.RESOLVED
    raw_status = _first_text(payload, ("status", "marketStatus"))
    if raw_status is not None:
        match raw_status.strip().upper():
            case "RESOLVED":
                return MarketStatus.RESOLVED
            case "CLOSED":
                return MarketStatus.CLOSED
            case "ACTIVE" | "OPEN":
                return MarketStatus.ACTIVE
            case "CANCELLED" | "CANCELED":
                return MarketStatus.CANCELLED
            case "UNKNOWN":
                return MarketStatus.UNKNOWN
    if _bool_value(payload.get("resolved")):
        return MarketStatus.RESOLVED
    closed = _bool_value(payload.get("closed")) or _bool_value(payload.get("archived"))
    active = _bool_value(payload.get("active"), default=not closed)
    if active and not closed:
        return MarketStatus.ACTIVE
    if closed:
        return MarketStatus.CLOSED
    return MarketStatus.UNKNOWN


def _resolved_outcome_from_gamma(payload: JsonObject, tokens: list[OutcomeToken]) -> Side | None:
    winning_token = _first_text(payload, WINNING_TOKEN_KEYS)
    prices = _outcome_prices_from_gamma(payload)
    if len(prices) == 2:
        if abs(prices[0] - 1.0) <= 1e-9 and abs(prices[1]) <= 1e-9:
            return Side.UP
        if abs(prices[0]) <= 1e-9 and abs(prices[1] - 1.0) <= 1e-9:
            return Side.DOWN
        if abs(prices[0] - 0.5) <= 1e-9 and abs(prices[1] - 0.5) <= 1e-9:
            return None
    if winning_token is not None:
        for token in tokens:
            if token.token_id == winning_token:
                return token.side
        return None
    outcome = _first_text(payload, OUTCOME_KEYS)
    if outcome is None or outcome.strip().upper() in VOID_OUTCOMES:
        return None
    return _side_from_text(outcome)
