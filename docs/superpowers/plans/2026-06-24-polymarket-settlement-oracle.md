# Polymarket Settlement Oracle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve open paper positions from authoritative CTF payouts, exact Gamma resolution data, and cached CLOB `market_resolved` hints without introducing live-trading capabilities.

**Architecture:** Add a paper-scoped settlement evidence model and pure decision function, then feed it with three read-only sources: CTF JSON-RPC, exact Gamma market fetch, and a WebSocket resolution cache. Scheduler settlement checks use the resolver first and preserve existing active-market TP/SL exit evaluation when no settlement decision is available.

**Tech Stack:** Python 3.11, Pydantic, HTTPX, existing websockets feed, no Web3.py/ethers/subgraph/Bitquery dependency.

## Global Constraints

- Polygon mainnet chain id: `137`.
- Conditional Tokens contract: `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045`.
- pUSD collateral: `0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB`; read-only only, no approve/split/merge/redeem.
- UMA adapter addresses are background only; do not call adapters or recompute condition IDs.
- Do not introduce Web3.py, ethers, subgraph client, Bitquery, private keys, authenticated CLOB APIs, order placement, or redeem calls.
- WS `market_resolved` is a hint/conflict source only; WS alone must not close positions.
- Chain `payoutDenominator > 0` is authoritative; Gamma can close only when chain is disabled, unavailable, errored, or unresolved.
- Chain slot payouts must map by local/Gamma `clobTokenIds` order, not by token ID returned from chain.
- Keep bounded provenance in `PaperTradeResult.details`; do not add a new evidence table.
- Preserve existing paper TP/SL exit behavior for active markets when no settlement decision exists.
- Use existing env override format `POLYSIGNAL_LAB__DATA__POLYMARKET__SETTLEMENT__POLYGON_RPC_URL`.
- Execute in an isolated worktree via `superpowers:using-git-worktrees` when implementing.

---

## File Structure

- Create `src/polysignal_lab/paper/settlement_sources.py`: settlement evidence dataclasses, WS cache, Gamma payload parsing helpers, and pure decision logic.
- Create `src/polysignal_lab/data/ctf_resolution_client.py`: read-only ConditionalTokens JSON-RPC `eth_call` client.
- Create `src/polysignal_lab/data/gamma_resolution_client.py`: exact Gamma `/markets/{id}` plus condition-id fallback evidence client.
- Create `src/polysignal_lab/paper/settlement_resolver.py`: concurrent source coordinator.
- Modify `src/polysignal_lab/config.py`: settlement config nested under `data.polymarket`.
- Modify `config/signal_bot.yaml` and `config/signal_bot.lab.yaml`: explicit settlement defaults.
- Modify `src/polysignal_lab/domain/market.py`: normalize Gamma `umaResolutionStatus` and terminal `outcomePrices` for market state only.
- Modify `src/polysignal_lab/data/polymarket_clob_ws.py`: keep existing queue/metric and optionally remember resolved events in `WsResolutionCache`.
- Modify `src/polysignal_lab/paper/settlement.py`: accept extra bounded details and reject invalid explicit payout values.
- Modify `src/polysignal_lab/app/scheduler.py`: instantiate resolver clients/cache.
- Modify `src/polysignal_lab/app/scheduler_reporting.py`: settlement resolver integration while preserving exit evaluation fallback.
- Modify `src/polysignal_lab/app/services/market_universe_service.py`: replace closed-first-page fallback with exact Gamma lookup for `open_market_ids`.
- Add tests: `tests/test_settlement_sources.py`, `tests/test_ctf_resolution_client.py`, `tests/test_gamma_resolution_client.py`, `tests/test_scheduler_settlement_resolution.py`; extend `tests/test_market_parsing.py`, `tests/test_market_universe_service.py`, and `tests/test_websocket_contracts.py`.

---

### Task 1: Settlement Evidence, Gamma Payload Parser, WS Cache, Decision Logic

**Files:**
- Create: `src/polysignal_lab/paper/settlement_sources.py`
- Create: `tests/test_settlement_sources.py`

**Interfaces:**
- Produces: `SettlementEvidence`, `ResolutionDecision`, `parse_gamma_resolution_payload(payload, market)`, `WsResolutionCache`, `choose_decision(evidence, market)`.
- Consumes: `Market`, `OutcomeToken`, token IDs from `market.outcome_tokens`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settlement_sources.py` with these tests:

```python
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.paper.settlement_sources import (
    SettlementEvidence,
    WsResolutionCache,
    choose_decision,
    parse_gamma_resolution_payload,
)


def _market() -> Market:
    return Market(
        market_id="market-1",
        market_slug="btc-updown-5m",
        condition_id="0x" + "1" * 64,
        asset="BTC",
        timeframe="5m",
        outcome_tokens=[
            OutcomeToken(token_id="token-up", side=Side.UP, outcome_name="Up", market_id="market-1"),
            OutcomeToken(token_id="token-down", side=Side.DOWN, outcome_name="Down", market_id="market-1"),
        ],
    )


def _evidence(source: str, values: dict[str, float], status: str = "resolved") -> SettlementEvidence:
    return SettlementEvidence(
        source=source,  # type: ignore[arg-type]
        confidence="authoritative" if source == "chain" else "exact" if source == "gamma" else "hint",
        market_id="market-1",
        market_slug="btc-updown-5m",
        condition_id="0x" + "1" * 64,
        outcome_values_by_token=values,
        status=status,  # type: ignore[arg-type]
        observed_at=datetime.now(UTC),
        raw_status=status,
    )


def test_chain_evidence_wins_and_records_conflicting_gamma() -> None:
    decision = choose_decision(
        [
            _evidence("chain", {"token-up": 1.0, "token-down": 0.0}),
            _evidence("gamma", {"token-up": 0.0, "token-down": 1.0}),
        ],
        _market(),
    )

    assert decision.status == "resolved"
    assert decision.source == "chain"
    assert decision.outcome_values_by_token == {"token-up": 1.0, "token-down": 0.0}
    assert decision.conflict is True
    assert decision.conflict_sources == ("gamma",)
    assert decision.details["settlement_conflict"] is True


def test_gamma_ws_conflict_without_chain_stays_unknown() -> None:
    decision = choose_decision(
        [
            _evidence("gamma", {"token-up": 1.0, "token-down": 0.0}),
            _evidence("ws", {"token-up": 0.0, "token-down": 1.0}),
        ],
        _market(),
    )

    assert decision.status == "unknown"
    assert decision.source == "none"
    assert decision.conflict is True
    assert decision.details["reason"] == "GAMMA_WS_CONFLICT"


