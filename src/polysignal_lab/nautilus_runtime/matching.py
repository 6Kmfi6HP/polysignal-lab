from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from polysignal_lab.alpha.types import NautilusOrderSpec
from polysignal_lab.domain.enums import OrderIntent, OrderStatus, Side
from polysignal_lab.domain.orderbook import BookLevel, OrderBook
from polysignal_lab.domain.paper_order import PaperFill, PaperOrder
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.nautilus_runtime.execution_types import PaperExecutionResult
from polysignal_lab.paper.wallet import PaperWallet
from polysignal_lab.utils import new_id, utc_now


@dataclass(frozen=True, slots=True)
class MatchingAccuracySettings:
    mode: str
    book_type: str
    trade_execution: bool
    bar_execution: bool
    liquidity_consumption: bool
    queue_position: bool
    support_gtd_orders: bool
    support_contingent_orders: bool
    use_reduce_only: bool
    price_protection_points: int

    @classmethod
    def from_mode(cls, mode: str) -> "MatchingAccuracySettings":
        if mode == "fast_l1":
            return cls(mode, "L1_MBP", True, False, False, False, True, False, True, 0)
        if mode == "depth_l2":
            return cls(mode, "L2_MBP", True, False, True, False, True, False, True, 0)
        if mode == "queue_l2":
            return cls(mode, "L2_MBP", True, False, True, True, True, False, True, 0)
        raise ValueError(f"unknown Nautilus matching accuracy mode: {mode}")


@dataclass(frozen=True, slots=True)
class MatchingTrade:
    token_id: str
    price: float
    size: float
    side: str | None
    ts_event: datetime | None


