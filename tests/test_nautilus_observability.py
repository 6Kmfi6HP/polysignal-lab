from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest
from polysignal_lab.alpha.types import AlphaDecision
from polysignal_lab.app.services.persistence_service import PersistenceService
from polysignal_lab.domain.enums import ExitMode, Side, OrderStatus, TradeResultStatus
from polysignal_lab.domain.paper_order import PaperFill, PaperOrder
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.paper_result import PaperTradeResult
from polysignal_lab.storage.jsonl_store import JSONLStore
from polysignal_lab.storage.sqlite_store import SQLiteStore
from polysignal_lab.storage.state_store import StateStore
from polysignal_lab.nautilus_runtime.execution_types import PaperExecutionResult
from polysignal_lab.nautilus_runtime.observability import (
    DecisionPolicyControl,
    NautilusEventStoreAdapter,
    NautilusNotifierAdapter,
    ObservabilityActor,
)
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor
from polysignal_lab.utils import utc_now


class FakeStore:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {}

    def insert_json(self, table: str, data: Mapping[str, object]) -> None:
        self.tables.setdefault(table, []).append(dict(data))

    def insert_many_json(self, table: str, rows: Sequence[Mapping[str, object]]) -> None:
        for row in rows:
            self.insert_json(table, row)


# ── ObservabilityActor tests ──────────────────────────────────────────────────

def test_startup_message_includes_matching_engine_metadata() -> None:
    publisher = FakePublisher()
    actor = ObservabilityActor(notifier=NautilusNotifierAdapter(publisher))

    asyncio.run(
        actor.notify_startup(
            ["ptb_diff"],
            paper_engine="nautilus_matching",
            accuracy_mode="depth_l2",
        )
    )

    assert publisher.calls == [
        (
            "Nautilus runtime started — 1 strategies loaded — "
            "paper_engine=nautilus_matching accuracy_mode=depth_l2",
            "startup",
        )
    ]
    component = actor.health.components["observability_actor"]
    assert component.metrics["paper_engine"] == "nautilus_matching"
    assert component.metrics["accuracy_mode"] == "depth_l2"



def test_record_decision_writes_to_signals_table() -> None:
    store = FakeStore()
    actor = ObservabilityActor(store=store)

    decision = AlphaDecision(
        strategy="test", asset="BTC", timeframe="5m",
        market_id="m1", market_slug="s1", condition_id="c1",
        token_id="t1", side=Side.UP, confidence=0.8,
        entry_reference_price=0.5, max_entry_price=0.55,
        seconds_to_close=120, data_freshness_ms=100,
        reason_codes=("EDGE",), metrics={},
    )
    actor.record_decision(decision, accepted=True)

    rows = store.tables.get("signals", [])
    assert len(rows) == 1
    assert rows[0]["strategy"] == "test"
    assert rows[0]["accepted"] is True
    assert rows[0]["side"] == "UP"


def test_record_order_writes_to_orders_table() -> None:
    store = FakeStore()
    actor = ObservabilityActor(store=store)

    order = PaperOrder(
        paper_order_id="order-1", signal_id="sig-1", token_id="t1",
        side=Side.UP, limit_price=0.82, stake_usdc=10.0,
        reference_price=0.82, asset="BTC", timeframe="5m", strategy="test",
        market_id="m1", market_slug="s1",
    )
    result = PaperExecutionResult(order=order, status=OrderStatus.FILLED)

    actor.record_order(result)

    rows = store.tables.get("orders", [])
    assert len(rows) == 1
    assert rows[0]["status"] == "FILLED"
    assert rows[0]["paper_order_id"] == "order-1"
    assert rows[0]["limit_price"] == 0.82
    assert rows[0]["stake_usdc"] == 10.0


def test_record_order_preserves_matching_metadata() -> None:
    store = FakeStore()
    actor = ObservabilityActor(store=store)

    order = PaperOrder(
        paper_order_id="order-1", signal_id="sig-1", token_id="t1",
        side=Side.UP, limit_price=0.82, stake_usdc=10.0,
        reference_price=0.82, asset="BTC", timeframe="5m", strategy="test",
        market_id="m1", market_slug="s1",
        metrics={"paper_engine": "nautilus_matching", "accuracy_mode": "depth_l2"},
    )
    result = PaperExecutionResult(order=order, status=OrderStatus.FILLED)

    actor.record_order(result)

    rows = store.tables.get("orders", [])
    assert len(rows) == 1
    assert rows[0]["metrics"]["paper_engine"] == "nautilus_matching"
    assert rows[0]["metrics"]["accuracy_mode"] == "depth_l2"