def test_chain_unresolved_allows_gamma_fallback() -> None:
    decision = choose_decision(
        [
            _evidence("chain", {}, status="unresolved"),
            _evidence("gamma", {"token-up": 0.5, "token-down": 0.5}),
        ],
        _market(),
    )

    assert decision.status == "resolved"
    assert decision.source == "gamma"
    assert decision.details["chain_status"] == "unresolved"


def test_gamma_outcome_prices_parse_real_resolved_shape() -> None:
    evidence = parse_gamma_resolution_payload(
        {
            "id": "market-1",
            "conditionId": "0x" + "1" * 64,
            "umaResolutionStatus": "resolved",
            "closed": True,
            "outcomePrices": '["1", "0"]',
            "outcomes": '["Up", "Down"]',
            "clobTokenIds": '["token-up", "token-down"]',
        },
        _market(),
    )

    assert evidence.status == "resolved"
    assert evidence.outcome_values_by_token == {"token-up": 1.0, "token-down": 0.0}
    assert evidence.raw_status == "resolved"


def test_ws_cache_matches_condition_slug_and_winning_asset() -> None:
    cache = WsResolutionCache()
    cache.remember({"event_id": "evt-condition", "condition_id": "0x" + "1" * 64, "winning_asset_id": "token-up"})
    cache.remember({"event_id": "evt-slug", "slug": "other-slug", "winning_asset_id": "token-down"})

    evidence = cache.evidence_for(_market())

    assert evidence is not None
    assert evidence.source == "ws"
    assert evidence.confidence == "hint"
    assert evidence.outcome_values_by_token == {"token-up": 1.0, "token-down": 0.0}
    assert evidence.event_id == "evt-condition"


def test_ws_cache_prunes_old_events() -> None:
    cache = WsResolutionCache()
    cache.remember({"event_id": "evt", "condition_id": "0x" + "1" * 64, "winning_asset_id": "token-up"})

    cache.prune(datetime.now(UTC) + timedelta(hours=2), ttl_sec=60)

    assert cache.evidence_for(_market()) is None
```

- [ ] **Step 2: Run tests and confirm failure**

Run:
```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_settlement_sources.py -v
```
Expected: fails because `polysignal_lab.paper.settlement_sources` does not exist.

- [ ] **Step 3: Implement the module**

Create `src/polysignal_lab/paper/settlement_sources.py` with:

```python
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
            winner = payload.get("winning_asset_id") or payload.get("winningAssetId")
            token_ids = [token.token_id for token in market.outcome_tokens]
            if condition != market.condition_id and slug != market.market_slug and winner not in token_ids:
                continue
            values = _values_from_winning_asset(payload, token_ids) or _values_from_winning_outcome(payload, market)
            if values is None:
                return SettlementEvidence("ws", "hint", market.market_id, market.market_slug, market.condition_id, {}, "unknown", observed_at, event_id=str(payload.get("event_id") or ""), raw={"event_id": str(payload.get("event_id") or "")})
            return SettlementEvidence("ws", "hint", market.market_id, market.market_slug, market.condition_id, values, "resolved", observed_at, event_id=str(payload.get("event_id") or ""), raw={"event_id": str(payload.get("event_id") or "")})
        return None
```

- [ ] **Step 4: Run tests and confirm pass**

Run:
```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_settlement_sources.py -v
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/paper/settlement_sources.py tests/test_settlement_sources.py
git commit -m "feat: add settlement evidence decision logic"
```

---

### Task 2: Chain CTF JSON-RPC Client

**Files:**
- Create: `src/polysignal_lab/data/ctf_resolution_client.py`
- Create: `tests/test_ctf_resolution_client.py`

**Interfaces:**
- Consumes: `condition_id: str`, `token_ids: tuple[str, ...]`.
- Produces: `CtfResolutionClient.get_payouts(condition_id, token_ids) -> SettlementEvidence`.
- Contract selectors: `payoutDenominator(bytes32)=0xdd34de67`, `payoutNumerators(bytes32,uint256)=0x0504c814`, `getOutcomeSlotCount(bytes32)=0xd42dc0c2`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_ctf_resolution_client.py`:

```python
from __future__ import annotations

import httpx
import pytest

from polysignal_lab.data.ctf_resolution_client import CtfResolutionClient

CONDITION_ID = "0x" + "a" * 64
CONTRACT = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"


def _word(value: int) -> str:
    return "0x" + hex(value)[2:].zfill(64)


def _client(results: list[object]) -> CtfResolutionClient:
    calls = iter(results)

    def handler(request: httpx.Request) -> httpx.Response:
        item = next(calls)
        if isinstance(item, Exception):
            raise item
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": item})

    client = CtfResolutionClient("https://rpc.invalid", timeout_sec=1.0, contract=CONTRACT)
    client._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


@pytest.mark.anyio
async def test_denominator_zero_returns_unresolved_without_numerators() -> None:
    evidence = await _client([_word(0)]).get_payouts(CONDITION_ID, ("token-up", "token-down"))

    assert evidence.status == "unresolved"
    assert evidence.outcome_values_by_token == {}


@pytest.mark.anyio
async def test_maps_one_zero_and_zero_one_and_half_half_vectors() -> None:
    up = await _client([_word(1), _word(2), _word(1), _word(0)]).get_payouts(CONDITION_ID, ("token-up", "token-down"))
    down = await _client([_word(1), _word(2), _word(0), _word(1)]).get_payouts(CONDITION_ID, ("token-up", "token-down"))
    half = await _client([_word(2), _word(2), _word(1), _word(1)]).get_payouts(CONDITION_ID, ("token-up", "token-down"))

    assert up.outcome_values_by_token == {"token-up": 1.0, "token-down": 0.0}
    assert down.outcome_values_by_token == {"token-up": 0.0, "token-down": 1.0}
    assert half.outcome_values_by_token == {"token-up": 0.5, "token-down": 0.5}


@pytest.mark.anyio
async def test_invalid_condition_id_does_not_call_rpc() -> None:
    evidence = await _client([]).get_payouts("bad-condition", ("token-up", "token-down"))

    assert evidence.status == "error"
    assert "condition_id" in (evidence.error or "")


@pytest.mark.anyio
async def test_rpc_error_returns_error_evidence() -> None:
    evidence = await _client([httpx.ConnectError("boom")]).get_payouts(CONDITION_ID, ("token-up", "token-down"))

    assert evidence.status == "error"
    assert "boom" in (evidence.error or "")
```

- [ ] **Step 2: Run tests and confirm failure**

Run:
```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_ctf_resolution_client.py -v
```
Expected: fails because `ctf_resolution_client.py` does not exist.

