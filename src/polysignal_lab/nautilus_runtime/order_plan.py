"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Mapping, dataclasses, dataclasses.dataclass, typing, typing.SupportsFloat, typing.cast, polysignal_lab.alpha.types
Output: build_order_spec, source_reduce_only, resolve_order_intent, explicit_order_intent, resolve_order_price, resolve_order_quantity, build_order_tags, add_optional_source_tags, add_time_in_force_tags, expiry_seconds_for
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""









from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import SupportsFloat, cast

from polysignal_lab.alpha.types import AlphaDecision, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.domain.signal import SignalCandidate


@dataclass(frozen=True, slots=True)
class OrderSubmissionPlan:
    instrument_id: str
    side: Side
    price: float
    quantity: float
    intent: OrderIntent
    expiry_seconds: int | None
    pair_id: str | None
    reduce_only: bool
    hedge_leg: bool
    tags: Mapping[str, str]


def build_order_spec(
    source: AlphaDecision | SignalCandidate,
    *,
    fixed_stake_usdc: float,
    best_ask: float | None,
    best_bid: float | None = None,
) -> OrderSubmissionPlan:
    intent = resolve_order_intent(source)
    expiry_seconds = expiry_seconds_for(source)
    pair_id = pair_id_for(source)
    metrics = dict(cast(Mapping[str, object], source.metrics))
    reduce_only = source_reduce_only(source)
    price = resolve_order_price(
        source,
        intent=intent,
        best_ask=best_ask,
        best_bid=best_bid,
        reduce_only=reduce_only,
    )
    quantity = resolve_order_quantity(metrics, fixed_stake_usdc=fixed_stake_usdc, price=price)
    return OrderSubmissionPlan(
        instrument_id=str(source.token_id),
        side=source.side,
        price=price,
        quantity=quantity,
        intent=intent,
        expiry_seconds=expiry_seconds,
        pair_id=pair_id,
        reduce_only=reduce_only,
        hedge_leg=source.hedge_leg,
        tags=build_order_tags(source, intent=intent, expiry_seconds=expiry_seconds),
    )


def source_reduce_only(source: AlphaDecision | SignalCandidate) -> bool:
    return (
        source.reduce_only
        if isinstance(source, SignalCandidate)
        else bool(source.order_intent and source.order_intent.reduce_only)
    )


def resolve_order_intent(source: AlphaDecision | SignalCandidate) -> OrderIntent:
    raw = source.order_intent
    if raw is None:
        return OrderIntent.TAKER_IOC
    if isinstance(raw, OrderIntent):
        return raw
    return raw.intent


def explicit_order_intent(source: AlphaDecision | SignalCandidate) -> OrderIntent | None:
    raw = source.order_intent
    if raw is None:
        return None
    if isinstance(raw, OrderIntent):
        return raw
    return raw.intent


def resolve_order_price(
    source: AlphaDecision | SignalCandidate,
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
    max_price = positive_float(source.max_entry_price, "max_entry_price")
    explicit_intent = explicit_order_intent(source)
    if explicit_intent is None and best_ask is None:
        return max_price
    if explicit_intent is not None and intent not in {OrderIntent.TAKER_FAK, OrderIntent.TAKER_FOK, OrderIntent.TAKER_IOC}:
        return max_price
    if best_ask is None:
        raise ValueError(f"{intent.value} requires best ask depth")
    price = positive_float(best_ask, "best_ask")
    if price > max_price:
        raise ValueError(f"best ask {price} exceeds max entry price {max_price}")
    return price


def resolve_order_quantity(
    metrics: Mapping[str, object],
    *,
    fixed_stake_usdc: float,
    price: float,
) -> float:
    contracts = metric_float(metrics, "contracts")
    quantity = (
        positive_float(contracts, "contracts")
        if contracts is not None
        else positive_float(fixed_stake_usdc, "fixed_stake_usdc") / price
    )
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    return quantity


def build_order_tags(
    source: AlphaDecision | SignalCandidate,
    *,
    intent: OrderIntent,
    expiry_seconds: int | None,
) -> dict[str, str]:
    tags: dict[str, str] = {
        "strategy": str(source.strategy),
        "asset": str(source.asset),
        "timeframe": str(source.timeframe),
        "market_id": str(source.market_id),
        "market_slug": str(source.market_slug),
        "condition_id": str(source.condition_id),
        "confidence": str(source.confidence),
        "entry_reference_price": str(source.entry_reference_price),
        "max_entry_price": str(source.max_entry_price),
        "order_intent": intent.value,
    }
    add_optional_source_tags(tags, source)
    metrics = cast(Mapping[str, object], source.metrics)
    if source_reduce_only(source):
        for key in ("position_id", "exit_reason"):
            value = metrics.get(key)
            if value is not None and str(value):
                tags[key] = str(value)
    else:
        # Entry-time exit threshold stamps for NativeExitPolicy (per-position).
        from polysignal_lab.nautilus_runtime.native_strategy_exit import (
            thresholds_from_metrics,
        )

        stamped = thresholds_from_metrics(metrics)
        if stamped is not None:
            if stamped.take_profit_price is not None:
                tags["exit_tp_price"] = str(stamped.take_profit_price)
            if stamped.stop_loss_price is not None:
                tags["exit_stop_price"] = str(stamped.stop_loss_price)
    pair_id = pair_id_for(source)
    if pair_id is not None:
        tags["pair_id"] = pair_id
    add_time_in_force_tags(tags, source=source, intent=intent, expiry_seconds=expiry_seconds)
    return tags


def add_optional_source_tags(tags: dict[str, str], source: AlphaDecision | SignalCandidate) -> None:
    if isinstance(source, SignalCandidate):
        tags["signal_id"] = str(source.signal_id)
        tags["dedupe_key"] = source.dedupe_key
    if source.seconds_to_close is not None:
        tags["seconds_to_close"] = str(source.seconds_to_close)
    if source.data_freshness_ms is not None:
        tags["data_freshness_ms"] = str(source.data_freshness_ms)
    if source.reason_codes:
        tags["reason_codes"] = "|".join(str(code) for code in source.reason_codes)
    if source.hedge_leg:
        tags["hedge_leg"] = "true"
    if source_reduce_only(source):
        tags["reduce_only"] = "true"


def add_time_in_force_tags(
    tags: dict[str, str],
    *,
    source: AlphaDecision | SignalCandidate,
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
    if explicit_order_intent(source) is None:
        tags["sandbox_safe_default"] = "true"


def expiry_seconds_for(source: AlphaDecision | SignalCandidate) -> int | None:
    raw = source.order_intent
    if isinstance(raw, OrderIntentSpec):
        return raw.expiry_seconds
    if isinstance(source, SignalCandidate):
        return source.expiry_seconds
    return None


def pair_id_for(source: AlphaDecision | SignalCandidate) -> str | None:
    raw = source.order_intent
    if isinstance(raw, OrderIntentSpec):
        return raw.pair_id
    if isinstance(source, SignalCandidate):
        return source.pair_id
    return None


def positive_float(value: float, name: str) -> float:
    number = float(value)
    if number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def metric_float(metrics: Mapping[str, object], *names: str) -> float | None:
    for name in names:
        value = metrics.get(name)
        if value is not None:
            return float(cast(SupportsFloat | str | bytes | bytearray, value))
    return None
