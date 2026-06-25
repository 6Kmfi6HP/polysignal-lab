from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone

import pytest
from polysignal_lab.alpha.types import AlphaDecision
from polysignal_lab.domain.enums import ExitMode, Side, OrderStatus, TradeResultStatus
from polysignal_lab.domain.paper_order import PaperFill, PaperOrder
from polysignal_lab.domain.paper_result import PaperTradeResult
from polysignal_lab.nautilus_runtime.execution import PaperExecutionResult
from polysignal_lab.nautilus_runtime.observability import (
    DecisionPolicyControl,
    NautilusEventStoreAdapter,
    NautilusNotifierAdapter,
    ObservabilityActor,
)
from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor
from polysignal_lab.utils import utc_now


class FakeStore:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {}

    def insert_json(self, table: str, data: Mapping[str, object]) -> None:
        self.tables.setdefault(table, []).append(dict(data))

    def insert_many_json(self, table: str, rows: Sequence[Mapping[str, object]]) -> None:
        for row in rows:
            self.insert_json(table, row)


# ── ObservabilityActor tests ──────────────────────────────────────────────────


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
    assert rows[0]["order_id"] == "order-1"


def test_record_fill_writes_to_fills_table() -> None:
    store = FakeStore()
    actor = ObservabilityActor(store=store)

    fill = PaperFill(
        paper_order_id="order-1", signal_id="sig-1", token_id="t1",
        side=Side.UP, raw_best_ask=0.82, slippage_bps=0,
        fill_price=0.82, stake_usdc=10.0, shares=12.0,
        depth_checked=False, available_depth_usdc=None, fill_ratio=1.0,
    )
    actor.record_fill(fill)

    rows = store.tables.get("fills", [])
    assert len(rows) == 1
    assert rows[0]["fill_price"] == 0.82


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
    def __init__(self):
        self.calls = []

    def insert_paper_order(self, payload): self.calls.append(("insert_paper_order", payload))
    def insert_paper_fill(self, payload): self.calls.append(("insert_paper_fill", payload))
    def upsert_paper_position(self, payload): self.calls.append(("upsert_paper_position", payload))
    def insert_paper_trade_result(self, payload): self.calls.append(("insert_paper_trade_result", payload))
    def insert_system_event(self, payload): self.calls.append(("insert_system_event", payload))


class FakePublisher:
    def __init__(self):
        self.calls = []

    def send(self, message: str, msg_type: str = "") -> None:
        self.calls.append((message, msg_type))


def test_event_store_routes_known_tables_and_rejects_unknown() -> None:
    persistence = FakePersistence()
    adapter = NautilusEventStoreAdapter(persistence)

    adapter.insert_json("orders", {"paper_order_id": "o1"})
    adapter.insert_json("fills", {"paper_fill_id": "f1"})
    adapter.insert_json("positions", {"paper_position_id": "p1"})
    adapter.insert_json("settlements", {"paper_trade_id": "t1"})
    adapter.insert_json("health_snapshot", {"event_id": "h1", "event_type": "health_snapshot", "severity": "info", "created_at": "now"})

    assert [name for name, _ in persistence.calls] == [
        "insert_paper_order",
        "insert_paper_fill",
        "upsert_paper_position",
        "insert_paper_trade_result",
        "insert_system_event",
    ]
    with pytest.raises(ValueError, match="Unknown Nautilus event table"):
        adapter.insert_json("unknown", {})


def test_notifier_adapter_sends_in_thread() -> None:
    publisher = FakePublisher()
    adapter = NautilusNotifierAdapter(publisher)

    asyncio.run(adapter.send("started", "startup"))

    assert publisher.calls == [("started", "startup")]
