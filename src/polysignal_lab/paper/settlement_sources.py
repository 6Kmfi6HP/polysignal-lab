from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from polysignal_lab.domain.market import Market

SettlementSource = Literal["chain", "gamma", "ws"]
SettlementConfidence = Literal["authoritative", "exact", "hint"]
SettlementStatus = Literal["resolved", "cancelled", "unresolved", "unknown", "error"]
DecisionStatus = Literal["resolved", "cancelled", "unknown"]


@dataclass(frozen=True, slots=True)
class SettlementEvidence:
    source: SettlementSource
    confidence: SettlementConfidence
    market_id: str | None
    market_slug: str | None
    condition_id: str
    outcome_values_by_token: dict[str, float]
    status: SettlementStatus
    observed_at: datetime
    raw_status: str | None = None
    error: str | None = None
    event_id: str | None = None
    raw: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ResolutionDecision:
    market_id: str
    condition_id: str
    status: DecisionStatus
    source: Literal["chain", "gamma", "ws", "none"]
    outcome_values_by_token: dict[str, float]
    conflict: bool
    conflict_sources: tuple[str, ...]
    details: dict[str, object]

    def outcome_value_for(self, token_id: str) -> float | None:
        return self.outcome_values_by_token.get(token_id)


def _loads_list(raw: object) -> list[object]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else [parsed]
    return []


def _boolish(raw: object) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"true", "1", "yes"}
    if isinstance(raw, int | float):
        return raw != 0
    return False


def _token_ids_from_payload(payload: dict[str, object], market: Market) -> list[str]:
    raw_ids = payload.get("clobTokenIds") or payload.get("clob_token_ids") or payload.get("tokenIds")
    parsed = _loads_list(raw_ids)
    ids = [str(item.get("id") or item.get("token_id") or item.get("asset_id")) if isinstance(item, dict) else str(item) for item in parsed]
    return ids or [token.token_id for token in market.outcome_tokens]


def _values_from_winning_asset(payload: dict[str, object], token_ids: list[str]) -> dict[str, float] | None:
    winner = payload.get("winning_asset_id") or payload.get("winningAssetId") or payload.get("winning_token_id") or payload.get("winningTokenId")
    if winner is None:
        return None
    winner_text = str(winner)
    if winner_text not in token_ids:
        return None
    return {token_id: 1.0 if token_id == winner_text else 0.0 for token_id in token_ids}


def _values_from_winning_outcome(payload: dict[str, object], market: Market) -> dict[str, float] | None:
    winner = payload.get("winning_outcome") or payload.get("winningOutcome") or payload.get("resolved_outcome") or payload.get("resolvedOutcome")
    if winner is None:
        return None
    winner_text = str(winner).strip().lower()
    for token in market.outcome_tokens:
        if token.outcome_name.strip().lower() == winner_text or token.side.value.lower() == winner_text:
            return {candidate.token_id: 1.0 if candidate.token_id == token.token_id else 0.0 for candidate in market.outcome_tokens}
    return None


def _terminal_prices(payload: dict[str, object], token_ids: list[str]) -> dict[str, float] | None:
    raw = payload.get("outcomePrices") or payload.get("outcome_prices")
    if raw is None:
        return None
    prices = [float(item) for item in _loads_list(raw)]
    if len(prices) != len(token_ids):
        return None
    if all(0.0 <= price <= 1.0 for price in prices):
        return dict(zip(token_ids, prices, strict=True))
    return None


def parse_gamma_resolution_payload(payload: dict[str, object], market: Market) -> SettlementEvidence:
    observed_at = datetime.now(UTC)
    token_ids = _token_ids_from_payload(payload, market)
    uma_status = str(payload.get("umaResolutionStatus") or "").strip().lower()
    raw_status = uma_status or str(payload.get("status") or payload.get("marketStatus") or "")
    cancelled = _boolish(payload.get("cancelled")) or _boolish(payload.get("canceled"))
    if cancelled:
        return SettlementEvidence("gamma", "exact", market.market_id, market.market_slug, market.condition_id, {}, "cancelled", observed_at, raw_status=raw_status, raw={"status": raw_status, "cancelled": True})

    values = None
    resolved_by_prices = uma_status == "resolved" or (_boolish(payload.get("closed")) and not _boolish(payload.get("acceptingOrders")) and _boolish(payload.get("automaticallyResolved")))
    if resolved_by_prices:
        values = _terminal_prices(payload, token_ids)
    if values is None:
        values = _values_from_winning_asset(payload, token_ids)
    if values is None:
        values = _values_from_winning_outcome(payload, market)

    return SettlementEvidence(
        "gamma",
        "exact",
        market.market_id,
        market.market_slug,
        market.condition_id,
        values or {},
        "resolved" if values is not None else "unresolved",
        observed_at,
        raw_status=raw_status,
        raw={"status": raw_status, "market_id": str(payload.get("id") or ""), "condition_id": str(payload.get("conditionId") or payload.get("condition_id") or "")},
    )


