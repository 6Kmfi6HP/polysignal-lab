# noqa: SIZE_OK  — integration coverage file for SQLite restore migrations
"""
Input: __future__, __future__.annotations, datetime, datetime.date, json, pytest, polysignal_lab.domain.enums, polysignal_lab.domain.enums.ExitMode, polysignal_lab.domain.enums.PositionStatus, polysignal_lab.domain.enums.Side, polysignal_lab.domain.enums.TradeResultStatus, polysignal_lab.domain.paper_result
Output: test_sqlite_store_restores_wallet_reports_and_leaderboard, test_sqlite_store_rejects_invalid_paper_trade_rows, test_sqlite_store_skips_malformed_payload_paper_trade_rows, test_sqlite_store_excludes_invalid_position_events, test_strategy_leaderboard_win_rate_counts_voids_as_closed, test_sqlite_store_uses_wal_and_busy_timeout
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import sqlite3

import pytest

from factories import sample_paper_trade_result

from polysignal_lab.domain.enums import ExitMode, PositionStatus, Side, TradeResultStatus
from polysignal_lab.domain.paper_result import (
    DailyReport,
    InvalidPaperTradeResultRow,
    PaperWalletSnapshot,
)
from polysignal_lab.storage.sqlite_store import MalformedSQLitePayloadError, SQLiteStore
from polysignal_lab.utils import utc_now
from signal_helpers import ptb_signal_from_snapshot


def test_payload_insert_preserves_duplicate_detection(tmp_path, snapshot, settings) -> None:
    store = SQLiteStore(tmp_path / "db.sqlite3")
    payload = ptb_signal_from_snapshot(snapshot, settings)

    store.insert_signal(payload)
    store.insert_signal(payload)

    assert store.counts()["signals"] == 1


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
    open_position = {
        "paper_position_id": "pp-open-1",
        "position_id": "pp-open-1",
        "signal_id": "sig-open-1",
        "paper_order_id": "po-open-1",
        "paper_fill_id": "pf-open-1",
        "strategy": "ptb_diff",
        "asset": "BTC",
        "timeframe": "5m",
        "market_id": "market-1",
        "market_slug": "btc-updown-5m",
        "token_id": "token-up",
        "side": Side.UP.value,
        "entry_price": 0.72,
        "shares": 13.88,
        "stake_usdc": 10.0,
        "status": PositionStatus.OPEN.value,
        "is_closed": False,
        "opened_at": now.isoformat(),
    }
    closed_position = {
        **open_position,
        "paper_position_id": "pp-closed-1",
        "position_id": "pp-closed-1",
        "signal_id": "sig-closed-1",
        "paper_order_id": "po-closed-1",
        "paper_fill_id": "pf-closed-1",
        "status": PositionStatus.CLOSED.value,
        "is_closed": True,
        "closed_at": now.isoformat(),
    }
    result = sample_paper_trade_result(
        paper_trade_id="pt-restore-1",
        signal_id=closed_position["signal_id"],
        paper_position_id=closed_position["paper_position_id"],
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id=closed_position["market_id"],
        market_slug=closed_position["market_slug"],
        side=Side.UP.value,
        entry_price=0.72,
        shares=13.88,
        stake_usdc=10.0,
        exit_mode=ExitMode.RESOLUTION.value,
        outcome_value=1.0,
        settlement_value=12.4,
        pnl_usdc=2.4,
        roi=0.24,
        result=TradeResultStatus.WIN.value,
        opened_at=now.isoformat(),
        closed_at=now.isoformat(),
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
    for pos in (open_position, closed_position):
        store.insert_system_event(
            {
                "event_id": f"evt-{pos['paper_position_id']}",
                "event_type": "nautilus_position",
                "severity": "info",
                "created_at": pos.get("closed_at") or pos["opened_at"],
                "ts": pos.get("closed_at") or pos["opened_at"],
                **pos,
            }
        )
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


def test_sqlite_store_rejects_invalid_paper_trade_rows(tmp_path) -> None:
    # Given: malformed trade-result rows which used to be silently coerced.
    store = SQLiteStore(tmp_path / "restore.sqlite3")
    invalid = sample_paper_trade_result(paper_trade_id="pt-invalid", shares="NaN")

    # When/Then: API inserts fail closed.
    with pytest.raises(InvalidPaperTradeResultRow):
        store.insert_paper_trade_result(invalid)

    # When: a hostile row already exists in persisted storage.
    with store._lock, store._conn:
        store._conn.execute(
            """INSERT INTO paper_trade_results(
                paper_trade_id,signal_id,strategy,asset,timeframe,market_id,result,pnl_usdc,roi,closed_at,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                invalid["paper_trade_id"],
                invalid["signal_id"],
                invalid["strategy"],
                invalid["asset"],
                invalid["timeframe"],
                invalid["market_id"],
                invalid["result"],
                invalid["pnl_usdc"],
                invalid["roi"],
                invalid["closed_at"],
                json.dumps(invalid),
            ),
        )

    # Then: restore/query excludes the invalid row instead of fabricating values.
    assert store.query_json("paper_trade_results") == []