def test_record_fill_writes_to_fills_table() -> None:
    store = FakeStore()
    actor = ObservabilityActor(store=store)

    fill = PaperFill(
        paper_order_id="order-1", signal_id="sig-1", token_id="t1",
        side=Side.UP, raw_best_ask=0.82, slippage_bps=0,
        fill_price=0.82, stake_usdc=10.0, shares=12.0,
        depth_checked=False, available_depth_usdc=None, fill_ratio=1.0,
        metrics={"paper_engine": "nautilus_matching", "accuracy_mode": "depth_l2"},
    )
    actor.record_fill(fill)

    rows = store.tables.get("fills", [])
    assert len(rows) == 1
    assert rows[0]["fill_price"] == 0.82
    assert rows[0]["metrics"]["paper_engine"] == "nautilus_matching"
    assert rows[0]["metrics"]["accuracy_mode"] == "depth_l2"



def test_record_position_preserves_display_metadata() -> None:
    store = FakeStore()
    actor = ObservabilityActor(store=store)

    position = PaperPosition(
        paper_position_id="pos-1",
        signal_id="sig-1",
        paper_order_id="order-1",
        paper_fill_id="fill-1",
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        token_id="t1",
        side=Side.UP,
        entry_price=0.5,
        shares=20.0,
        stake_usdc=10.0,
        signal_confidence=0.8,
        signal_metrics={
            "condition_id": "condition-btc-5m",
            "paper_engine": "nautilus_matching",
            "accuracy_mode": "depth_l2",
        },
    )

    actor.record_position(position)

    rows = store.tables.get("positions", [])
    assert len(rows) == 1
    assert rows[0]["signal_id"] == "sig-1"
    assert rows[0]["asset"] == "BTC"
    assert rows[0]["timeframe"] == "5m"
    assert rows[0]["market_id"] == "btc-5m"
    assert rows[0]["market_slug"] == "btc-updown-5m"
    assert rows[0]["signal_confidence"] == 0.8
    assert rows[0]["signal_metrics"]["paper_engine"] == "nautilus_matching"
    assert rows[0]["signal_metrics"]["accuracy_mode"] == "depth_l2"

def test_record_nautilus_projection_events_write_projected_rows() -> None:
    store = FakeStore()
    actor = ObservabilityActor(store=store)

    actor.record_nautilus_order_event(
        SimpleNamespace(
            client_order_id="C-001",
            instrument_id="up-token.POLYMARKET",
            order_side="BUY",
            order_type="LIMIT",
            time_in_force="GTD",
            quantity=10.0,
            price=0.01,
            status="ACCEPTED",
            metrics={"level_price": 0.01},
            tags=["strategy=one_cent_buy", "condition_id=condition-btc-5m"],
            ts_event=datetime(2026, 6, 27, tzinfo=UTC),
        )
    )
    actor.record_nautilus_fill_event(
        SimpleNamespace(
            client_order_id="C-001",
            instrument_id="up-token.POLYMARKET",
            trade_id="T-001",
            last_qty=10.0,
            last_px=0.01,
            liquidity_side="TAKER",
            metrics={"level_price": 0.01},
        )
    )
    actor.record_nautilus_position(
        SimpleNamespace(
            id="P-001",
            instrument_id="up-token.POLYMARKET",
            signed_qty=10.0,
            avg_px_open=0.01,
            realized_pnl=0.0,
            is_closed=False,
        )
    )

    order_rows = store.tables["nautilus_order"]
    fill_rows = store.tables["nautilus_fill"]
    position_rows = store.tables["nautilus_position"]

    assert order_rows[0]["client_order_id"] == "C-001"
    assert order_rows[0]["paper_order_id"] == "C-001"
    assert order_rows[0]["status"] == "ACCEPTED"
    assert order_rows[0]["metrics"]["level_price"] == 0.01
    assert fill_rows[0]["client_order_id"] == "C-001"
    assert fill_rows[0]["trade_id"] == "T-001"
    assert fill_rows[0]["paper_order_id"] == "C-001"
    assert fill_rows[0]["paper_fill_id"] == "T-001"
    assert position_rows[0]["position_id"] == "P-001"
    assert position_rows[0]["paper_position_id"] == "P-001"
    assert position_rows[0]["is_closed"] is False

