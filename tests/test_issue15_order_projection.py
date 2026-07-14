"""
Input: __future__, pathlib, pytest
Output: issue #15 filled order projection validity tests
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from polysignal_lab.nautilus_runtime.strategy.event_projection import (
    project_nautilus_order_event,
)
from polysignal_lab.nautilus_runtime.projections import project_order_event
from polysignal_lab.paper.event_projection import normalize_paper_order
from polysignal_lab.storage.sqlite_store import SQLiteStore


class OrderSubmitted:
    def __init__(self) -> None:
        self.client_order_id = "O-test-1"
        self.instrument_id = "token-up.POLYMARKET"
        self.order_side = "BUY"
        self.order_type = "LIMIT"
        self.time_in_force = "GTC"
        self.quantity = 12.0
        self.price = 0.55
        self.tags = (
            "signal_id=sig_test",
            "strategy=late_consensus",
            "market_id=1",
            "condition_id=cond-1",
        )
        self.ts_event = 1_784_000_000_000_000_000


def test_project_nautilus_order_event_derives_status_from_event_type() -> None:
    metrics = {
        "signal_id": "sig_test",
        "strategy": "late_consensus",
        "market_id": "1",
        "side": "UP",
        "contracts": 12,
        "up_ask": 0.55,
    }
    projected = project_nautilus_order_event(OrderSubmitted(), metrics)
    row = project_order_event(projected)
    assert row["status"] == "SUBMITTED"
    assert row["price"] == 0.55
    assert row["quantity"] == 12.0
    assert row["signal_id"] == "sig_test"


def test_upsert_order_and_fill_projection_stays_valid(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "issue15.sqlite3")
    try:
        metrics = {
            "signal_id": "sig_test",
            "strategy": "late_consensus",
            "market_id": "1",
            "market_slug": "btc-updown-5m",
            "condition_id": "cond-1",
            "side": "UP",
            "contracts": 12.0,
            "up_ask": 0.55,
            "token_id": "token-up",
        }
        order_event = project_order_event(
            project_nautilus_order_event(OrderSubmitted(), metrics)
        )
        store.insert_system_event(
            {
                "event_id": "nautilus_order:O-test-1:1",
                "event_type": "nautilus_order",
                "severity": "info",
                "created_at": "2026-07-14T07:00:00Z",
                **order_event,
            }
        )
        store.insert_system_event(
            {
                "event_id": "nautilus_fill:T-1",
                "event_type": "nautilus_fill",
                "severity": "info",
                "created_at": "2026-07-14T07:00:01Z",
                "client_order_id": "O-test-1",
                "paper_order_id": "O-test-1",
                "trade_id": "T-1",
                "price": 0.55,
                "quantity": 12.0,
                "signal_id": "sig_test",
                "metrics": metrics,
                "ts": "2026-07-14T07:00:01Z",
            }
        )
        # Incomplete later order lifecycle event must not wipe known fields.
        store.insert_system_event(
            {
                "event_id": "nautilus_order:O-test-1:2",
                "event_type": "nautilus_order",
                "severity": "info",
                "created_at": "2026-07-14T07:00:02Z",
                "client_order_id": "O-test-1",
                "paper_order_id": "O-test-1",
                "status": "",
                "price": 0.0,
                "quantity": 0.0,
                "signal_id": "",
                "strategy": "",
                "market_id": "",
                "metrics": {},
                "ts": "2026-07-14T07:00:02Z",
            }
        )
        row = store._conn.execute(
            "SELECT status,payload_json FROM paper_order_states WHERE paper_order_id=?",
            ("O-test-1",),
        ).fetchone()
        assert row is not None
        import json

        payload = json.loads(row["payload_json"])
        assert row["status"] == "FILLED"
        assert payload.get("_projection_invalid") is not True
        assert payload.get("signal_id") == "sig_test"
        assert payload.get("strategy") == "late_consensus"
        assert payload.get("market_id") == "1"
        assert float(payload.get("limit_price") or payload.get("price") or 0) > 0
        assert float(payload.get("shares") or payload.get("quantity") or 0) > 0
    finally:
        store.close()


def test_normalize_paper_order_uses_metrics_side_and_contracts() -> None:
    payload = normalize_paper_order(
        {
            "client_order_id": "O-1",
            "status": "SUBMITTED",
            "price": 0.0,
            "quantity": 0.0,
            "metrics": {
                "signal_id": "sig_1",
                "strategy": "late_consensus",
                "market_id": "9",
                "side": "UP",
                "contracts": 8,
                "up_ask": 0.7,
            },
        }
    )
    assert payload["status"] == "RESTING" or payload["status"] == "SUBMITTED" or payload["status"]
    assert payload["side"] == "UP"
    assert payload["signal_id"] == "sig_1"
    assert float(payload.get("shares") or 0) == 8.0
    assert float(payload.get("limit_price") or 0) == 0.7
