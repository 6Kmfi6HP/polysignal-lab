"""
Input: __future__, dataclasses, types, pytest, polysignal_lab.nautilus_runtime.paper_risk
Output: test_paper_risk_rejects_disabled_runtime, test_paper_risk_enforces_open_position_limit, test_paper_risk_enforces_strategy_exposure, test_paper_risk_enforces_market_exposure, test_paper_risk_allows_reduce_only
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.nautilus_runtime.order_plan import OrderSubmissionPlan
from polysignal_lab.nautilus_runtime.paper_risk import PaperRiskGate


@dataclass
class Position:
    instrument_id: str
    signed_qty: float
    avg_px_open: float


@dataclass
class Order:
    instrument_id: str
    quantity: float
    price: float
    reduce_only: bool = False


class Cache:
    def __init__(
        self,
        positions: list[Position],
        orders: list[Order] | None = None,
    ) -> None:
        self.positions = positions
        self.orders = orders or []

    def positions_open(self, *, strategy_id: object | None = None) -> list[Position]:
        _ = strategy_id
        return list(self.positions)

    def orders_open(self, *, strategy_id: object | None = None) -> list[Order]:
        _ = strategy_id
        return list(self.orders)


def _spec(*, market_id: str = "market-1", reduce_only: bool = False) -> OrderSubmissionPlan:
    return OrderSubmissionPlan(
        instrument_id="token-new",
        side=Side.UP,
        price=0.50,
        quantity=10.0,
        intent=OrderIntent.TAKER_IOC,
        expiry_seconds=None,
        pair_id=None,
        reduce_only=reduce_only,
        hedge_leg=False,
        tags={"market_id": market_id},
    )


def _strategy(cache: Cache) -> object:
    return SimpleNamespace(id="strategy-1", cache=cache)


def _gate(**kwargs: object) -> PaperRiskGate:
    values: dict[str, object] = {
        "enabled": True,
        "max_open_positions": 10,
        "max_market_exposure_usdc": 30.0,
        "max_strategy_exposure_usdc": 100.0,
        "market_id_for_instrument": lambda instrument_id: {
            "token-old": "market-1",
            "token-other": "market-2",
        }.get(instrument_id),
    }
    values.update(kwargs)
    return PaperRiskGate(**values)


def test_paper_risk_rejects_disabled_runtime() -> None:
    gate = PaperRiskGate(
        enabled=False,
        max_open_positions=10,
        max_market_exposure_usdc=30.0,
        max_strategy_exposure_usdc=100.0,
        market_id_for_instrument=lambda _instrument_id: "market-1",
    )

    with pytest.raises(ValueError, match="PAPER_TRADING_DISABLED"):
        gate.validate(_strategy(Cache([])), _spec(), market_id="market-1")


def test_paper_risk_enforces_open_position_limit() -> None:
    positions = [Position(f"token-{index}", 1.0, 0.5) for index in range(2)]
    gate = _gate(max_open_positions=2)

    with pytest.raises(ValueError, match="MAX_OPEN_POSITIONS"):
        gate.validate(_strategy(Cache(positions)), _spec(), market_id="market-1")


def test_paper_risk_enforces_strategy_exposure() -> None:
    gate = _gate(max_strategy_exposure_usdc=5.0)
    cache = Cache([Position("token-old", 10.0, 0.5)])

    with pytest.raises(ValueError, match="MAX_STRATEGY_EXPOSURE"):
        gate.validate(_strategy(cache), _spec(), market_id="market-1")


def test_paper_risk_enforces_market_exposure() -> None:
    gate = _gate(max_market_exposure_usdc=5.0)
    cache = Cache([Position("token-old", 10.0, 0.5)])

    with pytest.raises(ValueError, match="MAX_MARKET_EXPOSURE"):
        gate.validate(_strategy(cache), _spec(), market_id="market-1")


def test_paper_risk_allows_reduce_only() -> None:
    gate = _gate(max_open_positions=0, max_market_exposure_usdc=0.0, max_strategy_exposure_usdc=0.0)

    gate.validate(
        _strategy(Cache([])),
        _spec(reduce_only=True),
        market_id="market-1",
    )


def test_paper_risk_reservation_blocks_until_lifecycle_release() -> None:
    gate = _gate(max_market_exposure_usdc=5.0)
    strategy = _strategy(Cache([]))

    reservation_id = gate.validate(strategy, _spec(), market_id="market-1")

    assert reservation_id is not None
    with pytest.raises(ValueError, match="MAX_MARKET_EXPOSURE"):
        gate.validate(strategy, _spec(), market_id="market-1")

    gate.release_from_event(SimpleNamespace(tags=[f"reservation_id={reservation_id}"]))
    assert gate.validate(strategy, _spec(), market_id="market-1") is not None
