from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace

from polysignal_lab.alpha.types import AlphaDecision, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import ApprovedDecision
from polysignal_lab.nautilus_runtime.native_order import submit_approved_decision


@dataclass(slots=True)
class FakeOrder:
    instrument_id: str
    order_side: str
    quantity: float
    price: float
    time_in_force: str
    expire_time: object | None
    tags: list[str]


class FakeOrderFactory:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def limit(self, **kwargs):
        self.calls.append(kwargs)
        return FakeOrder(**kwargs)


class FakeStrategy:
    def __init__(self) -> None:
        self.order_factory = FakeOrderFactory()
        self.submitted: list[FakeOrder] = []

    def submit_order(self, order: FakeOrder) -> None:
        self.submitted.append(order)


def _approved(intent: OrderIntent = OrderIntent.TAKER_IOC) -> ApprovedDecision:
    signal = SignalCandidate.build(
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        token_id="up-token",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.50,
        max_entry_price=0.52,
        seconds_to_close=60,
        data_freshness_ms=20,
        reason_codes=["TEST"],
        metrics={},
        order_intent=intent,
        expiry_seconds=45 if intent == OrderIntent.PASSIVE_GTD else None,
        pair_id="pair-1",
        hedge_leg=False,
    )
    return ApprovedDecision(signal=signal)


def test_submit_approved_decision_submits_limit_order_through_strategy() -> None:
    strategy = FakeStrategy()

    order = submit_approved_decision(
        strategy,
        _approved(OrderIntent.TAKER_IOC),
        fixed_stake_usdc=10.0,
        best_ask=0.50,
        available_shares=100.0,
        instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
    )

    assert order is strategy.submitted[0]
    assert order.instrument_id == "up-token.POLYMARKET"
    assert order.order_side == "BUY"
    assert order.quantity == 20.0
    assert order.price == 0.50
    assert order.time_in_force == "IOC"
    assert order.expire_time is None
    assert "strategy=ptb_diff" in order.tags
    assert "condition_id=condition-btc-5m" in order.tags


def test_submit_approved_decision_maps_passive_gtd_expiry() -> None:
    strategy = FakeStrategy()

    order = submit_approved_decision(
        strategy,
        _approved(OrderIntent.PASSIVE_GTD),
        fixed_stake_usdc=10.0,
        best_ask=0.50,
        available_shares=100.0,
        instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
        now=lambda: datetime(2026, 6, 27, tzinfo=UTC),
    )

    assert order.time_in_force == "GTD"
    assert order.expire_time == datetime(2026, 6, 27, 0, 0, 45, tzinfo=UTC)


def test_submit_approved_decision_fok_rejects_insufficient_depth_before_submit() -> None:
    strategy = FakeStrategy()

    try:
        submit_approved_decision(
            strategy,
            _approved(OrderIntent.TAKER_FOK),
            fixed_stake_usdc=10.0,
            best_ask=0.50,
            available_shares=1.0,
            instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
        )
    except ValueError as exc:
        assert "insufficient depth" in str(exc)
    else:
        raise AssertionError("expected insufficient depth rejection")

    assert strategy.submitted == []