def test_nautilus_projection_events_with_integer_timestamps_get_unique_event_ids() -> None:
    persistence = FakePersistence()
    actor = ObservabilityActor(store=NautilusEventStoreAdapter(persistence))

    actor.record_nautilus_order_event(
        SimpleNamespace(
            client_order_id="C-001",
            instrument_id="up-token.POLYMARKET",
            order_side="BUY",
            order_type="LIMIT",
            time_in_force="GTD",
            quantity=10.0,
            price=0.01,
            status="ACCEPTED",
            metrics={"level_price": 0.01},
            tags=["strategy=one_cent_buy", "condition_id=condition-btc-5m"],
            ts_event=1_717_000_000_000_000_000,
        )
    )
    actor.record_nautilus_order_event(
        SimpleNamespace(
            client_order_id="C-002",
            instrument_id="up-token.POLYMARKET",
            order_side="BUY",
            order_type="LIMIT",
            time_in_force="GTD",
            quantity=12.0,
            price=0.02,
            status="ACCEPTED",
            metrics={"level_price": 0.02},
            tags=["strategy=one_cent_buy", "condition_id=condition-btc-5m"],
            ts_event=1_717_000_000_001_000_000,
        )
    )

    system_events = [
        payload
        for name, payload in persistence.calls
        if name == "insert_system_event"
    ]
    assert len(system_events) == 2
    first_event = cast(dict[str, object], system_events[0])
    second_event = cast(dict[str, object], system_events[1])
    assert first_event["created_at"] != ""
    assert second_event["created_at"] != ""
    assert first_event["event_id"] != second_event["event_id"]

def test_record_settlement_writes_to_settlements_table() -> None:
    store = FakeStore()
    actor = ObservabilityActor(store=store)
    now = utc_now()

    result = PaperTradeResult(
        signal_id="sig-1", paper_position_id="pos-1", strategy="test",
        asset="BTC", timeframe="5m", market_id="m1", market_slug="s1",
        side=Side.UP, entry_price=0.5, shares=20.0, stake_usdc=10.0,
        exit_mode=ExitMode.RESOLUTION, outcome_value=1.0,
        settlement_value=20.0, pnl_usdc=10.0, roi=1.0,
        result=TradeResultStatus.WIN,
        opened_at=now, closed_at=now,
    )
    actor.record_settlement(result)

    rows = store.tables.get("settlements", [])
    assert len(rows) == 1
    assert rows[0]["result"] == "WIN"


def test_event_count_increments() -> None:
    actor = ObservabilityActor()
    assert actor.event_count == 0
    decision = AlphaDecision(
        strategy="t", asset="BTC", timeframe="5m",
        market_id="m", market_slug="s", condition_id="c",
        token_id="t", side=Side.UP, confidence=0.5,
        entry_reference_price=0.5, max_entry_price=0.55,
        seconds_to_close=120, data_freshness_ms=100,
        reason_codes=(), metrics={},
    )
    actor.record_decision(decision, accepted=True)
    assert actor.event_count == 1


def test_decision_policy_control_proxies_disable() -> None:
    policy = DecisionPolicyActor()
    ctrl = DecisionPolicyControl(policy)

    assert ctrl.is_strategy_enabled("vwap_momentum")
    ctrl.set_strategy_enabled("vwap_momentum", enabled=False)
    assert not ctrl.is_strategy_enabled("vwap_momentum")


def test_decision_policy_control_returns_status_payload() -> None:
    policy = DecisionPolicyActor()
    ctrl = DecisionPolicyControl(policy)

    ctrl.set_strategy_enabled("test_strat", enabled=False)
    payload = ctrl.status_payload()
    assert "disabled_strategies" in payload
    disabled = payload["disabled_strategies"]
    assert isinstance(disabled, list)
    assert "test_strat" in disabled


class FakePersistence:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.logs: list[tuple[str, dict[str, Any]]] = []

    def insert_signal(self, signal: object) -> None:
        self.calls.append(("insert_signal", signal))

    def insert_rejected_signal(self, rejected: object) -> None:
        self.calls.append(("insert_rejected_signal", rejected))

    def insert_paper_order(self, order: object) -> None:
        self.calls.append(("insert_paper_order", order))

    def upsert_paper_order(self, order: object) -> None:
        self.calls.append(("upsert_paper_order", order))

    def insert_paper_fill(self, fill: object) -> None:
        self.calls.append(("insert_paper_fill", fill))

    def upsert_paper_position(self, position: object) -> None:
        self.calls.append(("upsert_paper_position", position))

    def insert_paper_trade_result(self, result: object) -> None:
        self.calls.append(("insert_paper_trade_result", result))

    def insert_system_event(self, event: object) -> None:
        self.calls.append(("insert_system_event", event))

    def append_log(self, stream: str, payload: object) -> None:
        self.logs.append((stream, dict(cast(Mapping[str, Any], payload))))


class FakePublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def send(
        self,
        message: str,
        message_type: str,
        signal_id: str | None = None,
    ) -> object:
        del signal_id
        self.calls.append((message, message_type))
        return None


