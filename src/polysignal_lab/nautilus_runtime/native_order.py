from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.nautilus_runtime.decision_policy import ApprovedDecision
from polysignal_lab.nautilus_runtime.order_mapping import order_spec_from_decision


def submit_approved_decision(
    strategy: Any,
    approved: ApprovedDecision,
    *,
    fixed_stake_usdc: float,
    best_ask: float | None,
    available_shares: float | None,
    instrument_id_resolver: Callable[[str], Any],
    now: Callable[[], datetime] | None = None,
) -> Any:
    """Create and submit a Nautilus-native order from an approved alpha decision."""

    spec = order_spec_from_decision(
        approved,
        fixed_stake_usdc=fixed_stake_usdc,
        best_ask=best_ask,
        available_shares=available_shares,
    )
    instrument_id = instrument_id_resolver(spec.instrument_id)
    order_side = _order_side(spec.side, reduce_only=spec.reduce_only)
    time_in_force = _time_in_force(spec.intent)
    expire_time = None
    if spec.intent == OrderIntent.PASSIVE_GTD:
        clock = now or (lambda: datetime.now(UTC))
        expire_time = clock() + timedelta(seconds=spec.expiry_seconds or 300)

    order = strategy.order_factory.limit(
        instrument_id=instrument_id,
        order_side=order_side,
        quantity=spec.quantity,
        price=spec.price,
        time_in_force=time_in_force,
        expire_time=expire_time,
        tags=[f"{key}={value}" for key, value in sorted(spec.tags.items())],
    )
    strategy.submit_order(order)
    return order


def _order_side(side: Side, *, reduce_only: bool) -> str:
    if reduce_only:
        return "SELL"
    if side in {Side.UP, Side.DOWN}:
        return "BUY"
    raise ValueError(f"unsupported side for Nautilus order: {side}")


def _time_in_force(intent: OrderIntent) -> str:
    if intent == OrderIntent.PASSIVE_GTD:
        return "GTD"
    if intent == OrderIntent.TAKER_FOK:
        return "FOK"
    return "IOC"