def test_sqlite_store_rejects_zero_money_paper_trade_rows(tmp_path: Path) -> None:
    # Given: zero money fields which would fabricate a settled trade.
    store = SQLiteStore(tmp_path / "restore.sqlite3")
    for key in ("entry_price", "shares", "stake_usdc"):
        invalid = sample_paper_trade_result(paper_trade_id=f"pt-zero-{key}")
        invalid[key] = 0.0

        # When/Then: API inserts fail closed.
        with pytest.raises(InvalidPaperTradeResultRow):
            store.insert_paper_trade_result(invalid)

        # When: a hostile row already exists in persisted storage.
        with store._lock, store._conn:
            store._conn.execute(
                """INSERT INTO paper_trade_results(
                    paper_trade_id,signal_id,strategy,asset,timeframe,market_id,result,pnl_usdc,roi,closed_at,payload_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    invalid["paper_trade_id"],
                    invalid["signal_id"],
                    invalid["strategy"],
                    invalid["asset"],
                    invalid["timeframe"],
                    invalid["market_id"],
                    invalid["result"],
                    invalid["pnl_usdc"],
                    invalid["roi"],
                    invalid["closed_at"],
                    json.dumps(invalid),
                ),
            )

    # Then: restore/query excludes zero-money rows instead of trusting them.
    assert store.query_json("paper_trade_results") == []


def test_sqlite_store_rejects_boolean_money_paper_trade_rows(tmp_path: Path) -> None:
    # Given: boolean money fields which JSON can otherwise coerce to one or zero.
    store = SQLiteStore(tmp_path / "restore.sqlite3")
    for key in ("entry_price", "shares", "stake_usdc"):
        invalid = sample_paper_trade_result(paper_trade_id=f"pt-bool-{key}")
        invalid[key] = True

        # When/Then: API inserts fail closed.
        with pytest.raises(InvalidPaperTradeResultRow):
            store.insert_paper_trade_result(invalid)

        # When: a hostile row already exists in persisted storage.
        with store._lock, store._conn:
            store._conn.execute(
                """INSERT INTO paper_trade_results(
                    paper_trade_id,signal_id,strategy,asset,timeframe,market_id,result,pnl_usdc,roi,closed_at,payload_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    invalid["paper_trade_id"],
                    invalid["signal_id"],
                    invalid["strategy"],
                    invalid["asset"],
                    invalid["timeframe"],
                    invalid["market_id"],
                    invalid["result"],
                    invalid["pnl_usdc"],
                    invalid["roi"],
                    invalid["closed_at"],
                    json.dumps(invalid),
                ),
            )

    # Then: restore/query excludes boolean-money rows instead of coercing them.
    assert store.query_json("paper_trade_results") == []


def test_sqlite_store_rejects_huge_integer_paper_trade_rows(tmp_path: Path) -> None:
    # Given: huge valid JSON integers which cannot fit paper numeric boundaries.
    store = SQLiteStore(tmp_path / "restore.sqlite3")
    invalid = sample_paper_trade_result(paper_trade_id="pt-huge-entry-price")
    invalid["entry_price"] = 10**4000

    # When/Then: API inserts fail closed with the typed parser error.
    with pytest.raises(InvalidPaperTradeResultRow):
        store.insert_paper_trade_result(invalid)

    # When: a hostile row already exists in persisted storage.
    with store._lock, store._conn:
        store._conn.execute(
            """INSERT INTO paper_trade_results(
                paper_trade_id,signal_id,strategy,asset,timeframe,market_id,result,pnl_usdc,roi,closed_at,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                invalid["paper_trade_id"],
                invalid["signal_id"],
                invalid["strategy"],
                invalid["asset"],
                invalid["timeframe"],
                invalid["market_id"],
                invalid["result"],
                invalid["pnl_usdc"],
                invalid["roi"],
                invalid["closed_at"],
                json.dumps(invalid),
            ),
        )

    # Then: restore/query excludes it instead of leaking OverflowError.
    assert store.query_json("paper_trade_results") == []


def test_sqlite_store_skips_malformed_payload_paper_trade_rows(tmp_path: Path) -> None:
    # Given: a persisted trade-result row whose payload_json is not valid JSON.
    db_path = tmp_path / "restore.sqlite3"
    store = SQLiteStore(db_path)

    with sqlite3.connect(db_path) as conn:
        _ = conn.execute(
            """INSERT INTO paper_trade_results(
                paper_trade_id,signal_id,strategy,asset,timeframe,market_id,result,pnl_usdc,roi,closed_at,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "pt-malformed-json",
                "sig-malformed-json",
                "ptb_diff",
                "BTC",
                "5m",
                "market-1",
                TradeResultStatus.WIN.value,
                2.4,
                0.24,
                utc_now().isoformat(),
                "{not-json",
            ),
        )

    # When/Then: restore/query excludes the bad row instead of raising JSONDecodeError.
    assert store.query_json("paper_trade_results") == []


