from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

from polysignal_lab.app import scheduler_reporting, scheduler_runtime
from polysignal_lab.app.scheduler import PolySignalScheduler
from polysignal_lab.domain.enums import (
    ExitMode,
    OrderIntent,
    OrderStatus,
    PositionStatus,
    Side,
    TradeResultStatus,
)
from polysignal_lab.domain.paper_result import PaperTradeResult
from polysignal_lab.domain.paper_order import PaperFill, PaperOrder
from polysignal_lab.strategies.ptb_diff import PTBDiffStrategy
from factories import BookFactoryConfig, sample_book


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


def _trade_result(position, result: TradeResultStatus = TradeResultStatus.WIN) -> PaperTradeResult:
    return PaperTradeResult(
        signal_id=position.signal_id,
        paper_position_id=position.paper_position_id,
        strategy=position.strategy,
        asset=position.asset,
        timeframe=position.timeframe,
        market_id=position.market_id,
        market_slug=position.market_slug,
        side=position.side,
        entry_price=position.entry_price,
        shares=position.shares,
        stake_usdc=position.stake_usdc,
        exit_mode=ExitMode.RESOLUTION,
        outcome_value=1.0,
        settlement_value=position.shares,
        pnl_usdc=position.shares - position.stake_usdc,
        roi=(position.shares - position.stake_usdc) / position.stake_usdc,
        result=result,
        opened_at=position.opened_at,
    )


async def test_paper_exit_publish_record_written(tmp_path: Path, snapshot, settings) -> None:
    # Given: an open paper position, active market, and a TP-triggering best bid.
    signal = await _signal(snapshot, settings)
    scheduler = _scheduler(tmp_path, settings)
    scheduler.ctx.markets.upsert_many([snapshot.market])
    scheduler.ctx.books.update(
        sample_book(signal.token_id, BookFactoryConfig(ask=0.82, bid=0.79, size=500))
    )
    processed = await scheduler.process_signal(signal)
    assert processed["paper_position"] is not None
    scheduler.ctx.books.update(
        sample_book(signal.token_id, BookFactoryConfig(ask=0.94, bid=0.91, size=500))
    )

    # When: scheduler reporting checks settlements/exits.
    results = await scheduler.check_settlements()

    # Then: the paper exit closes only paper state and persists result/publish rows.
    result_rows = scheduler.sqlite.query_json("paper_trade_results")
    position_rows = scheduler.sqlite.query_json("paper_positions")
    publish_rows = scheduler.sqlite.query_json("telegram_publishes")
    assert [result.result for result in results] == [TradeResultStatus.WIN]
    assert results[0].exit_mode == ExitMode.TAKE_PROFIT
    assert processed["paper_position"].status == PositionStatus.CLOSED
    assert scheduler.wallet.open_position_count == 0
    assert [row["result"] for row in result_rows] == ["WIN"]
    assert [row["exit_mode"] for row in result_rows] == ["TAKE_PROFIT"]
    assert [row["status"] for row in position_rows] == ["CLOSED"]
    assert [(row["message_type"], row["status"]) for row in publish_rows] == [
        ("paper_result", "DRY_RUN")
    ]
    assert scheduler.logs.read_all("paper_trade_results")[0]["result"] == "WIN"
    assert [
        (row["message_type"], row["status"])
        for row in scheduler.logs.read_all("telegram_publishes")
    ] == [("paper_result", "DRY_RUN")]
    assert not (scheduler.logs.base_dir / "paper_results.jsonl").exists()
    assert not (scheduler.logs.base_dir / "telegram_publish.jsonl").exists()


async def test_paper_exit_storage_failure_rolls_back_and_returns_no_success(
    tmp_path: Path, snapshot, settings
) -> None:
    # Given: an open paper position and a TP-triggering bid, but result storage fails.
    signal = await _signal(snapshot, settings)
    scheduler = _scheduler(tmp_path, settings)
    scheduler.ctx.markets.upsert_many([snapshot.market])
    scheduler.ctx.books.update(
        sample_book(signal.token_id, BookFactoryConfig(ask=0.82, bid=0.79, size=500))
    )
    processed = await scheduler.process_signal(signal)
    assert processed["paper_position"] is not None
    position = processed["paper_position"]
    cash_before = scheduler.wallet.cash_balance
    realized_before = scheduler.wallet.realized_pnl
    scheduler.ctx.books.update(
        sample_book(signal.token_id, BookFactoryConfig(ask=0.94, bid=0.91, size=500))
    )

    def fail_insert_trade_result(result: PaperTradeResult) -> None:
        raise sqlite3.OperationalError("paper result insert failed")

    scheduler.sqlite.insert_paper_trade_result = fail_insert_trade_result

    # When: scheduler reporting checks paper exits.
    results = await scheduler.check_settlements()

    # Then: no successful settlement is returned and in-memory/durable state remains open.
    result_rows = scheduler.sqlite.query_json("paper_trade_results")
    position_rows = scheduler.sqlite.query_json("paper_positions")
    publish_rows = scheduler.sqlite.query_json("telegram_publishes")
    assert results == []
    assert result_rows == []
    assert [row["status"] for row in position_rows] == ["OPEN"]
    assert publish_rows == []
    assert position.status == PositionStatus.OPEN
    assert position.closed_at is None
    assert scheduler.wallet.open_position_count == 1
    assert scheduler.wallet.cash_balance == cash_before
    assert scheduler.wallet.realized_pnl == realized_before


