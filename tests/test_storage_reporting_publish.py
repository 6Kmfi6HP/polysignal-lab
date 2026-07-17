"""
Input: __future__, __future__.annotations, concurrent.futures, concurrent.futures.ThreadPoolExecutor, datetime, datetime.date, datetime.datetime, datetime.timedelta, datetime.timezone, pathlib
Output: test_formatter_signal_message_within_limit, test_telegram_dry_run_publish, test_formatter_nautilus_fill_message_is_compact, test_jsonl_and_state_store, test_jsonl_and_state_restore_reporting_streams, test_sqlite_store_and_dashboard, test_schema_rejects_missing_required_columns, test_daily_report_claim_and_delivery_lease_are_atomic_across_connections, test_daily_report_publish_authorization_rejects_expired_lease, test_daily_report_publish_authorization_renews_sending_lease
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""









from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from factories import sample_report_result
from polysignal_lab.dashboard.app import create_dashboard_app
from polysignal_lab.app.reporting_build import _publish_report
from polysignal_lab.domain.anchor_price import AnchorPrice
from polysignal_lab.domain.enums import ExitMode, Side, TradeResultStatus
from polysignal_lab.domain.reporting_result import DailyReport
from polysignal_lab.domain.strategy_readiness import StrategyMarketStatus
from polysignal_lab.reporting.daily_report import DailyReportService
from polysignal_lab.publish.telegram_publisher import TelegramPublisher
from polysignal_lab.signal_layer.formatter import MessageFormatter
from polysignal_lab.storage import sqlite_store as sqlite_store_module
from polysignal_lab.storage.jsonl_store import JSONLStore
from polysignal_lab.storage.sqlite_store import DuplicateRecordError, SQLiteStore
from polysignal_lab.storage.sqlite_schema import SchemaValidationError
from polysignal_lab.storage.state_store import StateStore
from signal_helpers import ptb_signal_from_view
from factories import sample_storage_lifecycle


async def test_formatter_signal_message_within_limit(market_view, settings):
    # Given: a PRD signal candidate.
    sig = ptb_signal_from_view(market_view, settings)

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
    assert "Mode: Sandbox" in message
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


def test_formatter_nautilus_fill_message_is_compact() -> None:
    fill = {
        "strategy": "ptb_diff",
        "asset": "BTC",
        "timeframe": "5m",
        "market_id": "btc-5m",
        "market_slug": "btc-updown-5m",
        "condition_id": "condition-btc-5m",
        "token_id": "up-token",
        "side": "UP",
        "fill_price": 0.5,
        "shares": 10.0,
        "stake_usdc": 5.0,
        "signal_id": "sig-fill-1",
        "order_id": "order-1",
        "client_order_id": "client-1",
        "report_fill_id": "trade-1",
    }

    message = MessageFormatter(max_chars=4096).nautilus_fill_message(fill)

    assert len(message) <= 4096
    assert "<b>" in message
    assert "FILL" in message
    assert "<code>ptb_diff</code>" in message
    assert "Fill   0.5000" in message
    assert "Shares 10.0000" in message
    assert "Stake  5.00 USDC" in message
    assert "Mode: Sandbox" in message
    assert "Order  <code>client-1</code>" in message
    assert "FillID <code>trade-1</code>" in message


def test_jsonl_and_state_store(tmp_path):
    logs = JSONLStore(tmp_path / "logs")
    state = StateStore(tmp_path / "state")
    logs.append("signals", {"signal_id": "s1"})
    assert logs.read_all("signals")[0]["signal_id"] == "s1"
    state.write("telegram_disabled_strategies", ["late_consensus"])
    assert state.read("telegram_disabled_strategies") == ["late_consensus"]


def test_jsonl_and_state_restore_reporting_streams(tmp_path):
    # Given: the PRD audit streams and state files persisted under a temp root.
    logs = JSONLStore(tmp_path / "logs")
    state = StateStore(tmp_path / "state")
    streams = [
        "signals",
        "rejected_signals",
        "report_orders",
        "report_fills",
        "report_positions",
        "report_results",
        "report_account_snapshots",
        "daily_reports",
        "telegram_publishes",
        "system_events",
    ]
    for stream in streams:
        logs.append(stream, {"stream": stream, "id": f"{stream}-1"})
    state.write("telegram_disabled_strategies", ["late_consensus"])

    # When: persisted JSONL/state is restored from disk.
    restored_streams = {stream: logs.read_all(stream)[0]["stream"] for stream in streams}
    disabled = state.read("telegram_disabled_strategies")
    (tmp_path / "logs" / "broken.jsonl").write_text("{broken\n", encoding="utf-8")

    # Then: every PRD stream is present and malformed JSON is not silently accepted.
    assert restored_streams == {stream: stream for stream in streams}
    assert disabled == ["late_consensus"]
    with pytest.raises(ValueError):
        logs.read_all("broken")


async def test_sqlite_store_and_dashboard(tmp_path, market_view, settings):
    store = SQLiteStore(tmp_path / "db.sqlite3")
    sig = ptb_signal_from_view(market_view, settings)
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


def _daily_report_for_publish(
    *,
    ending_equity: float = 1000.0,
) -> DailyReport:
    return DailyReportService().build_daily_report(
        report_date=date(2026, 7, 15),
        starting_equity=1000.0,
        ending_equity=ending_equity,
        total_signals=1,
        order_count=0,
        fill_count=0,
        rejected_order_count=0,
        open_positions=0,
        results=[],
    )


def _authorize_attempt(
    store: SQLiteStore,
    attempt: dict[str, object],
    *,
    lease_sec: float = 1,
) -> None:
    assert store.authorize_daily_report_publish(
        str(attempt["intent_id"]),
        int(attempt["attempt_count"]),
        lease_sec=lease_sec,
    ) == "AUTHORIZED"


def test_daily_report_claim_and_delivery_lease_are_atomic_across_connections(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "reports.sqlite3"
    base_report = DailyReportService().build_daily_report(
        report_date=date(2026, 7, 13),
        starting_equity=1000.0,
        ending_equity=1005.0,
        total_signals=1,
        order_count=1,
        fill_count=1,
        rejected_order_count=0,
        open_positions=0,
        results=[],
    )
    reports = (
        base_report.model_copy(update={"report_id": "dr-concurrent-a"}),
        base_report.model_copy(update={"report_id": "dr-concurrent-b"}),
    )
    stores = (SQLiteStore(db_path), SQLiteStore(db_path))
    barrier = Barrier(2)

    def claim(item: tuple[SQLiteStore, DailyReport]) -> tuple[str, bool]:
        store, report = item
        barrier.wait()
        persisted, created = store.claim_daily_report(
            report,
            enqueue_publish=True,
        )
        return persisted.report_id, created

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(claim, zip(stores, reports, strict=True)))
    finally:
        for connection in stores:
            connection.close()

    store = SQLiteStore(db_path)
    outbox = store.restore_report_publish_outbox()

    assert sum(created for _, created in results) == 1
    assert len({report_id for report_id, _ in results}) == 1
    assert store.counts()["daily_reports"] == 1
    assert store.counts()["report_publish_outbox"] == 1
    assert len(outbox) == 1
    assert outbox[0]["idempotency_key"] == "daily_report:2026-07-13:r1"
    assert outbox[0]["status"] == "PENDING"

    observed_at = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(sqlite_store_module, "utc_now", lambda: observed_at)
    first_attempt = store.claim_daily_report_publish(
        outbox[0]["report_id"],
        lease_sec=1,
    )
    monkeypatch.setattr(
        sqlite_store_module,
        "utc_now",
        lambda: observed_at + timedelta(seconds=2),
    )
    second_attempt = store.claim_daily_report_publish(
        outbox[0]["report_id"],
        lease_sec=1,
    )

    assert first_attempt is not None
    assert second_attempt is not None
    assert first_attempt["attempt_count"] == 1
    assert second_attempt["attempt_count"] == 2
    assert not store.complete_daily_report_publish(
        first_attempt["intent_id"],
        first_attempt["attempt_count"],
        {
            "publish_id": "pub-stale",
            "message_type": "daily_report",
            "status": "SENT",
            "sent_at": "2026-07-13T12:00:01Z",
        },
    )
    delivering = store.restore_report_publish_outbox()[0]
    assert delivering["status"] == "DELIVERING"
    assert delivering["attempt_count"] == 2
    _authorize_attempt(store, second_attempt)
    assert store.complete_daily_report_publish(
        second_attempt["intent_id"],
        second_attempt["attempt_count"],
        {
            "publish_id": "pub-current",
            "message_type": "daily_report",
            "status": "SENT",
            "sent_at": "2026-07-13T12:00:02Z",
        },
    )
    assert store.restore_report_publish_outbox()[0]["status"] == "SENT"


def test_daily_report_publish_authorization_rejects_expired_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_at = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(sqlite_store_module, "utc_now", lambda: observed_at)
    store = SQLiteStore(tmp_path / "reports.sqlite3")
    report = _daily_report_for_publish()
    persisted, _ = store.claim_daily_report(report, enqueue_publish=True)
    attempt = store.claim_daily_report_publish(
        persisted.report_id,
        lease_sec=1,
    )

    assert attempt is not None
    monkeypatch.setattr(
        sqlite_store_module,
        "utc_now",
        lambda: observed_at + timedelta(seconds=2),
    )
    assert store.authorize_daily_report_publish(
        str(attempt["intent_id"]),
        int(attempt["attempt_count"]),
        lease_sec=1,
    ) == "EXPIRED"
    assert store.restore_report_publish_outbox()[0]["status"] == "DELIVERING"


def test_daily_report_publish_authorization_renews_sending_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_at = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(sqlite_store_module, "utc_now", lambda: observed_at)
    store = SQLiteStore(tmp_path / "reports.sqlite3")
    report = _daily_report_for_publish()
    persisted, _ = store.claim_daily_report(report, enqueue_publish=True)
    attempt = store.claim_daily_report_publish(
        persisted.report_id,
        lease_sec=1,
    )

    assert attempt is not None
    monkeypatch.setattr(
        sqlite_store_module,
        "utc_now",
        lambda: observed_at + timedelta(milliseconds=500),
    )
    assert store.authorize_daily_report_publish(
        str(attempt["intent_id"]),
        int(attempt["attempt_count"]),
        lease_sec=30,
    ) == "AUTHORIZED"
    outbox = store.restore_report_publish_outbox()[0]
    assert outbox["lease_until"] == "2026-07-15T12:00:30.500000Z"


def test_daily_report_publish_late_authorized_attempt_is_audited_after_reclaim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_at = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(sqlite_store_module, "utc_now", lambda: observed_at)
    store = SQLiteStore(tmp_path / "reports.sqlite3")
    report = _daily_report_for_publish()
    persisted, _ = store.claim_daily_report(report, enqueue_publish=True)
    first_attempt = store.claim_daily_report_publish(
        persisted.report_id,
        lease_sec=1,
    )

    assert first_attempt is not None
    assert store.authorize_daily_report_publish(
        str(first_attempt["intent_id"]),
        int(first_attempt["attempt_count"]),
        lease_sec=1,
    ) == "AUTHORIZED"
    monkeypatch.setattr(
        sqlite_store_module,
        "utc_now",
        lambda: observed_at + timedelta(seconds=2),
    )
    second_attempt = store.claim_daily_report_publish(
        persisted.report_id,
        lease_sec=30,
    )

    assert second_attempt is not None
    assert second_attempt["attempt_count"] == 2
    late_publish = store.complete_daily_report_publish(
        str(first_attempt["intent_id"]),
        int(first_attempt["attempt_count"]),
        {
            "publish_id": str(first_attempt["idempotency_key"]),
            "message_type": "daily_report",
            "status": "SENT",
            "sent_at": "2026-07-15T12:00:02Z",
        },
    )

    assert late_publish is not None
    assert late_publish["status"] == "SENT"
    outbox = store.restore_report_publish_outbox()[0]
    assert outbox["status"] == "DELIVERING"
    assert outbox["attempt_count"] == 2
    assert store.query_json("telegram_publishes")[0]["status"] == "SENT"
    assert store.authorize_daily_report_publish(
        str(second_attempt["intent_id"]),
        int(second_attempt["attempt_count"]),
        lease_sec=30,
    ) == "STALE"
    settled_outbox = store.restore_report_publish_outbox()[0]
    assert settled_outbox["status"] == "SENT"
    assert settled_outbox["publish_id"] == str(second_attempt["idempotency_key"])
    assert store.complete_daily_report_publish(
        str(second_attempt["intent_id"]),
        int(second_attempt["attempt_count"]),
        {
            "publish_id": str(second_attempt["idempotency_key"]),
            "message_type": "daily_report",
            "status": "FAILED",
            "error": "not authorized",
            "sent_at": None,
        },
    ) is None


def test_daily_report_publish_reclaim_preserves_legacy_authorized_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_at = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(sqlite_store_module, "utc_now", lambda: observed_at)
    store = SQLiteStore(tmp_path / "reports.sqlite3")
    report = _daily_report_for_publish()
    persisted, _ = store.claim_daily_report(report, enqueue_publish=True)
    first_attempt = store.claim_daily_report_publish(
        persisted.report_id,
        lease_sec=1,
    )

    assert first_attempt is not None
    intent_id = str(first_attempt["intent_id"])
    assert store.authorize_daily_report_publish(
        intent_id,
        int(first_attempt["attempt_count"]),
        lease_sec=1,
    ) == "AUTHORIZED"
    row = store._conn.execute(
        "SELECT payload_json FROM report_publish_outbox WHERE intent_id=?",
        (intent_id,),
    ).fetchone()
    assert row is not None
    payload = sqlite_store_module._payload_json(row)
    assert isinstance(payload, dict)
    payload.pop("authorized_attempts")
    payload.pop("send_authorized")
    with store._conn:
        store._conn.execute(
            "UPDATE report_publish_outbox SET payload_json=? WHERE intent_id=?",
            (store._json(payload), intent_id),
        )
    monkeypatch.setattr(
        sqlite_store_module,
        "utc_now",
        lambda: observed_at + timedelta(seconds=2),
    )

    reclaimed = store.claim_daily_report_publish(
        persisted.report_id,
        lease_sec=30,
    )

    assert reclaimed is not None
    assert reclaimed["authorized_attempts"] == [1]
    late_publish = store.complete_daily_report_publish(
        intent_id,
        1,
        {
            "publish_id": str(first_attempt["idempotency_key"]),
            "message_type": "daily_report",
            "status": "SENT",
            "sent_at": "2026-07-15T12:00:02Z",
        },
    )
    assert late_publish is not None
    assert store.restore_report_publish_outbox()[0]["attempt_count"] == 2


def test_daily_report_publish_retry_updates_failed_publish_record(
    tmp_path: Path,
) -> None:
    store = SQLiteStore(tmp_path / "reports.sqlite3")
    report = _daily_report_for_publish()
    persisted, _ = store.claim_daily_report(report, enqueue_publish=True)
    first_attempt = store.claim_daily_report_publish(
        persisted.report_id,
        lease_sec=1,
    )

    assert first_attempt is not None
    publish_id = str(first_attempt["idempotency_key"])
    _authorize_attempt(store, first_attempt)
    assert store.complete_daily_report_publish(
        str(first_attempt["intent_id"]),
        int(first_attempt["attempt_count"]),
        {
            "publish_id": publish_id,
            "message_type": "daily_report",
            "status": "FAILED",
            "error": "429 Too Many Requests",
            "sent_at": None,
        },
    )

    second_attempt = store.claim_daily_report_publish(
        persisted.report_id,
        lease_sec=1,
    )

    assert second_attempt is not None
    _authorize_attempt(store, second_attempt)
    assert store.complete_daily_report_publish(
        str(second_attempt["intent_id"]),
        int(second_attempt["attempt_count"]),
        {
            "publish_id": publish_id,
            "message_type": "daily_report",
            "status": "SENT",
            "error": None,
            "sent_at": "2026-07-15T12:00:02Z",
            "telegram_message_id": "123",
        },
    )
    assert store.restore_report_publish_outbox()[0]["status"] == "SENT"
    publishes = store.query_json("telegram_publishes")
    assert len(publishes) == 1
    assert publishes[0]["status"] == "SENT"
    assert publishes[0]["telegram_message_id"] == "123"


def test_daily_report_publish_failure_does_not_downgrade_success(
    tmp_path: Path,
) -> None:
    store = SQLiteStore(tmp_path / "reports.sqlite3")
    report = _daily_report_for_publish()
    persisted, _ = store.claim_daily_report(report, enqueue_publish=True)
    attempt = store.claim_daily_report_publish(
        persisted.report_id,
        lease_sec=1,
    )

    assert attempt is not None
    publish_id = str(attempt["idempotency_key"])
    _authorize_attempt(store, attempt)
    store.insert_telegram_publish(
        {
            "publish_id": publish_id,
            "message_type": "daily_report",
            "signal_id": None,
            "status": "SENT",
            "sent_at": "2026-07-15T12:00:01Z",
        }
    )

    effective_publish = store.complete_daily_report_publish(
        str(attempt["intent_id"]),
        int(attempt["attempt_count"]),
        {
            "publish_id": publish_id,
            "message_type": "daily_report",
            "signal_id": None,
            "status": "FAILED",
            "error": "timeout after Telegram accepted the request",
            "sent_at": None,
        },
    )
    assert effective_publish is not None
    assert effective_publish["status"] == "SENT"
    assert effective_publish["sent_at"] == "2026-07-15T12:00:01Z"
    assert store.restore_report_publish_outbox()[0]["status"] == "SENT"
    assert store.claim_daily_report_publish(
        persisted.report_id,
        lease_sec=1,
    ) is None
    publishes = store.query_json("telegram_publishes")
    assert len(publishes) == 1
    assert publishes[0]["status"] == "SENT"


def test_new_daily_report_revision_supersedes_delivering_publish(
    tmp_path: Path,
) -> None:
    store = SQLiteStore(tmp_path / "reports.sqlite3")
    report = _daily_report_for_publish()
    persisted, _ = store.claim_daily_report(report, enqueue_publish=True)
    attempt = store.claim_daily_report_publish(
        persisted.report_id,
        lease_sec=60,
    )

    assert attempt is not None
    revised, created = store.claim_daily_report(
        report.model_copy(
            update={
                "report_id": "dr-revised",
                "ending_equity": 1001.0,
            }
        ),
        enqueue_publish=True,
    )

    assert created
    assert revised.revision == 2
    outbox = {
        int(row["revision"]): row
        for row in store.restore_report_publish_outbox()
    }
    assert outbox[1]["status"] == "SUPERSEDED"
    assert outbox[1]["lease_until"] is None
    assert outbox[1]["last_error"] == "superseded_by_revision:2"
    assert outbox[2]["status"] == "PENDING"


def test_new_daily_report_revision_does_not_revoke_authorized_publish(
    tmp_path: Path,
) -> None:
    store = SQLiteStore(tmp_path / "reports.sqlite3")
    report = _daily_report_for_publish()
    persisted, _ = store.claim_daily_report(report, enqueue_publish=True)
    attempt = store.claim_daily_report_publish(
        persisted.report_id,
        lease_sec=60,
    )

    assert attempt is not None
    _authorize_attempt(store, attempt)
    revised, created = store.claim_daily_report(
        report.model_copy(
            update={
                "report_id": "dr-revised-after-authorization",
                "ending_equity": 1001.0,
            }
        ),
        enqueue_publish=True,
    )

    assert created
    assert revised.revision == 2
    outbox = {
        int(row["revision"]): row
        for row in store.restore_report_publish_outbox()
    }
    assert outbox[1]["status"] == "SENDING"
    assert outbox[2]["status"] == "PENDING"
    assert store.complete_daily_report_publish(
        str(attempt["intent_id"]),
        int(attempt["attempt_count"]),
        {
            "publish_id": str(attempt["idempotency_key"]),
            "message_type": "daily_report",
            "status": "SENT",
            "sent_at": "2026-07-15T12:00:02Z",
        },
    ) is not None


def test_new_daily_report_revision_failed_publish_becomes_superseded(
    tmp_path: Path,
) -> None:
    store = SQLiteStore(tmp_path / "reports.sqlite3")
    report = _daily_report_for_publish()
    first, _ = store.claim_daily_report(report, enqueue_publish=True)
    attempt = store.claim_daily_report_publish(
        first.report_id,
        lease_sec=60,
    )

    assert attempt is not None
    _authorize_attempt(store, attempt)
    revised, _ = store.claim_daily_report(
        report.model_copy(
            update={
                "report_id": "dr-revised-before-failure",
                "ending_equity": 1001.0,
            }
        ),
        enqueue_publish=True,
    )
    effective = store.complete_daily_report_publish(
        str(attempt["intent_id"]),
        int(attempt["attempt_count"]),
        {
            "publish_id": str(attempt["idempotency_key"]),
            "message_type": "daily_report",
            "status": "FAILED",
            "error": "429 Too Many Requests",
            "sent_at": None,
        },
    )

    assert revised.revision == 2
    assert effective is not None
    outbox = {
        int(row["revision"]): row
        for row in store.restore_report_publish_outbox()
    }
    assert outbox[1]["status"] == "SUPERSEDED"
    assert outbox[1]["last_error"] == "superseded_by_revision:2"
    assert outbox[2]["status"] == "PENDING"


def test_new_daily_report_revision_waits_for_authorized_publish(
    tmp_path: Path,
) -> None:
    store = SQLiteStore(tmp_path / "reports.sqlite3")
    report = _daily_report_for_publish()
    first, _ = store.claim_daily_report(report, enqueue_publish=True)
    first_attempt = store.claim_daily_report_publish(
        first.report_id,
        lease_sec=60,
    )

    assert first_attempt is not None
    _authorize_attempt(store, first_attempt)
    revised, _ = store.claim_daily_report(
        report.model_copy(
            update={
                "report_id": "dr-revised-waits",
                "ending_equity": 1001.0,
            }
        ),
        enqueue_publish=True,
    )
    second_attempt = store.claim_daily_report_publish(
        revised.report_id,
        lease_sec=60,
    )

    assert second_attempt is not None
    assert store.authorize_daily_report_publish(
        str(second_attempt["intent_id"]),
        int(second_attempt["attempt_count"]),
        lease_sec=60,
    ) == "BUSY"
    assert store.complete_daily_report_publish(
        str(first_attempt["intent_id"]),
        int(first_attempt["attempt_count"]),
        {
            "publish_id": str(first_attempt["idempotency_key"]),
            "message_type": "daily_report",
            "status": "SENT",
            "sent_at": "2026-07-15T12:00:02Z",
        },
    ) is not None
    assert store.authorize_daily_report_publish(
        str(second_attempt["intent_id"]),
        int(second_attempt["attempt_count"]),
        lease_sec=60,
    ) == "AUTHORIZED"


def test_new_daily_report_revision_reclaims_expired_waiting_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_at = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(sqlite_store_module, "utc_now", lambda: observed_at)
    store = SQLiteStore(tmp_path / "reports.sqlite3")
    report = _daily_report_for_publish()
    first, _ = store.claim_daily_report(report, enqueue_publish=True)
    first_attempt = store.claim_daily_report_publish(
        first.report_id,
        lease_sec=1,
    )

    assert first_attempt is not None
    _authorize_attempt(store, first_attempt)
    revised, _ = store.claim_daily_report(
        report.model_copy(
            update={
                "report_id": "dr-revised-reclaims",
                "ending_equity": 1001.0,
            }
        ),
        enqueue_publish=True,
    )
    second_attempt = store.claim_daily_report_publish(
        revised.report_id,
        lease_sec=1,
    )

    assert second_attempt is not None
    assert store.authorize_daily_report_publish(
        str(second_attempt["intent_id"]),
        int(second_attempt["attempt_count"]),
        lease_sec=60,
    ) == "BUSY"
    monkeypatch.setattr(
        sqlite_store_module,
        "utc_now",
        lambda: observed_at + timedelta(seconds=2),
    )
    assert store.authorize_daily_report_publish(
        str(second_attempt["intent_id"]),
        int(second_attempt["attempt_count"]),
        lease_sec=1,
    ) == "EXPIRED"
    reclaimed = store.claim_daily_report_publish(
        revised.report_id,
        lease_sec=1,
    )

    assert reclaimed is not None
    assert reclaimed["attempt_count"] == 2
    assert store.authorize_daily_report_publish(
        str(reclaimed["intent_id"]),
        int(reclaimed["attempt_count"]),
        lease_sec=1,
    ) == "AUTHORIZED"


def test_new_daily_report_revision_fences_expired_sending_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_at = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(sqlite_store_module, "utc_now", lambda: observed_at)
    store = SQLiteStore(tmp_path / "reports.sqlite3")
    report = _daily_report_for_publish()
    first, _ = store.claim_daily_report(report, enqueue_publish=True)
    first_attempt = store.claim_daily_report_publish(
        first.report_id,
        lease_sec=1,
    )

    assert first_attempt is not None
    _authorize_attempt(store, first_attempt)
    revised, _ = store.claim_daily_report(
        report.model_copy(
            update={
                "report_id": "dr-revised-fences",
                "ending_equity": 1001.0,
            }
        ),
        enqueue_publish=True,
    )
    second_attempt = store.claim_daily_report_publish(
        revised.report_id,
        lease_sec=1,
    )

    assert second_attempt is not None
    monkeypatch.setattr(
        sqlite_store_module,
        "utc_now",
        lambda: observed_at + timedelta(seconds=2),
    )
    reclaimed = store.claim_daily_report_publish(
        revised.report_id,
        lease_sec=1,
    )

    assert reclaimed is not None
    assert store.authorize_daily_report_publish(
        str(reclaimed["intent_id"]),
        int(reclaimed["attempt_count"]),
        lease_sec=1,
    ) == "AUTHORIZED"
    effective = store.complete_daily_report_publish(
        str(first_attempt["intent_id"]),
        int(first_attempt["attempt_count"]),
        {
            "publish_id": str(first_attempt["idempotency_key"]),
            "message_type": "daily_report",
            "status": "SENT",
            "sent_at": "2026-07-15T12:00:03Z",
        },
    )
    assert effective is not None
    assert effective["status"] == "SENT"
    outbox = {
        int(row["revision"]): row
        for row in store.restore_report_publish_outbox()
    }
    assert outbox[1]["status"] == "SUPERSEDED"
    assert outbox[1]["last_error"] == "superseded_by_revision:2"
    publishes = store.query_json("telegram_publishes")
    assert publishes[0]["status"] == "SENT"


def test_new_daily_report_revision_without_publish_supersedes_delivering_publish(
    tmp_path: Path,
) -> None:
    store = SQLiteStore(tmp_path / "reports.sqlite3")
    report = _daily_report_for_publish()
    persisted, _ = store.claim_daily_report(report, enqueue_publish=True)
    attempt = store.claim_daily_report_publish(
        persisted.report_id,
        lease_sec=60,
    )

    assert attempt is not None
    revised, created = store.claim_daily_report(
        report.model_copy(
            update={
                "report_id": "dr-revised-without-publish",
                "ending_equity": 1001.0,
            }
        ),
        enqueue_publish=False,
    )

    assert created
    assert revised.revision == 2
    assert not store.complete_daily_report_publish(
        str(attempt["intent_id"]),
        int(attempt["attempt_count"]),
        {
            "publish_id": str(attempt["idempotency_key"]),
            "message_type": "daily_report",
            "status": "SENT",
            "sent_at": "2026-07-15T12:00:02Z",
        },
    )
    outbox = store.restore_report_publish_outbox()
    assert len(outbox) == 1
    assert outbox[0]["status"] == "SUPERSEDED"
    assert outbox[0]["last_error"] == "superseded_by_revision:2"


def test_pending_daily_report_publishes_supersedes_stale_nonterminal_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_at = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(sqlite_store_module, "utc_now", lambda: observed_at)
    store = SQLiteStore(tmp_path / "reports.sqlite3")
    report = _daily_report_for_publish()
    first, _ = store.claim_daily_report(report, enqueue_publish=True)
    attempt = store.claim_daily_report_publish(
        first.report_id,
        lease_sec=1,
    )

    assert attempt is not None
    _authorize_attempt(store, attempt)
    revised, _ = store.claim_daily_report(
        report.model_copy(
            update={
                "report_id": "dr-revised-no-outbox-cleans-stale",
                "ending_equity": 1001.0,
            }
        ),
        enqueue_publish=False,
    )
    monkeypatch.setattr(
        sqlite_store_module,
        "utc_iso",
        lambda _dt=None: "2026-07-15T12:00:02Z",
    )

    assert revised.revision == 2
    assert store.pending_daily_report_publishes(
        before_date="2026-07-16",
    ) == []
    outbox = store.restore_report_publish_outbox()
    assert outbox[0]["status"] == "SUPERSEDED"
    assert outbox[0]["last_error"] == "superseded_by_revision:2"


def test_pending_daily_report_publishes_excludes_stale_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_at = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(sqlite_store_module, "utc_now", lambda: observed_at)
    store = SQLiteStore(tmp_path / "reports.sqlite3")
    report = _daily_report_for_publish()
    persisted, _ = store.claim_daily_report(report, enqueue_publish=True)
    attempt = store.claim_daily_report_publish(
        persisted.report_id,
        lease_sec=1,
    )

    assert attempt is not None
    revised, created = store.claim_daily_report(
        report.model_copy(
            update={
                "report_id": "dr-revised-without-outbox",
                "ending_equity": 1001.0,
            }
        ),
        enqueue_publish=False,
    )
    monkeypatch.setattr(
        sqlite_store_module,
        "utc_iso",
        lambda _dt=None: "2026-07-15T12:00:02Z",
    )

    assert created
    assert revised.revision == 2
    assert store.pending_daily_report_publishes(
        before_date="2026-07-16",
    ) == []


async def test_publish_report_skips_intent_superseded_before_delivery(
    tmp_path: Path,
) -> None:
    store = SQLiteStore(tmp_path / "reports.sqlite3")
    report = _daily_report_for_publish()
    persisted, _ = store.claim_daily_report(report, enqueue_publish=True)
    delivered: list[str] = []

    class Persistence:
        def claim_daily_report_publish(
            self,
            report_id: str,
            *,
            lease_sec: float,
        ) -> dict[str, object] | None:
            intent = store.claim_daily_report_publish(
                report_id,
                lease_sec=lease_sec,
            )
            store.claim_daily_report(
                report.model_copy(
                    update={
                        "report_id": "dr-superseding",
                        "ending_equity": 1001.0,
                    }
                ),
                enqueue_publish=False,
            )
            return intent

        def authorize_daily_report_publish(
            self,
            intent_id: str,
            attempt_count: int,
            *,
            lease_sec: float,
        ) -> str:
            return store.authorize_daily_report_publish(
                intent_id,
                attempt_count,
                lease_sec=lease_sec,
            )

    class Publisher:
        async def deliver_daily_report(
            self,
            _report: DailyReport,
            *,
            idempotency_key: str | None = None,
        ) -> None:
            delivered.append(str(idempotency_key))

    scheduler = SimpleNamespace(
        settings=SimpleNamespace(
            telegram=SimpleNamespace(publish_timeout_sec=20.0)
        ),
        persistence=Persistence(),
        publish_service=Publisher(),
        logger=SimpleNamespace(
            error=lambda *_args: None,
            info=lambda *_args: None,
        ),
    )

    assert await _publish_report(scheduler, persisted)
    assert delivered == []


async def test_publish_report_rejects_unknown_authorization() -> None:
    errors: list[str] = []
    delivered: list[str] = []

    class Persistence:
        def claim_daily_report_publish(
            self,
            _report_id: str,
            *,
            lease_sec: float,
        ) -> dict[str, object]:
            assert lease_sec == 40.0
            return {
                "intent_id": "outbox-unknown",
                "attempt_count": 1,
                "idempotency_key": "daily_report:2026-07-15:r1",
            }

        def authorize_daily_report_publish(
            self,
            _intent_id: str,
            _attempt_count: int,
            *,
            lease_sec: float,
        ) -> str:
            assert lease_sec == 40.0
            return "UNKNOWN"

    class Publisher:
        async def deliver_daily_report(
            self,
            _report: DailyReport,
            *,
            idempotency_key: str | None = None,
        ) -> None:
            delivered.append(str(idempotency_key))

    class Health:
        def inc_metric(self, *_args: str) -> None:
            return None

        def mark_down(self, *_args: str, **_kwargs: object) -> None:
            return None

    scheduler = SimpleNamespace(
        settings=SimpleNamespace(
            telegram=SimpleNamespace(publish_timeout_sec=20.0)
        ),
        persistence=Persistence(),
        publish_service=Publisher(),
        health=Health(),
        logger=SimpleNamespace(
            error=lambda message, *args: errors.append(message % args),
            info=lambda *_args: None,
        ),
    )

    assert not await _publish_report(scheduler, _daily_report_for_publish())
    assert delivered == []
    assert errors == [
        "Failed to authorize daily report publish: "
        "Unknown daily report publish authorization: UNKNOWN"
    ]


async def test_publish_report_exception_preserves_sending_lease(
    tmp_path: Path,
) -> None:
    store = SQLiteStore(tmp_path / "reports.sqlite3")
    report = _daily_report_for_publish()
    persisted, _ = store.claim_daily_report(report, enqueue_publish=True)

    class Persistence:
        def claim_daily_report_publish(
            self,
            report_id: str,
            *,
            lease_sec: float,
        ) -> dict[str, object] | None:
            return store.claim_daily_report_publish(
                report_id,
                lease_sec=lease_sec,
            )

        def authorize_daily_report_publish(
            self,
            intent_id: str,
            attempt_count: int,
            *,
            lease_sec: float,
        ) -> str:
            return store.authorize_daily_report_publish(
                intent_id,
                attempt_count,
                lease_sec=lease_sec,
            )

    class Publisher:
        async def deliver_daily_report(
            self,
            _report: DailyReport,
            *,
            idempotency_key: str | None = None,
        ) -> None:
            raise TimeoutError(str(idempotency_key))

    scheduler = SimpleNamespace(
        settings=SimpleNamespace(
            telegram=SimpleNamespace(publish_timeout_sec=20.0)
        ),
        persistence=Persistence(),
        publish_service=Publisher(),
        logger=SimpleNamespace(
            error=lambda *_args: None,
            info=lambda *_args: None,
        ),
    )

    assert not await _publish_report(scheduler, persisted)
    outbox = store.restore_report_publish_outbox()
    assert outbox[0]["status"] == "SENDING"
    assert outbox[0]["lease_until"] is not None


async def test_publish_report_skips_existing_success_result(
    tmp_path: Path,
) -> None:
    store = SQLiteStore(tmp_path / "reports.sqlite3")
    report = _daily_report_for_publish()
    persisted, _ = store.claim_daily_report(report, enqueue_publish=True)
    publish_id = "daily_report:2026-07-15:r1"
    store.insert_telegram_publish(
        {
            "publish_id": publish_id,
            "message_type": "daily_report",
            "signal_id": None,
            "status": "SENT",
            "sent_at": "2026-07-15T12:00:01Z",
        }
    )
    delivered: list[str] = []
    logged: list[dict[str, object]] = []
    health_metrics: list[tuple[str, str]] = []

    class Persistence:
        def claim_daily_report_publish(
            self,
            report_id: str,
            *,
            lease_sec: float,
        ) -> dict[str, object] | None:
            return store.claim_daily_report_publish(
                report_id,
                lease_sec=lease_sec,
            )

        def authorize_daily_report_publish(
            self,
            intent_id: str,
            attempt_count: int,
            *,
            lease_sec: float,
        ) -> str:
            return store.authorize_daily_report_publish(
                intent_id,
                attempt_count,
                lease_sec=lease_sec,
            )

        def complete_daily_report_publish(
            self,
            intent_id: str,
            attempt_count: int,
            publish: dict[str, object],
        ) -> dict[str, object] | None:
            return store.complete_daily_report_publish(
                intent_id,
                attempt_count,
                publish,
            )

        def append_log(
            self,
            _stream: str,
            payload: dict[str, object],
        ) -> None:
            logged.append(payload)

    class PublishResult:
        def as_dict(self) -> dict[str, object]:
            return {
                "publish_id": publish_id,
                "message_type": "daily_report",
                "signal_id": None,
                "status": "FAILED",
                "error": "timeout after Telegram accepted the request",
                "sent_at": None,
            }

    class Publisher:
        async def deliver_daily_report(
            self,
            _report: DailyReport,
            *,
            idempotency_key: str | None = None,
        ) -> PublishResult:
            delivered.append(str(idempotency_key))
            return PublishResult()

    class Health:
        def mark_ok(self, name: str, **_metrics: object) -> None:
            health_metrics.append((name, "ok"))

        def inc_metric(self, name: str, metric: str) -> None:
            health_metrics.append((name, metric))

    scheduler = SimpleNamespace(
        settings=SimpleNamespace(
            telegram=SimpleNamespace(publish_timeout_sec=20.0)
        ),
        persistence=Persistence(),
        publish_service=Publisher(),
        health=Health(),
        logger=SimpleNamespace(
            error=lambda *_args: None,
            info=lambda *_args: None,
        ),
    )

    assert await _publish_report(scheduler, persisted)
    assert delivered == []
    assert logged == []
    assert health_metrics == []
    outbox = store.restore_report_publish_outbox()[0]
    assert outbox["status"] == "SENT"
    assert outbox["publish_id"] == publish_id


def test_sqlite_anchor_prices_survive_reopen(tmp_path) -> None:
    db_path = tmp_path / "anchors.sqlite3"
    captured_at = datetime(2026, 6, 23, 12, 0, 1, tzinfo=timezone.utc)
    anchor = AnchorPrice(
        asset="BTC",
        timeframe="5m",
        market_slug="btc-updown-5m-1782216000",
        window_start=datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc),
        window_end=datetime(2026, 6, 23, 12, 5, tzinfo=timezone.utc),
        price=64250.25,
        source="binance",
        verified=True,
        captured_at=captured_at,
        lag_ms=750,
    )
    store = SQLiteStore(db_path)
    store.upsert_anchor_price(anchor)
    store.close()

    reopened = SQLiteStore(db_path)
    loaded = reopened.get_verified_anchor_price("btc", "5m", "btc-updown-5m-1782216000")
    assert loaded == anchor


def test_sqlite_verified_anchor_survives_later_unverified_upsert(tmp_path) -> None:
    db_path = tmp_path / "anchors.sqlite3"
    verified_anchor = AnchorPrice(
        asset="BTC",
        timeframe="5m",
        market_slug="btc-updown-5m-1782216000",
        window_start=datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc),
        window_end=datetime(2026, 6, 23, 12, 5, tzinfo=timezone.utc),
        price=64250.25,
        source="binance",
        verified=True,
        captured_at=datetime(2026, 6, 23, 12, 0, 1, tzinfo=timezone.utc),
        lag_ms=750,
    )
    stale_anchor = AnchorPrice(
        asset="BTC",
        timeframe="5m",
        market_slug="btc-updown-5m-1782216000",
        window_start=verified_anchor.window_start,
        window_end=verified_anchor.window_end,
        price=None,
        source="binance",
        verified=False,
        captured_at=datetime(2026, 6, 23, 12, 4, tzinfo=timezone.utc),
        lag_ms=240_000,
    )
    store = SQLiteStore(db_path)

    store.upsert_anchor_price(verified_anchor)
    store.upsert_anchor_price(stale_anchor)

    loaded = store.get_verified_anchor_price("btc", "5m", "btc-updown-5m-1782216000")
    assert loaded == verified_anchor


def test_sqlite_store_persists_strategy_status_rows(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "db.sqlite3")
    status = StrategyMarketStatus(
        strategy="ptb_diff",
        asset="ETH",
        timeframe="5m",
        status="unsupported_market",
        reason="UNSUPPORTED_ASSET",
    )

    store.insert_strategy_status(status)

    rows = store.query_json("strategy_status", limit=10)
    assert rows == [
        {
            "strategy": "ptb_diff",
            "asset": "ETH",
            "timeframe": "5m",
            "status": "unsupported_market",
            "reason": "UNSUPPORTED_ASSET",
        }
    ]


def test_duplicate_ids_are_idempotent_or_reported(tmp_path, market_view, settings):
    # Given: a SQLite store with one full PRD audit lifecycle persisted.
    store = SQLiteStore(tmp_path / "db.sqlite3")
    sig = ptb_signal_from_view(market_view, settings)
    lifecycle = sample_storage_lifecycle(sig)

    # When: the same payloads are inserted twice and one conflicting duplicate is inserted.
    store.insert_signal(sig)
    store.insert_signal(sig)
    store.insert_rejected_signal(lifecycle.rejected)
    store.insert_rejected_signal(lifecycle.rejected)
    store.insert_system_event({
        "event_id": "evt-order-dup",
        "event_type": "nautilus_order",
        "severity": "info",
        "created_at": str(lifecycle.order["created_at"]),
        **lifecycle.order,
    })
    store.insert_system_event({
        "event_id": "evt-fill-dup",
        "event_type": "nautilus_fill",
        "severity": "info",
        "created_at": str(lifecycle.fill["created_at"]),
        **lifecycle.fill,
    })
    store.insert_system_event({
        "event_id": "evt-pos-dup",
        "event_type": "nautilus_position",
        "severity": "info",
        "created_at": str(lifecycle.position["opened_at"]),
        **lifecycle.position,
        "ts": lifecycle.position["opened_at"],
    })
    store.insert_report_result(lifecycle.result)
    store.insert_report_result(lifecycle.result)
    store.insert_report_account_snapshot(lifecycle.account_snapshot)
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
    assert store.counts()["report_results"] == 1
    assert store.counts()["daily_reports"] == 1
    assert store.counts()["telegram_publishes"] == 1
    assert store.counts()["system_events"] == 4
    assert store.query_json("report_account_snapshots")[0]["cash_balance"] == 990.0
    with pytest.raises(DuplicateRecordError, match=sig.signal_id):
        store.insert_signal(conflicting_signal)


def test_report_calculates_daily_metrics(settings):
    report = DailyReportService().build_daily_report(
        report_date=date(2026, 6, 21),
        starting_equity=1000,
        ending_equity=1010,
        total_signals=2,
        order_count=2,
        fill_count=2,
        rejected_order_count=0,
        open_positions=0,
        results=[],
    )
    assert report.net_pnl == 10
    assert report.total_signals == 2
    assert report.win_rate == 0


def test_formatter_result_and_daily_messages_are_paper_only() -> None:
    # Given: paper result and daily report domain records.
    result = sample_report_result(
        signal_id="sig1",
        report_position_id="pos1",
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="market1",
        market_slug="btc-updown-5m",
        side=Side.UP.value,
        entry_price=0.62,
        shares=16.129,
        stake_usdc=10.0,
        exit_mode=ExitMode.RESOLUTION.value,
        outcome_value=1.0,
        settlement_value=16.129,
        pnl_usdc=6.129,
        roi=0.6129,
        result=TradeResultStatus.WIN.value,
        opened_at=date(2026, 6, 21).isoformat(),
    )
    report = DailyReport(
        report_date=date(2026, 6, 21),
        starting_equity=1000.0,
        ending_equity=1006.13,
        net_pnl=6.13,
        return_rate=0.00613,
        total_signals=1,
        order_count=1,
        fill_count=1,
        rejected_order_count=0,
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
        rejects_by_reason={"ENTRY_PRICE_MOVED": 1},
        average_execution_staleness_ms=25.0,
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
    assert "Mode: Sandbox" in result_message
    assert "ID: <code>" in result_message
    for removed in (
        "Note:",
        "Paper result only",
        "No real order was placed",
        "No profit guarantee",
    ):
        assert removed not in result_message

    # Then: daily messages use the compact report layout and no stale disclaimers.
    assert daily_message.startswith("<b>📊 Daily Trading Report</b>")
    assert "Equity  " in daily_message
    assert " → " in daily_message
    assert "PnL     " in daily_message
    assert "ROI     " in daily_message
    assert "Signals " in daily_message
    assert "Orders  " in daily_message
    assert "Rejects " in daily_message
    assert "ExecLag " in daily_message
    assert "Telemetry COMPLETE" in daily_message
    assert "ENTRY_PRICE_MOVED" in daily_message
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


async def test_formatter_truncates_long_signal_message(market_view, settings) -> None:
    # Given: a signal whose reasons would exceed a short Telegram message limit.
    sig = ptb_signal_from_view(market_view, settings).model_copy(
        update={"reason_codes": [f"reason-{index}" for index in range(30)]}
    )

    # When: the signal message is formatted with a small max length.
    message = MessageFormatter(max_chars=240).signal_message(sig, 10.0)

    # Then: the message is bounded and visibly marked as truncated.
    assert len(message) <= 240
    assert message.startswith("<b>🟢 ")
    assert message.endswith("[truncated for Telegram]")
