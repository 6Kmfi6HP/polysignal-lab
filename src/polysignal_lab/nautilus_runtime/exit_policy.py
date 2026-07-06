from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from polysignal_lab.alpha.types import SideBookView
from polysignal_lab.utils import parse_dt


class ExitReason(StrEnum):
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    MAX_HOLD_TIME = "max_hold_time"


@dataclass(frozen=True, slots=True)
class ExitPolicyConfig:
    mode: str
    take_profit_enabled: bool
    stop_loss_enabled: bool
    take_profit_price: float
    stop_loss_price: float
    max_hold_time_sec: int


@dataclass(frozen=True, slots=True)
class NautilusExitDecision:
    reason: ExitReason
    position_id: str
    instrument_id: str
    quantity: float
    limit_price: float
    ts_event: datetime


@dataclass(frozen=True, slots=True)
class TaggedBracketOrder:
    order_type: str
    position_id: str
    instrument_id: str
    quantity: float
    price: float
    trigger_price: float | None
    ts_event: datetime


def evaluate_exit_decision(
    position: Mapping[str, object],
    book: SideBookView,
    now: datetime,
    config: ExitPolicyConfig,
) -> NautilusExitDecision | None:
    if bool(position.get("is_closed")):
        return None
    best_bid = book.best_bid
    if best_bid is None or best_bid <= 0:
        return None
    entry_price = _float(position.get("avg_entry_price"))
    quantity = abs(_float(position.get("quantity")))
    instrument_id = str(position.get("instrument_id") or "")
    position_id = str(position.get("position_id") or position.get("paper_position_id") or "")
    if entry_price <= 0 or quantity <= 0 or not instrument_id or not position_id:
        return None
    if config.take_profit_enabled and best_bid >= config.take_profit_price:
        return _decision(ExitReason.TAKE_PROFIT, position_id, instrument_id, quantity, best_bid, now)
    if config.stop_loss_enabled and best_bid <= config.stop_loss_price:
        return _decision(ExitReason.STOP_LOSS, position_id, instrument_id, quantity, best_bid, now)
    opened_at = _opened_at(position)
    if opened_at is not None and (now - opened_at).total_seconds() >= config.max_hold_time_sec:
        return _decision(ExitReason.MAX_HOLD_TIME, position_id, instrument_id, quantity, best_bid, now)
    return None


def bracket_attachments_for(
    position: Mapping[str, object],
    book: SideBookView,
    now: datetime,
    config: ExitPolicyConfig,
) -> list[TaggedBracketOrder]:
    if bool(position.get("is_closed")):
        return []
    best_bid = book.best_bid
    if best_bid is None or best_bid <= 0:
        return []
    entry_price = _float(position.get("avg_entry_price"))
    quantity = abs(_float(position.get("quantity")))
    instrument_id = str(position.get("instrument_id") or "")
    position_id = str(position.get("position_id") or position.get("paper_position_id") or "")
    if entry_price <= 0 or quantity <= 0 or not instrument_id or not position_id:
        return []

    result: list[TaggedBracketOrder] = []
    now_utc = now.astimezone(UTC)

    if config.take_profit_enabled and best_bid >= config.take_profit_price:
        result.append(TaggedBracketOrder(
            order_type="TAKE_PROFIT",
            position_id=position_id,
            instrument_id=instrument_id,
            quantity=quantity,
            price=config.take_profit_price,
            trigger_price=None,
            ts_event=now_utc,
        ))
    if config.stop_loss_enabled and best_bid <= config.stop_loss_price:
        result.append(TaggedBracketOrder(
            order_type="STOP_LIMIT",
            position_id=position_id,
            instrument_id=instrument_id,
            quantity=quantity,
            price=config.stop_loss_price,
            trigger_price=config.stop_loss_price,
            ts_event=now_utc,
        ))
    return result


def _decision(
    reason: ExitReason,
    position_id: str,
    instrument_id: str,
    quantity: float,
    limit_price: float,
    now: datetime,
) -> NautilusExitDecision:
    return NautilusExitDecision(
        reason=reason,
        position_id=position_id,
        instrument_id=instrument_id,
        quantity=quantity,
        limit_price=limit_price,
        ts_event=now.astimezone(UTC),
    )


def _opened_at(position: Mapping[str, object]) -> datetime | None:
    value = position.get("opened_at") or position.get("ts")
    parsed = parse_dt(value)
    if parsed is None:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _float(value: object) -> float:
    if not isinstance(value, (int, float, str)):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