- [ ] **Step 3: Implement the client**

Create `src/polysignal_lab/data/ctf_resolution_client.py` with:

```python
from __future__ import annotations

from datetime import UTC, datetime
import re

import httpx

from polysignal_lab.paper.settlement_sources import SettlementEvidence

SELECTOR_DENOMINATOR = "0xdd34de67"
SELECTOR_NUMERATORS = "0x0504c814"
SELECTOR_SLOT_COUNT = "0xd42dc0c2"
_CONDITION_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")


class CtfResolutionClient:
    def __init__(self, rpc_url: str, *, timeout_sec: float, contract: str) -> None:
        self.rpc_url = rpc_url
        self.contract = contract
        self._http_client = httpx.AsyncClient(timeout=timeout_sec)

    async def get_payouts(self, condition_id: str, token_ids: tuple[str, ...]) -> SettlementEvidence:
        observed_at = datetime.now(UTC)
        if not _CONDITION_RE.fullmatch(condition_id):
            return self._error(condition_id, observed_at, "invalid condition_id")
        if len(token_ids) != 2:
            return self._error(condition_id, observed_at, "expected exactly two token_ids")

        try:
            condition_word = condition_id[2:].lower()
            denominator = await self._eth_call(SELECTOR_DENOMINATOR + condition_word)
            if denominator == 0:
                return SettlementEvidence("chain", "authoritative", None, None, condition_id, {}, "unresolved", observed_at, raw={"denominator": 0})

            slot_count = await self._eth_call(SELECTOR_SLOT_COUNT + condition_word)
            if slot_count != 2:
                return self._error(condition_id, observed_at, f"unsupported outcome slot count {slot_count}")

            numerators = []
            for index in (0, 1):
                numerators.append(await self._eth_call(SELECTOR_NUMERATORS + condition_word + hex(index)[2:].zfill(64)))
            if denominator > 0 and all(value == 0 for value in numerators):
                return self._error(condition_id, observed_at, "resolved condition has all-zero numerators")

            return SettlementEvidence(
                "chain",
                "authoritative",
                None,
                None,
                condition_id,
                {token_ids[0]: numerators[0] / denominator, token_ids[1]: numerators[1] / denominator},
                "resolved",
                observed_at,
                raw={"denominator": denominator, "numerators": numerators},
            )
        except Exception as exc:
            return self._error(condition_id, observed_at, str(exc)[:240])

    async def _eth_call(self, data: str) -> int:
        response = await self._http_client.post(
            self.rpc_url,
            json={"jsonrpc": "2.0", "method": "eth_call", "params": [{"to": self.contract, "data": data}, "latest"], "id": 1},
        )
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise RuntimeError(payload["error"])
        return int(str(payload["result"]), 16)

    @staticmethod
    def _error(condition_id: str, observed_at: datetime, message: str) -> SettlementEvidence:
        return SettlementEvidence("chain", "authoritative", None, None, condition_id, {}, "error", observed_at, error=message[:240])
```

- [ ] **Step 4: Run tests and confirm pass**

Run:
```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_ctf_resolution_client.py -v
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/data/ctf_resolution_client.py tests/test_ctf_resolution_client.py
git commit -m "feat: add CTF resolution JSON-RPC client"
```

---

### Task 3: Gamma Market Parsing and Exact Gamma Resolution Client

**Files:**
- Modify: `src/polysignal_lab/domain/market.py`
- Create: `src/polysignal_lab/data/gamma_resolution_client.py`
- Modify: `tests/test_market_parsing.py`
- Create: `tests/test_gamma_resolution_client.py`

**Interfaces:**
- Produces: `GammaResolutionClient.get_market(market: Market) -> SettlementEvidence`.
- Keeps settlement-specific payout parsing in `settlement_sources.parse_gamma_resolution_payload`; `Market.from_gamma()` only normalizes market status and `resolved_outcome` for existing UI/status flows.

- [ ] **Step 1: Add failing parser tests**

Append to `tests/test_market_parsing.py`:

```python
def test_gamma_uma_resolved_outcome_prices_sets_resolved_outcome() -> None:
    payload = _gamma_payload()
    payload.pop("resolved")
    payload.pop("winning_outcome")
    payload["closed"] = True
    payload["active"] = False
    payload["umaResolutionStatus"] = "resolved"
    payload["outcomePrices"] = '["1", "0"]'

    market = Market.from_gamma(payload, asset="BTC", timeframe="5m")

    assert market.status == MarketStatus.RESOLVED
    assert market.resolved_outcome == Side.UP


def test_gamma_half_half_outcome_prices_resolved_without_side_winner() -> None:
    payload = _gamma_payload()
    payload.pop("resolved")
    payload.pop("winning_outcome")
    payload["closed"] = True
    payload["active"] = False
    payload["umaResolutionStatus"] = "resolved"
    payload["outcomePrices"] = '["0.5", "0.5"]'

    market = Market.from_gamma(payload, asset="BTC", timeframe="5m")

    assert market.status == MarketStatus.RESOLVED
    assert market.resolved_outcome is None
```

- [ ] **Step 2: Add failing Gamma client tests**

Create `tests/test_gamma_resolution_client.py`:

```python
from __future__ import annotations

import httpx
import pytest

from polysignal_lab.data.gamma_resolution_client import GammaResolutionClient
from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market, OutcomeToken


def _market() -> Market:
    return Market(
        market_id="2649672",
        market_slug="btc-updown-5m",
        condition_id="0x" + "1" * 64,
        asset="BTC",
        timeframe="5m",
        outcome_tokens=[
            OutcomeToken(token_id="token-up", side=Side.UP, outcome_name="Up", market_id="2649672"),
            OutcomeToken(token_id="token-down", side=Side.DOWN, outcome_name="Down", market_id="2649672"),
        ],
    )


@pytest.mark.anyio
async def test_gamma_client_fetches_exact_market_by_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://gamma.invalid/markets/2649672"
        return httpx.Response(200, json={"id": "2649672", "conditionId": "0x" + "1" * 64, "umaResolutionStatus": "resolved", "outcomePrices": '["0", "1"]', "clobTokenIds": '["token-up", "token-down"]'})

    client = GammaResolutionClient("https://gamma.invalid")
    client._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    evidence = await client.get_market(_market())

    assert evidence.status == "resolved"
    assert evidence.outcome_values_by_token == {"token-up": 0.0, "token-down": 1.0}


@pytest.mark.anyio
async def test_gamma_client_falls_back_to_condition_query_on_404() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if str(request.url) == "https://gamma.invalid/markets/2649672":
            return httpx.Response(404)
        return httpx.Response(200, json=[{"id": "2649672", "conditionId": "0x" + "1" * 64, "umaResolutionStatus": "resolved", "outcomePrices": '["1", "0"]', "clobTokenIds": '["token-up", "token-down"]'}])

    client = GammaResolutionClient("https://gamma.invalid")
    client._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    evidence = await client.get_market(_market())

    assert evidence.status == "resolved"
    assert evidence.outcome_values_by_token == {"token-up": 1.0, "token-down": 0.0}
    assert seen[1].startswith("https://gamma.invalid/markets?condition_ids=")


@pytest.mark.anyio
async def test_gamma_client_error_evidence_on_http_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = GammaResolutionClient("https://gamma.invalid")
    client._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    evidence = await client.get_market(_market())

    assert evidence.status == "error"
    assert evidence.error
```

