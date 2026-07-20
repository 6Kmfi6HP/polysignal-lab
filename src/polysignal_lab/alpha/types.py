"""
Input: __future__, __future__.annotations, dataclasses, dataclasses.dataclass, datetime, datetime.UTC, datetime.datetime, types, types.MappingProxyType, typing
Output: SideBookView, SpotView, TradeView, FreshnessView, CachedOrderView, CachedPositionView, TradingStateView, MarketView, OrderIntentSpec, AlphaDecision
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""









from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence

from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.utils import compact_json, stable_hash


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True)
class SideBookView:
    token_id: str
    best_bid: float | None
    best_ask: float | None
    spread: float | None
    freshness_ms: int | None
    min_order_size: float | None = None
    tick_size: float | None = None
    last_trade_price: float | None = None
    last_trade_size: float | None = None
    last_trade_timestamp: str | None = None
    received_at: datetime | None = None
    ask_levels: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True, slots=True)
class SpotView:
    asset: str
    symbol: str
    price: float
    source: str
    freshness_ms: int | None
    received_at: datetime | None = None

    def freshness_ms_at(self, now: datetime) -> int | None:
        if self.received_at is None:
            return self.freshness_ms
        current = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        received = (
            self.received_at
            if self.received_at.tzinfo is not None
            else self.received_at.replace(tzinfo=UTC)
        )
        return max(
            0,
            int(
                (
                    current.astimezone(UTC) - received.astimezone(UTC)
                ).total_seconds()
                * 1000
            ),
        )


@dataclass(frozen=True, slots=True)
class TradeView:
    price: float
    size: float
    side: str | None
    ts: datetime | None


@dataclass(frozen=True, slots=True)
class FreshnessView:
    up_book_ms: int | None
    down_book_ms: int | None
    spot_ms: int | None
    max_ms: int | None


@dataclass(frozen=True, slots=True)
class CachedOrderView:
    client_order_id: str
    instrument_id: str
    strategy: str
    market_id: str
    condition_id: str
    side: Side
    pair_id: str | None
    position_id: str | None
    status: str
    price: float | None
    filled_quantity: float
    average_fill_price: float | None
    ts_event: datetime | None
    hedge_leg: bool
    reduce_only: bool
    is_open: bool
    is_inflight: bool
    take_profit_price: float | None
    stop_loss_price: float | None
    dedupe_key: str | None = None

    @property
    def has_fill(self) -> bool:
        return self.filled_quantity > 0.0 or "FILLED" in self.status.upper()

    @property
    def is_active(self) -> bool:
        return self.is_open or self.is_inflight or self.has_fill

    @property
    def was_accepted(self) -> bool:
        status = self.status.upper()
        if "REJECTED" in status or "DENIED" in status:
            return False
        return self.is_active or any(
            name in status
            for name in ("ACCEPTED", "CANCELED", "EXPIRED", "TRIGGERED")
        )


@dataclass(frozen=True, slots=True)
class CachedPositionView:
    position_id: str
    instrument_id: str
    strategy: str
    market_id: str
    condition_id: str
    side: Side
    pair_id: str | None
    quantity: float
    avg_entry_price: float
    opened_at: datetime | None


@dataclass(frozen=True, slots=True)
class TradingStateView:
    orders: tuple[CachedOrderView, ...] = ()
    positions: tuple[CachedPositionView, ...] = ()

    def for_condition(self, condition_id: str) -> "TradingStateView":
        return TradingStateView(
            orders=tuple(
                order for order in self.orders if order.condition_id == condition_id
            ),
            positions=tuple(
                position
                for position in self.positions
                if position.condition_id == condition_id
            ),
        )

    def has_market_activity(
        self,
        strategy: str,
        market_id: str,
        side: Side | None = None,
    ) -> bool:
        return any(
            order.strategy == strategy
            and order.market_id == market_id
            and not order.reduce_only
            and order.is_active
            and (side is None or order.side is side)
            for order in self.orders
        ) or any(
            position.strategy == strategy
            and position.market_id == market_id
            and (side is None or position.side is side)
            for position in self.positions
        )

    def unhedged_leg(
        self,
        strategy: str,
        market_id: str,
    ) -> CachedPositionView | None:
        legs = tuple(
            position
            for position in self.positions
            if position.strategy == strategy and position.market_id == market_id
        )
        if len({leg.side for leg in legs}) != 1:
            return None
        return legs[0] if legs else None

    def position(
        self,
        strategy: str,
        market_id: str,
        side: Side,
    ) -> CachedPositionView | None:
        return next(
            (
                position
                for position in self.positions
                if position.strategy == strategy
                and position.market_id == market_id
                and position.side is side
            ),
            None,
        )

    def has_hedge_order(self, strategy: str, market_id: str) -> bool:
        return any(
            order.strategy == strategy
            and order.market_id == market_id
            and order.hedge_leg
            and order.is_active
            for order in self.orders
        )

    def has_exit_order(self, position_id: str) -> bool:
        return any(
            order.reduce_only
            and order.position_id == position_id
            and (order.is_open or order.is_inflight)
            for order in self.orders
        )

    def accepted_entry_orders(
        self,
        strategy: str,
        market_id: str,
    ) -> tuple[CachedOrderView, ...]:
        return tuple(
            order
            for order in self.orders
            if order.strategy == strategy
            and order.market_id == market_id
            and not order.reduce_only
            and order.was_accepted
        )

    def latest_accepted_entry(
        self,
        strategy: str,
        market_id: str,
    ) -> CachedOrderView | None:
        dated = tuple(
            order
            for order in self.accepted_entry_orders(strategy, market_id)
            if order.ts_event is not None
        )
        return (
            max(
                dated,
                key=lambda order: (order.ts_event, order.client_order_id),
            )
            if dated
            else None
        )

    def has_entry_level(
        self,
        strategy: str,
        market_id: str,
        side: Side,
        price: float,
    ) -> bool:
        return any(
            order.side is side
            and order.price is not None
            and abs(order.price - price) < 1e-12
            for order in self.accepted_entry_orders(strategy, market_id)
        )

    def filled_layer_count(self, strategy: str, market_id: str, side: Side) -> int:
        return sum(
            1
            for order in self.orders
            if order.strategy == strategy
            and order.market_id == market_id
            and order.side is side
            and not order.reduce_only
            and order.has_fill
        )

    def exit_thresholds(
        self,
        position_id: str,
    ) -> tuple[float | None, float | None]:
        position = next(
            (item for item in self.positions if item.position_id == position_id),
            None,
        )
        if position is None:
            return None, None
        orders = sorted(
            (
                order
                for order in self.orders
                if order.instrument_id == position.instrument_id
                and order.strategy == position.strategy
                and not order.reduce_only
            ),
            key=lambda order: (order.ts_event or datetime.min.replace(tzinfo=UTC), order.client_order_id),
            reverse=True,
        )
        for order in orders:
            if order.take_profit_price is not None or order.stop_loss_price is not None:
                return order.take_profit_price, order.stop_loss_price
        return None, None


@dataclass(frozen=True, slots=True)
class MarketView:
    view_id: str
    market_id: str
    market_slug: str
    condition_id: str
    asset: str
    timeframe: str
    start_ts: datetime | None
    end_ts: datetime | None
    created_at: datetime
    seconds_to_close: int | None
    up: SideBookView
    down: SideBookView
    spot: SpotView | None
    price_to_beat: float | None
    up_trades: Sequence[TradeView]
    down_trades: Sequence[TradeView]
    metrics: Mapping[str, Any]
    freshness: FreshnessView
    trading: TradingStateView = TradingStateView()

    def book_for(self, side: Side) -> SideBookView:
        return self.up if side == Side.UP else self.down

    def ask_for(self, side: Side) -> float | None:
        return self.book_for(side).best_ask


@dataclass(frozen=True, slots=True)
class OrderIntentSpec:
    intent: OrderIntent
    expiry_seconds: int | None = None
    pair_id: str | None = None
    reduce_only: bool = False
    quantity: float | None = None
    notional: float | None = None

    def __post_init__(self) -> None:
        if self.quantity is not None and self.notional is not None:
            raise ValueError("order intent accepts quantity or notional, not both")
        for name, value in (("quantity", self.quantity), ("notional", self.notional)):
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True, slots=True)
class AlphaDecision:
    """Sole trading intent SoT. Nautilus Order is built only from this (+ book depth).

    SignalCandidate is a publish/projection DTO, never the order-routing type.
    """

    strategy: str
    asset: str
    timeframe: str
    market_id: str
    market_slug: str
    condition_id: str
    token_id: str
    side: Side
    confidence: float
    entry_reference_price: float
    max_entry_price: float
    seconds_to_close: int | None
    data_freshness_ms: int | None
    reason_codes: tuple[str, ...]
    metrics: Mapping[str, Any]
    order_intent: OrderIntentSpec | None = None
    hedge_leg: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(self, "metrics", _freeze_mapping(self.metrics))

    @property
    def reduce_only(self) -> bool:
        return bool(self.order_intent and self.order_intent.reduce_only)

    @property
    def resolved_intent(self) -> OrderIntent:
        if self.order_intent is None:
            return OrderIntent.TAKER_IOC
        return self.order_intent.intent

    @property
    def explicit_intent(self) -> OrderIntent | None:
        return None if self.order_intent is None else self.order_intent.intent

    @property
    def expiry_seconds(self) -> int | None:
        return None if self.order_intent is None else self.order_intent.expiry_seconds

    @property
    def pair_id(self) -> str | None:
        return None if self.order_intent is None else self.order_intent.pair_id

    @property
    def quantity(self) -> float | None:
        return None if self.order_intent is None else self.order_intent.quantity

    @property
    def notional(self) -> float | None:
        return None if self.order_intent is None else self.order_intent.notional

    def signal_id(self, view_id: str) -> str:
        """Stable execution/report correlation derived only from trading inputs."""
        intent = self.order_intent
        hash_val = stable_hash(
            self.strategy,
            self.asset,
            self.timeframe,
            self.market_id,
            self.token_id,
            self.side.value,
            self.confidence,
            self.entry_reference_price,
            self.max_entry_price,
            self.reason_codes,
            compact_json(dict(self.metrics)),
            intent.intent.value if intent is not None else "",
            intent.expiry_seconds if intent is not None else None,
            intent.pair_id if intent is not None else None,
            intent.quantity if intent is not None else None,
            intent.notional if intent is not None else None,
            self.reduce_only,
            self.hedge_leg,
            view_id,
            length=20,
        )
        return f"sig_{hash_val}"

    def dedupe_key(self) -> str:
        scope = "exit" if self.reduce_only else "entry"
        return (
            f"{self.asset}:{self.timeframe}:{self.market_id}:"
            f"{self.side.value}:{self.strategy}:{scope}"
        )


class AlphaCore(Protocol):
    def evaluate(self, view: MarketView) -> list[AlphaDecision]: ...
