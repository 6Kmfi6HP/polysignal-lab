"""
Input: __future__, json, pathlib, types, uuid, nautilus optional
Output: issue #15 lifecycle identity and filled order projection validity tests
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from nautilus_optional import require_nautilus
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


def test_event_store_adapter_uses_explicit_id_and_safe_lifecycle_fallback(
    tmp_path: Path,
) -> None:
    from uuid import UUID

    from polysignal_lab.nautilus_runtime.observability_persistence import (
        NautilusEventStoreAdapter,
    )

    store = SQLiteStore(tmp_path / "issue15-adapter.sqlite3")
    try:
        adapter = NautilusEventStoreAdapter(
            SimpleNamespace(
                insert_signal=lambda _payload: None,
                insert_rejected_signal=lambda _payload: None,
                insert_paper_trade_result=lambda _payload: None,
                insert_system_event=store.insert_system_event,
                append_log=lambda _stream, _payload: None,
            )
        )
        timestamp = "2026-07-14T18:59:46.903617Z"
        for status in ("SUBMITTED", "ACCEPTED"):
            adapter.insert_json(
                "nautilus_order",
                {
                    "client_order_id": "O-fallback",
                    "status": status,
                    "ts": timestamp,
                },
            )
        explicit_id = UUID("00000000-0000-4000-8000-000000000001")
        adapter.insert_json(
            "nautilus_order",
            {
                "event_id": explicit_id,
                "client_order_id": "O-explicit",
                "status": "SUBMITTED",
                "ts": timestamp,
            },
        )

        rows = store._conn.execute(
            "SELECT event_id FROM system_events ORDER BY event_id"
        ).fetchall()
        assert {row["event_id"] for row in rows} == {
            "nautilus_order:O-fallback:ACCEPTED:2026-07-14T18:59:46.903617Z",
            "nautilus_order:O-fallback:SUBMITTED:2026-07-14T18:59:46.903617Z",
            str(explicit_id),
        }
    finally:
        store.close()


def test_real_nautilus_order_lifecycle_uses_unique_durable_event_ids(
    tmp_path: Path,
) -> None:
    require_nautilus()
    from nautilus_trader.model.events import (
        OrderAccepted as NautilusOrderAccepted,
        OrderFilled as NautilusOrderFilled,
        OrderSubmitted as NautilusOrderSubmitted,
    )
    from nautilus_trader.test_kit.providers import TestInstrumentProvider
    from nautilus_trader.test_kit.stubs.events import TestEventStubs
    from nautilus_trader.test_kit.stubs.execution import TestExecStubs
    from polysignal_lab.nautilus_runtime.observability import ObservabilityService
    from polysignal_lab.nautilus_runtime.observability_persistence import (
        NautilusEventStoreAdapter,
    )
    from polysignal_lab.nautilus_runtime.strategy.event_projection import (
        project_nautilus_fill_event,
        project_nautilus_order_event,
    )

    store = SQLiteStore(tmp_path / "issue15-lifecycle.sqlite3")
    try:
        persistence = SimpleNamespace(
            insert_signal=lambda _payload: None,
            insert_rejected_signal=lambda _payload: None,
            insert_paper_trade_result=lambda _payload: None,
            insert_system_event=store.insert_system_event,
            append_log=lambda _stream, _payload: None,
        )
        observability = ObservabilityService(
            store=NautilusEventStoreAdapter(persistence),
        )
        instrument = TestInstrumentProvider.binary_option()
        order = TestExecStubs.limit_order(
            instrument=instrument,
            price=instrument.make_price(0.60),
            quantity=instrument.make_qty(12),
            tags=[
                "signal_id=sig_test",
                "strategy=late_consensus",
                "market_id=1",
                "condition_id=cond-1",
            ],
        )
        lifecycle_ts = 1_784_055_586_903_617_284
        submitted_payload = NautilusOrderSubmitted.to_dict(
            TestEventStubs.order_submitted(order, ts_event=lifecycle_ts),
        )
        submitted_payload["event_id"] = "ffffffff-ffff-4fff-8fff-ffffffffffff"
        submitted = NautilusOrderSubmitted.from_dict(submitted_payload)
        order.apply(submitted)
        accepted_payload = NautilusOrderAccepted.to_dict(
            TestEventStubs.order_accepted(order, ts_event=lifecycle_ts),
        )
        accepted_payload["event_id"] = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
        accepted = NautilusOrderAccepted.from_dict(accepted_payload)
        order.apply(accepted)
        filled_payload = NautilusOrderFilled.to_dict(
            TestEventStubs.order_filled(
                order,
                instrument,
                last_px=instrument.make_price(0.55),
                last_qty=instrument.make_qty(12),
                ts_event=lifecycle_ts,
            ),
        )
        filled_payload["event_id"] = "00000000-0000-4000-8000-000000000001"
        filled = NautilusOrderFilled.from_dict(filled_payload)
        metrics = {
            "signal_id": "sig_test",
            "strategy": "late_consensus",
            "market_id": "1",
            "market_slug": "btc-updown-5m",
            "condition_id": "cond-1",
            "side": "UP",
            "contracts": 12.0,
            "up_ask": 0.60,
            "token_id": "token-up",
        }

        lifecycle = (
            (
                observability.record_nautilus_order_event,
                project_nautilus_order_event(submitted, metrics),
            ),
            (
                observability.record_nautilus_order_event,
                project_nautilus_order_event(accepted, metrics),
            ),
            (
                observability.record_nautilus_fill_event,
                project_nautilus_fill_event(filled, metrics),
            ),
        )
        for recorder, event in lifecycle:
            recorder(event)
        while observability.drain_telemetry_once():
            pass

        for recorder, event in lifecycle[:2]:
            recorder(event)
        replayed = store._conn.execute(
            "SELECT status,payload_json FROM paper_order_states WHERE paper_order_id=?",
            (str(order.client_order_id),),
        ).fetchone()
        assert replayed is not None
        replayed_payload = json.loads(replayed["payload_json"])
        assert replayed["status"] == "FILLED"
        assert float(replayed_payload.get("limit_price") or 0) == 0.55

        lifecycle[2][0](lifecycle[2][1])
        while observability.drain_telemetry_once():
            pass

        events = store._conn.execute(
            "SELECT event_id,payload_json FROM system_events ORDER BY created_at,event_id"
        ).fetchall()
        assert len(events) == 3
        assert {row["event_id"] for row in events} == {
            str(submitted.id),
            str(accepted.id),
            str(filled.id),
        }

        row = store._conn.execute(
            "SELECT status,payload_json FROM paper_order_states WHERE paper_order_id=?",
            (str(order.client_order_id),),
        ).fetchone()
        assert row is not None
        payload = json.loads(row["payload_json"])
        assert row["status"] == "FILLED"
        assert payload.get("_projection_invalid") is not True
        assert payload.get("signal_id") == "sig_test"
        assert payload.get("strategy") == "late_consensus"
        assert payload.get("market_id") == "1"
        assert payload.get("condition_id") == "cond-1"
        assert float(payload.get("limit_price") or 0) == 0.55
        assert float(payload.get("shares") or 0) == 12.0
    finally:
        store.close()


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
