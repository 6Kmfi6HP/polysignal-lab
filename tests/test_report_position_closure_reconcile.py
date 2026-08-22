"""TDD: ``report_results`` insertion must close the matching report position.

A report-only position (no cache/Nautilus ``Position`` behind it) only ever
reaches the terminal ``CLOSED`` projection via an incoming ``nautilus_position``
close event. When the position is *report-only* that event never arrives, so
even after a settlement a ``report_result`` row exists while
``report_positions.status`` stays ``OPEN`` forever.

The invariant "a ``report_results`` row implies its position is CLOSED" is
enforced at the single storage entry point: ``insert_report_result`` closes
the matching open position inline, and ``reconcile_report_position_closure``
(recalled at store init) drains positions stuck OPEN from prior sessions.
"""
from __future__ import annotations

from factories import sample_report_result

from polysignal_lab.domain.enums import PositionStatus, Side
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.utils import utc_now

OPEN = PositionStatus.OPEN.value
CLOSED = PositionStatus.CLOSED.value


def _open_position_event(
    *,
    report_position_id: str,
    signal_id: str,
    event_id: str,
    at: str,
) -> dict[str, object]:
    """Minimal ``nautilus_position`` OPEN event that survives ``_valid_position_event``."""
    return {
        "event_id": event_id,
        "event_type": "nautilus_position",
        "severity": "info",
        "created_at": at,
        "ts": at,
        "report_position_id": report_position_id,
        "position_id": report_position_id,
        "signal_id": signal_id,
        "report_order_id": f"po-{report_position_id}",
        "report_fill_id": f"pf-{report_position_id}",
        "strategy": "ptb_diff",
        "asset": "BTC",
        "timeframe": "5m",
        "market_id": f"market-{report_position_id}",
        "market_slug": "btc-updown-5m",
        "token_id": "token-up",
        "side": Side.UP.value,
        "entry_price": 0.72,
        "shares": 13.88,
        "stake_usdc": 10.0,
        "opened_at": at,
        "status": OPEN,
        "is_closed": False,
    }


def _position_ids(rows: list[dict[str, object]]) -> list[str]:
    return [str(row["report_position_id"]) for row in rows]


def _closed_by_id(store: SQLiteStore) -> dict[str, dict[str, object]]:
    return {
        str(row["report_position_id"]): row
        for row in store.query_report_closed_positions()
    }


def test_report_result_closes_matching_report_position(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "cycle1.sqlite3")
    at = utc_now().isoformat()
    store.insert_system_event(
        _open_position_event(
            report_position_id="pp-1",
            signal_id="sig-1",
            event_id="evt-pp-1",
            at=at,
        ),
    )
    assert "pp-1" in _position_ids(store.query_report_open_positions())

    created = store.insert_report_result(
        sample_report_result(
            report_result_id="pt-1",
            signal_id="sig-1",
            report_position_id="pp-1",
            opened_at=at,
            closed_at=at,
        ),
    )
    assert created is True

    assert "pp-1" not in _position_ids(store.query_report_open_positions())
    closed = _closed_by_id(store)
    assert "pp-1" in closed
    assert closed["pp-1"]["is_closed"] is True
    store.close()


def test_reconcile_drains_open_positions_with_existing_result(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "cycle2.sqlite3")
    at = utc_now().isoformat()
    # Result inserted before the position exists: inline close finds no row.
    created = store.insert_report_result(
        sample_report_result(
            report_result_id="pt-2",
            signal_id="sig-2",
            report_position_id="pp-2",
            opened_at=at,
            closed_at=at,
        ),
    )
    assert created is True
    # The OPEN position now appears -- already settled but stuck OPEN.
    store.insert_system_event(
        _open_position_event(
            report_position_id="pp-2",
            signal_id="sig-2",
            event_id="evt-pp-2",
            at=at,
        ),
    )
    assert "pp-2" in _position_ids(store.query_report_open_positions())

    closed_count = store.reconcile_report_position_closure()
    assert closed_count == 1

    assert "pp-2" not in _position_ids(store.query_report_open_positions())
    closed = _closed_by_id(store)
    assert "pp-2" in closed
    assert closed["pp-2"]["is_closed"] is True
    store.close()


def test_store_init_reconciles_prior_session_stuck(tmp_path) -> None:
    path = tmp_path / "cycle3.sqlite3"
    at = utc_now().isoformat()
    store = SQLiteStore(path)
    # Seed a stuck position: result first, then OPEN position (inline misses).
    store.insert_report_result(
        sample_report_result(
            report_result_id="pt-3",
            signal_id="sig-3",
            report_position_id="pp-3",
            opened_at=at,
            closed_at=at,
        ),
    )
    store.insert_system_event(
        _open_position_event(
            report_position_id="pp-3",
            signal_id="sig-3",
            event_id="evt-pp-3",
            at=at,
        ),
    )
    assert "pp-3" in _position_ids(store.query_report_open_positions())
    store.close()

    # Reopen the same database: __init__ auto-reconciles the stuck row.
    rebuilt = SQLiteStore(path)
    assert "pp-3" not in _position_ids(rebuilt.query_report_open_positions())
    closed = _closed_by_id(rebuilt)
    assert "pp-3" in closed
    assert closed["pp-3"]["is_closed"] is True
    rebuilt.close()


def test_reconcile_leaves_active_open_positions(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "guard.sqlite3")
    at = utc_now().isoformat()
    store.insert_system_event(
        _open_position_event(
            report_position_id="pp-active",
            signal_id="sig-active",
            event_id="evt-pp-active",
            at=at,
        ),
    )
    assert "pp-active" in _position_ids(store.query_report_open_positions())

    closed_count = store.reconcile_report_position_closure()
    assert closed_count == 0
    assert "pp-active" in _position_ids(store.query_report_open_positions())
    store.close()
