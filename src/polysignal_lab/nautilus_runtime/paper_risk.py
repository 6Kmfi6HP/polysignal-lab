"""
Input: __future__, collections.abc, dataclasses, math, threading, typing, uuid, polysignal_lab.nautilus_runtime.order_plan
Output: PaperReservationBook, PaperRiskGate
Pos: Native paper-trading risk boundary

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
import math
from threading import Lock
from typing import cast
from uuid import uuid4

from polysignal_lab.nautilus_runtime.order_plan import OrderSubmissionPlan


@dataclass(frozen=True, slots=True)
class PaperReservation:
    reservation_id: str
    strategy_id: str
    instrument_id: str
    market_id: str
    notional_usdc: float


class PaperReservationBook:
    """Process-local atomic reservations layered over native Cache truth."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._reservations: dict[str, PaperReservation] = {}

    def reserve(
        self,
        *,
        strategy_id: str,
        instrument_id: str,
        market_id: str,
        notional_usdc: float,
        base_open_instruments: set[str],
        base_strategy_exposure: float,
        base_market_exposure: float,
        max_open_positions: int,
        max_strategy_exposure_usdc: float,
        max_market_exposure_usdc: float,
    ) -> str:
        with self._lock:
            active = tuple(self._reservations.values())
            reserved_instruments = {item.instrument_id for item in active}
            open_instruments = base_open_instruments | reserved_instruments
            if (
                instrument_id not in open_instruments
                and len(open_instruments) >= max_open_positions
            ):
                raise ValueError("MAX_OPEN_POSITIONS")
            strategy_reserved = sum(
                item.notional_usdc for item in active if item.strategy_id == strategy_id
            )
            if (
                base_strategy_exposure + strategy_reserved + notional_usdc
                > max_strategy_exposure_usdc
            ):
                raise ValueError("MAX_STRATEGY_EXPOSURE")
            market_reserved = sum(
                item.notional_usdc for item in active if item.market_id == market_id
            )
            if base_market_exposure + market_reserved + notional_usdc > max_market_exposure_usdc:
                raise ValueError("MAX_MARKET_EXPOSURE")
            reservation_id = f"res_{uuid4().hex}"
            self._reservations[reservation_id] = PaperReservation(
                reservation_id=reservation_id,
                strategy_id=strategy_id,
                instrument_id=instrument_id,
                market_id=market_id,
                notional_usdc=notional_usdc,
            )
            return reservation_id

    def release(self, reservation_id: str | None) -> None:
        if not reservation_id:
            return
        with self._lock:
            self._reservations.pop(reservation_id, None)

    def active(self) -> tuple[PaperReservation, ...]:
        with self._lock:
            return tuple(self._reservations.values())


@dataclass(frozen=True, slots=True)
class PaperRiskGate:
    enabled: bool
    max_open_positions: int
    max_market_exposure_usdc: float
    max_strategy_exposure_usdc: float
    market_id_for_instrument: Callable[[str], str | None]
    reservations: PaperReservationBook = field(default_factory=PaperReservationBook)

    def validate(
        self,
        strategy: object,
        spec: OrderSubmissionPlan,
        *,
        market_id: str,
        instrument_id: str | None = None,
    ) -> str | None:
        if not self.enabled:
            raise ValueError("PAPER_TRADING_DISABLED")
        if spec.reduce_only:
            return None
        _validate_limits(self)
        strategy_id, cache = _risk_context(strategy)
        all_positions, strategy_positions, all_orders, strategy_orders = _risk_state(
            cache,
            strategy_id,
        )
        order_notional = _order_notional(spec)
        resolved_instrument_id = instrument_id or spec.instrument_id
        open_instruments = _open_position_keys(all_positions, all_orders)
        _check_open_position_limit(self, open_instruments, resolved_instrument_id)
        strategy_exposure = _total_exposure(strategy_positions, strategy_orders)
        if strategy_exposure + order_notional > self.max_strategy_exposure_usdc:
            raise ValueError("MAX_STRATEGY_EXPOSURE")
        market_exposure = _market_exposure(
            self.market_id_for_instrument,
            all_positions,
            all_orders,
            market_id,
        )
        if market_exposure + order_notional > self.max_market_exposure_usdc:
            raise ValueError("MAX_MARKET_EXPOSURE")
        return self.reservations.reserve(
            strategy_id=str(strategy_id),
            instrument_id=resolved_instrument_id,
            market_id=market_id,
            notional_usdc=order_notional,
            base_open_instruments=open_instruments,
            base_strategy_exposure=strategy_exposure,
            base_market_exposure=market_exposure,
            max_open_positions=self.max_open_positions,
            max_strategy_exposure_usdc=self.max_strategy_exposure_usdc,
            max_market_exposure_usdc=self.max_market_exposure_usdc,
        )

    def release(self, reservation_id: str | None) -> None:
        self.reservations.release(reservation_id)

    def release_from_event(self, event: object) -> None:
        self.release(_reservation_id_from_event(event))


def _risk_context(strategy: object) -> tuple[object, object]:
    strategy_id = getattr(strategy, "id", None)
    cache = getattr(strategy, "cache", None)
    if strategy_id is None or cache is None:
        raise ValueError("PAPER_RISK_STATE_UNAVAILABLE")
    return strategy_id, cache


