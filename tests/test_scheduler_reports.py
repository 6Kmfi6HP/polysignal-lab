from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from polysignal_lab.app import scheduler_reporting, scheduler_runtime
from polysignal_lab.app.scheduler import PolySignalScheduler
from polysignal_lab.domain.enums import (
    ExitMode,
    MarketStatus,
    OrderIntent,
    OrderStatus,
    Side,
    TradeResultStatus,
)
from polysignal_lab.domain.paper_result import PaperTradeResult
from polysignal_lab.domain.paper_order import PaperFill, PaperOrder
from polysignal_lab.strategies.ptb_diff import PTBDiffStrategy
from polysignal_lab.nautilus_runtime.observability import (
    NautilusEventStoreAdapter,
    ObservabilityActor,
)
from unittest.mock import AsyncMock

from polysignal_lab.paper.settlement_sources import ResolutionDecision


def _scheduler(tmp_path: Path, settings) -> PolySignalScheduler:
    settings.telegram.enabled = True
    settings.telegram.dry_run = True
    settings.telegram.send_signals = False
    settings.telegram.send_paper_results = True
    settings.telegram.send_daily_report = True
    settings.data.binance.enabled = False
    settings.data.polymarket.use_market_ws = False
    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)
    scheduler._initialize_trading_components()
    return scheduler


async def _signal(snapshot, settings):
    return PTBDiffStrategy(settings.strategies.ptb_diff).evaluate(snapshot)[0]


def _projection_from_signal(signal, *, market_id: str, quantity: float = 12.658, entry_price: float = 0.79) -> dict[str, object]:
    return {
        "paper_position_id": "pos-settle-1",
        "position_id": "pos-settle-1",
        "market_id": market_id,
        "token_id": signal.token_id,
        "side": signal.side.value,
        "quantity": quantity,
        "avg_entry_price": entry_price,
        "signal_id": signal.signal_id,
        "strategy": signal.strategy,
        "asset": signal.asset,
        "timeframe": signal.timeframe,
        "is_closed": False,
    }


async def test_projection_settlement_publish_timeout_keeps_durable_closed_result(
    tmp_path: Path, snapshot, settings
) -> None:
    # Given: an open Nautilus position projection on a resolved market, but publish times out.
    signal = await _signal(snapshot, settings)
    scheduler = _scheduler(tmp_path, settings)
    resolved_market = snapshot.market.model_copy(
        update={"status": MarketStatus.RESOLVED, "resolved_outcome": signal.side}
    )
    scheduler.ctx.markets.upsert_many([resolved_market])
    scheduler.nautilus_cache_reader = SimpleNamespace(
        read_positions=lambda: [_projection_from_signal(signal, market_id=resolved_market.market_id)],
    )
    scheduler.settlement_resolver = AsyncMock()
    scheduler.settlement_resolver.resolve_market.return_value = ResolutionDecision(
        resolved_market.market_id,
        resolved_market.condition_id,
        "resolved",
        "chain",
        {signal.token_id: 1.0},
        False,
        (),
        {"settlement_source": "chain"},
    )

    async def timeout_publish(result: PaperTradeResult) -> None:
        raise TimeoutError("paper publish timed out")

    scheduler.publish_service.publish_paper_result = timeout_publish

    # When: scheduler reporting settles from Nautilus projections.
    results = await scheduler.check_settlements()

    # Then: publish failure is best-effort for settlement closes too.
    result_rows = scheduler.sqlite.query_json("paper_trade_results")
    event_rows = scheduler.sqlite.query_json("system_events")
    assert [result.result for result in results] == [TradeResultStatus.WIN]
    assert [row["result"] for row in result_rows] == ["WIN"]
    assert [row["event_type"] for row in event_rows] == ["paper_result_publish_failed"]


