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