- [ ] **Step 3: Run tests and confirm failure**

Run:
```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_parsing.py tests/test_gamma_resolution_client.py -v
```
Expected: new market parsing tests fail; Gamma client import fails.

- [ ] **Step 4: Implement market parser enhancement**

In `src/polysignal_lab/domain/market.py`:
- Add a helper near `_resolved_outcome_from_gamma`:

```python
def _outcome_prices_from_gamma(payload: JsonObject) -> list[float]:
    prices = _json_list(payload.get("outcomePrices") or payload.get("outcome_prices"))
    parsed: list[float] = []
    for price in prices:
        value = safe_float(price)
        if value is None:
            return []
        parsed.append(value)
    return parsed
```

- In `_status_from_gamma`, before `raw_status`, add:

```python
    uma_status = payload.get("umaResolutionStatus")
    if isinstance(uma_status, str) and uma_status.strip().lower() == "resolved":
        prices = _outcome_prices_from_gamma(payload)
        if prices or _first_text(payload, WINNING_TOKEN_KEYS) or _first_text(payload, OUTCOME_KEYS):
            return MarketStatus.RESOLVED
```

- At the top of `_resolved_outcome_from_gamma`, add:

```python
    prices = _outcome_prices_from_gamma(payload)
    if len(prices) == 2:
        if abs(prices[0] - 1.0) <= 1e-9 and abs(prices[1]) <= 1e-9:
            return Side.UP
        if abs(prices[0]) <= 1e-9 and abs(prices[1] - 1.0) <= 1e-9:
            return Side.DOWN
        if abs(prices[0] - 0.5) <= 1e-9 and abs(prices[1] - 0.5) <= 1e-9:
            return None
```

- [ ] **Step 5: Implement GammaResolutionClient**

Create `src/polysignal_lab/data/gamma_resolution_client.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

import httpx

from polysignal_lab.domain.market import Market
from polysignal_lab.paper.settlement_sources import SettlementEvidence, parse_gamma_resolution_payload


class GammaResolutionClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._http_client = httpx.AsyncClient(timeout=5.0)

    async def get_market(self, market: Market) -> SettlementEvidence:
        try:
            response = await self._http_client.get(f"{self.base_url}/markets/{market.market_id}")
            if response.status_code == 404:
                response = await self._http_client.get(f"{self.base_url}/markets", params={"condition_ids": market.condition_id, "closed": "true"})
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, list) or not data:
                    raise RuntimeError("Gamma condition_ids query returned no markets")
                payload = data[0]
            else:
                response.raise_for_status()
                payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError("Gamma response was not an object")
            return parse_gamma_resolution_payload(payload, market)
        except Exception as exc:
            return SettlementEvidence("gamma", "exact", market.market_id, market.market_slug, market.condition_id, {}, "error", datetime.now(UTC), error=str(exc)[:240])
```

- [ ] **Step 6: Run tests and confirm pass**

Run:
```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_parsing.py tests/test_gamma_resolution_client.py tests/test_settlement_sources.py -v
```
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/polysignal_lab/domain/market.py src/polysignal_lab/data/gamma_resolution_client.py tests/test_market_parsing.py tests/test_gamma_resolution_client.py
git commit -m "feat: add exact Gamma settlement resolution"
```

---

### Task 4: Settlement Config and WebSocket Cache Hook

**Files:**
- Modify: `src/polysignal_lab/config.py`
- Modify: `config/signal_bot.yaml`
- Modify: `config/signal_bot.lab.yaml`
- Modify: `src/polysignal_lab/data/polymarket_clob_ws.py`
- Modify: `tests/test_websocket_contracts.py`
- Create: `tests/test_settlement_config.py`

**Interfaces:**
- Produces: `settings.data.polymarket.settlement`.
- Modifies: `PolymarketMarketWebSocket(..., resolution_cache: WsResolutionCache | None = None)`.

- [ ] **Step 1: Write failing config test**

Create `tests/test_settlement_config.py`:

```python
from polysignal_lab.config import Settings, load_settings


def test_default_settlement_config() -> None:
    config = Settings().data.polymarket.settlement

    assert config.chain_enabled is True
    assert config.polygon_rpc_url == ""
    assert config.chain_timeout_sec == 3.0
    assert config.gamma_enabled is True
    assert config.ws_enabled is True
    assert config.prefer_chain is True


def test_settlement_env_override(monkeypatch) -> None:
    monkeypatch.setenv("POLYSIGNAL_LAB__DATA__POLYMARKET__SETTLEMENT__POLYGON_RPC_URL", "https://rpc.example")

    settings = load_settings()

    assert settings.data.polymarket.settlement.polygon_rpc_url == "https://rpc.example"
```

- [ ] **Step 2: Write failing websocket test**

Add to `tests/test_websocket_contracts.py`:

```python
def test_market_resolved_message_updates_resolution_cache() -> None:
    from polysignal_lab.config import PolymarketDataConfig
    from polysignal_lab.data.polymarket_clob_ws import PolymarketMarketWebSocket
    from polysignal_lab.data.state import OrderBookRegistry
    from polysignal_lab.domain.enums import Side
    from polysignal_lab.domain.market import Market, OutcomeToken
    from polysignal_lab.paper.settlement_sources import WsResolutionCache

    cache = WsResolutionCache()
    ws = PolymarketMarketWebSocket(PolymarketDataConfig(), OrderBookRegistry(), resolution_cache=cache)
    ws.handle_message({"event_type": "market_resolved", "condition_id": "0x" + "1" * 64, "winning_asset_id": "token-up"})

    market = Market(
        market_id="market-1",
        market_slug="slug",
        condition_id="0x" + "1" * 64,
        asset="BTC",
        timeframe="5m",
        outcome_tokens=[
            OutcomeToken(token_id="token-up", side=Side.UP, outcome_name="Up", market_id="market-1"),
            OutcomeToken(token_id="token-down", side=Side.DOWN, outcome_name="Down", market_id="market-1"),
        ],
    )

    assert ws.resolved_events.qsize() == 1
    assert cache.evidence_for(market).outcome_values_by_token == {"token-up": 1.0, "token-down": 0.0}