async def test_daily_report_uses_next_local_midnight_for_dst_day(
    tmp_path: Path, settings, monkeypatch
) -> None:
    # Given: Europe/Berlin starts DST on 2026-03-29, making that local day 23 hours.
    settings.app.timezone = "Europe/Berlin"
    scheduler = _scheduler(tmp_path, settings)
    captured_day_params: dict[str, tuple[str, str]] = {}
    original_query_json = scheduler.sqlite.query_json

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return cls(2026, 3, 29, 10, 0, tzinfo=UTC)
            return cls(2026, 3, 29, 12, 0, tzinfo=tz)

    def capture_query_json(table: str, limit: int = 100, where: str = "", params=()):
        if table == "signals":
            captured_day_params[table] = tuple(params)
        return original_query_json(table, limit=limit, where=where, params=params)

    monkeypatch.setattr(scheduler_reporting, "datetime", FixedDateTime)
    scheduler.sqlite.query_json = capture_query_json

    # When: the daily report computes the persisted-row UTC window for that local day.
    report = await scheduler.generate_daily_report()

    # Then: the window ends at the next local midnight, not fixed 24 hours after UTC start.
    assert report is not None
    assert report.report_date == date(2026, 3, 29)
    assert captured_day_params["signals"] == (
        "2026-03-28T23:00:00.000000Z",
        "2026-03-29T22:00:00.000000Z",
    )


async def test_daily_report_includes_fractional_timestamp_in_first_second(
    tmp_path: Path, snapshot, settings, monkeypatch
) -> None:
    # Given: a persisted signal in the first UTC second of the report day.
    settings.app.timezone = "UTC"
    scheduler = _scheduler(tmp_path, settings)
    signal = await _signal(snapshot, settings)
    scheduler.sqlite.insert_signal(
        signal.model_copy(
            update={
                "signal_id": "sig-first-second-fractional",
                "created_at": datetime(2026, 6, 23, 0, 0, 0, 500000, tzinfo=UTC),
            }
        )
    )

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return cls(2026, 6, 23, 12, 0, tzinfo=UTC)
            return cls(2026, 6, 23, 12, 0, tzinfo=tz)

    monkeypatch.setattr(scheduler_reporting, "datetime", FixedDateTime)

    # When: the daily report queries the local day's stored UTC TEXT window.
    report = await scheduler.generate_daily_report()

    # Then: the fractional timestamp still belongs to the report day.
    assert report is not None
    assert report.report_date == date(2026, 6, 23)
    assert report.total_signals == 1


async def test_iteration_report_uses_configured_report_date_when_local_date_differs(
    tmp_path: Path, settings, monkeypatch
) -> None:
    # Given: the configured report timezone is still on the previous local date.
    settings.app.timezone = "America/Los_Angeles"
    scheduler = _scheduler(tmp_path, settings)

    class FixedProcessDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 6, 23)

    class FixedReportDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return cls(2026, 6, 23, 6, 30, tzinfo=UTC)
            return cls(2026, 6, 22, 23, 30, tzinfo=tz)

    monkeypatch.setattr(scheduler_runtime, "date", FixedProcessDate)
    monkeypatch.setattr(scheduler_reporting, "datetime", FixedReportDateTime)

    monkeypatch.setattr(scheduler_runtime, "datetime", FixedReportDateTime)
    # When: the run-loop gate has already recorded the process-local date.
    report_date = await scheduler_runtime._generate_iteration_report(
        scheduler, last_report_date=date(2026, 6, 23)
    )

    # Then: the configured local report is not skipped and the stored date is returned.
    assert report_date == date(2026, 6, 22)
    report_rows = scheduler.sqlite.query_json("daily_reports")
    assert [row["report_date"] for row in report_rows] == ["2026-06-22"]


