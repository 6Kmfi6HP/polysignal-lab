from __future__ import annotations

from collections.abc import Mapping
from typing import SupportsFloat, cast

from polysignal_lab.alpha.types import AlphaDecision, NautilusOrderSpec, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.nautilus_runtime.decision_policy import ApprovedDecision


def order_spec_from_decision(
    decision: ApprovedDecision | AlphaDecision | SignalCandidate,
    fixed_stake_usdc: float,
    best_ask: float | None = None,
) -> NautilusOrderSpec:
    source = _decision_source(decision)
    max_price = _positive_float(source.max_entry_price, "max_entry_price")
    intent = _intent(source) or OrderIntent.TAKER_IOC
    expiry_seconds = _expiry_seconds(source)
    pair_id = _pair_id(source)
    metrics = dict(cast(Mapping[str, object], source.metrics))

    explicit_intent = _intent(source)
    if explicit_intent is None:
        if best_ask is None:
            price = max_price
        else:
            price = _positive_float(best_ask, "best_ask")
            if price > max_price:
                raise ValueError(f"best ask {price} exceeds max entry price {max_price}")
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
    if quantity <= 0:
        raise ValueError("quantity must be positive")

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
    signal_id = source.signal_id if isinstance(source, SignalCandidate) else None
    if signal_id is not None:
        tags["signal_id"] = str(signal_id)
    seconds_to_close = source.seconds_to_close
    if seconds_to_close is not None:
        tags["seconds_to_close"] = str(seconds_to_close)
    data_freshness_ms = source.data_freshness_ms
    if data_freshness_ms is not None:
        tags["data_freshness_ms"] = str(data_freshness_ms)
    reason_codes = source.reason_codes
    if reason_codes:
        tags["reason_codes"] = "|".join(str(code) for code in reason_codes)
    if source.hedge_leg:
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
        hedge_leg=source.hedge_leg,
        tags=tags,
    )


def _decision_source(
    decision: ApprovedDecision | AlphaDecision | SignalCandidate,
) -> AlphaDecision | SignalCandidate:
    if isinstance(decision, ApprovedDecision):
        return decision.signal
    return decision


def _intent(source: AlphaDecision | SignalCandidate) -> OrderIntent | None:
    raw = source.order_intent
    if raw is None:
        return None
    if isinstance(raw, OrderIntent):
        return raw
    return raw.intent


def _expiry_seconds(source: AlphaDecision | SignalCandidate) -> int | None:
    raw = source.order_intent
    if isinstance(raw, OrderIntentSpec):
        return raw.expiry_seconds
    if isinstance(source, SignalCandidate):
        return source.expiry_seconds
    return None


def _pair_id(source: AlphaDecision | SignalCandidate) -> str | None:
    raw = source.order_intent
    if isinstance(raw, OrderIntentSpec):
        return raw.pair_id
    if isinstance(source, SignalCandidate):
        return source.pair_id
    return None


def _positive_float(value: float, name: str) -> float:
    number = float(value)
    if number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def _metric_float(metrics: dict[str, object], *names: str) -> float | None:
    for name in names:
        value = metrics.get(name)
        if value is not None:
            return float(cast(SupportsFloat | str | bytes | bytearray, value))
    return None
