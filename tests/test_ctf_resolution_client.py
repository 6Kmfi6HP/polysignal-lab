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
