"""
Input: __future__, __future__.annotations, datetime, datetime.date, polysignal_lab.domain.enums, polysignal_lab.domain.enums.ExitMode, polysignal_lab.domain.enums.PositionStatus, polysignal_lab.domain.enums.Side, polysignal_lab.domain.enums.TradeResultStatus, polysignal_lab.domain.paper_position
Output: test_sqlite_store_restores_wallet_reports_and_leaderboard, test_strategy_leaderboard_win_rate_counts_voids_as_closed, test_sqlite_store_uses_wal_and_busy_timeout
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""





from __future__ import annotations

from datetime import date

from polysignal_lab.domain.enums import ExitMode, PositionStatus, Side, TradeResultStatus
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import DailyReport, PaperTradeResult, PaperWalletSnapshot
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.utils import utc_now


def test_sqlite_store_restores_wallet_reports_and_leaderboard(tmp_path):
    # Given: wallet, open position, trade result, and report rows persisted to SQLite.
    store = SQLiteStore(tmp_path / "restore.sqlite3")
    now = utc_now()
    wallet = PaperWalletSnapshot(
        starting_balance=1000.0,
        cash_balance=975.5,
        realized_pnl=14.25,
        equity=1014.25,
        open_position_count=1,
        created_at=now,
    )
    open_position = PaperPosition(
        paper_position_id="pp-open-1",
        signal_id="sig-open-1",
        paper_order_id="po-open-1",
        paper_fill_id="pf-open-1",
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="market-1",
        market_slug="btc-updown-5m",
        token_id="token-up",
        side=Side.UP,
        entry_price=0.72,
        shares=13.88,
        stake_usdc=10.0,
        status=PositionStatus.OPEN,
        opened_at=now,
    )
    closed_position = open_position.model_copy(
        update={
            "paper_position_id": "pp-closed-1",
            "signal_id": "sig-closed-1",
            "paper_order_id": "po-closed-1",
            "paper_fill_id": "pf-closed-1",
            "status": PositionStatus.CLOSED,
            "closed_at": now,
        }
    )
    result = PaperTradeResult(
        paper_trade_id="pt-restore-1",
        signal_id=closed_position.signal_id,
        paper_position_id=closed_position.paper_position_id,
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id=closed_position.market_id,
        market_slug=closed_position.market_slug,
        side=Side.UP,
        entry_price=0.72,
        shares=13.88,
        stake_usdc=10.0,
        exit_mode=ExitMode.RESOLUTION,
        outcome_value=1.0,
        settlement_value=12.4,
        pnl_usdc=2.4,
        roi=0.24,
        result=TradeResultStatus.WIN,
        opened_at=now,
        closed_at=now,
    )
    report = DailyReport(
        report_id="dr-restore-1",
        report_date=date(2026, 6, 21),
        starting_equity=1000.0,
        ending_equity=1014.25,
        paper_pnl=14.25,
        paper_roi=0.01425,
        total_signals=7,
        paper_orders=5,
        paper_fills=4,
        rejected_paper_orders=1,
        open_positions=1,
        closed_positions=1,
        win_count=1,
        loss_count=0,
        void_count=0,
        win_rate=1.0,
        total_pnl_usdc=2.4,
        average_roi=0.24,
        max_drawdown=0.0,
        profit_factor=None,
        strategy_breakdown={
            "ptb_diff": {
                "closed_positions": 1,
                "win_count": 1,
                "loss_count": 0,
                "void_count": 0,
                "total_pnl_usdc": 2.4,
                "average_roi": 0.24,
            }
        },
    )
    store.insert_wallet_snapshot(wallet)
    store.upsert_paper_position(open_position)
    store.upsert_paper_position(closed_position)
    store.insert_paper_trade_result(result)
    store.insert_daily_report(report)

    # When: restart-time data is reconstructed from SQLite payloads.
    restored_wallet = store.restore_latest_wallet_snapshot()
    restored_positions = store.restore_open_positions()
    restored_reports = store.restore_daily_reports()
    leaderboard = store.restore_strategy_leaderboard()

    # Then: restored values match persisted rows, not fabricated in-memory state.
    assert restored_wallet is not None
    assert restored_wallet["cash_balance"] == 975.5
    assert restored_wallet["equity"] == 1014.25
    assert [position["paper_position_id"] for position in restored_positions] == ["pp-open-1"]
    assert restored_reports[0]["report_id"] == "dr-restore-1"
    assert restored_reports[0]["total_signals"] == 7
    assert leaderboard == [
        {
            "strategy": "ptb_diff",
            "closed_positions": 1,
            "win_count": 1,
            "loss_count": 0,
            "void_count": 0,
            "total_pnl_usdc": 2.4,
            "average_roi": 0.24,
            "win_rate": 1.0,
        }
    ]


def test_strategy_leaderboard_win_rate_counts_voids_as_closed(tmp_path):
    # Given: a restored daily report with one WIN and one VOID closed position.
    store = SQLiteStore(tmp_path / "restore.sqlite3")
    report = DailyReport(
        report_id="dr-win-void",
        report_date=date(2026, 6, 22),
        starting_equity=1000.0,
        ending_equity=1002.4,
        paper_pnl=2.4,
        paper_roi=0.0024,
        total_signals=2,
        paper_orders=2,
        paper_fills=2,
        rejected_paper_orders=0,
        open_positions=0,
        closed_positions=2,
        win_count=1,
        loss_count=0,
        void_count=1,
        win_rate=0.5,
        total_pnl_usdc=2.4,
        average_roi=0.12,
        max_drawdown=0.0,
        profit_factor=None,
        strategy_breakdown={
            "ptb_diff": {
                "closed_positions": 2,
                "win_count": 1,
                "loss_count": 0,
                "void_count": 1,
                "total_pnl_usdc": 2.4,
                "average_roi": 0.12,
            }
        },
    )
    store.insert_daily_report(report)

    # When: the strategy leaderboard is reconstructed from persisted reports.
    leaderboard = store.restore_strategy_leaderboard()

    # Then: win_rate uses closed positions, so voids remain in the denominator.
    assert leaderboard[0]["closed_positions"] == 2
    assert leaderboard[0]["win_count"] == 1
    assert leaderboard[0]["void_count"] == 1
    assert leaderboard[0]["win_rate"] == 0.5


def test_sqlite_store_uses_wal_and_busy_timeout(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "pragma.sqlite3")
    try:
        journal_mode = store._conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = store._conn.execute("PRAGMA busy_timeout").fetchone()[0]
        synchronous = store._conn.execute("PRAGMA synchronous").fetchone()[0]
    finally:
        store.close()

    assert str(journal_mode).lower() == "wal"
    assert busy_timeout == 30000
    assert int(synchronous) == 1
