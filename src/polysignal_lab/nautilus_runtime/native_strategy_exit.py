"""
Input: __future__, dataclasses, datetime, math, polysignal_lab.alpha.types, polysignal_lab.domain.enums, polysignal_lab.nautilus_bridge.market_catalog, polysignal_lab.nautilus_runtime.projections
Output: NativeExitPolicy
Pos: Native strategy risk-exit policy

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import math

from polysignal_lab.alpha.types import AlphaDecision, MarketView, OrderIntentSpec
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
from polysignal_lab.nautilus_runtime.projections import project_position
from polysignal_lab.utils import parse_dt


@dataclass(frozen=True, slots=True)
class NativeExitPolicy:
    """Generate reduce-only decisions from native open positions and market views."""

    mode: str
    take_profit_enabled: bool
    stop_loss_enabled: bool
    take_profit_price: float
    stop_loss_price: float
    max_hold_time_sec: int

    @classmethod
    def from_config(cls, config: object | None) -> "NativeExitPolicy | None":
        if config is None:
            return None
        mode = str(getattr(config, "mode", "hold_to_resolution_with_optional_tp_sl"))
        if mode in {"disabled", "none"}:
            return None
        if mode not in {
            "hold_to_resolution",
            "hold_to_resolution_with_optional_tp_sl",
        }:
            raise ValueError(f"unsupported native exit model mode: {mode!r}")
        take_profit_price = _positive_float(
            getattr(config, "take_profit_price", 0.90),
            "take_profit_price",
        )
        stop_loss_price = _positive_float(
            getattr(config, "stop_loss_price", 0.35),
            "stop_loss_price",
        )
        max_hold_time_sec = int(getattr(config, "max_hold_time_sec", 900))
        if max_hold_time_sec <= 0:
            raise ValueError("max_hold_time_sec must be positive")
        return cls(
            mode=mode,
            take_profit_enabled=bool(getattr(config, "take_profit_enabled", True)),
            stop_loss_enabled=bool(getattr(config, "stop_loss_enabled", True)),
            take_profit_price=take_profit_price,
            stop_loss_price=stop_loss_price,
            max_hold_time_sec=max_hold_time_sec,
        )

    def decisions(
        self,
        *,
        cache: object | None,
        strategy_id: object | None,
        registry: MarketCatalog,
        view: MarketView,
        now: datetime,
        inflight: set[str],
    ) -> tuple[AlphaDecision, ...]:
        if cache is None or strategy_id is None:
            return ()
        pair = registry.by_condition(view.condition_id)
        if pair is None:
            return ()
        decisions: list[AlphaDecision] = []
        for position in _open_positions(cache, strategy_id):
            decision = self._decision_for_position(
                position,
                registry=registry,
                pair=pair,
                view=view,
                now=now,
                inflight=inflight,
            )
            if decision is not None:
                decisions.append(decision)
        return tuple(decisions)

    def _decision_for_position(
        self,
        position: object,
        *,
        registry: MarketCatalog,
        pair: object,
        view: MarketView,
        now: datetime,
        inflight: set[str],
    ) -> AlphaDecision | None:
        projection = project_position(position)
        if bool(projection.get("is_closed")):
            return None
        position_id = str(projection.get("position_id") or "")
        instrument_id = str(projection.get("instrument_id") or "")
        quantity = _finite_float(projection.get("quantity"))
        entry_price = _finite_float(projection.get("avg_entry_price"))
        if not position_id or not instrument_id or quantity is None or quantity <= 0:
            return None
        identity = _position_identity(registry, pair, instrument_id)
        if identity is None:
            return None
        token_id, side = identity
        bid = view.book_for(side).best_bid
        if bid is None or not math.isfinite(float(bid)) or float(bid) <= 0:
            return None
        reason = self._reason(
            bid=float(bid),
            entry_price=entry_price,
            opened_at=_opened_at(projection),
            now=now,
        )
        if reason is None or position_id in inflight:
            return None
        return _build_exit_decision(
            view=view,
            token_id=token_id,
            side=side,
            bid=float(bid),
            reason=reason,
            position_id=position_id,
            quantity=quantity,
            entry_price=entry_price,
        )

    def _reason(
        self,
        *,
        bid: float,
        entry_price: float | None,
        opened_at: datetime | None,
        now: datetime,
    ) -> str | None:
        if (
            self.mode == "hold_to_resolution_with_optional_tp_sl"
            and self.stop_loss_enabled
            and bid <= self.stop_loss_price
        ):
            return "STOP_LOSS"
        if (
            self.mode == "hold_to_resolution_with_optional_tp_sl"
            and self.take_profit_enabled
            and bid >= self.take_profit_price
        ):
            return "TAKE_PROFIT"
        if opened_at is not None and (now - opened_at).total_seconds() >= self.max_hold_time_sec:
            return "MAX_HOLD_TIME"
        _ = entry_price
        return None


def _build_exit_decision(
    *,
    view: MarketView,
    token_id: str,
    side: Side,
    bid: float,
    reason: str,
    position_id: str,
    quantity: float,
    entry_price: float | None,
) -> AlphaDecision:
    return AlphaDecision(
        strategy="native_exit",
        asset=view.asset,
        timeframe=view.timeframe,
        market_id=view.market_id,
        market_slug=view.market_slug,
        condition_id=view.condition_id,
        token_id=token_id,
        side=side,
        confidence=1.0,
        entry_reference_price=bid,
        max_entry_price=bid,
        seconds_to_close=view.seconds_to_close,
        data_freshness_ms=view.freshness.max_ms,
        reason_codes=("NATIVE_EXIT", reason),
        metrics={
            "reduce_only": True,
            "exit_reason": reason,
            "position_id": position_id,
            "position_quantity": quantity,
            "entry_price": entry_price,
            "exit_price": bid,
        },
        order_intent=OrderIntentSpec(
            intent=OrderIntent.TAKER_FAK,
            reduce_only=True,
        ),
    )


def _open_positions(cache: object, strategy_id: object) -> tuple[object, ...]:
    method = getattr(cache, "positions_open", None)
    if not callable(method):
        return ()
    try:
        raw = method(strategy_id=strategy_id)
    except TypeError:
        raw = method()
    if isinstance(raw, (str, bytes, bytearray)):
        return ()
    try:
        return tuple(raw)
    except TypeError:
        return ()


def _position_identity(
    registry: MarketCatalog,
    pair: object,
    instrument_id: str,
) -> tuple[str, Side] | None:
    for token_meta in (getattr(pair, "up", None), getattr(pair, "down", None)):
        if token_meta is None:
            continue
        token_id = str(getattr(token_meta, "token_id", ""))
        if not token_id:
            continue
        if registry.instrument_id_for_token(token_id) == instrument_id:
            side = getattr(token_meta, "side", None)
            if isinstance(side, Side):
                return token_id, side
    return None


def _opened_at(projection: dict[str, object]) -> datetime | None:
    raw = projection.get("opened_at") or projection.get("ts")
    if isinstance(raw, datetime):
        return raw.astimezone(UTC) if raw.tzinfo is not None else raw.replace(tzinfo=UTC)
    if isinstance(raw, str):
        try:
            return parse_dt(raw)
        except ValueError:
            return None
    return None


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive_float(value: object, name: str) -> float:
    number = _finite_float(value)
    if number is None or number <= 0:
        raise ValueError(f"{name} must be positive")
    return number
