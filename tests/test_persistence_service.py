from typing import cast

from polysignal_lab.app.services.persistence_service import PersistenceService
from polysignal_lab.storage.jsonl_store import JSONLStore
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.storage.state_store import StateStore


class _CleanupStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []

    def delete_report_result_rows(
        self,
        report_result_id: str,
        publish_id: str | None,
    ) -> None:
        self.calls.append(("paper", report_result_id, publish_id))

    def delete_daily_report_rows(
        self,
        report_id: str,
        publish_id: str | None,
    ) -> None:
        self.calls.append(("daily", report_id, publish_id))


def test_persistence_service_uses_public_cleanup_transactions() -> None:
    store = _CleanupStore()
    service = PersistenceService(
        logs=cast(JSONLStore, object()),
        sqlite=cast(SQLiteStore, store),
        state=cast(StateStore, object()),
    )

    service.delete_report_result_rows("trade-1", "publish-1")
    service.delete_daily_report_rows("report-1", None)

    assert store.calls == [
        ("paper", "trade-1", "publish-1"),
        ("daily", "report-1", None),
    ]


def test_persistence_service_cleanup_transactions_delete_related_rows(tmp_path) -> None:
    service = PersistenceService(
        logs=JSONLStore(tmp_path / "logs"),
        sqlite=SQLiteStore(tmp_path / "db.sqlite3"),
        state=StateStore(tmp_path / "state"),
    )
    service.insert_daily_report(
        {
            "report_id": "report-1",
            "report_date": "2026-07-13",
            "total_signals": 0,
            "total_pnl_usdc": 0.0,
            "win_rate": 0.0,
            "created_at": "2026-07-13T00:00:00Z",
        }
    )
    service.insert_telegram_publish(
        {
            "publish_id": "publish-1",
            "message_type": "daily_report",
            "signal_id": None,
            "status": "pending",
            "sent_at": None,
        }
    )

    service.delete_daily_report_rows("report-1", "publish-1")
    counts = service.counts()
    service.close()

    assert counts["daily_reports"] == 0
    assert counts["telegram_publishes"] == 0


def test_persistence_service_wraps_counts_and_close(tmp_path) -> None:
    service = PersistenceService(
        logs=JSONLStore(tmp_path / "logs"),
        sqlite=SQLiteStore(tmp_path / "db.sqlite3"),
        state=StateStore(tmp_path / "state"),
    )

    counts = service.counts()
    service.close()

    assert "signals" in counts