def _values_match(left: dict[str, float], right: dict[str, float]) -> bool:
    if left.keys() != right.keys():
        return False
    return all(abs(left[key] - right[key]) <= 1e-9 for key in left)


def _decision_from(evidence: SettlementEvidence, market: Market, *, conflict: bool, conflict_sources: tuple[str, ...], extra: dict[str, object] | None = None) -> ResolutionDecision:
    details: dict[str, object] = {
        "resolved_outcome": market.resolved_outcome.value if market.resolved_outcome else None,
        "settlement_source": evidence.source,
        "condition_id": evidence.condition_id,
        "payout_values_by_token": evidence.outcome_values_by_token,
        "settlement_conflict": conflict,
        "source_status": evidence.raw_status or evidence.status,
    }
    if evidence.event_id:
        details["ws_event_id"] = evidence.event_id
    if extra:
        details.update(extra)
    return ResolutionDecision(market.market_id, market.condition_id, "cancelled" if evidence.status == "cancelled" else "resolved", evidence.source, evidence.outcome_values_by_token, conflict, conflict_sources, details)


def choose_decision(evidence: list[SettlementEvidence], market: Market) -> ResolutionDecision:
    chain = next((ev for ev in evidence if ev.source == "chain" and ev.status == "resolved"), None)
    gamma = next((ev for ev in evidence if ev.source == "gamma" and ev.status in {"resolved", "cancelled"}), None)
    ws = next((ev for ev in evidence if ev.source == "ws" and ev.status == "resolved"), None)
    chain_status = next((ev.status for ev in evidence if ev.source == "chain"), None)

    if chain is not None:
        conflicts = tuple(ev.source for ev in (gamma, ws) if ev is not None and not _values_match(chain.outcome_values_by_token, ev.outcome_values_by_token))
        return _decision_from(chain, market, conflict=bool(conflicts), conflict_sources=conflicts, extra={"chain_status": "resolved", "gamma_status": gamma.raw_status if gamma else None, "ws_event_id": ws.event_id if ws else None})

    if gamma is not None and ws is not None and gamma.status == "resolved" and not _values_match(gamma.outcome_values_by_token, ws.outcome_values_by_token):
        return ResolutionDecision(market.market_id, market.condition_id, "unknown", "none", {}, True, ("gamma", "ws"), {"reason": "GAMMA_WS_CONFLICT", "chain_status": chain_status or "missing"})

    if gamma is not None:
        return _decision_from(gamma, market, conflict=False, conflict_sources=(), extra={"chain_status": chain_status or "missing", "ws_event_id": ws.event_id if ws else None})

    return ResolutionDecision(market.market_id, market.condition_id, "unknown", "none", {}, False, (), {"reason": "NO_RESOLVED_EVIDENCE", "chain_status": chain_status or "missing"})


class WsResolutionCache:
    def __init__(self) -> None:
        self._events: list[tuple[dict[str, object], datetime]] = []

    def remember(self, payload: dict[str, object]) -> None:
        self._events.append((dict(payload), datetime.now(UTC)))

    def prune(self, now: datetime, ttl_sec: int) -> None:
        self._events = [(payload, observed_at) for payload, observed_at in self._events if (now - observed_at).total_seconds() <= ttl_sec]

    def evidence_for(self, market: Market) -> SettlementEvidence | None:
        self.prune(datetime.now(UTC), ttl_sec=3600)
        for payload, observed_at in reversed(self._events):
            condition = payload.get("condition_id") or payload.get("conditionId") or payload.get("market")
            slug = payload.get("slug") or payload.get("market_slug")
            token_ids = [token.token_id for token in market.outcome_tokens]
            if condition != market.condition_id and slug != market.market_slug:
                continue
            values = _values_from_winning_asset(payload, token_ids) or _values_from_winning_outcome(payload, market)
            if values is None:
                return SettlementEvidence("ws", "hint", market.market_id, market.market_slug, market.condition_id, {}, "unknown", observed_at, event_id=str(payload.get("event_id") or ""), raw={"event_id": str(payload.get("event_id") or "")})
            return SettlementEvidence("ws", "hint", market.market_id, market.market_slug, market.condition_id, values, "resolved", observed_at, event_id=str(payload.get("event_id") or ""), raw={"event_id": str(payload.get("event_id") or "")})
        return None