async def test_daily_report_uses_prior_day_resting_fill_intent(
    tmp_path: Path, settings, monkeypatch
) -> None:
    # Given: a passive order created before the report day fills today.
    settings.app.timezone = "UTC"
    scheduler = _scheduler(tmp_path, settings)
    prior_day_order = PaperOrder(
        paper_order_id="po-prior-passive",
        signal_id="sig-prior-passive",
        created_at=datetime(2026, 6, 22, 23, 55, tzinfo=UTC),
        asset="BTC",
        timeframe="5m",
        strategy="ptb_diff",
        market_id="m-prior-passive",
        market_slug="prior-passive",
        token_id="t-prior-passive",
        side=Side.UP,
        order_intent=OrderIntent.PASSIVE_GTD,
        limit_price=0.8,
        reference_price=0.8,
        stake_usdc=10.0,
        status=OrderStatus.FILLED,
        metrics={"paper_order_intent": OrderIntent.PASSIVE_GTD},
    )
    fill = PaperFill(
        paper_fill_id="pf-prior-passive",
        paper_order_id=prior_day_order.paper_order_id,
        signal_id=prior_day_order.signal_id,
        created_at=datetime(2026, 6, 23, 12, 0, tzinfo=UTC),
        token_id=prior_day_order.token_id,
        side=Side.UP,
        raw_best_ask=0.79,
        slippage_bps=0.0,
        fill_price=0.79,
        stake_usdc=10.0,
        shares=12.658,
        depth_checked=True,
        available_depth_usdc=100.0,
        fill_ratio=1.0,
    )
    scheduler.sqlite.insert_paper_order(prior_day_order)
    scheduler.sqlite.insert_paper_fill(fill)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return cls(2026, 6, 23, 12, 30, tzinfo=UTC)
            return cls(2026, 6, 23, 12, 30, tzinfo=tz)

    monkeypatch.setattr(scheduler_reporting, "datetime", FixedDateTime)

    # When: the daily report aggregates today's fill.
    report = await scheduler.generate_daily_report()

    # Then: the fill inherits its prior-day passive intent without counting the
    # prior-day order as a new report-day attempt.
    assert report is not None
    assert report.report_date == date(2026, 6, 23)
    assert report.paper_orders == 0
    assert report.paper_fills == 1
    assert report.paper_attempts_by_intent == {}
    assert report.paper_fills_by_intent == {"passive_gtd": 1}



async def test_daily_report_uses_nautilus_cache_reader_projection_rows(
    tmp_path: Path, settings, monkeypatch
) -> None:
    # Given: no legacy paper_* rows exist for the day, and stale persisted
    # Nautilus observability events must not be used as a reporting fallback.
    settings.app.timezone = "UTC"
    scheduler = _scheduler(tmp_path, settings)
    scheduler.settings.telegram.send_daily_report = False
    actor = ObservabilityActor(store=NautilusEventStoreAdapter(scheduler.persistence))
    for index in range(2):
        actor.record_nautilus_order_event(
            SimpleNamespace(
                client_order_id=f"C-PERSISTED-{index}",
                instrument_id="up-token.POLYMARKET",
                order_side="BUY",
                order_type="LIMIT",
                time_in_force="GTD",
                quantity=1.0,
                price=0.20,
                status="FILLED",
                metrics={"orderbook_fresh": True},
                tags=[
                    "strategy=one_cent_buy",
                    "condition_id=condition-btc-5m",
                    "market_id=btc-5m",
                    "order_intent=persisted_system_event",
                ],
                ts_event=datetime(2026, 6, 23, 9, index, tzinfo=UTC),
            )
        )
        actor.record_nautilus_fill_event(
            SimpleNamespace(
                client_order_id=f"C-PERSISTED-{index}",
                instrument_id="up-token.POLYMARKET",
                trade_id=f"T-PERSISTED-{index}",
                last_qty=1.0,
                last_px=0.20,
                liquidity_side="TAKER",
                ts_event=datetime(2026, 6, 23, 9, index, tzinfo=UTC),
            )
        )
    while actor.drain_telemetry_once():
        pass
    setattr(
        scheduler,
        "nautilus_cache_reader",
        SimpleNamespace(
            read_orders=lambda: [
                {
                    "paper_order_id": "C-NAUTILUS-1",
                    "client_order_id": "C-NAUTILUS-1",
                    "status": "FILLED",
                    "order_intent": "passive_gtd",
                    "metrics": {"paper_order_intent": "passive_gtd", "orderbook_fresh": False},
                    "ts": "2026-06-23T10:00:00+00:00",
                },
                {
                    "paper_order_id": "C-OLD-NAUTILUS",
                    "client_order_id": "C-OLD-NAUTILUS",
                    "status": "FILLED",
                    "order_intent": "old_projection",
                    "metrics": {"paper_order_intent": "old_projection", "orderbook_fresh": False},
                    "ts": "2026-06-22T10:00:00+00:00",
                },
            ],
            read_fills=lambda: [
                {
                    "paper_fill_id": "T-NAUTILUS-1",
                    "paper_order_id": "C-NAUTILUS-1",
                    "client_order_id": "C-NAUTILUS-1",
                    "order_intent": "passive_gtd",
                    "ts": "2026-06-23T10:01:00+00:00",
                },
                {
                    "paper_fill_id": "T-OLD-NAUTILUS",
                    "paper_order_id": "C-OLD-NAUTILUS",
                    "client_order_id": "C-OLD-NAUTILUS",
                    "order_intent": "old_projection",
                    "ts": "2026-06-22T10:01:00+00:00",
                },
            ],
            read_positions=lambda: [],
        ),
    )

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return cls(2026, 6, 23, 12, 30, tzinfo=UTC)
            return cls(2026, 6, 23, 12, 30, tzinfo=tz)

    monkeypatch.setattr(scheduler_reporting, "datetime", FixedDateTime)

    # When: the daily report aggregates the report-day Nautilus cache rows.
    report = await scheduler.generate_daily_report()

    # Then: report counts and intent buckets come from read-only Nautilus cache
    # projections, not persisted system_events or legacy paper_* inserts.
    assert report is not None
    assert report.report_date == date(2026, 6, 23)
    assert report.paper_orders == 1
    assert report.paper_fills == 1
    assert report.rejected_paper_orders == 0
    assert report.stale_paper_fills == 1
    assert report.paper_attempts_by_intent == {"passive_gtd": 1}
    assert report.paper_fills_by_intent == {"passive_gtd": 1}

