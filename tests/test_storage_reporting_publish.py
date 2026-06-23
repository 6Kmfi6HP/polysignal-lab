from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from polysignal_lab.dashboard.app import create_dashboard_app
from polysignal_lab.domain.enums import ExitMode, Side, TradeResultStatus
from polysignal_lab.domain.paper_result import DailyReport, PaperTradeResult
from polysignal_lab.paper.report import PaperReportService
from polysignal_lab.publish.telegram_publisher import TelegramPublisher
from polysignal_lab.signal_layer.formatter import MessageFormatter
from polysignal_lab.storage.jsonl_store import JSONLStore
from polysignal_lab.storage.sqlite_store import DuplicateRecordError, SQLiteStore
from polysignal_lab.storage.sqlite_schema import SchemaValidationError
from polysignal_lab.storage.state_store import StateStore
from polysignal_lab.strategies.ptb_diff import PTBDiffStrategy
from factories import sample_storage_lifecycle


async def test_formatter_signal_message_within_limit(snapshot, settings):
    # Given: a PRD signal candidate.
    sig = PTBDiffStrategy(settings.strategies.ptb_diff).evaluate(snapshot)[0]

    # When: the Telegram signal message is formatted.
    message = MessageFormatter(max_chars=4096).signal_message(sig, 10.0)

    # Then: the message is bounded, compact, and free of verbose risk copy.
    assert len(message) <= 4096
    assert "<b>🟢 " in message
    assert " · BUY " in message
    assert "</b>" in message
    assert "<code>" in message
    assert "Entry  " in message
    assert "Max    " in message
    assert "Stake  10.00 USDC" in message
    assert "Conf   " in message
    assert "Close  " in message
    assert "<b>Why</b>" in message
    assert "Mode: Paper" in message
    assert "ID: <code>" in message
    for removed in (
        "Risk:",
        "Manual execution only",
        "Do not chase above max entry",
        "not financial advice",
        "No profit guarantee",
        "No real order",
    ):
        assert removed not in message


async def test_telegram_dry_run_publish(settings):
    pub = TelegramPublisher(settings.telegram)
    result = await pub.send("hello", "signal", "sig1")
    assert result.status == "DRY_RUN"
    assert result.signal_id == "sig1"


def test_jsonl_and_state_store(tmp_path):
    logs = JSONLStore(tmp_path / "logs")
    state = StateStore(tmp_path / "state")
    logs.append("signals", {"signal_id": "s1"})
    assert logs.read_all("signals")[0]["signal_id"] == "s1"
    state.write("paper_wallet", {"cash": 10})
    assert state.read("paper_wallet")["cash"] == 10


def test_jsonl_and_state_restore_required_streams(tmp_path):
    # Given: the PRD audit streams and state files persisted under a temp root.
    logs = JSONLStore(tmp_path / "logs")
    state = StateStore(tmp_path / "state")
    streams = [
        "signals",
        "rejected_signals",
        "paper_orders",
        "paper_fills",
        "paper_positions",
        "paper_trade_results",
        "paper_wallet_snapshots",
        "daily_reports",
        "telegram_publishes",
        "system_events",
    ]
    for stream in streams:
        logs.append(stream, {"stream": stream, "id": f"{stream}-1"})
    state.write("paper_wallet", {"cash_balance": 990.0, "equity": 1012.0})
    state.write("open_positions", [{"paper_position_id": "pos1", "status": "OPEN"}])

    # When: persisted JSONL/state is restored from disk.
    restored_streams = {stream: logs.read_all(stream)[0]["stream"] for stream in streams}
    wallet = state.read("paper_wallet")
    positions = state.read("open_positions")
    (tmp_path / "logs" / "broken.jsonl").write_text("{broken\n", encoding="utf-8")

    # Then: every PRD stream is present and malformed JSON is not silently accepted.
    assert restored_streams == {stream: stream for stream in streams}
    assert wallet["cash_balance"] == 990.0
    assert positions[0]["paper_position_id"] == "pos1"
    with pytest.raises(ValueError):
        logs.read_all("broken")


async def test_sqlite_store_and_dashboard(tmp_path, snapshot, settings):
    store = SQLiteStore(tmp_path / "db.sqlite3")
    sig = PTBDiffStrategy(settings.strategies.ptb_diff).evaluate(snapshot)[0]
    store.insert_signal(sig)
    assert store.counts()["signals"] == 1
    app = create_dashboard_app(store)
    client = TestClient(app)
    resp = client.get("/api/signals")
    assert resp.status_code == 200
    assert resp.json()[0]["signal_id"] == sig.signal_id


def test_schema_rejects_missing_required_columns(tmp_path):
    # Given: an existing corrupt SQLite table missing required PRD audit columns.
    db_path = tmp_path / "broken.sqlite3"
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE signals (signal_id TEXT PRIMARY KEY)")

    # When / Then: startup migration validates the schema and refuses the corrupt DB.
    with pytest.raises(SchemaValidationError, match="signals"):
        SQLiteStore(db_path)


