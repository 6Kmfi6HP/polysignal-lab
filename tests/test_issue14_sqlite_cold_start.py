from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from polysignal_lab.storage.sqlite_store import SQLiteStore


def test_sqlite_store_retries_until_parent_and_file_become_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "data" / "polysignal_lab.sqlite3"
    attempts = {"n": 0}
    real_connect = sqlite3.connect

    def flaky_connect(path, *args, **kwargs):  # type: ignore[no-untyped-def]
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise sqlite3.OperationalError("unable to open database file")
        return real_connect(path, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", flaky_connect)

    store = SQLiteStore(db_path, connect_retries=5, retry_delay_sec=0.01)
    try:
        assert attempts["n"] == 3
        assert db_path.exists()
        store.validate_schema()
    finally:
        store.close()


def test_sqlite_store_raises_after_retry_exhaustion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "missing" / "db.sqlite3"
    monkeypatch.setattr(
        sqlite3,
        "connect",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            sqlite3.OperationalError("unable to open database file")
        ),
    )

    with pytest.raises(sqlite3.OperationalError, match="unable to open database file"):
        SQLiteStore(db_path, connect_retries=2, retry_delay_sec=0.01)


def test_dashboard_cli_uses_retrying_sqlite_open() -> None:
    source = Path("src/polysignal_lab/app/main.py").read_text(encoding="utf-8")
    assert "connect_retries" in source
    assert "SQLiteStore(" in source