async def test_daily_report_uses_nautilus_cache_reader_when_wallet_missing(
    tmp_path: Path, settings, monkeypatch
) -> None:
    # Given: the Nautilus runtime path initialized scheduler compatibility state
    # without a PaperWallet, but exposed a read-only Nautilus cache projection.
    from polysignal_lab.nautilus_runtime.node import _initialize_nautilus_scheduler_components

    settings.app.timezone = "UTC"
    settings.telegram.enabled = False
    settings.telegram.dry_run = True
    settings.telegram.send_daily_report = False
    settings.data.binance.enabled = False
    settings.data.polymarket.use_market_ws = False
    scheduler = PolySignalScheduler(settings, base_dir=tmp_path)
    _initialize_nautilus_scheduler_components(scheduler)
    setattr(
        scheduler,
        "nautilus_cache_reader",
        SimpleNamespace(
            read_account_projection=lambda: {
                "account_id": "acct-1",
                "balances": [{"currency": "USDC", "total": 987.0}],
            },
            snapshot_portfolio_projection=lambda: {
                "portfolio_id": "portfolio-1",
                "equity": 987.0,
            },
            read_positions=lambda: [
                {"position_id": "pos-open", "is_closed": False},
                {"position_id": "pos-closed", "is_closed": True},
            ],
        ),
    )
    actor = ObservabilityActor(store=NautilusEventStoreAdapter(scheduler.persistence))
    actor.record_nautilus_order_event(
        SimpleNamespace(
            client_order_id="C-NAUTILUS-2",
            instrument_id="up-token.POLYMARKET",
            order_side="BUY",
            order_type="LIMIT",
            time_in_force="GTD",
            quantity=10.0,
            price=0.80,
            status="ACCEPTED",
            tags=[
                "strategy=one_cent_buy",
                "condition_id=condition-btc-5m",
                "market_id=btc-5m",
                "order_intent=passive_gtd",
            ],
            ts_event=datetime(2026, 6, 23, 10, 0, tzinfo=UTC),
        )
    )

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return cls(2026, 6, 23, 12, 30, tzinfo=UTC)
            return cls(2026, 6, 23, 12, 30, tzinfo=tz)

    monkeypatch.setattr(scheduler_reporting, "datetime", FixedDateTime)

    # When: the daily report is generated from Nautilus projections only.
    report = await scheduler.generate_daily_report()

    # Then: equity/open-position stats come from the Nautilus cache reader,
    # not a missing legacy wallet object.
    assert report is not None
    assert report.report_date == date(2026, 6, 23)
    assert report.starting_equity == settings.paper_trading.starting_balance_usdc
    assert report.ending_equity == 987.0
    assert report.open_positions == 1