def test_sqlite_store_skips_malformed_timestamp_paper_trade_rows(tmp_path: Path) -> None:
    # Given: a persisted trade-result row whose timestamp payload cannot be parsed.
    db_path = tmp_path / "restore.sqlite3"
    store = SQLiteStore(db_path)
    for key in ("opened_at", "closed_at"):
        invalid = sample_paper_trade_result(paper_trade_id=f"pt-malformed-{key}")
        invalid[key] = "not-a-date"

        with sqlite3.connect(db_path) as conn:
            _ = conn.execute(
                """INSERT INTO paper_trade_results(
                    paper_trade_id,signal_id,strategy,asset,timeframe,market_id,result,pnl_usdc,roi,closed_at,payload_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    invalid["paper_trade_id"],
                    invalid["signal_id"],
                    invalid["strategy"],
                    invalid["asset"],
                    invalid["timeframe"],
                    invalid["market_id"],
                    invalid["result"],
                    invalid["pnl_usdc"],
                    invalid["roi"],
                    invalid["closed_at"],
                    json.dumps(invalid),
                ),
            )

    # When/Then: restore/query excludes the bad row instead of raising ValueError.
    assert store.query_json("paper_trade_results") == []


def test_sqlite_store_skips_json_integer_digit_limit_payloads(tmp_path: Path) -> None:
    # Given: valid JSON payloads can still fail Python's integer parser before row validation.
    db_path = tmp_path / "restore.sqlite3"
    store = SQLiteStore(db_path)
    huge_json_integer = "1" + ("0" * 5000)
    trade = sample_paper_trade_result(paper_trade_id="pt-digit-limit")
    trade["entry_price"] = "__HUGE__"
    trade_payload = json.dumps(trade).replace('"__HUGE__"', huge_json_integer)
    now = utc_now().isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO paper_trade_results(
                paper_trade_id,signal_id,strategy,asset,timeframe,market_id,result,pnl_usdc,roi,closed_at,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                trade["paper_trade_id"],
                trade["signal_id"],
                trade["strategy"],
                trade["asset"],
                trade["timeframe"],
                trade["market_id"],
                trade["result"],
                trade["pnl_usdc"],
                trade["roi"],
                trade["closed_at"],
                trade_payload,
            ),
        )
        conn.execute(
            """INSERT INTO system_events(event_id,event_type,severity,created_at,payload_json)
            VALUES(?,?,?,?,?)""",
            (
                "evt-digit-limit",
                "nautilus_position",
                "info",
                now,
                f'{{"event_id":"evt-digit-limit","stake_usdc":{huge_json_integer}}}',
            ),
        )
        conn.execute(
            """INSERT INTO daily_reports(
                report_id,report_date,total_signals,total_pnl_usdc,win_rate,created_at,payload_json
            ) VALUES(?,?,?,?,?,?,?)""",
            (
                "dr-digit-limit",
                date(2026, 6, 22).isoformat(),
                1,
                0.0,
                0.0,
                now,
                f'{{"report_id":"dr-digit-limit","total_pnl_usdc":{huge_json_integer}}}',
            ),
        )
        conn.execute(
            """INSERT INTO paper_wallet_snapshots(
                wallet_id, equity, cash_balance, realized_pnl, open_position_count, created_at, payload_json
            ) VALUES(?,?,?,?,?,?,?)""",
            (
                "wallet-digit-limit",
                1000.0,
                1000.0,
                0.0,
                0,
                now,
                f'{{"wallet_id":"wallet-digit-limit","equity":{huge_json_integer}}}',
            ),
        )

    assert store.query_json("paper_trade_results") == []
    assert store.query_json("system_events") == []
    assert store.restore_daily_reports() == []
    assert store.restore_latest_wallet_snapshot() is None


def test_sqlite_store_skips_malformed_system_events(tmp_path: Path) -> None:
    # Given: a malformed system event payload row exists in persisted storage.
    db_path = tmp_path / "restore.sqlite3"
    store = SQLiteStore(db_path)
    with sqlite3.connect(db_path) as conn:
        _ = conn.execute(
            """INSERT INTO system_events(event_id,event_type,severity,created_at,payload_json)
            VALUES(?,?,?,?,?)""",
            (
                "evt-malformed-json",
                "nautilus_position",
                "info",
                utc_now().isoformat(),
                "{not-json",
            ),
        )

    # When/Then: restore surfaces skip the bad row instead of raising JSONDecodeError.
    assert store.query_json("system_events") == []
    assert store.restore_open_positions() == []
    assert store.restore_latest_system_event("nautilus_position") is None


def test_sqlite_store_skips_malformed_daily_reports(tmp_path: Path) -> None:
    # Given: a malformed daily report payload row exists in persisted storage.
    db_path = tmp_path / "restore.sqlite3"
    store = SQLiteStore(db_path)
    with sqlite3.connect(db_path) as conn:
        _ = conn.execute(
            """INSERT INTO daily_reports(
                report_id,report_date,total_signals,total_pnl_usdc,win_rate,created_at,payload_json
            ) VALUES(?,?,?,?,?,?,?)""",
            (
                "dr-malformed-json",
                date(2026, 6, 22).isoformat(),
                1,
                0.0,
                0.0,
                utc_now().isoformat(),
                "{not-json",
            ),
        )

    # When/Then: report restore surfaces skip the bad row instead of raising JSONDecodeError.
    assert store.restore_daily_reports() == []
    assert store.restore_strategy_leaderboard() == []


def test_sqlite_store_rejects_malformed_existing_payload(tmp_path: Path) -> None:
    # Given: an existing same-key row has malformed payload_json.
    db_path = tmp_path / "restore.sqlite3"
    store = SQLiteStore(db_path)
    with sqlite3.connect(db_path) as conn:
        _ = conn.execute(
            """INSERT INTO system_events(event_id,event_type,severity,created_at,payload_json)
            VALUES(?,?,?,?,?)""",
            (
                "evt-malformed-existing",
                "health",
                "info",
                utc_now().isoformat(),
                "{not-json",
            ),
        )

    # When/Then: idempotent insert fails closed with a typed store error, not JSONDecodeError.
    with pytest.raises(MalformedSQLitePayloadError):
        store.insert_system_event(
            {
                "event_id": "evt-malformed-existing",
                "event_type": "health",
                "severity": "info",
                "created_at": utc_now().isoformat(),
            }
        )


def test_sqlite_store_rejects_incomplete_paper_trade_rows(tmp_path) -> None:
    # Given: persisted trade-result JSON missing fields required by the old model.
    store = SQLiteStore(tmp_path / "restore.sqlite3")
    incomplete = sample_paper_trade_result(paper_trade_id="pt-incomplete")
    del incomplete["signal_id"]
    del incomplete["side"]
    del incomplete["opened_at"]

    # When/Then: API inserts fail closed with the typed parser error.
    with pytest.raises(InvalidPaperTradeResultRow):
        store.insert_paper_trade_result(incomplete)

    # When: an incomplete row already exists in persisted storage.
    with store._lock, store._conn:
        store._conn.execute(
            """INSERT INTO paper_trade_results(
                paper_trade_id,signal_id,strategy,asset,timeframe,market_id,result,pnl_usdc,roi,closed_at,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                incomplete["paper_trade_id"],
                "",
                incomplete["strategy"],
                incomplete["asset"],
                incomplete["timeframe"],
                incomplete["market_id"],
                incomplete["result"],
                incomplete["pnl_usdc"],
                incomplete["roi"],
                incomplete["closed_at"],
                json.dumps(incomplete),
            ),
        )

    # Then: restore/query excludes it instead of fabricating missing fields.
    assert store.query_json("paper_trade_results") == []


