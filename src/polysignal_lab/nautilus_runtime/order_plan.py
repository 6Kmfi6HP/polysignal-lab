"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Mapping, typing, typing.SupportsFloat, typing.cast, polysignal_lab.alpha.types, polysignal_lab.alpha.types.AlphaDecision, polysignal_lab.alpha.types.NautilusOrderSpec
Output: build_order_spec, resolve_order_intent, explicit_order_intent, resolve_order_price, resolve_order_quantity, build_order_tags, add_optional_source_tags, add_time_in_force_tags, expiry_seconds_for, pair_id_for
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

from collections.abc import Mapping
from typing import SupportsFloat, cast

from polysignal_lab.alpha.types import AlphaDecision, NautilusOrderSpec, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_bridge.enum_parser import PolymarketEnumParser


def build_order_spec(
    source: AlphaDecision | SignalCandidate,
    *,
    fixed_stake_usdc: float,
    best_ask: float | None,
) -> NautilusOrderSpec:
    intent = resolve_order_intent(source)
    expiry_seconds = expiry_seconds_for(source)
    pair_id = pair_id_for(source)
    metrics = dict(cast(Mapping[str, object], source.metrics))
    price = resolve_order_price(source, intent=intent, best_ask=best_ask)
    quantity = resolve_order_quantity(metrics, fixed_stake_usdc=fixed_stake_usdc, price=price)
    return NautilusOrderSpec(
        instrument_id=str(source.token_id),
        side=source.side,
        price=price,
        quantity=quantity,
        intent=intent,
        expiry_seconds=expiry_seconds,
        pair_id=pair_id,
        reduce_only=False,
        hedge_leg=source.hedge_leg,
        tags=build_order_tags(source, intent=intent, expiry_seconds=expiry_seconds),
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
) -> float:
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
    add_time_in_force_tags(tags, source=source, intent=intent, expiry_seconds=expiry_seconds)
    return tags


def add_optional_source_tags(tags: dict[str, str], source: AlphaDecision | SignalCandidate) -> None:
    signal_id = source.signal_id if isinstance(source, SignalCandidate) else None
    if signal_id is not None:
        tags["signal_id"] = str(signal_id)
    if source.seconds_to_close is not None:
        tags["seconds_to_close"] = str(source.seconds_to_close)
    if source.data_freshness_ms is not None:
        tags["data_freshness_ms"] = str(source.data_freshness_ms)
    if source.reason_codes:
        tags["reason_codes"] = "|".join(str(code) for code in source.reason_codes)
    if source.hedge_leg:
        tags["hedge_leg"] = "true"


def add_time_in_force_tags(
    tags: dict[str, str],
    *,
    source: AlphaDecision | SignalCandidate,
    intent: OrderIntent,
    expiry_seconds: int | None,
) -> None:
    tags["time_in_force"] = PolymarketEnumParser.to_nautilus_time_in_force(intent).name
    if intent == OrderIntent.PASSIVE_GTD:
        if expiry_seconds is not None:
            tags["expire_seconds"] = str(expiry_seconds)
        return
    if intent == OrderIntent.TAKER_FOK:
        return
    tags["fill_policy"] = "FAK" if intent == OrderIntent.TAKER_FAK else "IOC"
    if explicit_order_intent(source) is None:
        tags["paper_safe_default"] = "true"


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
