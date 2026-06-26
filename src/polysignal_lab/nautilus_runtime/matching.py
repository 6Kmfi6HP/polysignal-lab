from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from polysignal_lab.alpha.types import NautilusOrderSpec
from polysignal_lab.domain.enums import OrderIntent, OrderStatus, Side
from polysignal_lab.domain.orderbook import OrderBook
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


@dataclass(frozen=True, slots=True)
class NautilusFillEvent:
    fill_price: float
    shares: float
    stake_usdc: float
    raw_best_ask: float
    available_depth_usdc: float | None = None
    fill_ratio: float = 1.0
    fill_id: str | None = None
    position_id: str | None = None


@dataclass(frozen=True, slots=True)
class NautilusMatchingOutcome:
    status: OrderStatus
    fills: tuple[NautilusFillEvent, ...] = ()
    reason: str | None = None


class NautilusMatchingUnavailable(RuntimeError):
    def __init__(self, reason: str = "MATCHING_NOT_CONNECTED") -> None:
        super().__init__(reason)
        self.reason = reason


class NautilusMatchingBoundary(Protocol):
    def update_book(self, token_id: str, book: OrderBook) -> None: ...
    def submit_order(self, order: PaperOrder, spec: NautilusOrderSpec) -> NautilusMatchingOutcome: ...


class OwnedNautilusMatchingBoundary:
    """Lazy boundary for the owned Nautilus SimulatedExchange execution path."""

    def __init__(self, settings: MatchingAccuracySettings) -> None:
        self.settings = settings
        self._simulated_exchange_cls: Any | None = None
        self._backtest_exec_client_cls: Any | None = None

    def update_book(self, token_id: str, book: OrderBook) -> None:
        return None

    def submit_order(self, order: PaperOrder, spec: NautilusOrderSpec) -> NautilusMatchingOutcome:
        self._load_nautilus_components()
        raise NautilusMatchingUnavailable()

    def _load_nautilus_components(self) -> None:
        if self._simulated_exchange_cls is not None and self._backtest_exec_client_cls is not None:
            return
        try:
            from nautilus_trader.backtest.engine import SimulatedExchange
            from nautilus_trader.backtest.execution_client import BacktestExecClient
        except Exception as exc:  # pragma: no cover - depends on optional Nautilus runtime
            raise NautilusMatchingUnavailable() from exc
        self._simulated_exchange_cls = SimulatedExchange
        self._backtest_exec_client_cls = BacktestExecClient

class NautilusMatchingPaperExecutionClient:
    paper_engine = "nautilus_matching"

    def __init__(
        self,
        wallet: PaperWallet | None = None,
        accuracy_mode: str = "depth_l2",
        max_book_staleness_ms: int = 10_000,
        matching_boundary: NautilusMatchingBoundary | None = None,
    ) -> None:
        self.wallet = wallet or PaperWallet(starting_balance=10_000.0)
        self.settings = MatchingAccuracySettings.from_mode(accuracy_mode)
        self.accuracy_mode = self.settings.mode
        self.max_book_staleness_ms = max_book_staleness_ms
        self._books: dict[str, OrderBook] = {}
        self._trades: dict[str, list[MatchingTrade]] = {}
        self._pending: list[PaperExecutionResult] = []
        self._mirrored_fill_ids: set[str] = set()
        self.matching_boundary = matching_boundary or OwnedNautilusMatchingBoundary(self.settings)

    def update_book(self, token_id: str, book: OrderBook) -> None:
        self._books[token_id] = book
        self.matching_boundary.update_book(token_id, book)

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
        if spec.side not in {Side.UP, Side.DOWN}:
            return PaperExecutionResult(status=OrderStatus.REJECTED, reason="UNSUPPORTED_SIDE")
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
        return self._submit_taker_to_matching_boundary(order, spec)

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

    def _submit_taker_to_matching_boundary(
        self,
        order: PaperOrder,
        spec: NautilusOrderSpec,
    ) -> PaperExecutionResult:
        try:
            outcome = self.matching_boundary.submit_order(order, spec)
        except NautilusMatchingUnavailable as exc:
            result = PaperExecutionResult(
                order=order,
                status=OrderStatus.PENDING,
                reason=exc.reason,
            )
            self._pending.append(result)
            return result
        return self._mirror_matching_outcome(order, outcome)

    def _mirror_matching_outcome(
        self,
        order: PaperOrder,
        outcome: NautilusMatchingOutcome,
    ) -> PaperExecutionResult:
        if outcome.status == OrderStatus.REJECTED:
            return self._reject(order, outcome.reason or "MATCHING_REJECTED")
        if outcome.status not in {OrderStatus.FILLED, OrderStatus.PARTIAL}:
            result = PaperExecutionResult(
                order=order,
                status=outcome.status,
                reason=outcome.reason,
            )
            if outcome.status == OrderStatus.PENDING:
                self._pending.append(result)
            return result
        if not outcome.fills:
            return self._reject(order, outcome.reason or "INSUFFICIENT_DEPTH")

        fills: list[PaperFill] = []
        positions: list[PaperPosition] = []
        for event in outcome.fills:
            fill_fields: dict[str, Any] = {}
            if event.fill_id is not None:
                fill_fields["paper_fill_id"] = event.fill_id
            fill = PaperFill(
                **fill_fields,
                paper_order_id=order.paper_order_id,
                signal_id=order.signal_id,
                token_id=order.token_id,
                side=order.side,
                raw_best_ask=event.raw_best_ask,
                slippage_bps=0.0,
                fill_price=event.fill_price,
                stake_usdc=event.stake_usdc,
                shares=event.shares,
                depth_checked=True,
                available_depth_usdc=event.available_depth_usdc,
                fill_ratio=event.fill_ratio,
            )
            position_fields: dict[str, Any] = {}
            if event.position_id is not None:
                position_fields["paper_position_id"] = event.position_id
            position = PaperPosition(
                **position_fields,
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
                entry_price=event.fill_price,
                shares=event.shares,
                stake_usdc=event.stake_usdc,
                signal_confidence=order.signal_confidence,
                signal_metrics=dict(order.metrics),
            )
            fills.append(fill)
            positions.append(position)

        if not self.wallet.can_afford(sum(position.stake_usdc for position in positions)):
            return self._reject(order, "WALLET_INSUFFICIENT_CASH")
        for position in positions:
            self._apply_fill_once(position)
        order.status = outcome.status
        return PaperExecutionResult(
            order=order,
            fills=fills,
            positions=positions,
            status=outcome.status,
            reason=outcome.reason,
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