def _risk_state(
    cache: object,
    strategy_id: object,
) -> tuple[tuple[object, ...], tuple[object, ...], tuple[object, ...], tuple[object, ...]]:
    all_positions = _read_collection(cache, "positions_open")
    strategy_positions = _read_collection(cache, "positions_open", strategy_id=strategy_id)
    all_orders = _read_collection(cache, "orders_open")
    strategy_orders = _read_collection(cache, "orders_open", strategy_id=strategy_id)
    return all_positions, strategy_positions, all_orders, strategy_orders


def _validate_limits(gate: PaperRiskGate) -> None:
    values = (
        gate.max_open_positions,
        gate.max_market_exposure_usdc,
        gate.max_strategy_exposure_usdc,
    )
    if gate.max_open_positions < 1 or any(
        not math.isfinite(float(value)) or float(value) <= 0 for value in values[1:]
    ):
        raise ValueError("PAPER_RISK_CONFIG_INVALID")


def _read_collection(
    cache: object,
    method_name: str,
    *,
    strategy_id: object | None = None,
) -> tuple[object, ...]:
    method = getattr(cache, method_name, None)
    if not callable(method):
        raise ValueError("PAPER_RISK_STATE_UNAVAILABLE")
    try:
        raw = (
            method(strategy_id=strategy_id)
            if strategy_id is not None
            else method()
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("PAPER_RISK_STATE_UNAVAILABLE") from exc
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes, bytearray)):
        raise ValueError("PAPER_RISK_STATE_UNAVAILABLE")
    return tuple(cast(Iterable[object], raw))


def _open_position_keys(
    positions: tuple[object, ...],
    orders: tuple[object, ...],
) -> set[str]:
    keys = {
        _instrument_key(item)
        for item in positions
        if _quantity(item, "signed_qty") > 0
    }
    keys.update(
        _instrument_key(item)
        for item in orders
        if not bool(getattr(item, "reduce_only", False))
    )
    return keys


def _check_open_position_limit(
    gate: PaperRiskGate,
    keys: set[str],
    instrument_id: str,
) -> None:
    if instrument_id not in keys and len(keys) >= gate.max_open_positions:
        raise ValueError("MAX_OPEN_POSITIONS")


def _total_exposure(positions: tuple[object, ...], orders: tuple[object, ...]) -> float:
    return sum(
        _notional(item, "signed_qty", "avg_px_open") for item in positions
    ) + sum(_notional(item, "quantity", "price") for item in orders)


def _market_exposure(
    resolver: Callable[[str], str | None],
    positions: tuple[object, ...],
    orders: tuple[object, ...],
    market_id: str,
) -> float:
    total = 0.0
    for item in (*positions, *orders):
        if bool(getattr(item, "reduce_only", False)):
            continue
        item_market_id = resolver(_instrument_key(item))
        if item_market_id is None:
            raise ValueError("PAPER_RISK_STATE_UNAVAILABLE")
        if item_market_id == market_id:
            total += _item_notional(item)
    return total


def _item_notional(item: object) -> float:
    if hasattr(item, "avg_px_open"):
        return _notional(item, "signed_qty", "avg_px_open")
    return _notional(item, "quantity", "price")


def _order_notional(spec: OrderSubmissionPlan) -> float:
    notional = float(spec.price) * float(spec.quantity)
    if not math.isfinite(notional) or notional <= 0:
        raise ValueError("PAPER_RISK_STATE_UNAVAILABLE")
    return notional


def _notional(item: object, quantity_name: str, price_name: str) -> float:
    quantity = abs(_number(getattr(item, quantity_name, None)))
    price = _number(getattr(item, price_name, None))
    notional = quantity * price
    if not math.isfinite(notional) or notional < 0:
        raise ValueError("PAPER_RISK_STATE_UNAVAILABLE")
    return notional


def _number(value: object) -> float:
    if value is None:
        raise ValueError("PAPER_RISK_STATE_UNAVAILABLE")
    as_double = getattr(value, "as_double", None)
    if callable(as_double):
        value = as_double()
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("PAPER_RISK_STATE_UNAVAILABLE") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError("PAPER_RISK_STATE_UNAVAILABLE")
    return number


def _quantity(item: object, name: str) -> float:
    value = getattr(item, name, None)
    as_double = getattr(value, "as_double", None)
    if callable(as_double):
        value = as_double()
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("PAPER_RISK_STATE_UNAVAILABLE") from exc


def _instrument_key(item: object) -> str:
    value = getattr(item, "instrument_id", item)
    value = getattr(value, "id", value)
    text = str(value)
    if not text:
        raise ValueError("PAPER_RISK_STATE_UNAVAILABLE")
    return text


def _reservation_id_from_event(event: object) -> str | None:
    metrics = getattr(event, "metrics", None)
    if isinstance(metrics, Mapping):
        value = metrics.get("reservation_id")
        if value:
            return str(value)
    tags = getattr(event, "tags", ())
    if isinstance(tags, (str, bytes)):
        tags = (tags,)
    for tag in tags:
        text = str(tag)
        if text.startswith("reservation_id="):
            return text.partition("=")[2] or None
    return None
