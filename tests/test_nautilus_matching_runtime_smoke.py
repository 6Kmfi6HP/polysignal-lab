from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from polysignal_lab.app import scheduler_market_data
from polysignal_lab.domain.enums import OrderStatus, Side
from polysignal_lab.domain.paper_order import PaperFill, PaperOrder
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.nautilus_runtime.execution_types import PaperExecutionResult
from polysignal_lab.nautilus_runtime.observability import NautilusEventStoreAdapter, ObservabilityActor
from polysignal_lab.nautilus_runtime.orchestrator import NautilusOrchestrator
from polysignal_lab.observability.health import HealthRegistry


class RecordingStore:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, object]]] = {}
        self.logs: list[tuple[str, dict[str, object]]] = []

    def insert_json(self, table: str, data: dict[str, object]) -> None:
        self.rows.setdefault(table, []).append(dict(data))

    def insert_many_json(self, table: str, rows: list[dict[str, object]]) -> None:
        for row in rows:
            self.insert_json(table, row)

    def insert_signal(self, payload: dict[str, object]) -> None:
        self.insert_json("signals", payload)

    def insert_rejected_signal(self, payload: dict[str, object]) -> None:
        self.insert_json("rejected_signals", payload)

    def upsert_paper_order(self, payload: dict[str, object]) -> None:
        self.insert_json("paper_orders", payload)

    def insert_paper_fill(self, payload: dict[str, object]) -> None:
        self.insert_json("paper_fills", payload)

    def upsert_paper_position(self, payload: dict[str, object]) -> None:
        self.insert_json("paper_positions", payload)

    def insert_paper_trade_result(self, payload: dict[str, object]) -> None:
        self.insert_json("paper_trade_results", payload)

    def insert_system_event(self, payload: dict[str, object]) -> None:
        self.insert_json("system_events", payload)

    def append_log(self, stream: str, payload: dict[str, object]) -> None:
        self.logs.append((stream, dict(payload)))


class FakeMatchingClient:
    paper_engine = "nautilus_matching"
    accuracy_mode = "depth_l2"

    def __init__(self, result: PaperExecutionResult) -> None:
        self._pending = [result]
        self.wallet = SimpleNamespace(open_positions={})

    def drain_events(self) -> list[PaperExecutionResult]:
        pending = self._pending
        self._pending = []
        return pending

    def process_resting_orders(self) -> list[PaperExecutionResult]:
        return []


class FakeScheduler:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(
            telegram=SimpleNamespace(send_signals=False),
            paper_trading=SimpleNamespace(fixed_stake_usdc=10.0),
        )
        self.publish_service = SimpleNamespace()
        self.settlement_calls = 0
        self.daily_report_calls = 0
        self.paper_execution_metadata: dict[str, str] = {}

    async def check_settlements(self) -> list[object]:
        self.settlement_calls += 1
        return []

    async def generate_daily_report(self) -> None:
        self.daily_report_calls += 1


class FakeDataIngestor:
    def sync_all(self) -> tuple[str, ...]:
        return ()


async def test_run_once_records_matching_order_fill_and_position_metadata(monkeypatch) -> None:
    async def refresh_markets_once(_scheduler: object) -> None:
        return None

    monkeypatch.setattr(scheduler_market_data, "refresh_markets_once", refresh_markets_once)
    metadata = {
        "paper_engine": "nautilus_matching",
        "accuracy_mode": "depth_l2",
        "condition_id": "condition-btc-5m",
        "confidence": "0.82",
        "entry_reference_price": "0.41",
        "max_entry_price": "0.42",
    }
    order = PaperOrder(
        paper_order_id="order-1",
        signal_id="signal-1",
        asset="BTC",
        timeframe="5m",
        strategy="late_consensus",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        token_id="up-token",
        side=Side.UP,
        limit_price=0.42,
        reference_price=0.41,
        stake_usdc=10.0,
        shares=25.0,
        signal_confidence=0.82,
        metrics=dict(metadata),
        status=OrderStatus.FILLED,
    )
    fill = PaperFill(
        paper_fill_id="fill-1",
        paper_order_id=order.paper_order_id,
        signal_id=order.signal_id,
        token_id=order.token_id,
        side=order.side,
        raw_best_ask=0.41,
        slippage_bps=0.0,
        fill_price=0.41,
        stake_usdc=10.0,
        shares=25.0,
        depth_checked=True,
        available_depth_usdc=500.0,
        metrics=dict(metadata),
    )
    position = PaperPosition(
        paper_position_id="position-1",
        signal_id=order.signal_id,
        paper_order_id=order.paper_order_id,
        paper_fill_id=fill.paper_fill_id,
        strategy=order.strategy,
        asset=order.asset,
        timeframe=order.timeframe,
        market_id=order.market_id,
        market_slug=order.market_slug,
        token_id=order.token_id,
        side=order.side,
        entry_price=fill.fill_price,
        shares=fill.shares,
        stake_usdc=fill.stake_usdc,
        signal_confidence=order.signal_confidence,
        signal_metrics=dict(metadata),
    )
    result = PaperExecutionResult(
        order=order,
        fills=[fill],
        positions=[position],
        status=OrderStatus.FILLED,
    )
    store = RecordingStore()
    health = HealthRegistry()
    scheduler = FakeScheduler()
    orchestrator = NautilusOrchestrator(
        scheduler=scheduler,  # type: ignore[arg-type]
        registered_strategies=[],
        data_ingestor=FakeDataIngestor(),  # type: ignore[arg-type]
        book_data_provider=SimpleNamespace(snapshot_for_token=lambda _token_id: None),
        paper_client=FakeMatchingClient(result),  # type: ignore[arg-type]
        position_policy=SimpleNamespace(evaluate=lambda *_args, **_kwargs: None),
        settlement_actor=SimpleNamespace(),
        observability=ObservabilityActor(store=NautilusEventStoreAdapter(store), health=health),
        health=health,
        refresh_interval_sec=0.01,
    )

    await orchestrator.run_once()

    assert scheduler.settlement_calls == 1
    assert scheduler.daily_report_calls == 1
    assert scheduler.paper_execution_metadata == {
        "paper_engine": "nautilus_matching",
        "accuracy_mode": "depth_l2",
    }
    assert store.rows["paper_orders"][0]["metrics"]["paper_engine"] == "nautilus_matching"
    assert store.rows["paper_orders"][0]["metrics"]["accuracy_mode"] == "depth_l2"
    assert store.rows["paper_fills"][0]["metrics"]["paper_engine"] == "nautilus_matching"
    assert store.rows["paper_fills"][0]["metrics"]["accuracy_mode"] == "depth_l2"
    assert store.rows["paper_positions"][0]["signal_metrics"]["paper_engine"] == "nautilus_matching"
    assert store.rows["paper_positions"][0]["signal_metrics"]["accuracy_mode"] == "depth_l2"
    assert [stream for stream, _ in store.logs] == [
        "signals",
        "paper_orders",
        "paper_fills",
        "paper_positions",
        "system_events",
    ]
    assert store.logs[1][1]["metrics"]["paper_engine"] == "nautilus_matching"
    assert store.logs[2][1]["metrics"]["accuracy_mode"] == "depth_l2"
    assert store.logs[3][1]["signal_metrics"]["paper_engine"] == "nautilus_matching"
