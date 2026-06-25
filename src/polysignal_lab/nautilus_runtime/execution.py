from __future__ import annotations

from typing import Any

from polysignal_lab.alpha.types import AlphaDecision, NautilusOrderSpec
from polysignal_lab.domain.enums import OrderIntent
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import ApprovedDecision


def order_spec_from_decision(
    decision: ApprovedDecision | AlphaDecision | SignalCandidate,
    fixed_stake_usdc: float,
    best_ask: float | None = None,
    available_shares: float | None = None,
) -> NautilusOrderSpec:
    source = _decision_source(decision)
    max_price = _positive_float(source.max_entry_price, "max_entry_price")
    intent = _intent(source) or OrderIntent.TAKER_IOC
    expiry_seconds = _expiry_seconds(source)
    pair_id = _pair_id(source)
    metrics = dict(getattr(source, "metrics", {}) or {})
    if available_shares is None:
        available_shares = _metric_float(
            metrics, "available_ask_shares", "ask_available_shares", "depth_shares"
        )

    explicit_intent = _intent(source)
    if explicit_intent is None:
        price = max_price
    elif intent in {
        OrderIntent.TAKER_FAK,
        OrderIntent.TAKER_FOK,
        OrderIntent.TAKER_IOC,
    }:
        if best_ask is None:
            raise ValueError(f"{intent.value} requires best ask depth")
        price = _positive_float(best_ask, "best_ask")
        if price > max_price:
            raise ValueError(f"best ask {price} exceeds max entry price {max_price}")
    else:
        price = max_price

    contracts = _metric_float(metrics, "contracts")
    quantity = (
        _positive_float(contracts, "contracts")
        if contracts is not None
        else _positive_float(fixed_stake_usdc, "fixed_stake_usdc") / price
    )
    if intent == OrderIntent.TAKER_FOK:
        if available_shares is None or available_shares < quantity:
            raise ValueError("insufficient depth for full fill")
    elif available_shares is not None and available_shares <= 0:
        raise ValueError("insufficient depth for taker order")

    tags: dict[str, str] = {
        "strategy": str(source.strategy),
        "order_intent": intent.value,
    }
    signal_id = getattr(source, "signal_id", None)
    if signal_id is not None:
        tags["signal_id"] = str(signal_id)
    if bool(getattr(source, "hedge_leg", False)):
        tags["hedge_leg"] = "true"
    if intent == OrderIntent.PASSIVE_GTD:
        tags["time_in_force"] = "GTD"
        if expiry_seconds is not None:
            tags["expire_seconds"] = str(expiry_seconds)
    elif intent == OrderIntent.TAKER_FOK:
        tags["time_in_force"] = "FOK"
    else:
        tags["time_in_force"] = "IOC"
        tags["fill_policy"] = "FAK" if intent == OrderIntent.TAKER_FAK else "IOC"
        if _intent(source) is None:
            tags["paper_safe_default"] = "true"

    return NautilusOrderSpec(
        instrument_id=str(source.token_id),
        side=source.side,
        price=price,
        quantity=quantity,
        intent=intent,
        expiry_seconds=expiry_seconds,
        pair_id=pair_id,
        reduce_only=False,
        hedge_leg=bool(getattr(source, "hedge_leg", False)),
        tags=tags,
    )


def _decision_source(
    decision: ApprovedDecision | AlphaDecision | SignalCandidate,
) -> AlphaDecision | SignalCandidate:
    if isinstance(decision, ApprovedDecision):
        return decision.signal
    return decision


def _intent(source: AlphaDecision | SignalCandidate) -> OrderIntent | None:
    raw = getattr(source, "order_intent", None)
    if raw is None:
        return None
    if isinstance(raw, OrderIntent):
        return raw
    value = getattr(raw, "intent", raw)
    return value if isinstance(value, OrderIntent) else OrderIntent(value)


def _expiry_seconds(source: AlphaDecision | SignalCandidate) -> int | None:
    raw = getattr(source, "order_intent", None)
    value = getattr(raw, "expiry_seconds", None)
    if value is None and (raw is None or isinstance(raw, OrderIntent)):
        value = getattr(source, "expiry_seconds", None)
    return int(value) if value is not None else None


def _pair_id(source: AlphaDecision | SignalCandidate) -> str | None:
    raw = getattr(source, "order_intent", None)
    value = getattr(raw, "pair_id", None)
    if value is None and (raw is None or isinstance(raw, OrderIntent)):
        value = getattr(source, "pair_id", None)
    return str(value) if value is not None else None


def _positive_float(value: float, name: str) -> float:
    number = float(value)
    if number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def _metric_float(metrics: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = metrics.get(name)
        if value is not None:
            return float(value)
    return None
