"""
Input: __future__, datetime, pytest
Output: issue #16 readiness recovery and health regression tests
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from polysignal_lab.domain.enums import Side
from polysignal_lab.observability.runtime_health import (
    evaluate_liveness,
    read_runtime_heartbeat,
    write_runtime_heartbeat,
)


def _dt(second: int) -> datetime:
    return datetime(2026, 7, 14, 6, 0, 0, tzinfo=UTC) + timedelta(seconds=second)


def test_liveness_fails_for_persistent_readiness_miss(tmp_path: Path) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    write_runtime_heartbeat(path, phase="readiness_miss", now=_dt(0))
    # Keep heartbeat fresh while readiness_miss phase remains long-lived.
    write_runtime_heartbeat(path, phase="readiness_miss", now=_dt(290))

    result = evaluate_liveness(
        path,
        max_age_sec=120,
        max_readiness_miss_sec=300,
        now=_dt(301),
    )

    assert result.ok is False
    assert result.reason == "readiness_miss"
    heartbeat = read_runtime_heartbeat(path)
    assert heartbeat.phase == "readiness_miss"
    assert heartbeat.phase_started_at is not None


def test_liveness_allows_brief_readiness_miss(tmp_path: Path) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    write_runtime_heartbeat(path, phase="readiness_miss", now=_dt(0))

    result = evaluate_liveness(
        path,
        max_age_sec=120,
        max_readiness_miss_sec=300,
        now=_dt(30),
    )

    assert result.ok is True


def test_phase_started_at_resets_when_phase_changes(tmp_path: Path) -> None:
    path = tmp_path / "runtime_heartbeat.json"
    write_runtime_heartbeat(path, phase="readiness_miss", now=_dt(0))
    first = read_runtime_heartbeat(path)
    write_runtime_heartbeat(path, phase="running", now=_dt(10))
    second = read_runtime_heartbeat(path)
    write_runtime_heartbeat(path, phase="readiness_miss", now=_dt(20))
    third = read_runtime_heartbeat(path)

    assert first.phase_started_at == first.updated_at
    assert second.phase == "running"
    assert second.phase_started_at == second.updated_at
    assert third.phase == "readiness_miss"
    assert third.phase_started_at == third.updated_at
    assert third.phase_started_at != first.phase_started_at


def test_refresh_stale_market_subscription_clears_wire_and_resubscribes() -> None:
    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketCatalog,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_runtime.strategy.subscriptions import (
        MarketSubscriptionState,
        refresh_stale_market_subscription,
        subscribe_market_conditions,
    )

    class FakeStrategy:
        def __init__(self) -> None:
            self.registry = MarketCatalog()
            self.book_type = "L2_MBP"
            self._startup_condition_ids: tuple[str, ...] = ()
            self._active_condition_ids = {"condition-a"}
            self._subscription_state = MarketSubscriptionState()
            self._asset_condition_ids: dict[str, tuple[str, ...]] = {}
            self.book_subs: list[str] = []
            self.quote_subs: list[str] = []
            self.trade_subs: list[str] = []
            self.book_unsubs: list[str] = []
            self.quote_unsubs: list[str] = []
            self.trade_unsubs: list[str] = []
            self.requests: list[str] = []

        def request_instrument(self, instrument_id: object) -> None:
            self.requests.append(str(instrument_id))

        def subscribe_quote_ticks(self, instrument_id: object) -> None:
            self.quote_subs.append(str(instrument_id))

        def subscribe_trade_ticks(self, instrument_id: object) -> None:
            self.trade_subs.append(str(instrument_id))

        def subscribe_order_book_deltas(self, instrument_id: object, *, book_type: object) -> None:
            _ = book_type
            self.book_subs.append(str(instrument_id))

        def unsubscribe_quote_ticks(self, instrument_id: object) -> None:
            self.quote_unsubs.append(str(instrument_id))

        def unsubscribe_trade_ticks(self, instrument_id: object) -> None:
            self.trade_unsubs.append(str(instrument_id))

        def unsubscribe_order_book_deltas(self, instrument_id: object) -> None:
            self.book_unsubs.append(str(instrument_id))

    strategy = FakeStrategy()
    strategy.registry.register(
        MarketPairMeta(
            market_id="m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )
    subscribe_market_conditions(strategy, ("condition-a",))
    assert strategy._subscription_state.wire_condition_ids == {"condition-a"}
    first_book = list(strategy.book_subs)

    refreshed = refresh_stale_market_subscription(
        strategy,
        "condition-a",
        now=_dt(0),
        min_interval_sec=30,
    )
    assert refreshed is True
    assert strategy.book_unsubs
    assert len(strategy.book_subs) > len(first_book)
    assert strategy._subscription_state.wire_condition_ids == {"condition-a"}

    # Throttle: immediate second refresh is a no-op.
    book_count = len(strategy.book_subs)
    refreshed_again = refresh_stale_market_subscription(
        strategy,
        "condition-a",
        now=_dt(10),
        min_interval_sec=30,
    )
    assert refreshed_again is False
    assert len(strategy.book_subs) == book_count


def test_record_rejected_stale_orderbook_triggers_subscription_refresh() -> None:
    from polysignal_lab.nautilus_runtime.decision_policy import RejectedDecision
    from polysignal_lab.nautilus_runtime.strategy.observability_hooks import record_rejected
    from polysignal_lab.domain.signal import SignalCandidate

    calls: list[str] = []

    class Strategy:
        observability = None
        fixed_stake_usdc = 1.0

        def _note_runtime_progress(self, phase: str) -> None:
            _ = phase

        def refresh_stale_market_subscription(self, condition_id: str) -> bool:
            calls.append(condition_id)
            return True

    candidate = SignalCandidate.build(
        strategy="late_consensus",
        asset="BTC",
        timeframe="5m",
        market_id="1",
        market_slug="btc-updown-5m",
        condition_id="condition-a",
        token_id="up-a",
        side=Side.UP,
        confidence=0.7,
        entry_reference_price=0.5,
        max_entry_price=0.9,
        seconds_to_close=60,
        data_freshness_ms=200_000,
        reason_codes=["EDGE"],
        metrics={},
        created_at=_dt(0),
        snapshot_id="view-1",
    )
    rejected = RejectedDecision(
        reason_code="STALE_ORDERBOOK",
        detail={"lag_ms": 200_000, "source": "orderbook"},
        candidate=candidate,
    )
    record_rejected(Strategy(), rejected)
    assert calls == ["condition-a"]
