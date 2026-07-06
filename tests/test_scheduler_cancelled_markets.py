from __future__ import annotations

from types import SimpleNamespace, TracebackType

import pytest
from pydantic import JsonValue

from polysignal_lab.app import scheduler_market_data, scheduler_reporting
from polysignal_lab.app.scheduler import PolySignalScheduler
from polysignal_lab.config import Settings
from polysignal_lab.domain.enums import MarketStatus, PositionStatus, Side, TradeResultStatus
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.paper.settlement import PaperSettlementEngine
from factories import MarketFactoryConfig, sample_market


class _LedgerWallet:
    def __init__(self, starting_balance: float) -> None:
        self.starting_balance = starting_balance
        self.cash_balance = starting_balance
        self.realized_pnl = 0.0
        self.open_positions: dict[str, PaperPosition] = {}

    def apply_fill(self, position: PaperPosition) -> None:
        self.open_positions[position.paper_position_id] = position
        self.cash_balance -= position.stake_usdc


def _scheduler(tmp_path) -> PolySignalScheduler:
    settings = Settings()
    settings.telegram.enabled = False
    settings.telegram.send_paper_results = False
    settings.telegram.send_daily_report = False
    settings.data.binance.enabled = False
    settings.data.polymarket.use_market_ws = False
    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)
    scheduler.wallet = _LedgerWallet(starting_balance=1000.0)
    scheduler.settlement = PaperSettlementEngine()
    return scheduler


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


def _position(market_id: str = "gamma-cancelled-1") -> PaperPosition:
    return PaperPosition(
        signal_id="sig-cancelled",
        paper_order_id="order-cancelled",
        paper_fill_id="fill-cancelled",
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id=market_id,
        market_slug="btc-updown-5m-cancelled",
        token_id="token-up",
        side=Side.UP,
        entry_price=0.40,
        shares=25.0,
        stake_usdc=10.0,
    )


async def test_cancelled_gamma_refresh_reaches_registry_and_storage(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given: an open paper position whose closed Gamma payload is cancelled.
    scheduler = _scheduler(tmp_path)
    position = _position()
    scheduler.nautilus_cache_reader = SimpleNamespace(
        read_positions=lambda: [
            {
                "market_id": position.market_id,
                "token_id": position.token_id,
                "is_closed": False,
            }
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


@pytest.mark.skip(reason="Task 5: wallet-based settlement removed; projection path pending")
async def test_scheduler_settles_cancelled_market_as_void_refund(tmp_path) -> None:
    # Given: an open paper position on a market marked CANCELLED in the scheduler registry.
    scheduler = _scheduler(tmp_path)
    position = _position("btc-5m-test")
    scheduler.wallet.apply_fill(position)
    cancelled_market = sample_market(
        MarketFactoryConfig(asset="BTC", timeframe="5m", seconds_to_close=-1)
    ).model_copy(update={"status": MarketStatus.CANCELLED, "resolved_outcome": None})
    scheduler.ctx.markets.upsert_many([cancelled_market])

    # When: scheduler settlement runs.
    results = await scheduler_reporting.check_settlements(scheduler)

    # Then: VOID semantics close the position and refund the stake through storage.
    result_rows = scheduler.sqlite.query_json("paper_trade_results")
    position_rows = scheduler.sqlite.query_json("paper_positions")
    assert [result.result for result in results] == [TradeResultStatus.VOID]
    assert results[0].settlement_value == 10.0
    assert position.status == PositionStatus.CLOSED
    assert len(scheduler.wallet.open_positions) == 0
    assert scheduler.wallet.cash_balance == 1000.0
    assert [row["result"] for row in result_rows] == ["VOID"]
    assert [row["status"] for row in position_rows] == ["CLOSED"]