def test_sqlite_store_rejects_paper_trade_rows_missing_exit_mode(tmp_path: Path) -> None:
    # Given: a persisted trade-result row missing the required settlement mode.
    store = SQLiteStore(tmp_path / "restore.sqlite3")
    incomplete = sample_paper_trade_result(paper_trade_id="pt-missing-exit-mode")
    del incomplete["exit_mode"]

    with store._lock, store._conn:
        store._conn.execute(
            """INSERT INTO paper_trade_results(
                paper_trade_id,signal_id,strategy,asset,timeframe,market_id,result,pnl_usdc,roi,closed_at,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                incomplete["paper_trade_id"],
                incomplete["signal_id"],
                incomplete["strategy"],
                incomplete["asset"],
                incomplete["timeframe"],
                incomplete["market_id"],
                incomplete["result"],
                incomplete["pnl_usdc"],
                incomplete["roi"],
                incomplete["closed_at"],
                json.dumps(incomplete),
            ),
        )

    # When/Then: restore/query excludes it instead of accepting an incomplete settlement row.
    assert store.query_json("paper_trade_results") == []


def test_sqlite_store_rejects_paper_trade_rows_with_invalid_exit_mode(tmp_path: Path) -> None:
    # Given: a persisted trade-result row with an unknown settlement mode.
    store = SQLiteStore(tmp_path / "restore.sqlite3")
    invalid = sample_paper_trade_result(paper_trade_id="pt-invalid-exit-mode")
    invalid["exit_mode"] = "BROKEN"

    with store._lock, store._conn:
        store._conn.execute(
            """INSERT INTO paper_trade_results(
                paper_trade_id,signal_id,strategy,asset,timeframe,market_id,result,pnl_usdc,roi,closed_at,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                invalid["paper_trade_id"],
                invalid["signal_id"],
                invalid["strategy"],
                invalid["asset"],
                invalid["timeframe"],
                invalid["market_id"],
                invalid["result"],
                invalid["pnl_usdc"],
                invalid["roi"],
                invalid["closed_at"],
                json.dumps(invalid),
            ),
        )

    # When/Then: restore/query excludes it instead of accepting an unknown settlement mode.
    assert store.query_json("paper_trade_results") == []