async def test_daily_report_counts_cancelled_paper_rejects(
    tmp_path: Path, settings, monkeypatch
) -> None:
    # Given: a cancelled resting reject carries today's reject reason.
    settings.app.timezone = "UTC"
    scheduler = _scheduler(tmp_path, settings)
    cancelled = PaperOrder(
        paper_order_id="po-cancelled-resting",
        signal_id="sig-cancelled-resting",
        created_at=datetime(2026, 6, 23, 10, 0, tzinfo=UTC),
        asset="BTC",
        timeframe="5m",
        strategy="ptb_diff",
        market_id="m-cancelled-resting",
        market_slug="cancelled-resting",
        token_id="t-cancelled-resting",
        side=Side.UP,
        order_intent=OrderIntent.PASSIVE_GTD,
        limit_price=0.7,
        reference_price=0.7,
        stake_usdc=10.0,
        status=OrderStatus.CANCELLED,
        reject_reason="GTD_EXPIRED",
        metrics={"paper_order_intent": OrderIntent.PASSIVE_GTD},
    )
    scheduler.sqlite.insert_paper_order(cancelled)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return cls(2026, 6, 23, 12, 30, tzinfo=UTC)
            return cls(2026, 6, 23, 12, 30, tzinfo=tz)

    monkeypatch.setattr(scheduler_reporting, "datetime", FixedDateTime)

    # When: the daily report aggregates today's rejected paper orders.
    report = await scheduler.generate_daily_report()

    # Then: the cancelled reject contributes to today's rejected-paper count.
    assert report is not None
    assert report.report_date == date(2026, 6, 23)
    assert report.paper_orders == 1
    assert report.paper_fills == 0
    assert report.rejected_paper_orders == 1
    assert report.paper_attempts_by_intent == {"passive_gtd": 1}
    assert report.paper_rejects_by_reason == {"PAPER_GTD_EXPIRED": 1}
    assert report.paper_rejects_by_original_reason == {"GTD_EXPIRED": 1}


async def test_daily_report_counts_prior_day_resting_terminal_rejects_today(
    tmp_path: Path, settings, monkeypatch
) -> None:
    # Given: a passive GTD order created before today's report window is
    # cancelled today and carries its durable terminal timestamp.
    settings.app.timezone = "UTC"
    scheduler = _scheduler(tmp_path, settings)
    cancelled = PaperOrder(
        paper_order_id="po-prior-day-cancelled-resting",
        signal_id="sig-prior-day-cancelled-resting",
        created_at=datetime(2026, 6, 22, 23, 55, tzinfo=UTC),
        asset="BTC",
        timeframe="5m",
        strategy="ptb_diff",
        market_id="m-prior-day-cancelled-resting",
        market_slug="prior-day-cancelled-resting",
        token_id="t-prior-day-cancelled-resting",
        side=Side.UP,
        order_intent=OrderIntent.PASSIVE_GTD,
        limit_price=0.7,
        reference_price=0.7,
        stake_usdc=10.0,
        status=OrderStatus.CANCELLED,
        reject_reason="PAPER_GTD_EXPIRED",
        metrics={
            "paper_order_intent": OrderIntent.PASSIVE_GTD,
            "paper_original_reason": "GTD_EXPIRED",
            "paper_normalized_reason": "PAPER_GTD_EXPIRED",
            "paper_terminal_at": datetime(2026, 6, 23, 0, 5, tzinfo=UTC),
        },
    )
    scheduler.sqlite.insert_paper_order(cancelled)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return cls(2026, 6, 23, 12, 30, tzinfo=UTC)
            return cls(2026, 6, 23, 12, 30, tzinfo=tz)

    monkeypatch.setattr(scheduler_reporting, "datetime", FixedDateTime)

    # When: today's daily report aggregates paper-order rejects.
    report = await scheduler.generate_daily_report()

    # Then: the terminal reject is reported today without becoming a new
    # report-day paper-order attempt.
    assert report is not None
    assert report.report_date == date(2026, 6, 23)
    assert report.paper_orders == 0
    assert report.paper_fills == 0
    assert report.rejected_paper_orders == 1
    assert report.paper_attempts_by_intent == {}
    assert report.paper_rejects_by_reason == {"PAPER_GTD_EXPIRED": 1}
    assert report.paper_rejects_by_original_reason == {"GTD_EXPIRED": 1}