```

- [ ] **Step 3: Run tests and confirm failure**

Run:
```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_settlement_config.py tests/test_websocket_contracts.py -v
```
Expected: config test fails because `settlement` is missing; websocket test fails because constructor does not accept `resolution_cache`.

- [ ] **Step 4: Implement config**

In `src/polysignal_lab/config.py`, before `PolymarketDataConfig`, add:

```python
class PolymarketSettlementConfig(BaseModel):
    chain_enabled: bool = True
    polygon_rpc_url: str = ""
    chain_timeout_sec: float = 3.0
    gamma_enabled: bool = True
    ws_enabled: bool = True
    prefer_chain: bool = True
```

Inside `PolymarketDataConfig`, add:

```python
    settlement: PolymarketSettlementConfig = Field(default_factory=PolymarketSettlementConfig)
```

Under `data.polymarket` in both `config/signal_bot.yaml` and `config/signal_bot.lab.yaml`, add:

```yaml
    settlement:
      chain_enabled: true
      polygon_rpc_url: ""
      chain_timeout_sec: 3.0
      gamma_enabled: true
      ws_enabled: true
      prefer_chain: true
```

Use the existing YAML indentation under `data.polymarket`; do not introduce a top-level `settlement` key.

- [ ] **Step 5: Implement websocket hook**

In `src/polysignal_lab/data/polymarket_clob_ws.py`:
- Import only for type checking to avoid runtime cycles:

```python
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from polysignal_lab.paper.settlement_sources import WsResolutionCache
```

- Update constructor signature and attribute:

```python
    def __init__(self, config: PolymarketDataConfig, registry: OrderBookRegistry, resolution_cache: "WsResolutionCache | None" = None):
        self.config = config
        self.registry = registry
        self.resolved_events: Queue[JsonObject] = Queue()
        self.resolution_cache = resolution_cache
```

Keep the existing remaining attributes exactly as they are.

- In the `market_resolved` branch, replace the queue call with:

```python
                event = {"event_id": new_id("resolved"), **payload}
                self.resolved_events.put_nowait(event)
                if self.resolution_cache is not None:
                    self.resolution_cache.remember(dict(event))
```

- [ ] **Step 6: Run tests and confirm pass**

Run:
```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_settlement_config.py tests/test_websocket_contracts.py -v
```
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/polysignal_lab/config.py config/signal_bot.yaml config/signal_bot.lab.yaml src/polysignal_lab/data/polymarket_clob_ws.py tests/test_settlement_config.py tests/test_websocket_contracts.py
git commit -m "feat: configure settlement sources and cache WS resolution events"
```

---

### Task 5: SettlementResolver Coordinator

**Files:**
- Create: `src/polysignal_lab/paper/settlement_resolver.py`
- Create: `tests/test_settlement_resolver.py`

**Interfaces:**
- Produces: `SettlementResolver.resolve_market(market: Market) -> ResolutionDecision`.
- Consumes: optional chain client, optional Gamma client, optional `WsResolutionCache`.

- [ ] **Step 1: Write failing resolver tests**

Create `tests/test_settlement_resolver.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
import logging
from unittest.mock import AsyncMock, Mock

import pytest

from polysignal_lab.domain.enums import Side
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.paper.settlement_resolver import SettlementResolver
from polysignal_lab.paper.settlement_sources import SettlementEvidence


def _market() -> Market:
    return Market(
        market_id="market-1",
        market_slug="slug",
        condition_id="0x" + "1" * 64,
        asset="BTC",
        timeframe="5m",
        outcome_tokens=[
            OutcomeToken(token_id="token-up", side=Side.UP, outcome_name="Up", market_id="market-1"),
            OutcomeToken(token_id="token-down", side=Side.DOWN, outcome_name="Down", market_id="market-1"),
        ],
    )


def _chain_result() -> SettlementEvidence:
    return SettlementEvidence("chain", "authoritative", "market-1", "slug", "0x" + "1" * 64, {"token-up": 1.0, "token-down": 0.0}, "resolved", datetime.now(UTC))


@pytest.mark.anyio
async def test_resolver_collects_chain_gamma_and_ws() -> None:
    chain = AsyncMock()
    gamma = AsyncMock()
    ws_cache = Mock()
    chain.get_payouts.return_value = _chain_result()
    gamma.get_market.return_value = SettlementEvidence("gamma", "exact", "market-1", "slug", "0x" + "1" * 64, {"token-up": 1.0, "token-down": 0.0}, "resolved", datetime.now(UTC))
    ws_cache.evidence_for.return_value = None

    decision = await SettlementResolver(chain, gamma, ws_cache, logger=logging.getLogger("test")).resolve_market(_market())

    assert decision.status == "resolved"
    assert decision.source == "chain"
    chain.get_payouts.assert_awaited_once_with("0x" + "1" * 64, ("token-up", "token-down"))
    gamma.get_market.assert_awaited_once()
    ws_cache.evidence_for.assert_called_once()


@pytest.mark.anyio
async def test_resolver_turns_source_exception_into_retryable_decision() -> None:
    chain = AsyncMock()
    gamma = AsyncMock()
    chain.get_payouts.side_effect = RuntimeError("rpc down")
    gamma.get_market.return_value = SettlementEvidence("gamma", "exact", "market-1", "slug", "0x" + "1" * 64, {}, "unresolved", datetime.now(UTC))

    decision = await SettlementResolver(chain, gamma, None, logger=logging.getLogger("test")).resolve_market(_market())

    assert decision.status == "unknown"
    assert decision.details["reason"] == "NO_RESOLVED_EVIDENCE"
```

- [ ] **Step 2: Run tests and confirm failure**

Run:
```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_settlement_resolver.py -v
```
Expected: fails because `settlement_resolver.py` does not exist.

- [ ] **Step 3: Implement resolver**

Create `src/polysignal_lab/paper/settlement_resolver.py`:

