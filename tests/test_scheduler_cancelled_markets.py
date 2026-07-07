"""
Input: __future__, __future__.annotations, types, types.SimpleNamespace, types.TracebackType, unittest.mock, unittest.mock.AsyncMock, pytest, pydantic, pydantic.JsonValue
Output: test_cancelled_gamma_refresh_reaches_registry_and_storage, test_scheduler_settles_cancelled_market_as_void_refund, FakeGammaResponse, FakeGammaClient
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from types import SimpleNamespace, TracebackType
from unittest.mock import AsyncMock

import pytest
from pydantic import JsonValue

from polysignal_lab.app import scheduler_market_data, scheduler_reporting
from polysignal_lab.app.scheduler import PolySignalScheduler
from polysignal_lab.config import Settings
from polysignal_lab.domain.enums import MarketStatus, Side, TradeResultStatus
from polysignal_lab.paper.settlement_sources import ResolutionDecision
from factories import MarketFactoryConfig, sample_market


class FakeGammaResponse:
    def __init__(self, payload: list[JsonValue]) -> None:
        self.status_code = 200
        self._payload = payload

    def json(self) -> JsonValue:
        return self._payload


class FakeGammaClient:
    def __init__(self, timeout: float) -> None:
        self.timeout = timeout

    async def __aenter__(self) -> FakeGammaClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def get(self, url: str, params: dict[str, str] | None = None) -> FakeGammaResponse:
        payload = {
            "id": "gamma-cancelled-1",
            "conditionId": "0xcondition",
            "slug": "btc-updown-5m-cancelled",
            "question": "BTC Up or Down - 5m",
            "active": False,
            "closed": True,
            "cancelled": True,
            "resolved": False,
            "outcomes": '["Up", "Down"]',
            "clobTokenIds": '["token-up", "token-down"]',
        }
        return FakeGammaResponse([payload])


def _scheduler(tmp_path) -> PolySignalScheduler:
    settings = Settings()
    settings.telegram.enabled = False
    settings.telegram.send_paper_results = False
    settings.telegram.send_daily_report = False
    settings.data.binance.enabled = False
    settings.data.polymarket.use_market_ws = False
    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)
    scheduler._initialize_trading_components()
    return scheduler


def _projection(market_id: str, token_id: str) -> dict[str, object]:
    return {
        "paper_position_id": "pos-cancelled",
        "position_id": "pos-cancelled",
        "market_id": market_id,
        "token_id": token_id,
        "side": Side.UP.value,
        "quantity": 25.0,
        "avg_entry_price": 0.40,
        "signal_id": "sig-cancelled",
        "strategy": "ptb_diff",
        "asset": "BTC",
        "timeframe": "5m",
        "is_closed": False,
    }


async def test_cancelled_gamma_refresh_reaches_registry_and_storage(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: an open paper position whose closed Gamma payload is cancelled.
    scheduler = _scheduler(tmp_path)
    scheduler.nautilus_cache_reader = SimpleNamespace(
        read_positions=lambda: [
            _projection("gamma-cancelled-1", "token-up"),
        ]
    )
    monkeypatch.setattr(scheduler_market_data.httpx, "AsyncClient", FakeGammaClient)

    # When: the scheduler refreshes closed markets from Gamma.
    await scheduler_market_data.fetch_resolved_markets(scheduler)

    # Then: the cancelled market reaches both runtime registry and SQLite storage.
    market = scheduler.ctx.markets.get("gamma-cancelled-1")
    rows = scheduler.sqlite.query_json(
        "markets", where="WHERE market_id = ?", params=("gamma-cancelled-1",)
    )
    assert market is not None
    assert market.status == MarketStatus.CANCELLED
    assert market.resolved_outcome is None
    assert [row["status"] for row in rows] == ["CANCELLED"]


async def test_scheduler_settles_cancelled_market_as_void_refund(tmp_path) -> None:
    # Given: an open Nautilus position projection on a market marked CANCELLED.
    scheduler = _scheduler(tmp_path)
    cancelled_market = sample_market(
        MarketFactoryConfig(asset="BTC", timeframe="5m", seconds_to_close=-1)
    ).model_copy(update={"status": MarketStatus.CANCELLED, "resolved_outcome": None})
    scheduler.ctx.markets.upsert_many([cancelled_market])
    scheduler.nautilus_cache_reader = SimpleNamespace(
        read_positions=lambda: [
            _projection(cancelled_market.market_id, cancelled_market.token_for(Side.UP).token_id),
        ]
    )
    scheduler.settlement_resolver = AsyncMock()
    scheduler.settlement_resolver.resolve_market.return_value = ResolutionDecision(
        cancelled_market.market_id,
        cancelled_market.condition_id,
        "cancelled",
        "gamma",
        {},
        False,
        (),
        {"settlement_source": "gamma"},
    )

    # When: scheduler settlement runs from Nautilus projections.
    results = await scheduler_reporting.check_settlements(scheduler)

    # Then: VOID semantics close the position and refund the stake through storage.
    result_rows = scheduler.sqlite.query_json("paper_trade_results")
    assert [result.result for result in results] == [TradeResultStatus.VOID]
    assert results[0].settlement_value == 10.0
    assert [row["result"] for row in result_rows] == ["VOID"]
