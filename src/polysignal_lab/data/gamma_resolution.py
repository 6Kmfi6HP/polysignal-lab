from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Protocol, cast

import httpx
from pydantic import JsonValue, TypeAdapter

from polysignal_lab.data.market_discovery_helpers import gamma_events_from_json
from polysignal_lab.nautilus_runtime._polymarket_common_compat import build_markets_query
from polysignal_lab.utils import safe_float

JsonObject = dict[str, JsonValue]
JSON_VALUE_ADAPTER: Final = TypeAdapter(JsonValue)
GAMMA_RESOLUTION_USER_AGENT: Final = (
    "polysignal-lab/1.0 (+https://github.com/polysignal-lab)"
)
GAMMA_RESOLUTION_BATCH_SIZE: Final = 25
GAMMA_RESOLUTION_PAGE_LIMIT: Final = 100


class _SyncJsonResponse(Protocol):
    def raise_for_status(self) -> None: ...

    def json(self) -> object: ...


class _SyncJsonClient(Protocol):
    def get(self, url: str, params: Mapping[str, Any]) -> _SyncJsonResponse: ...


@dataclass(frozen=True, slots=True)
class ResolvedMarketEvidence:
    condition_id: str
    token_outcomes: Mapping[str, float]
    raw: Mapping[str, object] = field(default_factory=dict)

    def outcome_for_token(self, token_id: str) -> float | None:
        return self.token_outcomes.get(token_id)


def query_resolved_markets_by_conditions(
    condition_ids: Sequence[str],
    *,
    gamma_base_url: str,
    client: _SyncJsonClient | None = None,
) -> dict[str, ResolvedMarketEvidence]:
    """Query Gamma /markets for strict resolved evidence by condition id."""
    ids = tuple(dict.fromkeys(str(value).strip() for value in condition_ids if value))
    if not ids:
        return {}
    if client is not None:
        resolved_client = client
    else:
        resolved_client = cast(
            _SyncJsonClient,
            cast(
                object,
                httpx.Client(
                    timeout=15.0,
                    headers={"User-Agent": GAMMA_RESOLUTION_USER_AGENT},
                ),
            ),
        )
    try:
        evidence: dict[str, ResolvedMarketEvidence] = {}
        for batch in _batches(ids, GAMMA_RESOLUTION_BATCH_SIZE):
            params = build_markets_query(
                {
                    "condition_ids": list(batch),
                    "closed": "true",
                    "limit": str(GAMMA_RESOLUTION_PAGE_LIMIT),
                }
            )
            response = resolved_client.get(
                f"{gamma_base_url}/markets",
                params=params,
            )
            _ = response.raise_for_status()
            payloads = gamma_events_from_json(
                JSON_VALUE_ADAPTER.validate_python(response.json())
            )
            wanted = set(batch)
            for payload in payloads:
                parsed = resolution_evidence_from_gamma(payload)
                if parsed is not None and parsed.condition_id in wanted:
                    evidence[parsed.condition_id] = parsed
        return evidence
    finally:
        if client is None:
            close = getattr(resolved_client, "close", None)
            if callable(close):
                close()


def resolution_evidence_from_gamma(
    payload: Mapping[str, Any],
) -> ResolvedMarketEvidence | None:
    """Parse one Gamma market into strict binary settlement evidence."""
    condition_id = str(payload.get("conditionId") or payload.get("condition_id") or "")
    if not condition_id:
        return None
    uma_status = str(payload.get("umaResolutionStatus") or "").strip().lower()
    closed = _as_bool(payload.get("closed"))
    if not closed or uma_status != "resolved":
        return None
    token_ids = _string_list(
        payload.get("clobTokenIds") or payload.get("clob_token_ids")
    )
    prices = _finite_prices(payload.get("outcomePrices") or payload.get("outcome_prices"))
    if len(token_ids) != 2 or len(prices) != 2:
        return None
    if not _strict_binary_prices(prices):
        return None
    return ResolvedMarketEvidence(
        condition_id=condition_id,
        token_outcomes={
            token_id: price
            for token_id, price in zip(token_ids, prices, strict=True)
        },
        raw=dict(payload),
    )


def _batches(values: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _strict_binary_prices(prices: Sequence[float]) -> bool:
    return tuple(sorted(prices)) == (0.0, 1.0)


def _finite_prices(raw: object) -> list[float]:
    values: list[float] = []
    for item in _json_list(raw):
        parsed = safe_float(item)
        if parsed is None:
            return []
        values.append(parsed)
    return values


def _string_list(raw: object) -> list[str]:
    return [str(item).strip() for item in _json_list(raw) if item]


def _json_list(raw: object) -> list[object]:
    if isinstance(raw, list):
        return [item for item in raw if item is not None]
    if isinstance(raw, str):
        try:
            decoded = JSON_VALUE_ADAPTER.validate_json(raw)
        except Exception:
            return []
        return _json_list(decoded)
    if isinstance(raw, dict):
        return [raw]
    if raw is None:
        return []
    return [raw]


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes"}
