"""
Input: polysignal_lab.app.services.persistence_service, polysignal_lab.app.services.persistence_service.PersistenceService, polysignal_lab.storage.jsonl_store, polysignal_lab.storage.jsonl_store.JSONLStore, polysignal_lab.storage.sqlite_store, polysignal_lab.storage.sqlite_store.SQLiteStore, polysignal_lab.storage.state_store, polysignal_lab.storage.state_store.StateStore
Output: test_persistence_service_wraps_counts_and_close
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from polysignal_lab.app.services.persistence_service import PersistenceService
from polysignal_lab.storage.jsonl_store import JSONLStore
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.storage.state_store import StateStore


def test_persistence_service_wraps_counts_and_close(tmp_path) -> None:
    service = PersistenceService(
        logs=JSONLStore(tmp_path / "logs"),
        sqlite=SQLiteStore(tmp_path / "db.sqlite3"),
        state=StateStore(tmp_path / "state"),
    )

    counts = service.counts()
    service.close()

    assert "signals" in counts