async def test_daily_report_publish_record_written(
    tmp_path: Path, snapshot, settings, monkeypatch
) -> None:
    # Given: stored signals, one filled paper order, one rejected paper order, and a closed result.
    settings.app.timezone = "UTC"
    signal = await _signal(snapshot, settings)
    scheduler = _scheduler(tmp_path, settings)
    report_day = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)
    scheduler.sqlite.insert_signal(
        signal.model_copy(update={"created_at": report_day.replace(hour=10)})
    )
    scheduler.sqlite.insert_signal(
        signal.model_copy(
            update={
                "signal_id": "sig-rejected-report",
                "token_id": "missing-token-report",
                "created_at": report_day.replace(hour=10, minute=5),
            }
        )
    )
    filled_order = PaperOrder(
        paper_order_id="po-filled-report",
        signal_id=signal.signal_id,
        created_at=report_day.replace(hour=10, minute=1),
        asset=signal.asset,
        timeframe=signal.timeframe,
        strategy=signal.strategy,
        market_id=signal.market_id,
        market_slug=signal.market_slug,
        token_id=signal.token_id,
        side=signal.side,
        order_intent=OrderIntent.PASSIVE_GTD,
        limit_price=0.79,
        reference_price=0.79,
        stake_usdc=10.0,
        status=OrderStatus.FILLED,
        metrics={
            "paper_order_intent": OrderIntent.PASSIVE_GTD,
            "paper_orderbook_staleness_ms": 12.0,
            "paper_available_depth_usdc": 250.0,
        },
    )
    rejected_order = PaperOrder(
        paper_order_id="po-rejected-report",
        signal_id="sig-rejected-report",
        created_at=report_day.replace(hour=10, minute=6),
        asset=signal.asset,
        timeframe=signal.timeframe,
        strategy=signal.strategy,
        market_id=signal.market_id,
        market_slug=signal.market_slug,
        token_id="missing-token-report",
        side=signal.side,
        order_intent=OrderIntent.PASSIVE_GTD,
        limit_price=0.79,
        reference_price=0.79,
        stake_usdc=10.0,
        status=OrderStatus.REJECTED,
        reject_reason="MISSING_ORDERBOOK",
        metrics={
            "paper_order_intent": OrderIntent.PASSIVE_GTD,
            "paper_orderbook_staleness_ms": 15.0,
            "paper_available_depth_usdc": 0.0,
        },
    )
    fill = PaperFill(
        paper_fill_id="pf-filled-report",
        paper_order_id=filled_order.paper_order_id,
        signal_id=signal.signal_id,
        created_at=report_day.replace(hour=10, minute=2),
        token_id=signal.token_id,
        side=signal.side,
        raw_best_ask=0.79,
        slippage_bps=0.0,
        fill_price=0.79,
        stake_usdc=10.0,
        shares=12.658,
        depth_checked=True,
        available_depth_usdc=250.0,
        fill_ratio=1.0,
    )
    result = PaperTradeResult(
        signal_id=signal.signal_id,
        paper_position_id="pos-filled-report",
        strategy=signal.strategy,
        asset=signal.asset,
        timeframe=signal.timeframe,
        market_id=signal.market_id,
        market_slug=signal.market_slug,
        side=signal.side,
        entry_price=0.79,
        shares=12.658,
        stake_usdc=10.0,
        exit_mode=ExitMode.RESOLUTION,
        outcome_value=1.0,
        settlement_value=12.658,
        pnl_usdc=2.658,
        roi=0.2658,
        result=TradeResultStatus.WIN,
        opened_at=report_day.replace(hour=10, minute=2),
        closed_at=report_day.replace(hour=11),
    )
    scheduler.sqlite.insert_paper_order(filled_order)
    scheduler.sqlite.insert_paper_order(rejected_order)
    scheduler.sqlite.insert_paper_fill(fill)
    scheduler.sqlite.insert_paper_trade_result(result)
    scheduler.nautilus_cache_reader = SimpleNamespace(
        snapshot_portfolio_projection=lambda: {"equity": settings.paper_trading.starting_balance_usdc},
        read_account_projection=lambda: {
            "balances": [{"currency": "USDC", "total": settings.paper_trading.starting_balance_usdc}],
        },
        read_positions=lambda: [],
    )
    setattr(
        scheduler,
        "paper_execution_metadata",
        {
            "paper_engine": "nautilus_matching",
            "accuracy_mode": "queue_l2",
        },
    )

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return cls(2026, 6, 23, 12, 30, tzinfo=UTC)
            return cls(2026, 6, 23, 12, 30, tzinfo=tz)

    monkeypatch.setattr(scheduler_reporting, "datetime", FixedDateTime)

    # When: the daily report is generated with Telegram daily reporting enabled.
    report = await scheduler.generate_daily_report()

    # Then: the report uses persisted rows and writes a durable Telegram publish record.
    assert report is not None
    report_rows = scheduler.sqlite.query_json("daily_reports")
    publish_rows = scheduler.sqlite.query_json("telegram_publishes")
    assert report.report_date == date(2026, 6, 23)
    assert report.total_signals == 2
    assert report.paper_orders == 2
    assert report.paper_fills == 1
    assert report.rejected_paper_orders == 1
    assert report.open_positions == 0
    assert report.closed_positions == 1
    assert report.win_count == 1
    assert report.total_pnl_usdc == result.pnl_usdc
    assert report.stale_paper_fills == 0
    assert report.paper_attempts_by_intent == {"passive_gtd": 2}
    assert report.paper_fills_by_intent == {"passive_gtd": 1}
    assert report.paper_rejects_by_reason == {"PAPER_MISSING_ORDERBOOK": 1}
    assert report.paper_rejects_by_original_reason == {"MISSING_ORDERBOOK": 1}
    assert report.average_execution_staleness_ms is not None
    assert report.average_executable_depth_usdc is not None
    assert report.paper_execution_assumptions == {
        "accuracy_mode": "queue_l2",
        "max_book_staleness_ms": settings.data.polymarket.max_book_staleness_ms,
        "min_fill_ratio": settings.paper_trading.fill_model.min_fill_ratio,
        "paper_engine": "nautilus_matching",
        "reject_if_partial": settings.paper_trading.fill_model.reject_if_partial,
        "require_depth_check": settings.paper_trading.fill_model.require_depth_check,
        "slippage_bps": settings.paper_trading.fill_model.slippage_bps,
    }
    assert report_rows[0]["paper_execution_assumptions"] == report.paper_execution_assumptions
    assert report.strategy_breakdown["ptb_diff"]["win_count"] == 1
    assert report.asset_breakdown["BTC"]["closed_positions"] == 1
    assert report.timeframe_breakdown["5m"]["total_pnl_usdc"] == result.pnl_usdc
    assert [row["report_id"] for row in report_rows] == [report.report_id]
    assert [(row["message_type"], row["status"]) for row in publish_rows] == [
        ("daily_report", "DRY_RUN")
    ]
    assert scheduler.logs.read_all("daily_reports")[0]["report_id"] == report.report_id
    assert [
        (row["message_type"], row["status"])
        for row in scheduler.logs.read_all("telegram_publishes")
    ] == [("daily_report", "DRY_RUN")]
    assert not (scheduler.logs.base_dir / "telegram_publish.jsonl").exists()