def test_sqlite_store_rejects_paper_trade_rows_missing_market_slug(tmp_path: Path) -> None:
    # Given: a persisted trade-result row missing the market display key.
    store = SQLiteStore(tmp_path / "restore.sqlite3")
    incomplete = sample_paper_trade_result(paper_trade_id="pt-missing-market-slug")
    del incomplete["market_slug"]

    with store._lock, store._conn:
        store._conn.execute(
            """INSERT INTO paper_trade_results(
                paper_trade_id,signal_id,strategy,asset,timeframe,market_id,result,pnl_usdc,roi,closed_at,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                incomplete["paper_trade_id"],
                incomplete["signal_id"],
                incomplete["strategy"],
                incomplete["asset"],
                incomplete["timeframe"],
                incomplete["market_id"],
                incomplete["result"],
                incomplete["pnl_usdc"],
                incomplete["roi"],
                incomplete["closed_at"],
                json.dumps(incomplete),
            ),
        )

    # When/Then: restore/query excludes it instead of accepting an incomplete market row.
    assert store.query_json("paper_trade_results") == []


def test_sqlite_store_excludes_invalid_position_events(tmp_path) -> None:
    # Given: a malformed position event with an unknown status.
    store = SQLiteStore(tmp_path / "restore.sqlite3")
    store.insert_system_event(
        {
            "event_id": "evt-bad-position",
            "event_type": "nautilus_position",
            "severity": "info",
            "created_at": utc_now().isoformat(),
            "paper_position_id": "pos-bad",
            "market_id": "market-1",
            "token_id": "token-up",
            "status": "BROKEN",
            "is_closed": False,
            "shares": 10.0,
            "entry_price": 0.5,
            "stake_usdc": 5.0,
        }
    )

    # When/Then: restore paths fail closed instead of treating it as OPEN.
    assert store.restore_open_positions() == []
    assert store.restore_closed_positions() == []


def test_sqlite_store_excludes_incomplete_open_position_events(tmp_path) -> None:
    # Given: a persisted open position event missing settlement money fields.
    store = SQLiteStore(tmp_path / "restore.sqlite3")
    store.insert_system_event(
        {
            "event_id": "evt-incomplete-position",
            "event_type": "nautilus_position",
            "severity": "info",
            "created_at": utc_now().isoformat(),
            "paper_position_id": "pos-incomplete",
            "market_id": "market-1",
            "token_id": "token-up",
            "status": PositionStatus.OPEN.value,
            "is_closed": False,
        }
    )

    # When/Then: restore paths fail closed instead of returning an un-settleable row.
    assert store.restore_open_positions() == []
    assert store.restore_closed_positions() == []


def test_sqlite_store_excludes_open_position_events_with_zero_money(tmp_path) -> None:
    # Given: open position rows with finite but un-settleable zero money fields.
    store = SQLiteStore(tmp_path / "restore.sqlite3")
    event_time = utc_now().isoformat()
    base = {
        "event_type": "nautilus_position",
        "severity": "info",
        "created_at": event_time,
        "ts": event_time,
        "market_id": "market-1",
        "token_id": "token-up",
        "side": Side.UP.value,
        "status": PositionStatus.OPEN.value,
        "is_closed": False,
        "shares": 10.0,
        "entry_price": 0.5,
        "stake_usdc": 5.0,
        "opened_at": event_time,
    }
    for key in ("shares", "entry_price", "stake_usdc"):
        store.insert_system_event(
            {
                **base,
                "event_id": f"evt-zero-{key}",
                "paper_position_id": f"pos-zero-{key}",
                key: 0.0,
            }
        )

    # When/Then: restore fails closed instead of returning zero-money rows.
    assert store.restore_open_positions() == []
    assert store.restore_closed_positions() == []


def test_sqlite_store_excludes_closed_position_events_with_zero_money(tmp_path) -> None:
    # Given: closed position rows with finite but un-settleable zero money fields.
    store = SQLiteStore(tmp_path / "restore.sqlite3")
    event_time = utc_now().isoformat()
    base = {
        "event_type": "nautilus_position",
        "severity": "info",
        "created_at": event_time,
        "ts": event_time,
        "market_id": "market-1",
        "token_id": "token-up",
        "side": Side.UP.value,
        "status": PositionStatus.CLOSED.value,
        "is_closed": True,
        "shares": 10.0,
        "entry_price": 0.5,
        "stake_usdc": 5.0,
        "opened_at": event_time,
        "closed_at": event_time,
    }
    for key in ("shares", "entry_price", "stake_usdc"):
        store.insert_system_event(
            {
                **base,
                "event_id": f"evt-closed-zero-{key}",
                "paper_position_id": f"pos-closed-zero-{key}",
                key: 0.0,
            }
        )

    # When/Then: restore fails closed instead of returning zero-money rows.
    assert store.restore_open_positions() == []
    assert store.restore_closed_positions() == []


def test_sqlite_store_excludes_open_position_events_with_boolean_money(
    tmp_path,
) -> None:
    # Given: open position rows with boolean money fields from hostile JSON.
    store = SQLiteStore(tmp_path / "restore.sqlite3")
    event_time = utc_now().isoformat()
    base = {
        "event_type": "nautilus_position",
        "severity": "info",
        "created_at": event_time,
        "ts": event_time,
        "market_id": "market-1",
        "token_id": "token-up",
        "side": Side.UP.value,
        "status": PositionStatus.OPEN.value,
        "is_closed": False,
        "shares": 10.0,
        "entry_price": 0.5,
        "stake_usdc": 5.0,
        "opened_at": event_time,
    }
    for key in ("shares", "entry_price", "stake_usdc"):
        store.insert_system_event(
            {
                **base,
                "event_id": f"evt-bool-{key}",
                "paper_position_id": f"pos-bool-{key}",
                key: True,
            }
        )

    # When/Then: restore fails closed instead of coercing true to one.
    assert store.restore_open_positions() == []
    assert store.restore_closed_positions() == []


def test_sqlite_store_skips_malformed_wallet_snapshot_payload(tmp_path: Path) -> None:
    # Given: a persisted wallet snapshot row whose payload_json is not valid JSON.
    db_path = tmp_path / "restore.sqlite3"
    store = SQLiteStore(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO paper_wallet_snapshots(
                wallet_id, equity, cash_balance, realized_pnl, open_position_count, created_at, payload_json
            ) VALUES(?,?,?,?,?,?,?)""",
            (
                "wallet-malformed",
                1000.0,
                1000.0,
                0.0,
                0,
                utc_now().isoformat(),
                "{not-json",
            ),
        )

    # When/Then: restore fails closed instead of raising JSONDecodeError.
    assert store.restore_latest_wallet_snapshot() is None


