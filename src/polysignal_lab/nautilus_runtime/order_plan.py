"""
Input: __future__, __future__.annotations, collections.abc, dataclasses, typing, polysignal_lab.alpha.types
Output: build_order_spec, OrderSubmissionPlan, resolve_order_intent, resolve_order_price, resolve_order_quantity, build_order_tags
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""


from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from polysignal_lab.alpha.types import AlphaDecision
from polysignal_lab.domain.enums import OrderIntent, Side


@dataclass(frozen=True, slots=True)
class OrderSubmissionPlan:
    """Nautilus OrderFactory parameter bundle — not a parallel domain Order."""

    instrument_id: str
    side: Side
    price: float
    quantity: float
    intent: OrderIntent
    expiry_seconds: int | None
    pair_id: str | None
    reduce_only: bool
    hedge_leg: bool
    max_entry_price: float | None
    tags: Mapping[str, str]


def build_order_spec(
    decision: AlphaDecision,
    *,
    fixed_stake_usdc: float,
    best_ask: float | None,
    best_bid: float | None = None,
    view_id: str = "",
) -> OrderSubmissionPlan:
    """Map AlphaDecision (+ book) to OrderFactory inputs. Single trading SoT path."""
    intent = resolve_order_intent(decision)
    expiry_seconds = decision.expiry_seconds
    pair_id = decision.pair_id
    reduce_only = decision.reduce_only
    price = resolve_order_price(
        decision,
        intent=intent,
        best_ask=best_ask,
        best_bid=best_bid,
        reduce_only=reduce_only,
    )
    quantity = resolve_order_quantity(
        decision,
        fixed_stake_usdc=fixed_stake_usdc,
        price=price,
    )
    return OrderSubmissionPlan(
        instrument_id=str(decision.token_id),
        side=decision.side,
        price=price,
        quantity=quantity,
        intent=intent,
        expiry_seconds=expiry_seconds,
        pair_id=pair_id,
        reduce_only=reduce_only,
        hedge_leg=decision.hedge_leg,
        max_entry_price=None if reduce_only else decision.max_entry_price,
        tags=build_order_tags(
            decision,
            intent=intent,
            expiry_seconds=expiry_seconds,
            view_id=view_id,
        ),
    )


def resolve_order_intent(decision: AlphaDecision) -> OrderIntent:
    return decision.resolved_intent


def explicit_order_intent(decision: AlphaDecision) -> OrderIntent | None:
    return decision.explicit_intent


def resolve_order_price(
    decision: AlphaDecision,
    *,
    intent: OrderIntent,
    best_ask: float | None,
    best_bid: float | None = None,
    reduce_only: bool = False,
) -> float:
    if reduce_only:
        if best_bid is None:
            raise ValueError(f"{intent.value} reduce-only close requires best bid depth")
        return positive_float(best_bid, "best_bid")
    max_price = positive_float(decision.max_entry_price, "max_entry_price")
    explicit_intent = explicit_order_intent(decision)
    if explicit_intent is None and best_ask is None:
        return max_price
    if explicit_intent is not None and intent not in {
        OrderIntent.TAKER_FAK,
        OrderIntent.TAKER_FOK,
        OrderIntent.TAKER_IOC,
    }:
        return max_price
    if best_ask is None:
        raise ValueError(f"{intent.value} requires best ask depth")
    price = positive_float(best_ask, "best_ask")
    if price > max_price:
        raise ValueError(f"best ask {price} exceeds max entry price {max_price}")
    return price


def resolve_order_quantity(
    decision: AlphaDecision,
    *,
    fixed_stake_usdc: float,
    price: float,
) -> float:
    if decision.quantity is not None:
        return positive_float(decision.quantity, "quantity")
    if decision.notional is not None:
        return positive_float(decision.notional, "notional") / price
    if decision.reduce_only:
        raise ValueError("reduce-only decision requires explicit quantity")
    return positive_float(fixed_stake_usdc, "fixed_stake_usdc") / price


def build_order_tags(
    decision: AlphaDecision,
    *,
    intent: OrderIntent,
    expiry_seconds: int | None,
    view_id: str = "",
) -> dict[str, str]:
    tags = _core_order_tags(decision, intent=intent, view_id=view_id)
    _add_optional_decision_tags(tags, decision)
    _add_exit_or_reduce_tags(tags, decision)
    if decision.pair_id is not None:
        tags["pair_id"] = decision.pair_id
    add_time_in_force_tags(
        tags, decision=decision, intent=intent, expiry_seconds=expiry_seconds
    )
    return tags


def _core_order_tags(
    decision: AlphaDecision,
    *,
    intent: OrderIntent,
    view_id: str,
) -> dict[str, str]:
    return {
        "signal_id": decision.signal_id(view_id),
        "strategy": str(decision.strategy),
        "asset": str(decision.asset),
        "timeframe": str(decision.timeframe),
        "market_id": str(decision.market_id),
        "market_slug": str(decision.market_slug),
        "condition_id": str(decision.condition_id),
        "token_id": str(decision.token_id),
        "side": decision.side.value,
        "confidence": str(decision.confidence),
        "entry_reference_price": str(decision.entry_reference_price),
        "max_entry_price": str(decision.max_entry_price),
        "order_intent": intent.value,
        "dedupe_key": decision.dedupe_key(),
    }


def _add_optional_decision_tags(tags: dict[str, str], decision: AlphaDecision) -> None:
    if decision.seconds_to_close is not None:
        tags["seconds_to_close"] = str(decision.seconds_to_close)
    if decision.data_freshness_ms is not None:
        tags["data_freshness_ms"] = str(decision.data_freshness_ms)
    if decision.reason_codes:
        tags["reason_codes"] = "|".join(str(code) for code in decision.reason_codes)
    if decision.hedge_leg:
        tags["hedge_leg"] = "true"


def _add_exit_or_reduce_tags(tags: dict[str, str], decision: AlphaDecision) -> None:
    if decision.reduce_only:
        tags["reduce_only"] = "true"
        metrics = cast(Mapping[str, object], decision.metrics)
        for key in (
            "position_id",
            "exit_reason",
            "entry_price",
            "position_quantity",
            "stake_usdc",
            "opened_at",
        ):
            value = metrics.get(key)
            if value is not None and str(value):
                tags[key] = str(value)
        return
    from polysignal_lab.nautilus_runtime.native_strategy_exit import (
        thresholds_from_metrics,
    )

    stamped = thresholds_from_metrics(decision.metrics)
    if stamped is None:
        return
    if stamped.take_profit_price is not None:
        tags["exit_tp_price"] = str(stamped.take_profit_price)
    if stamped.stop_loss_price is not None:
        tags["exit_stop_price"] = str(stamped.stop_loss_price)


def add_time_in_force_tags(
    tags: dict[str, str],
    *,
    decision: AlphaDecision,
    intent: OrderIntent,
    expiry_seconds: int | None,
) -> None:
    from polysignal_lab.nautilus_runtime.polymarket_adapter import PolymarketEnumParser

    tags["time_in_force"] = PolymarketEnumParser.to_nautilus_time_in_force(intent).name
    if intent == OrderIntent.PASSIVE_GTD:
        if expiry_seconds is not None:
            tags["expire_seconds"] = str(expiry_seconds)
        return
    if intent == OrderIntent.TAKER_FOK:
        return
    tags["fill_policy"] = "FAK" if intent == OrderIntent.TAKER_FAK else "IOC"
    if explicit_order_intent(decision) is None:
        tags["sandbox_safe_default"] = "true"


def positive_float(value: float, name: str) -> float:
    number = float(value)
    if number <= 0:
        raise ValueError(f"{name} must be positive")
    return number