def test_duplicate_ids_are_idempotent_or_reported(tmp_path, snapshot, settings):
    # Given: a SQLite store with one full PRD audit lifecycle persisted.
    store = SQLiteStore(tmp_path / "db.sqlite3")
    sig = PTBDiffStrategy(settings.strategies.ptb_diff).evaluate(snapshot)[0]
    lifecycle = sample_storage_lifecycle(sig)

    # When: the same payloads are inserted twice and one conflicting duplicate is inserted.
    store.insert_signal(sig)
    store.insert_signal(sig)
    store.insert_rejected_signal(lifecycle.rejected)
    store.insert_rejected_signal(lifecycle.rejected)
    store.insert_paper_order(lifecycle.order)
    store.insert_paper_order(lifecycle.order)
    store.insert_paper_fill(lifecycle.fill)
    store.insert_paper_fill(lifecycle.fill)
    store.upsert_paper_position(lifecycle.position)
    store.upsert_paper_position(lifecycle.position)
    store.insert_paper_trade_result(lifecycle.result)
    store.insert_paper_trade_result(lifecycle.result)
    store.insert_wallet_snapshot(lifecycle.wallet)
    store.insert_daily_report(lifecycle.report)
    store.insert_daily_report(lifecycle.report)
    store.insert_telegram_publish(lifecycle.publish)
    store.insert_telegram_publish(lifecycle.publish)
    store.insert_system_event(lifecycle.event)
    store.insert_system_event(lifecycle.event)
    conflicting_signal = sig.model_copy(update={"confidence": 0.01})

    # Then: duplicates are idempotent by ID, and conflicting payload reuse is explicit.
    assert store.counts()["signals"] == 1
    assert store.counts()["rejected_signals"] == 1
    assert store.counts()["paper_orders"] == 1
    assert store.counts()["paper_fills"] == 1
    assert store.counts()["paper_positions"] == 1
    assert store.counts()["paper_trade_results"] == 1
    assert store.counts()["daily_reports"] == 1
    assert store.counts()["telegram_publishes"] == 1
    assert store.counts()["system_events"] == 1
    assert store.query_json("paper_wallet_snapshots")[0]["cash_balance"] == 990.0
    with pytest.raises(DuplicateRecordError, match=sig.signal_id):
        store.insert_signal(conflicting_signal)


def test_report_calculates_daily_metrics(settings):
    report = PaperReportService().build_daily_report(
        report_date=date(2026, 6, 21),
        starting_equity=1000,
        ending_equity=1010,
        total_signals=2,
        paper_orders=2,
        paper_fills=2,
        rejected_paper_orders=0,
        open_positions=0,
        results=[],
    )
    assert report.paper_pnl == 10
    assert report.total_signals == 2
    assert report.win_rate == 0


def test_formatter_result_and_daily_messages_are_paper_only() -> None:
    # Given: paper result and daily report domain records.
    result = PaperTradeResult(
        signal_id="sig1",
        paper_position_id="pos1",
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="market1",
        market_slug="btc-updown-5m",
        side=Side.UP,
        entry_price=0.62,
        shares=16.129,
        stake_usdc=10.0,
        exit_mode=ExitMode.RESOLUTION,
        outcome_value=1.0,
        settlement_value=16.129,
        pnl_usdc=6.129,
        roi=0.6129,
        result=TradeResultStatus.WIN,
        opened_at=date(2026, 6, 21),
    )
    report = DailyReport(
        report_date=date(2026, 6, 21),
        starting_equity=1000.0,
        ending_equity=1006.13,
        paper_pnl=6.13,
        paper_roi=0.00613,
        total_signals=1,
        paper_orders=1,
        paper_fills=1,
        rejected_paper_orders=0,
        open_positions=0,
        closed_positions=1,
        win_count=1,
        loss_count=0,
        void_count=0,
        win_rate=1.0,
        total_pnl_usdc=6.13,
        average_roi=0.6129,
        max_drawdown=0.0,
        profit_factor=None,
        strategy_breakdown={"ptb_diff": {"closed_positions": 1}},
    )
    formatter = MessageFormatter(max_chars=4096)

    # When: result and daily Telegram messages are formatted.
    result_message = formatter.result_message(result)
    daily_message = formatter.daily_report_message(report)

    # Then: result messages are compact, paper-marked, and free of stale disclaimers.
    assert result_message.startswith("<b>")
    assert " · WIN</b>" in result_message
    assert "<code>" in result_message
    assert "Side   " in result_message
    assert "Entry  " in result_message
    assert "Stake  " in result_message
    assert "Shares " in result_message
    assert "PnL    " in result_message
    assert "ROI    " in result_message
    assert "Settle " in result_message
    assert "Mode: Paper" in result_message
    assert "ID: <code>" in result_message
    for removed in (
        "Note:",
        "Paper result only",
        "No real order was placed",
        "No profit guarantee",
    ):
        assert removed not in result_message

    # Then: daily messages use the compact report layout and no stale disclaimers.
    assert daily_message.startswith("<b>📊 Daily Paper Report</b>")
    assert "Equity  " in daily_message
    assert " → " in daily_message
    assert "PnL     " in daily_message
    assert "ROI     " in daily_message
    assert "Signals " in daily_message
    assert "Filled  " in daily_message
    assert "Closed  " in daily_message
    assert "W/L     " in daily_message
    assert "WR      " in daily_message
    assert "<b>Strategies</b>" in daily_message
    assert "•" in daily_message
    for removed in (
        "Notes:",
        "Paper results only",
        "No real trades were placed",
        "No profit guarantee",
    ):
        assert removed not in daily_message


async def test_formatter_truncates_long_signal_message(snapshot, settings) -> None:
    # Given: a signal whose reasons would exceed a short Telegram message limit.
    sig = PTBDiffStrategy(settings.strategies.ptb_diff).evaluate(snapshot)[0].model_copy(
        update={"reason_codes": [f"reason-{index}" for index in range(30)]}
    )

    # When: the signal message is formatted with a small max length.
    message = MessageFormatter(max_chars=240).signal_message(sig, 10.0)

    # Then: the message is bounded and visibly marked as truncated.
    assert len(message) <= 240
    assert message.startswith("<b>🟢 ")
    assert message.endswith("[truncated for Telegram]")
