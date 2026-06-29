from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

DB_PATH = Path(os.environ.get("POLYSIGNAL_DB_PATH", "data/polysignal_lab.sqlite3"))
EVIDENCE_PATH = Path(
    os.environ.get(
        "POLYSIGNAL_CONTAINER_EVIDENCE",
        "/tmp/nautilus_container_evidence.json",
    )
)
BASELINE_SIGNALS = int(os.environ.get("POLYSIGNAL_BASELINE_SIGNALS", "0"))
BASELINE_SIGNAL_PUBLISHES = int(
    os.environ.get("POLYSIGNAL_BASELINE_SIGNAL_PUBLISHES", "0")
)
WAIT_SEC = float(os.environ.get("POLYSIGNAL_WAIT_SEC", "420"))
POLL_SEC = float(os.environ.get("POLYSIGNAL_POLL_SEC", "5"))


def _signal_preview(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    payload = json.loads(row["payload_json"])
    return {
        "signal_id": row["signal_id"],
        "strategy": row["strategy"],
        "asset": row["asset"],
        "timeframe": row["timeframe"],
        "market_id": row["market_id"],
        "market_slug": payload.get("market_slug"),
        "side": row["side"],
        "created_at": row["created_at"],
    }


def _publish_preview(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    payload = json.loads(row["payload_json"])
    return {
        "publish_id": row["publish_id"],
        "signal_id": row["signal_id"],
        "message_type": row["message_type"],
        "status": row["status"],
        "sent_at": row["sent_at"],
        "message": payload.get("message"),
    }


def _signal_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    signal_count = int(conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0])
    publish_count = int(
        conn.execute(
            "SELECT COUNT(*) FROM telegram_publishes WHERE message_type = 'signal'"
        ).fetchone()[0]
    )
    latest_signal = _signal_preview(
        conn.execute(
            """
            SELECT signal_id, strategy, asset, timeframe, market_id, side, created_at, payload_json
            FROM signals
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
    )
    latest_publish = _publish_preview(
        conn.execute(
            """
            SELECT publish_id, signal_id, message_type, status, sent_at, payload_json
            FROM telegram_publishes
            WHERE message_type = 'signal'
            ORDER BY sent_at DESC
            LIMIT 1
            """
        ).fetchone()
    )

    new_signal_count = max(signal_count - BASELINE_SIGNALS, 0)
    new_publish_count = max(publish_count - BASELINE_SIGNAL_PUBLISHES, 0)
    new_signals: list[dict[str, Any]] = []
    new_signal_ids: set[str] = set()
    if new_signal_count:
        rows = conn.execute(
            """
            SELECT signal_id, strategy, asset, timeframe, market_id, side, created_at, payload_json
            FROM signals
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (new_signal_count,),
        ).fetchall()
        new_signals = [preview for row in rows if (preview := _signal_preview(row)) is not None]
        new_signal_ids = {row["signal_id"] for row in new_signals}

    matched_publish = None
    matched_signal = None
    if new_publish_count and new_signal_ids:
        publish_rows = conn.execute(
            """
            SELECT publish_id, signal_id, message_type, status, sent_at, payload_json
            FROM telegram_publishes
            WHERE message_type = 'signal'
            ORDER BY sent_at DESC
            LIMIT ?
            """,
            (new_publish_count,),
        ).fetchall()
        by_signal_id = {row["signal_id"]: row for row in new_signals}
        for row in publish_rows:
            publish = _publish_preview(row)
            if (
                publish is not None
                and publish["status"] == "SENT"
                and publish["signal_id"] in new_signal_ids
            ):
                matched_publish = publish
                matched_signal = by_signal_id[publish["signal_id"]]
                break

    return {
        "signal_count": signal_count,
        "signal_publish_count": publish_count,
        "latest_signal": latest_signal,
        "latest_signal_publish": latest_publish,
        "new_signal_count": new_signal_count,
        "new_signal_publish_count": new_publish_count,
        "verified_signal": matched_signal,
        "verified_signal_publish": matched_publish,
    }


def _verified(snapshot: dict[str, Any]) -> bool:
    return bool(snapshot.get("verified_signal") and snapshot.get("verified_signal_publish"))


def main() -> None:
    deadline = time.monotonic() + WAIT_SEC
    last_snapshot: dict[str, Any] = {}

    while True:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            last_snapshot = _signal_snapshot(conn)
        finally:
            conn.close()

        if _verified(last_snapshot):
            break
        if time.monotonic() >= deadline:
            raise SystemExit(
                json.dumps(
                    {
                        "verified": False,
                        "baseline_signals": BASELINE_SIGNALS,
                        "baseline_signal_publishes": BASELINE_SIGNAL_PUBLISHES,
                        **last_snapshot,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        time.sleep(POLL_SEC)

    evidence = {
        "verified": True,
        "baseline_signals": BASELINE_SIGNALS,
        "baseline_signal_publishes": BASELINE_SIGNAL_PUBLISHES,
        **last_snapshot,
    }
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