def test_sqlite_store_skips_hostile_wallet_snapshot_payload(tmp_path: Path) -> None:
    # Given: a persisted wallet snapshot row whose payload_json is valid JSON but not valid money state.
    db_path = tmp_path / "restore.sqlite3"
    store = SQLiteStore(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO paper_wallet_snapshots(
                wallet_id, equity, cash_balance, realized_pnl, open_position_count, created_at, payload_json
            ) VALUES(?,?,?,?,?,?,?)""",
            (
                "wallet-hostile",
                1000.0,
                1000.0,
                0.0,
                0,
                utc_now().isoformat(),
                json.dumps(
                    {
                        "wallet_id": "wallet-hostile",
                        "equity": float("nan"),
                        "cash_balance": True,
                        "realized_pnl": 0.0,
                        "open_position_count": 0,
                        "created_at": utc_now().isoformat(),
                    }
                ),
            ),
        )

    # When/Then: restore fails closed instead of returning fabricated money.
    assert store.restore_latest_wallet_snapshot() is None


def test_sqlite_store_skips_wallet_snapshot_with_oversized_count(tmp_path: Path) -> None:
    # Given: a persisted wallet snapshot row whose count cannot be represented safely.
    db_path = tmp_path / "restore.sqlite3"
    store = SQLiteStore(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO paper_wallet_snapshots(
                wallet_id, equity, cash_balance, realized_pnl, open_position_count, created_at, payload_json
            ) VALUES(?,?,?,?,?,?,?)""",
            (
                "wallet-overflow",
                1000.0,
                1000.0,
                0.0,
                0,
                utc_now().isoformat(),
                json.dumps(
                    {
                        "wallet_id": "wallet-overflow",
                        "equity": 1000.0,
                        "cash_balance": 1000.0,
                        "realized_pnl": 0.0,
                        "open_position_count": 10**4000,
                        "created_at": utc_now().isoformat(),
                    }
                ),
            ),
        )

    # When/Then: restore fails closed instead of raising OverflowError.
    assert store.restore_latest_wallet_snapshot() is None


