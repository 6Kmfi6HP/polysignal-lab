"""Gamma batch resolved-evidence query (issue #2): comma-joined multi-value.

Regression target: ``query_resolved_markets_by_conditions`` joined >=2
condition ids with ``",".join(batch)`` into a single comma string passed to
Gamma ``/markets?closed=true``. The live endpoint silently returns an empty
array for a comma-joined multi-value ``condition_ids`` combined with
``closed=true``, so batch reconciliation never fetched resolved evidence and
the OPEN backlog could not settle. Using ``list(batch)`` lets httpx encode
repeated params (``condition_ids=c1&condition_ids=c2``), which the live
endpoint resolves correctly (verified on the wire).

The contract under test:

- A batch of two resolved conditions each yields its own evidence entry with
  the correct per-token settlement outcome (UP-wins vs DOWN-wins).
- A single-condition batch still resolves after the fix (1-element guard).

A fake ``_SyncJsonClient`` mirrors the live Gamma contract: a comma-joined
multi-value ``condition_ids`` string returns ``[]`` (the bug), while a list or
a single value returns the requested resolved markets. Expected
``outcome_for_token`` values are taken from the known-good market literals
(independent truth), not recomputed by the code under test.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from polysignal_lab.data.gamma_resolution import (
    ResolvedMarketEvidence,
    query_resolved_markets_by_conditions,
)

_GAMMA_BASE = "https://gamma.test.example.com"


def _market(
    condition_id: str, up_token: str, down_token: str, *, up_wins: bool
) -> dict[str, Any]:
    """Known-good Gamma resolved-market literal.

    ``clobTokenIds`` aligns positionally with ``outcomePrices``: index 0 maps
    to the UP token, index 1 to the DOWN token.
    """
    return {
        "conditionId": condition_id,
        "closed": True,
        "umaResolutionStatus": "resolved",
        "clobTokenIds": [up_token, down_token],
        "outcomePrices": ["1", "0"] if up_wins else ["0", "1"],
    }


_MARKET_CA = _market("cA", "tokA_up", "tokA_down", up_wins=True)
_MARKET_CB = _market("cB", "tokB_up", "tokB_down", up_wins=False)


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


class _FakeGammaClient:
    """Mirrors the live Gamma /markets contract for condition_ids + closed=true.

    A comma-joined multi-value string silently empties (the bug); a list or a
    single value returns the requested resolved markets from the database.
    """

    def __init__(self, database: Mapping[str, dict[str, Any]]) -> None:
        self._database = database

    def get(self, url: str, params: Mapping[str, Any]) -> _FakeResponse:
        assert url.endswith("/markets")
        ids_param = params.get("condition_ids")
        assert ids_param is not None
        if isinstance(ids_param, str):
            if "," in ids_param:
                # Live Gamma silently empties a comma-joined multi-value string
                # combined with closed=true (the bug).
                return _FakeResponse([])
            requested: list[str] = [ids_param]
        elif isinstance(ids_param, (list, tuple)):
            requested = [str(item) for item in ids_param]
        else:
            requested = [str(ids_param)]
        payload = [self._database[cid] for cid in requested if cid in self._database]
        return _FakeResponse(payload)


def test_batch_resolved_returns_evidence_for_each_condition() -> None:
    """Cycle 1: >=2 conditions each parse to evidence (the core fix)."""
    client = _FakeGammaClient({"cA": _MARKET_CA, "cB": _MARKET_CB})
    result = query_resolved_markets_by_conditions(
        ["cA", "cB"],
        gamma_base_url=_GAMMA_BASE,
        client=client,
    )

    assert set(result) == {"cA", "cB"}
    evidence_a = result["cA"]
    evidence_b = result["cB"]
    assert isinstance(evidence_a, ResolvedMarketEvidence)
    assert isinstance(evidence_b, ResolvedMarketEvidence)
    # cA: UP token wins -> outcome 1.0; DOWN token -> 0.0 (from the literal).
    assert evidence_a.outcome_for_token("tokA_up") == 1.0
    assert evidence_a.outcome_for_token("tokA_down") == 0.0
    # cB: DOWN token wins -> outcome 1.0; UP token -> 0.0 (from the literal).
    assert evidence_b.outcome_for_token("tokB_down") == 1.0
    assert evidence_b.outcome_for_token("tokB_up") == 0.0


def test_single_condition_batch_resolves() -> None:
    """Cycle 2: a 1-element batch still resolves (edge guard)."""
    client = _FakeGammaClient({"cA": _MARKET_CA})
    result = query_resolved_markets_by_conditions(
        ["cA"],
        gamma_base_url=_GAMMA_BASE,
        client=client,
    )

    assert set(result) == {"cA"}
    evidence = result["cA"]
    assert isinstance(evidence, ResolvedMarketEvidence)
    assert evidence.outcome_for_token("tokA_up") == 1.0
