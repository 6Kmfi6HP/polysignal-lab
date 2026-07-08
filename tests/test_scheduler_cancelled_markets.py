"""
Input: __future__, __future__.annotations, types, types.SimpleNamespace, types.TracebackType, unittest.mock, unittest.mock.AsyncMock, pytest, pydantic, pydantic.JsonValue
Output: test_cancelled_gamma_refresh_reaches_registry_and_storage, test_runtime_settles_cancelled_market_as_void_refund, FakeGammaResponse, FakeGammaClient
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from types import SimpleNamespace, TracebackType
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import JsonValue

from polysignal_lab.app.scheduler_reporting import check_settlements
from polysignal_lab.config import Settings
from polysignal_lab.domain.enums import MarketStatus, Side, TradeResultStatus
from polysignal_lab.nautilus_runtime.runtime_context_factory import build_nautilus_runtime_context
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


def _runtime(tmp_path):
    settings = Settings()
    settings.telegram.enabled = False
    settings.telegram.send_paper_results = False
    settings.telegram.send_daily_report = False
    settings.data.binance.enabled = False
    settings.data.polymarket.use_market_ws = False
    return build_nautilus_runtime_context(settings, base_dir=tmp_path)


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


def _settlement_scheduler(market, decision: ResolutionDecision) -> Mock:
    scheduler = Mock()
    scheduler.settlement_resolver = AsyncMock()
    scheduler.settlement_resolver.resolve_market.return_value = decision
    scheduler.markets = SimpleNamespace(get=Mock(return_value=market), upsert_many=Mock())
    scheduler.nautilus_cache = object()
    scheduler.nautilus_portfolio = None
    scheduler.persistence = Mock()
    scheduler.persistence.insert_paper_trade_result.return_value = None
    scheduler.persistence.append_log.return_value = None
    scheduler.persistence.insert_system_event.return_value = None
    scheduler.persistence.query_json.return_value = []
    scheduler.settings = SimpleNamespace(telegram=SimpleNamespace(send_paper_results=False))
    scheduler.sqlite = scheduler.persistence
    scheduler.logger = Mock()
    return scheduler


async def test_cancelled_gamma_refresh_reaches_registry_and_storage(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime(tmp_path)
    runtime.nautilus_cache = object()
    runtime.nautilus_portfolio = None
    monkeypatch.setattr(
        "polysignal_lab.app.services.market_universe_service.httpx.AsyncClient",
        FakeGammaClient,
    )

    await runtime.market_universe.fetch_resolved(open_market_ids={"gamma-cancelled-1"})

    market = runtime.market_universe.markets.get("gamma-cancelled-1")
    rows = runtime.sqlite.query_json(
        "markets", where="WHERE market_id = ?", params=("gamma-cancelled-1",)
    )
    assert market is not None
    assert market.status == MarketStatus.CANCELLED
    assert market.resolved_outcome is None
    assert [row["status"] for row in rows] == ["CANCELLED"]


async def test_runtime_settles_cancelled_market_as_void_refund(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import polysignal_lab.app._settlement_check as settlement_mod

    runtime = _runtime(tmp_path)
    cancelled_market = sample_market(
        MarketFactoryConfig(asset="BTC", timeframe="5m", seconds_to_close=-1)
    ).model_copy(update={"status": MarketStatus.CANCELLED, "resolved_outcome": None})
    scheduler = _settlement_scheduler(
        cancelled_market,
        ResolutionDecision(
            cancelled_market.market_id,
            cancelled_market.condition_id,
            "cancelled",
            "gamma",
            {},
            False,
            (),
            {"settlement_source": "gamma"},
        ),
    )
    scheduler.persistence = runtime.persistence
    scheduler.sqlite = runtime.sqlite
    scheduler.markets = runtime.markets
    runtime.markets.upsert_many([cancelled_market])

    monkeypatch.setattr(
        settlement_mod,
        "_nautilus_positions",
        lambda s: [
            _projection(
                cancelled_market.market_id,
                cancelled_market.token_for(Side.UP).token_id,
            )
        ],
    )

    results = await check_settlements(scheduler)

    result_rows = runtime.sqlite.query_json("paper_trade_results")
    assert [result.result for result in results] == [TradeResultStatus.VOID]
    assert results[0].settlement_value == 10.0
    assert [row["result"] for row in result_rows] == ["VOID"]