```python
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import logging
from typing import Protocol

from polysignal_lab.domain.market import Market
from polysignal_lab.paper.settlement_sources import ResolutionDecision, SettlementEvidence, WsResolutionCache, choose_decision


class ChainResolutionSource(Protocol):
    async def get_payouts(self, condition_id: str, token_ids: tuple[str, ...]) -> SettlementEvidence: ...


class GammaResolutionSource(Protocol):
    async def get_market(self, market: Market) -> SettlementEvidence: ...


class SettlementResolver:
    def __init__(self, chain: ChainResolutionSource | None, gamma: GammaResolutionSource | None, ws_cache: WsResolutionCache | None, *, logger: logging.Logger) -> None:
        self.chain = chain
        self.gamma = gamma
        self.ws_cache = ws_cache
        self.logger = logger

    async def resolve_market(self, market: Market) -> ResolutionDecision:
        token_ids = tuple(token.token_id for token in market.outcome_tokens)
        pending: list[tuple[str, object]] = []
        if self.chain is not None:
            pending.append(("chain", self.chain.get_payouts(market.condition_id, token_ids)))
        if self.gamma is not None:
            pending.append(("gamma", self.gamma.get_market(market)))

        evidence: list[SettlementEvidence] = []
        if pending:
            results = await asyncio.gather(*(task for _, task in pending), return_exceptions=True)
            for (source, _), result in zip(pending, results, strict=True):
                if isinstance(result, Exception):
                    self.logger.warning("settlement %s source failed for %s: %s", source, market.market_id, result)
                    evidence.append(SettlementEvidence(source, "authoritative" if source == "chain" else "exact", market.market_id, market.market_slug, market.condition_id, {}, "error", datetime.now(UTC), error=str(result)[:240]))
                else:
                    evidence.append(result)

        if self.ws_cache is not None:
            ws_evidence = self.ws_cache.evidence_for(market)
            if ws_evidence is not None:
                evidence.append(ws_evidence)

        return choose_decision(evidence, market)
```

- [ ] **Step 4: Run tests and confirm pass**

Run:
```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_settlement_resolver.py tests/test_settlement_sources.py -v
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/paper/settlement_resolver.py tests/test_settlement_resolver.py
git commit -m "feat: coordinate settlement evidence sources"
```

---

### Task 6: Exact Resolved Market Refresh Compatibility

**Files:**
- Modify: `src/polysignal_lab/app/services/market_universe_service.py`
- Modify: `tests/test_market_universe_service.py`

**Interfaces:**
- Modifies: `MarketUniverseService.fetch_resolved(open_market_ids)` to fetch exact market IDs instead of closed first page.
- Preserves: custom `discovery.resolved_markets()` hook used by tests.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_market_universe_service.py`:

```python
@pytest.mark.anyio
async def test_fetch_resolved_uses_exact_market_lookup_for_open_ids(monkeypatch) -> None:
    from polysignal_lab.app.services.market_universe_service import MarketUniverseService
    from polysignal_lab.config import Settings
    from polysignal_lab.data.state import MarketRegistry
    from polysignal_lab.domain.enums import MarketStatus
    from factories import sample_market

    calls: list[str] = []

    class _Response:
        status_code = 200
        def json(self) -> dict[str, object]:
            return {
                "id": "market-1",
                "conditionId": "condition-1",
                "slug": "slug-1",
                "umaResolutionStatus": "resolved",
                "outcomePrices": '["1", "0"]',
                "clobTokenIds": '["token-up", "token-down"]',
                "outcomes": '["Up", "Down"]',
            }
        def raise_for_status(self) -> None:
            return None

    class _Client:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def get(self, url: str, params: dict[str, str] | None = None):
            calls.append(url)
            return _Response()

    monkeypatch.setattr("polysignal_lab.app.services.market_universe_service.httpx.AsyncClient", _Client)
    registry = MarketRegistry()
    registry.upsert_many([sample_market().model_copy(update={"market_id": "market-1", "condition_id": "condition-1"})])
    service = MarketUniverseService(discovery=object(), markets=registry, persistence=object(), settings=Settings())
    service.persistence.upsert_market = lambda market: None

    resolved = await service.fetch_resolved({"market-1"})

    assert resolved[0].market_id == "market-1"
    assert resolved[0].status == MarketStatus.RESOLVED
    assert calls == ["https://gamma-api.polymarket.com/markets/market-1"]
```

- [ ] **Step 2: Run test and confirm failure**

Run:
```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_universe_service.py::test_fetch_resolved_uses_exact_market_lookup_for_open_ids -v
```
Expected: fails because current fallback calls `/markets?closed=true&limit=200&offset=0`.

- [ ] **Step 3: Implement exact lookup**

In `src/polysignal_lab/app/services/market_universe_service.py`, keep the `resolved_markets` hook. Replace the closed-page fallback with this behavior:

```python
        if not open_market_ids or self.settings is None:
            return []

        resolved: list[Market] = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            for market_id in sorted(open_market_ids):
                local_market = self.markets.get(market_id)
                response = await client.get(f"{self.settings.data.polymarket.gamma_base_url}/markets/{market_id}")
                if response.status_code == 404 and local_market is not None and local_market.condition_id:
                    response = await client.get(
                        f"{self.settings.data.polymarket.gamma_base_url}/markets",
                        params={"condition_ids": local_market.condition_id, "closed": "true"},
                    )
                if response.status_code != 200:
                    continue
                data = response.json()
                payload = data[0] if isinstance(data, list) and data else data
                if not isinstance(payload, dict):
                    continue
                match = self.discovery._match_crypto_updown(payload) if hasattr(self.discovery, "_match_crypto_updown") else None
                asset, timeframe = match if match else ((local_market.asset, local_market.timeframe) if local_market else ("UNKNOWN", "UNKNOWN"))
                market = Market.from_gamma(payload, asset=asset, timeframe=timeframe)
                if market.status in {MarketStatus.RESOLVED, MarketStatus.CANCELLED}:
                    resolved.append(market)
```

Then call `self._store_resolved(resolved)` and log as the existing method does.

- [ ] **Step 4: Run tests and confirm pass**

Run:
```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_market_universe_service.py -v
```
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/polysignal_lab/app/services/market_universe_service.py tests/test_market_universe_service.py
git commit -m "fix: use exact Gamma lookup for resolved open markets"
```

---

### Task 7: Scheduler Settlement Integration

**Files:**
- Modify: `src/polysignal_lab/paper/settlement.py`
- Modify: `src/polysignal_lab/app/scheduler.py`
- Modify: `src/polysignal_lab/app/scheduler_reporting.py`
- Create: `tests/test_scheduler_settlement_resolution.py`

**Interfaces:**
- Consumes: `scheduler.settlement_resolver.resolve_market(market)`.
- Produces: `PaperTradeResult.details` provenance and correct numeric payout settlement.
- Preserves: active-market `scheduler.exits.evaluate(position, book)` fallback when resolver returns unknown.

