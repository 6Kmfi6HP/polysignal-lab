from __future__ import annotations

from datetime import UTC, datetime

from polysignal_lab.data.price_to_beat_provider import PriceToBeatProvider
from polysignal_lab.domain.enums import MarketStatus, Side
from polysignal_lab.domain.market import Market, OutcomeToken


class FailingAsyncClient:
    async def get(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> "RecordingResponse":
        del url, params, headers
        raise AssertionError("crypto-price API should not be called")


class RecordingResponse:
    status_code: int = 200

    def json(self) -> dict[str, float]:
        return {"openPrice": 123.45}


class RecordingAsyncClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str], dict[str, str]]] = []

    async def get(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> RecordingResponse:
        self.calls.append((url, params or {}, headers or {}))
        return RecordingResponse()


def _market(*, asset: str = "ETH", timeframe: str = "5m") -> Market:
    market_id = f"{asset.lower()}-{timeframe}"
    return Market(
        market_id=market_id,
        market_slug=f"{asset.lower()}-updown-{timeframe}-1782297000",
        condition_id=f"condition-{market_id}",
        question=f"{asset} Up or Down {timeframe}?",
        asset=asset,
        timeframe=timeframe,
        start_ts=datetime(2026, 6, 24, 10, 30, tzinfo=UTC),
        end_ts=datetime(2026, 6, 24, 10, 35, tzinfo=UTC),
        status=MarketStatus.ACTIVE,
        price_to_beat=None,
        outcome_tokens=[
            OutcomeToken(token_id=f"{market_id}-UP", side=Side.UP, outcome_name="Up", market_id=market_id),
            OutcomeToken(token_id=f"{market_id}-DOWN", side=Side.DOWN, outcome_name="Down", market_id=market_id),
        ],
        raw={"eventStartTime": "2026-06-24T10:30:00Z"},
    )


async def test_crypto_price_api_is_opt_in_to_avoid_cloudflare_startup_403() -> None:
    provider = PriceToBeatProvider(client=FailingAsyncClient())

    result = await provider.get(_market())

    assert result.value is None
    assert result.source == "unavailable"
    assert result.reason == "PTB_UNAVAILABLE"


async def test_enabled_crypto_price_api_uses_market_asset_and_timeframe_variant() -> None:
    client = RecordingAsyncClient()
    provider = PriceToBeatProvider(client=client, use_crypto_price_api=True)

    result = await provider.get(_market(asset="ETH", timeframe="5m"))

    assert result.value == 123.45
    assert result.source == "crypto_price_api"
    assert client.calls[0][1]["symbol"] == "ETH"
    assert client.calls[0][1]["variant"] == "fiveminute"