def test_sqlite_store_skips_hostile_daily_report_payload(tmp_path: Path) -> None:
    # Given: a persisted daily report row whose payload_json has hostile valid JSON numerics.
    db_path = tmp_path / "restore.sqlite3"
    store = SQLiteStore(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO daily_reports(
                report_id, report_date, total_signals, total_pnl_usdc, win_rate, created_at, payload_json
            ) VALUES(?,?,?,?,?,?,?)""",
            (
                "dr-hostile",
                "2026-06-22",
                1,
                0.0,
                0.0,
                utc_now().isoformat(),
                json.dumps(
                    {
                        "report_id": "dr-hostile",
                        "report_date": "2026-06-22",
                        "total_pnl_usdc": float("inf"),
                        "average_roi": "NaN",
                        "win_rate": 0.0,
                        "strategy_breakdown": {
                            "bad": {
                                "closed_positions": True,
                                "win_count": True,
                                "loss_count": 0,
                                "void_count": 0,
                                "total_pnl_usdc": "Infinity",
                                "average_roi": "NaN",
                            }
                        },
                        "created_at": utc_now().isoformat(),
                    }
                ),
            ),
        )

    # When/Then: restore and leaderboard fail closed.
    assert store.restore_daily_reports() == []
    assert store.restore_strategy_leaderboard() == []


def test_sqlite_store_excludes_open_position_events_without_timestamp(tmp_path) -> None:
    # Given: a persisted open position event with money fields but no event timestamp.
    store = SQLiteStore(tmp_path / "restore.sqlite3")
    payload = {
        "event_id": "evt-open-no-timestamp",
        "event_type": "nautilus_position",
        "severity": "info",
        "paper_position_id": "pos-open-no-timestamp",
        "market_id": "market-1",
        "token_id": "token-up",
        "status": PositionStatus.OPEN.value,
        "is_closed": False,
        "shares": 10.0,
        "entry_price": 0.5,
        "stake_usdc": 5.0,
    }
    with store._lock, store._conn:
        store._conn.execute(
            """INSERT INTO system_events(event_id,event_type,severity,created_at,payload_json)
            VALUES(?,?,?,?,?)""",
            (
                payload["event_id"],
                payload["event_type"],
                payload["severity"],
                utc_now().isoformat(),
                json.dumps(payload),
            ),
        )

    # When/Then: restore paths fail closed instead of returning an un-settleable row.
    assert store.restore_open_positions() == []
    assert store.restore_closed_positions() == []


def test_sqlite_store_excludes_closed_position_events_without_state_fields(tmp_path) -> None:
    # Given: a persisted closed position event with no side, money fields, or event timestamp.
    store = SQLiteStore(tmp_path / "restore.sqlite3")
    payload = {
        "event_id": "evt-closed-incomplete",
        "event_type": "nautilus_position",
        "severity": "info",
        "paper_position_id": "pos-closed-incomplete",
        "status": PositionStatus.CLOSED.value,
        "is_closed": True,
    }
    with store._lock, store._conn:
        store._conn.execute(
            """INSERT INTO system_events(event_id,event_type,severity,created_at,payload_json)
            VALUES(?,?,?,?,?)""",
            (
                payload["event_id"],
                payload["event_type"],
                payload["severity"],
                utc_now().isoformat(),
                json.dumps(payload),
            ),
        )

    # When/Then: restore paths fail closed instead of returning an un-settleable row.
    assert store.restore_open_positions() == []
    assert store.restore_closed_positions() == []


def test_sqlite_store_excludes_contradictory_position_state(tmp_path) -> None:
    # Given: a position event with valid money fields but contradictory lifecycle state.
    store = SQLiteStore(tmp_path / "restore.sqlite3")
    now = utc_now().isoformat()
    store.insert_system_event(
        {
            "event_id": "evt-position-contradictory-state",
            "event_type": "nautilus_position",
            "severity": "info",
            "created_at": now,
            "paper_position_id": "pos-contradictory-state",
            "status": PositionStatus.OPEN.value,
            "is_closed": True,
            "side": Side.UP.value,
            "shares": 10.0,
            "entry_price": 0.5,
            "stake_usdc": 5.0,
            "opened_at": now,
            "closed_at": now,
        }
    )

    # When/Then: restore paths reject the row instead of returning it as both open and closed.
    assert store.restore_open_positions() == []
    assert store.restore_closed_positions() == []


def test_sqlite_store_excludes_open_position_event_with_invalid_opened_at(tmp_path) -> None:
    # Given: an OPEN position whose primary opened_at is malformed but fallbacks are valid.
    store = SQLiteStore(tmp_path / "restore.sqlite3")
    event_time = "2026-06-26T00:00:00+00:00"
    store.insert_system_event(
        {
            "event_id": "evt-open-invalid-opened-at",
            "event_type": "nautilus_position",
            "severity": "info",
            "created_at": event_time,
            "paper_position_id": "pos-open-invalid-opened-at",
            "market_id": "market-1",
            "token_id": "token-up",
            "side": Side.UP.value,
            "status": PositionStatus.OPEN.value,
            "is_closed": False,
            "shares": 10.0,
            "entry_price": 0.5,
            "stake_usdc": 5.0,
            "opened_at": "not-a-date",
            "ts": event_time,
        }
    )

    # When/Then: restore fails closed instead of falling through to ts/created_at.
    assert store.restore_open_positions() == []
    assert store.restore_closed_positions() == []


def test_sqlite_store_excludes_open_position_event_without_side(tmp_path) -> None:
    # Given: an otherwise settleable open position event with no trustworthy side.
    store = SQLiteStore(tmp_path / "restore.sqlite3")
    event_time = utc_now().isoformat()
    store.insert_system_event(
        {
            "event_id": "evt-open-no-side",
            "event_type": "nautilus_position",
            "severity": "info",
            "created_at": event_time,
            "paper_position_id": "pos-open-no-side",
            "market_id": "market-1",
            "token_id": "token-up",
            "status": PositionStatus.OPEN.value,
            "is_closed": False,
            "shares": 10.0,
            "entry_price": 0.5,
            "stake_usdc": 5.0,
            "opened_at": event_time,
            "ts": event_time,
        }
    )

    # When/Then: restore fails closed instead of fabricating UP.
    assert store.restore_open_positions() == []
    assert store.restore_closed_positions() == []


def test_sqlite_store_newer_invalid_position_event_blocks_stale_restore(tmp_path) -> None:
    # Given: a valid open event followed by a newer malformed event for the same position.
    store = SQLiteStore(tmp_path / "restore.sqlite3")
    older = "2026-06-26T00:00:00+00:00"
    newer = "2026-06-26T00:01:00+00:00"
    base = {
        "event_type": "nautilus_position",
        "severity": "info",
        "paper_position_id": "pos-stale-blocked",
        "market_id": "market-1",
        "token_id": "token-up",
        "side": Side.UP.value,
        "status": PositionStatus.OPEN.value,
        "is_closed": False,
        "shares": 10.0,
        "entry_price": 0.5,
        "stake_usdc": 5.0,
        "opened_at": older,
    }
    store.insert_system_event({"event_id": "evt-valid-older", "created_at": older, "ts": older, **base})
    store.insert_system_event(
        {
            "event_id": "evt-invalid-newer",
            "created_at": newer,
            "ts": newer,
            **base,
            "side": "",
        }
    )

    # When/Then: the malformed latest state wins selection and is filtered out.
    assert store.restore_open_positions() == []
    assert store.restore_closed_positions() == []


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
