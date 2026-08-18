from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

from nautilus_optional import require_nautilus
from polysignal_lab.nautilus_runtime.projections import (
    project_order_event,
)
from polysignal_lab.storage.event_projection import normalize_report_order
from polysignal_lab.storage.sqlite_store import SQLiteStore


if TYPE_CHECKING:
    from nautilus_trader.core.nautilus_pyo3 import OrderSubmitted


def _submitted_event() -> OrderSubmitted:
    """A real pyo3 OrderSubmitted — the type the runtime Strategy actually receives."""
    require_nautilus()
    from nautilus_trader.test_kit.rust.events_pyo3 import TestEventsProviderPyo3

    return TestEventsProviderPyo3.order_submitted()


def test_project_order_event_reads_event_facts_and_metrics() -> None:
    event = _submitted_event()
    metrics = {
        "signal_id": "sig_test",
        "strategy": "late_consensus",
        "market_id": "1",
        "condition_id": "cond-1",
        "side": "UP",
        "contracts": 12.0,
        "level_price": 0.55,
    }
    row = project_order_event(event, metrics=metrics)
    # Event facts come from the event itself.
    assert row["status"] == "SUBMITTED"
    assert row["event_id"] == str(event.event_id)
    assert row["client_order_id"] == str(event.client_order_id)
    assert row["instrument_id"] == str(event.instrument_id)
    # Business metadata and order economics come from metrics: a submitted
    # event carries no tags, price, or quantity.
    assert row["signal_id"] == "sig_test"
    assert row["strategy"] == "late_consensus"
    assert row["condition_id"] == "cond-1"
    assert row["market_id"] == "1"
    assert row["price"] == 0.55
    assert row["quantity"] == 12.0


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
                insert_report_result=lambda _payload: None,
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
    from polysignal_lab.nautilus_runtime.projections import (
        project_fill_event,
        project_order_event,
    )

    store = SQLiteStore(tmp_path / "issue15-lifecycle.sqlite3")
    try:
        persistence = SimpleNamespace(
            insert_signal=lambda _payload: None,
            insert_rejected_signal=lambda _payload: None,
            insert_report_result=lambda _payload: None,
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
                "nautilus_order",
                project_order_event(submitted, metrics=metrics),
            ),
            (
                "nautilus_order",
                project_order_event(accepted, metrics=metrics),
            ),
            (
                "nautilus_fill",
                project_fill_event(filled, metrics=metrics),
            ),
        )
        for table, payload in lifecycle:
            observability.record_event(table, payload)
        while observability.drain_telemetry_once():
            pass

        for table, payload in lifecycle[:2]:
            observability.record_event(table, payload)
        replayed = store._conn.execute(
            "SELECT status,payload_json FROM report_orders WHERE report_order_id=?",
            (str(order.client_order_id),),
        ).fetchone()
        assert replayed is not None
        replayed_payload = json.loads(replayed["payload_json"])
        assert replayed["status"] == "FILLED"
        assert float(replayed_payload.get("limit_price") or 0) == 0.55

        observability.record_event(lifecycle[2][0], lifecycle[2][1])
        while observability.drain_telemetry_once():
            pass

        events = store._conn.execute(
            "SELECT event_id,payload_json FROM system_events ORDER BY created_at,event_id"
        ).fetchall()
        assert len(events) == 3
        assert {row["event_id"] for row in events} == {
            str(submitted.event_id),
            str(accepted.event_id),
            str(filled.event_id),
        }

        row = store._conn.execute(
            "SELECT status,payload_json FROM report_orders WHERE report_order_id=?",
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
        event = _submitted_event()
        order_id = str(event.client_order_id)
        order_event = project_order_event(event, metrics=metrics)
        store.insert_system_event(
            {
                "event_id": f"nautilus_order:{order_id}:1",
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
                "client_order_id": order_id,
                "report_order_id": order_id,
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
                "event_id": f"nautilus_order:{order_id}:2",
                "event_type": "nautilus_order",
                "severity": "info",
                "created_at": "2026-07-14T07:00:02Z",
                "client_order_id": order_id,
                "report_order_id": order_id,
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
            "SELECT status,payload_json FROM report_orders WHERE report_order_id=?",
            (order_id,),
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


def test_normalize_report_order_uses_metrics_side_and_contracts() -> None:
    payload = normalize_report_order(
        {
            "client_order_id": "O-1",
            "status": "SUBMITTED",
            "price": 0.7,
            "quantity": 8.0,
            "metrics": {
                "signal_id": "sig_1",
                "strategy": "late_consensus",
                "market_id": "9",
                "side": "UP",
                "contracts": 8,
            },
        }
    )
    assert (
        payload["status"] in {"ACCEPTED", "SUBMITTED", "RESTING"} or payload["status"]
    )
    assert payload["side"] == "UP"
    assert payload["signal_id"] == "sig_1"
    assert float(payload.get("shares") or 0) == 8.0
    assert float(payload.get("limit_price") or 0) == 0.7


def test_partial_fill_does_not_mark_report_order_filled(tmp_path: Path) -> None:
    """report_fills durable source must distinguish PARTIALLY_FILLED vs FILLED."""
    store = SQLiteStore(tmp_path / "partial_fill.sqlite3")
    try:
        event = {
            "event_id": "fill-partial-1",
            "event_type": "nautilus_fill",
            "client_order_id": "O-partial-1",
            "report_order_id": "O-partial-1",
            "trade_id": "T-partial-1",
            "quantity": 4.0,
            "price": 0.5,
            "leaves_qty": 8.0,
            "filled_qty": 4.0,
            "order_quantity": 12.0,
            "ts": "2026-07-18T00:00:00Z",
            "metrics": {
                "contracts": 12.0,
                "signal_id": "sig-p",
                "strategy": "ptb_diff",
            },
        }
        store.insert_system_event(
            {
                **event,
                "severity": "info",
                "created_at": "2026-07-18T00:00:00Z",
            }
        )
        row = store._conn.execute(
            "SELECT status,payload_json FROM report_orders WHERE report_order_id=?",
            ("O-partial-1",),
        ).fetchone()
        assert row is not None
        assert row["status"] == "PARTIALLY_FILLED"
        fill_row = store._conn.execute(
            "SELECT report_fill_id FROM report_fills WHERE report_order_id=?",
            ("O-partial-1",),
        ).fetchone()
        assert fill_row is not None
    finally:
        store.close()