def test_event_store_routes_known_tables_and_rejects_unknown() -> None:
    persistence = FakePersistence()
    adapter = NautilusEventStoreAdapter(persistence)

    adapter.insert_json("signals", {"signal_id": "s1"})
    adapter.insert_json("rejected_signals", {"rejected_id": "r1"})
    adapter.insert_json("orders", {"paper_order_id": "o1"})
    adapter.insert_json("fills", {"paper_fill_id": "f1"})
    adapter.insert_json("positions", {"paper_position_id": "p1"})
    adapter.insert_json("settlements", {"paper_trade_id": "t1"})
    adapter.insert_json("health_snapshot", {"event_id": "h1", "event_type": "health_snapshot", "severity": "info", "created_at": "now"})

    assert [name for name, _ in persistence.calls] == [
        "insert_signal",
        "insert_rejected_signal",
        "upsert_paper_order",
        "insert_paper_fill",
        "upsert_paper_position",
        "insert_paper_trade_result",
        "insert_system_event",
    ]
    assert [stream for stream, _ in persistence.logs] == [
        "signals",
        "rejected_signals",
        "paper_orders",
        "paper_fills",
        "paper_positions",
        "paper_trade_results",
        "system_events",
    ]
    with pytest.raises(ValueError, match="Unknown Nautilus event table"):
        adapter.insert_json("unknown", {})


def test_observability_actor_records_matching_execution_to_sqlite_and_jsonl_streams() -> None:
    persistence = FakePersistence()
    actor = ObservabilityActor(store=NautilusEventStoreAdapter(persistence))
    metadata = {"paper_engine": "nautilus_matching", "accuracy_mode": "depth_l2"}
    order = PaperOrder(
        paper_order_id="order-1", signal_id="sig-1", token_id="t1",
        side=Side.UP, limit_price=0.82, stake_usdc=10.0,
        reference_price=0.82, asset="BTC", timeframe="5m", strategy="test",
        market_id="m1", market_slug="s1", metrics=dict(metadata),
    )
    fill = PaperFill(
        paper_fill_id="fill-1", paper_order_id="order-1", signal_id="sig-1",
        token_id="t1", side=Side.UP, raw_best_ask=0.82, slippage_bps=0,
        fill_price=0.82, stake_usdc=10.0, shares=12.0,
        depth_checked=False, available_depth_usdc=None, fill_ratio=1.0,
        metrics=dict(metadata),
    )
    position = PaperPosition(
        paper_position_id="pos-1", signal_id="sig-1", paper_order_id="order-1",
        paper_fill_id="fill-1", strategy="test", asset="BTC", timeframe="5m",
        market_id="m1", market_slug="s1", token_id="t1", side=Side.UP,
        entry_price=0.82, shares=12.0, stake_usdc=10.0,
        signal_confidence=0.8, signal_metrics=dict(metadata),
    )

    actor.record_order(PaperExecutionResult(order=order, status=OrderStatus.FILLED))
    actor.record_fill(fill)
    actor.record_position(position)

    assert [name for name, _ in persistence.calls] == [
        "upsert_paper_order",
        "insert_paper_fill",
        "upsert_paper_position",
    ]
    assert [stream for stream, _ in persistence.logs] == [
        "paper_orders",
        "paper_fills",
        "paper_positions",
    ]
    assert persistence.logs[0][1]["metrics"]["paper_engine"] == "nautilus_matching"
    assert persistence.logs[1][1]["metrics"]["accuracy_mode"] == "depth_l2"
    assert persistence.logs[2][1]["signal_metrics"]["paper_engine"] == "nautilus_matching"


def test_event_store_upserts_terminal_order_update(tmp_path) -> None:
    persistence = PersistenceService(
        JSONLStore(tmp_path / "logs"),
        SQLiteStore(tmp_path / "paper.sqlite"),
        StateStore(tmp_path / "state"),
    )
    adapter = NautilusEventStoreAdapter(persistence)
    order = PaperOrder(
        paper_order_id="order-1", signal_id="sig-1", token_id="t1",
        side=Side.UP, limit_price=0.82, stake_usdc=10.0,
        reference_price=0.82, asset="BTC", timeframe="5m", strategy="test",
        market_id="m1", market_slug="s1", status=OrderStatus.RESTING,
    )

    adapter.insert_json("orders", order.model_dump(mode="json"))
    adapter.insert_json(
        "orders",
        order.model_copy(update={"status": OrderStatus.REJECTED}).model_dump(mode="json"),
    )

    rows = persistence.query_json("paper_orders")
    persistence.close()
    assert len(rows) == 1
    assert rows[0]["paper_order_id"] == "order-1"
    assert rows[0]["status"] == "REJECTED"


def test_notifier_adapter_sends_in_thread() -> None:
    publisher = FakePublisher()
    adapter = NautilusNotifierAdapter(publisher)

    asyncio.run(adapter.send("started", "startup"))

    assert publisher.calls == [("started", "startup")]