- [ ] **Step 1: Write failing tests**

Create `tests/test_scheduler_settlement_resolution.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from polysignal_lab.app.scheduler_reporting import check_settlements
from polysignal_lab.domain.enums import MarketStatus, PositionStatus, Side, TradeResultStatus
from polysignal_lab.domain.market import Market, OutcomeToken
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.paper.settlement import PaperSettlementEngine
from polysignal_lab.paper.settlement_sources import ResolutionDecision
from polysignal_lab.paper.wallet import PaperWallet


def _market(status: MarketStatus = MarketStatus.ACTIVE) -> Market:
    return Market(
        market_id="market-1",
        market_slug="slug",
        condition_id="0x" + "1" * 64,
        asset="BTC",
        timeframe="5m",
        status=status,
        outcome_tokens=[
            OutcomeToken(token_id="token-up", side=Side.UP, outcome_name="Up", market_id="market-1"),
            OutcomeToken(token_id="token-down", side=Side.DOWN, outcome_name="Down", market_id="market-1"),
        ],
    )


def _position(token_id: str = "token-up", side: Side = Side.UP) -> PaperPosition:
    return PaperPosition(
        signal_id="sig-1",
        paper_order_id="order-1",
        paper_fill_id="fill-1",
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="market-1",
        market_slug="slug",
        token_id=token_id,
        side=side,
        entry_price=0.40,
        shares=25.0,
        stake_usdc=10.0,
    )


def _scheduler(wallet: PaperWallet, market: Market, decision: ResolutionDecision) -> Mock:
    scheduler = Mock()
    scheduler.wallet = wallet
    scheduler.settlement = PaperSettlementEngine(wallet)
    scheduler.settlement_resolver = AsyncMock()
    scheduler.settlement_resolver.resolve_market.return_value = decision
    scheduler.ctx.markets.get.return_value = market
    scheduler.persistence.insert_paper_trade_result.return_value = None
    scheduler.persistence.upsert_paper_position.return_value = None
    scheduler.persistence.append_log.return_value = None
    scheduler.persistence.insert_system_event.return_value = None
    scheduler.settings.telegram.send_paper_results = False
    return scheduler


@pytest.mark.anyio
async def test_resolved_numeric_half_payout_closes_as_void_with_provenance() -> None:
    wallet = PaperWallet(1000.0)
    position = _position()
    wallet.apply_fill(position)
    scheduler = _scheduler(
        wallet,
        _market(),
        ResolutionDecision("market-1", "0x" + "1" * 64, "resolved", "chain", {"token-up": 0.5, "token-down": 0.5}, False, (), {"settlement_source": "chain", "condition_id": "0x" + "1" * 64}),
    )

    results = await check_settlements(scheduler)

    assert len(results) == 1
    assert results[0].result == TradeResultStatus.VOID
    assert results[0].outcome_value == 0.5
    assert results[0].settlement_value == 12.5
    assert results[0].details["settlement_source"] == "chain"
    assert position.status == PositionStatus.CLOSED


@pytest.mark.anyio
async def test_unknown_settlement_preserves_existing_active_exit_evaluation() -> None:
    wallet = PaperWallet(1000.0)
    position = _position()
    wallet.apply_fill(position)
    decision = ResolutionDecision("market-1", "0x" + "1" * 64, "unknown", "none", {}, False, (), {"reason": "NO_RESOLVED_EVIDENCE"})
    scheduler = _scheduler(wallet, _market(MarketStatus.ACTIVE), decision)
    scheduler.ctx.books.get.return_value = object()
    scheduler.exits.evaluate.return_value = None

    results = await check_settlements(scheduler)

    assert results == []
    scheduler.exits.evaluate.assert_called_once_with(position, scheduler.ctx.books.get.return_value)
    assert position.status == PositionStatus.OPEN


@pytest.mark.anyio
async def test_cancelled_decision_uses_refund_path() -> None:
    wallet = PaperWallet(1000.0)
    position = _position()
    wallet.apply_fill(position)
    decision = ResolutionDecision("market-1", "0x" + "1" * 64, "cancelled", "gamma", {}, False, (), {"settlement_source": "gamma"})
    scheduler = _scheduler(wallet, _market(MarketStatus.CLOSED), decision)

    results = await check_settlements(scheduler)

    assert results[0].result == TradeResultStatus.VOID
    assert results[0].outcome_value == position.entry_price
    assert results[0].settlement_value == position.stake_usdc


@pytest.mark.anyio
async def test_chain_conflict_settlement_logs_system_event() -> None:
    wallet = PaperWallet(1000.0)
    position = _position()
    wallet.apply_fill(position)
    decision = ResolutionDecision("market-1", "0x" + "1" * 64, "resolved", "chain", {"token-up": 1.0, "token-down": 0.0}, True, ("gamma",), {"settlement_source": "chain", "settlement_conflict": True})
    scheduler = _scheduler(wallet, _market(), decision)

    results = await check_settlements(scheduler)

    assert results[0].result == TradeResultStatus.WIN
    scheduler.persistence.insert_system_event.assert_called_once()
```

- [ ] **Step 2: Run tests and confirm failure**

Run:
```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_scheduler_settlement_resolution.py -v
```
Expected: fails because resolver is not wired and `settle()` does not accept `details`.

- [ ] **Step 3: Update PaperSettlementEngine**

In `src/polysignal_lab/paper/settlement.py`, change signature to:

```python
    def settle(
        self,
        position: PaperPosition,
        market: Market,
        outcome_value: float | None = None,
        details: dict[str, object] | None = None,
    ) -> PaperTradeResult:
```

In explicit payout handling, replace the final `else: status = TradeResultStatus.VOID` with:

```python
            else:
                status = TradeResultStatus.UNKNOWN
                outcome_value = 0.0
```

When creating `PaperTradeResult`, set details to:

```python
            details={
                "resolved_outcome": market.resolved_outcome.value if market.resolved_outcome else None,
                "confidence": position.signal_confidence,
                **(details or {}),
            },
```

This preserves current unknown behavior and prevents invalid `<0` or `>1` payouts from silently closing positions.

- [ ] **Step 4: Instantiate resolver in scheduler**

In `src/polysignal_lab/app/scheduler.py`, import:

```python
from polysignal_lab.data.ctf_resolution_client import CtfResolutionClient
from polysignal_lab.data.gamma_resolution_client import GammaResolutionClient
from polysignal_lab.paper.settlement_resolver import SettlementResolver
from polysignal_lab.paper.settlement_sources import WsResolutionCache
```

Before creating `PolymarketMarketWebSocket`, add:

```python
        self.ws_resolution_cache = WsResolutionCache()
```

Create the websocket with:

```python
        self.poly_ws = PolymarketMarketWebSocket(settings.data.polymarket, self.ctx.books, resolution_cache=self.ws_resolution_cache)
```

After `self.market_universe = MarketUniverseService(...)`, add:

```python
        settlement_config = settings.data.polymarket.settlement
        chain_source = None
        if settlement_config.chain_enabled and settlement_config.polygon_rpc_url:
            chain_source = CtfResolutionClient(
                settlement_config.polygon_rpc_url,
                timeout_sec=settlement_config.chain_timeout_sec,
                contract="0x4D97DCd97eC945f40cF65F87097ACe5EA0476045",
            )
        gamma_source = GammaResolutionClient(settings.data.polymarket.gamma_base_url) if settlement_config.gamma_enabled else None
        self.settlement_resolver = SettlementResolver(
            chain_source,
            gamma_source,
            self.ws_resolution_cache if settlement_config.ws_enabled else None,
            logger=self.logger,
        )
```

- [ ] **Step 5: Integrate resolver in check_settlements without dropping exits**

In `src/polysignal_lab/app/scheduler_reporting.py`, add a helper near `_store_paper_result`:

```python
def _should_evaluate_exit_after_unknown_resolution(market: Market) -> bool:
    return market.status in {MarketStatus.ACTIVE, MarketStatus.CLOSED, MarketStatus.UNKNOWN}
```

Inside `check_settlements`, after market lookup and before the existing `match market.status`, insert:

```python
        decision = await scheduler.settlement_resolver.resolve_market(market)
        if decision.status == "cancelled":
            try:
                result = scheduler.settlement.settle(
                    position,
                    market.model_copy(update={"status": MarketStatus.CANCELLED}),
                    details=decision.details,
                )
            except (KeyError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
                scheduler.logger.error("Failed to settle position %s: %s", position.paper_position_id, exc)
                continue
        elif decision.status == "resolved":
            outcome_value = decision.outcome_value_for(position.token_id)
            if outcome_value is None:
                scheduler.logger.warning("No settlement payout for token %s in market %s", position.token_id, market.market_id)
                continue
            try:
                result = scheduler.settlement.settle(position, market, outcome_value=outcome_value, details=decision.details)
            except (KeyError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
                scheduler.logger.error("Failed to settle position %s: %s", position.paper_position_id, exc)
                continue
        elif _should_evaluate_exit_after_unknown_resolution(market):
            book = scheduler.ctx.books.get(position.token_id)
            if book is None:
                continue
            try:
                result = scheduler.exits.evaluate(position, book)
            except (KeyError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
                scheduler.logger.error("Failed to evaluate paper exit for position %s: %s", position.paper_position_id, exc)
                continue
            if result is None:
                continue
        else:
            continue
```

Remove the old `match market.status` block lines 62-111. Keep rollback, persistence, append, and log code after it unchanged.

After successful `_store_paper_result`, if `decision.conflict` is true, insert:

```python
        if decision.conflict:
            event = {
                "event_id": new_id("evt", "settlement_conflict", result.paper_trade_id),
                "event_type": "settlement_conflict",
                "severity": "WARNING",
                "created_at": utc_iso(),
                "market_id": decision.market_id,
                "condition_id": decision.condition_id,
                "paper_trade_id": result.paper_trade_id,
                "conflict_sources": list(decision.conflict_sources),
            }
            try:
                scheduler.persistence.insert_system_event(event)
                scheduler.persistence.append_log("system_events", event)
            except (OSError, sqlite3.Error, TypeError, ValueError):
                scheduler.logger.warning("Failed to audit settlement conflict for %s", decision.market_id)
```

- [ ] **Step 6: Run tests and confirm pass**

Run:
```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_settlement.py tests/test_scheduler_settlement_resolution.py -v
```
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/polysignal_lab/paper/settlement.py src/polysignal_lab/app/scheduler.py src/polysignal_lab/app/scheduler_reporting.py tests/test_scheduler_settlement_resolution.py
git commit -m "feat: settle paper positions from resolution oracle"
```

---

### Task 8: Final Regression, Safety, and Runtime Verification

**Files:**
- Test only; no planned source edits unless a verification failure identifies a concrete bug.

**Interfaces:**
- Verifies all acceptance criteria and project safety constraints.

- [ ] **Step 1: Run targeted settlement suite**

Run:
```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest \
  tests/test_settlement.py \
  tests/test_market_parsing.py \
  tests/test_settlement_sources.py \
  tests/test_ctf_resolution_client.py \
  tests/test_gamma_resolution_client.py \
  tests/test_settlement_resolver.py \
  tests/test_market_universe_service.py \
  tests/test_scheduler_settlement_resolution.py \
  tests/test_websocket_contracts.py -v
```
Expected: all tests pass.

- [ ] **Step 2: Run full tests**

Run:
```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest
```
Expected: full suite passes.

- [ ] **Step 3: Run safety scan**

Run:
```bash
UV_PYTHON=/home/gyue/.local/bin/python3.11 uv run python -m pytest tests/test_safety.py -v
```
Expected: passes; no literal `ClobClient(` and no authenticated trading clients introduced.

- [ ] **Step 4: Rebuild runtime containers for formal runtime**

Run:
```bash
docker compose up -d --build --force-recreate
```
Expected: containers rebuild and start successfully.

- [ ] **Step 5: Verify container health**

Run:
```bash
docker compose ps
```
Expected: `polysignal-lab` and dashboard containers are running/healthy.

- [ ] **Step 6: Commit final fixes if verification required changes**

If Step 1-5 required code changes, commit them:
```bash
git add <changed-files>
git commit -m "fix: stabilize settlement oracle integration"
```
If Step 1-5 did not require changes, skip this commit.

---

## Self-Review

- Spec coverage: chain, Gamma exact, WS cache, conflict priority, 50/50 payout, provenance, exact open-market lookup, error tolerance, and read-only boundaries are covered by tasks 1-8.
- Placeholder scan: no banned placeholder words, stub `pass`, fake edit hashes, or unresolved implementation placeholders remain.
- Type consistency: `SettlementEvidence.observed_at` is always `datetime`; `WsResolutionCache` lives in `settlement_sources.py`; `PolymarketMarketWebSocket` parameter name is consistently `resolution_cache`; `SettlementResolver.resolve_market()` returns `ResolutionDecision`.
- Important preservation: active-market exit evaluation remains in `check_settlements()` when the resolver returns `unknown`; the previous plan would have broken paper TP/SL exits.