async def test_daily_report_publish_row_failure_returns_no_report(
    tmp_path: Path, snapshot, settings, monkeypatch
) -> None:
    # Given: stored report inputs, but daily publish-row persistence fails.
    settings.app.timezone = "UTC"
    signal = await _signal(snapshot, settings)
    scheduler = _scheduler(tmp_path, settings)
    report_day = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)
    scheduler.sqlite.insert_signal(
        signal.model_copy(update={"created_at": report_day.replace(hour=10)})
    )
    filled_order = PaperOrder(
        paper_order_id="po-filled-report-fail",
        signal_id=signal.signal_id,
        created_at=report_day.replace(hour=10, minute=1),
        asset=signal.asset,
        timeframe=signal.timeframe,
        strategy=signal.strategy,
        market_id=signal.market_id,
        market_slug=signal.market_slug,
        token_id=signal.token_id,
        side=signal.side,
        order_intent=OrderIntent.PASSIVE_GTD,
        limit_price=0.79,
        reference_price=0.79,
        stake_usdc=10.0,
        status=OrderStatus.FILLED,
        metrics={"paper_order_intent": OrderIntent.PASSIVE_GTD},
    )
    fill = PaperFill(
        paper_fill_id="pf-filled-report-fail",
        paper_order_id=filled_order.paper_order_id,
        signal_id=signal.signal_id,
        created_at=report_day.replace(hour=10, minute=2),
        token_id=signal.token_id,
        side=signal.side,
        raw_best_ask=0.79,
        slippage_bps=0.0,
        fill_price=0.79,
        stake_usdc=10.0,
        shares=12.658,
        depth_checked=True,
        available_depth_usdc=250.0,
        fill_ratio=1.0,
    )
    result = PaperTradeResult(
        signal_id=signal.signal_id,
        paper_position_id="pos-filled-report-fail",
        strategy=signal.strategy,
        asset=signal.asset,
        timeframe=signal.timeframe,
        market_id=signal.market_id,
        market_slug=signal.market_slug,
        side=signal.side,
        entry_price=0.79,
        shares=12.658,
        stake_usdc=10.0,
        exit_mode=ExitMode.RESOLUTION,
        outcome_value=1.0,
        settlement_value=12.658,
        pnl_usdc=2.658,
        roi=0.2658,
        result=TradeResultStatus.WIN,
        opened_at=report_day.replace(hour=10, minute=2),
        closed_at=report_day.replace(hour=11),
    )
    scheduler.sqlite.insert_paper_order(filled_order)
    scheduler.sqlite.insert_paper_fill(fill)
    scheduler.sqlite.insert_paper_trade_result(result)
    scheduler.nautilus_cache_reader = SimpleNamespace(
        snapshot_portfolio_projection=lambda: {"equity": settings.paper_trading.starting_balance_usdc},
        read_account_projection=lambda: {
            "balances": [{"currency": "USDC", "total": settings.paper_trading.starting_balance_usdc}],
        },
        read_positions=lambda: [],
    )

    def fail_insert_publish(publish: dict[str, str | None]) -> None:
        raise sqlite3.OperationalError("publish insert failed")

    scheduler.sqlite.insert_telegram_publish = fail_insert_publish

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return cls(2026, 6, 23, 12, 30, tzinfo=UTC)
            return cls(2026, 6, 23, 12, 30, tzinfo=tz)

    monkeypatch.setattr(scheduler_reporting, "datetime", FixedDateTime)

    # When: the daily report is generated with Telegram daily reporting enabled.
    report = await scheduler.generate_daily_report()

    # Then: runtime receives no successful report and no durable report/publish rows exist.
    assert report is None
    assert scheduler.sqlite.query_json("daily_reports") == []
    assert scheduler.sqlite.query_json("telegram_publishes") == []