async def test_paper_exit_publish_row_failure_rolls_back_without_closed_rows(
    tmp_path: Path, snapshot, settings
) -> None:
    # Given: an open paper position and a TP-triggering bid, but publish-row storage fails.
    signal = await _signal(snapshot, settings)
    scheduler = _scheduler(tmp_path, settings)
    scheduler.ctx.markets.upsert_many([snapshot.market])
    scheduler.ctx.books.update(
        sample_book(signal.token_id, BookFactoryConfig(ask=0.82, bid=0.79, size=500))
    )
    processed = await scheduler.process_signal(signal)
    assert processed["paper_position"] is not None
    position = processed["paper_position"]
    scheduler.ctx.books.update(
        sample_book(signal.token_id, BookFactoryConfig(ask=0.94, bid=0.91, size=500))
    )

    def fail_insert_publish(publish: dict[str, str | None]) -> None:
        raise sqlite3.OperationalError("paper publish insert failed")

    scheduler.sqlite.insert_telegram_publish = fail_insert_publish

    # When: scheduler reporting checks paper exits with paper-result publishing enabled.
    results = await scheduler.check_settlements()

    # Then: no success is returned and no closed durable rows remain.
    assert results == []
    assert scheduler.sqlite.query_json("paper_trade_results") == []
    assert [row["status"] for row in scheduler.sqlite.query_json("paper_positions")] == [
        "OPEN"
    ]
    assert scheduler.sqlite.query_json("telegram_publishes") == []
    assert position.status == PositionStatus.OPEN
    assert scheduler.wallet.open_position_count == 1


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

async def test_daily_report_publish_record_written(tmp_path: Path, snapshot, settings) -> None:
    # Given: stored signals, one filled paper order, one rejected paper order, and a closed result.
    signal = await _signal(snapshot, settings)
    scheduler = _scheduler(tmp_path, settings)
    scheduler.ctx.books.update(
        sample_book(signal.token_id, BookFactoryConfig(ask=0.82, bid=0.79, size=500))
    )
    filled = await scheduler.process_signal(signal)
    assert filled["paper_position"] is not None
    rejected_signal = signal.model_copy(
        update={"signal_id": "sig-rejected-report", "token_id": "missing-token-report"}
    )
    rejected = await scheduler.process_signal(rejected_signal)
    assert rejected["paper_order"] is not None
    assert rejected["paper_order"].status == OrderStatus.REJECTED
    position = filled["paper_position"]
    result = _trade_result(position)
    position.status = PositionStatus.CLOSED
    position.closed_at = result.closed_at
    scheduler.wallet.close_position(position.paper_position_id, result.settlement_value, result.pnl_usdc)
    scheduler.sqlite.upsert_paper_position(position)
    scheduler.sqlite.insert_paper_trade_result(result)

    # When: the daily report is generated with Telegram daily reporting enabled.
    report = await scheduler.generate_daily_report()

    # Then: the report uses persisted rows and writes a durable Telegram publish record.
    assert report is not None
    report_rows = scheduler.sqlite.query_json("daily_reports")
    publish_rows = scheduler.sqlite.query_json("telegram_publishes")
    assert report.report_date == date.today()
    assert report.total_signals == 2
    assert report.paper_orders == 2
    assert report.paper_fills == 1
    assert report.rejected_paper_orders == 1
    assert report.open_positions == 0
    assert report.closed_positions == 1
    assert report.win_count == 1
    assert report.total_pnl_usdc == result.pnl_usdc
    assert report.stale_paper_fills == 0
    assert report.paper_attempts_by_intent == {"default": 2}
    assert report.paper_fills_by_intent == {"default": 1}
    assert report.paper_rejects_by_reason == {"PAPER_MISSING_ORDERBOOK": 1}
    assert report.paper_rejects_by_original_reason == {"MISSING_ORDERBOOK": 1}
    assert report.average_execution_staleness_ms is not None
    assert report.average_executable_depth_usdc is not None
    assert report.paper_execution_assumptions == {
        "max_book_staleness_ms": settings.data.polymarket.max_book_staleness_ms,
        "min_fill_ratio": settings.paper_trading.fill_model.min_fill_ratio,
        "reject_if_partial": settings.paper_trading.fill_model.reject_if_partial,
        "require_depth_check": settings.paper_trading.fill_model.require_depth_check,
        "slippage_bps": settings.paper_trading.fill_model.slippage_bps,
    }
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
    tmp_path: Path, snapshot, settings
) -> None:
    # Given: stored report inputs, but daily publish-row persistence fails.
    signal = await _signal(snapshot, settings)
    scheduler = _scheduler(tmp_path, settings)
    scheduler.ctx.books.update(
        sample_book(signal.token_id, BookFactoryConfig(ask=0.82, bid=0.79, size=500))
    )
    filled = await scheduler.process_signal(signal)
    assert filled["paper_position"] is not None
    position = filled["paper_position"]
    result = _trade_result(position)
    position.status = PositionStatus.CLOSED
    position.closed_at = result.closed_at
    scheduler.wallet.close_position(
        position.paper_position_id, result.settlement_value, result.pnl_usdc
    )
    scheduler.sqlite.upsert_paper_position(position)
    scheduler.sqlite.insert_paper_trade_result(result)

    def fail_insert_publish(publish: dict[str, str | None]) -> None:
        raise sqlite3.OperationalError("publish insert failed")

    scheduler.sqlite.insert_telegram_publish = fail_insert_publish

    # When: the daily report is generated with Telegram daily reporting enabled.
    report = await scheduler.generate_daily_report()

    # Then: runtime receives no successful report and no durable report/publish rows exist.
    assert report is None
    assert scheduler.sqlite.query_json("daily_reports") == []
    assert scheduler.sqlite.query_json("telegram_publishes") == []