class NautilusMatchingPaperExecutionClient:
    paper_engine = "nautilus_matching"

    def __init__(
        self,
        wallet: PaperWallet | None = None,
        accuracy_mode: str = "depth_l2",
        max_book_staleness_ms: int = 10_000,
    ) -> None:
        self.wallet = wallet or PaperWallet(starting_balance=10_000.0)
        self.settings = MatchingAccuracySettings.from_mode(accuracy_mode)
        self.accuracy_mode = self.settings.mode
        self.max_book_staleness_ms = max_book_staleness_ms
        self._books: dict[str, OrderBook] = {}
        self._trades: dict[str, list[MatchingTrade]] = {}
        self._pending: list[PaperExecutionResult] = []
        self._remaining_asks: dict[str, dict[float, float]] = {}
        self._mirrored_fill_ids: set[str] = set()
        self._exchange: Any | None = None

    def update_book(self, token_id: str, book: OrderBook) -> None:
        self._books[token_id] = book
        self._remaining_asks[token_id] = _level_sizes(book.asks)

    def update_trade(
        self,
        token_id: str,
        price: float,
        size: float,
        side: str | None = None,
        ts_event: datetime | None = None,
    ) -> None:
        if price <= 0 or size <= 0:
            return
        self._trades.setdefault(token_id, []).append(
            MatchingTrade(
                token_id=token_id,
                price=price,
                size=size,
                side=side,
                ts_event=ts_event,
            )
        )

    def recent_trades_for(self, token_id: str) -> list[MatchingTrade]:
        return list(self._trades.get(token_id, ()))

    def drain_events(self) -> list[PaperExecutionResult]:
        events = self._pending
        self._pending = []
        return events

    def submit_spec(self, spec: NautilusOrderSpec) -> PaperExecutionResult:
        order = self._paper_order_from_spec(spec)
        book = self._books.get(spec.instrument_id)
        if book is None:
            return PaperExecutionResult(
                order=order,
                status=OrderStatus.REJECTED,
                reason="MISSING_ORDERBOOK",
            )
        freshness_ms = _freshness_ms(book)
        if freshness_ms is not None and freshness_ms > self.max_book_staleness_ms:
            return PaperExecutionResult(
                order=order,
                status=OrderStatus.REJECTED,
                reason="STALE_ORDERBOOK",
            )
        if spec.side not in {Side.UP, Side.DOWN}:
            return self._reject(order, "UNSUPPORTED_SIDE")
        if spec.intent not in {
            OrderIntent.TAKER_FAK,
            OrderIntent.TAKER_FOK,
            OrderIntent.TAKER_IOC,
        }:
            result = PaperExecutionResult(
                order=order,
                status=OrderStatus.PENDING,
                reason="MATCHING_NOT_CONNECTED",
            )
            self._pending.append(result)
            return result
        return self._match_taker(order, book, spec)

    def _paper_order_from_spec(self, spec: NautilusOrderSpec) -> PaperOrder:
        tags = dict(spec.tags)
        metrics = {
            **tags,
            "paper_engine": self.paper_engine,
            "accuracy_mode": self.accuracy_mode,
        }
        return PaperOrder(
            paper_order_id=new_id("paper"),
            signal_id=tags.get("signal_id", ""),
            token_id=spec.instrument_id,
            side=spec.side,
            limit_price=_tag_float(tags, "max_entry_price", spec.price),
            stake_usdc=spec.quantity * spec.price,
            shares=spec.quantity,
            asset=tags.get("asset", ""),
            timeframe=tags.get("timeframe", ""),
            strategy=tags.get("strategy", ""),
            market_id=tags.get("market_id", tags.get("market", "")),
            market_slug=tags.get("market_slug", ""),
            reference_price=spec.price,
            created_at=utc_now(),
            order_intent=spec.intent,
            pair_id=spec.pair_id,
            reduce_only=spec.reduce_only,
            hedge_leg=spec.hedge_leg,
            signal_confidence=_tag_float(tags, "confidence"),
            metrics=metrics,
        )

    def _match_taker(
        self,
        order: PaperOrder,
        book: OrderBook,
        spec: NautilusOrderSpec,
    ) -> PaperExecutionResult:
        best_ask = book.best_ask
        if best_ask is None:
            return self._reject(order, "INSUFFICIENT_DEPTH")
        ceiling = order.limit_price
        if best_ask > ceiling:
            return self._reject(order, "PRICE_ABOVE_LIMIT")

        depth = self._remaining_asks.setdefault(order.token_id, _level_sizes(book.asks))
        available = _available_levels(depth, ceiling)
        available_shares = sum(size for _, size in available)
        available_usdc = sum(price * size for price, size in available)
        if spec.intent == OrderIntent.TAKER_FOK and available_shares + 1e-12 < spec.quantity:
            return self._reject(order, "INSUFFICIENT_DEPTH")

        remaining = spec.quantity
        filled_shares = 0.0
        filled_usdc = 0.0
        consumed: dict[float, float] = {}
        for price, size in available:
            take = min(remaining, size)
            if take <= 0:
                continue
            consumed[price] = consumed.get(price, 0.0) + take
            filled_shares += take
            filled_usdc += take * price
            remaining -= take
            if remaining <= 1e-12:
                break

        if filled_shares <= 0:
            return self._reject(order, "INSUFFICIENT_DEPTH")

        fill_price = filled_usdc / filled_shares
        fill = PaperFill(
            paper_order_id=order.paper_order_id,
            signal_id=order.signal_id,
            token_id=order.token_id,
            side=order.side,
            raw_best_ask=best_ask,
            slippage_bps=0.0,
            fill_price=fill_price,
            stake_usdc=filled_usdc,
            shares=filled_shares,
            depth_checked=True,
            available_depth_usdc=available_usdc,
            fill_ratio=filled_shares / spec.quantity,
        )
        position = PaperPosition(
            signal_id=order.signal_id,
            paper_order_id=order.paper_order_id,
            paper_fill_id=fill.paper_fill_id,
            strategy=order.strategy,
            asset=order.asset,
            timeframe=order.timeframe,
            market_id=order.market_id,
            market_slug=order.market_slug,
            token_id=order.token_id,
            side=order.side,
            entry_price=fill_price,
            shares=filled_shares,
            stake_usdc=filled_usdc,
            signal_confidence=order.signal_confidence,
            signal_metrics=dict(order.metrics),
        )
        if not self.wallet.can_afford(position.stake_usdc):
            return self._reject(order, "WALLET_INSUFFICIENT_CASH")
        if self.settings.liquidity_consumption:
            for price, size in consumed.items():
                depth[price] = max(0.0, depth.get(price, 0.0) - size)
        self._apply_fill_once(position)
        order.status = OrderStatus.FILLED
        return PaperExecutionResult(
            order=order,
            fills=[fill],
            positions=[position],
            status=OrderStatus.FILLED,
        )

    def _apply_fill_once(self, position: PaperPosition) -> None:
        if position.paper_fill_id in self._mirrored_fill_ids:
            return
        self.wallet.apply_fill(position)
        self._mirrored_fill_ids.add(position.paper_fill_id)

    def _reject(self, order: PaperOrder, reason: str) -> PaperExecutionResult:
        order.status = OrderStatus.REJECTED
        order.reject_reason = reason
        return PaperExecutionResult(order=order, status=OrderStatus.REJECTED, reason=reason)


def _level_sizes(levels: list[BookLevel]) -> dict[float, float]:
    sizes: dict[float, float] = {}
    for level in levels:
        if level.price <= 0 or level.size <= 0:
            continue
        sizes[level.price] = sizes.get(level.price, 0.0) + level.size
    return sizes


def _available_levels(depth: dict[float, float], ceiling: float) -> list[tuple[float, float]]:
    return sorted(
        (price, size)
        for price, size in depth.items()
        if price <= ceiling and size > 0
    )


def _freshness_ms(book: OrderBook) -> int | None:
    if book.received_at is None:
        return None
    return max(0, int((datetime.now(UTC) - book.received_at).total_seconds() * 1000))


def _tag_float(tags: dict[str, str], key: str, default: float | None = None) -> float | None:
    value = tags.get(key)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
