"""Order Intent Executors — FAK, FOK, PASSIVE_GTD, and multi-leg coordination."""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import isfinite

from polysignal_lab.config import FillModelConfig
from polysignal_lab.data.state import OrderBookRegistry
from polysignal_lab.domain.enums import OrderIntent, OrderStatus
from polysignal_lab.domain.orderbook import OrderBook
from polysignal_lab.domain.paper_order import PaperFill, PaperOrder
from polysignal_lab.domain.paper_position import PaperPosition
from polysignal_lab.domain.signal import SignalCandidate
from polysignal_lab.utils import new_id


@dataclass
class IntentDispatchResult:
    order: PaperOrder
    fills: list[PaperFill] = field(default_factory=list)
    positions: list[PaperPosition] = field(default_factory=list)
    status: OrderStatus = OrderStatus.PENDING
    reject_reason: str | None = None


@dataclass
class RestingOrder:
    order: PaperOrder
    signal_id: str
    limit_price: float
    expiry_ts: float
    pair_id: str | None = None


class BestAskTakerExecutor:
    def __init__(
        self,
        fill_model: FillModelConfig,
        max_book_staleness_ms: int,
        registry: OrderBookRegistry | None = None,
    ):
        self.fill_model = fill_model
        self.max_book_staleness_ms = max_book_staleness_ms
        self.registry = registry

    def execute(
        self, order: PaperOrder, book: OrderBook, intent: OrderIntent | None = None
    ) -> IntentDispatchResult:
        if book.token_id != order.token_id:
            return self._reject(order, "MALFORMED_ORDERBOOK")
        registry_reason = self._registry_reject_reason(order.token_id, order.created_at)
        if registry_reason is not None:
            return self._reject(order, registry_reason)
        if self.registry is None and not book.is_fresh(
            self.max_book_staleness_ms, order.created_at
        ):
            return self._reject(order, "STALE_ORDERBOOK")
        if not book.asks or book.best_ask is None:
            return self._reject(order, "MISSING_BEST_ASK")
        if book.best_ask > order.limit_price:
            return self._reject(order, "ASK_ABOVE_MAX_ENTRY")
        if any(
            not isfinite(level.price)
            or level.price <= 0
            or not isfinite(level.size)
            or level.size <= 0
            for level in book.asks
        ):
            return self._reject(order, "MALFORMED_ORDERBOOK")

        if intent == OrderIntent.TAKER_FOK:
            return self._execute_fok(order, book)
        if intent == OrderIntent.TAKER_FAK:
            return self._execute_fak(order, book)
        # Default: existing best-ask taker with slippage
        return self._execute_default(order, book)

    def _registry_reject_reason(self, token_id: str, now: datetime) -> str | None:
        if self.registry is None:
            return None
        if self.registry.is_fill_eligible(token_id, self.max_book_staleness_ms, now):
            return None
        state = self.registry.get_state(token_id)
        reason = state.stale_reason if state else "NO_SNAPSHOT"
        return reason or "STALE_ORDERBOOK"

    def _execute_default(self, order: PaperOrder, book: OrderBook) -> IntentDispatchResult:
        fill_price = book.best_ask + book.best_ask * self.fill_model.slippage_bps / 10000
        if fill_price > order.limit_price:
            return self._reject(order, "SLIPPAGE_EXCEEDS_MAX_ENTRY")
        if self.fill_model.require_depth_check:
            available = book.depth_until(order.limit_price)
            if available < order.stake_usdc and self.fill_model.reject_if_partial:
                return self._reject(order, "INSUFFICIENT_DEPTH", available_depth_usdc=available)
        shares = order.stake_usdc / fill_price
        fill = PaperFill(
            paper_fill_id=new_id("pf"),
            paper_order_id=order.paper_order_id,
            signal_id=order.signal_id,
            token_id=order.token_id,
            side=order.side,
            raw_best_ask=book.best_ask,
            slippage_bps=self.fill_model.slippage_bps,
            fill_price=fill_price,
            stake_usdc=order.stake_usdc,
            shares=shares,
            depth_checked=self.fill_model.require_depth_check,
            available_depth_usdc=book.depth_until(order.limit_price),
            fill_ratio=1.0,
        )
        position = PaperPosition(
            paper_position_id=new_id("pp"),
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
            shares=shares,
            stake_usdc=order.stake_usdc,
            signal_confidence=order.signal_confidence,
        )
        order.status = OrderStatus.FILLED
        return IntentDispatchResult(order=order, fills=[fill], positions=[position], status=OrderStatus.FILLED)

    def _execute_fak(self, order: PaperOrder, book: OrderBook) -> IntentDispatchResult:
        remaining = order.stake_usdc
        filled_usdc = 0.0
        shares = 0.0
        for level in sorted(book.asks, key=lambda x: x.price):
            if level.price > order.limit_price:
                break
            available = level.price * level.size
            take = min(remaining, available)
            filled_usdc += take
            shares += take / level.price
            remaining -= take
            if remaining <= 0:
                break
        if filled_usdc <= 0 or shares <= 0:
            return self._reject(order, "FAK_NO_LIQUIDITY")
        fill_ratio = filled_usdc / order.stake_usdc
        fill_price = filled_usdc / shares
        slippage = fill_price * self.fill_model.slippage_bps / 10000
        fill_price_with_slippage = fill_price + slippage
        if fill_price_with_slippage > order.limit_price:
            return self._reject(order, "SLIPPAGE_EXCEEDS_MAX_ENTRY")
        fill = PaperFill(
            paper_fill_id=new_id("pf"),
            paper_order_id=order.paper_order_id,
            signal_id=order.signal_id,
            token_id=order.token_id,
            side=order.side,
            raw_best_ask=book.best_ask,
            slippage_bps=self.fill_model.slippage_bps,
            fill_price=fill_price_with_slippage,
            stake_usdc=filled_usdc,
            shares=shares,
            depth_checked=False,
            fill_ratio=fill_ratio,
        )
        position = PaperPosition(
            paper_position_id=new_id("pp"),
            signal_id=order.signal_id,
            paper_order_id=order.paper_order_id,
            paper_fill_id=fill.paper_fill_id,
            strategy=order.strategy, asset=order.asset, timeframe=order.timeframe,
            market_id=order.market_id, market_slug=order.market_slug,
            token_id=order.token_id, side=order.side,
            entry_price=fill_price_with_slippage, shares=shares, stake_usdc=filled_usdc,
            signal_confidence=order.signal_confidence,
        )
        status = OrderStatus.FILLED if fill_ratio >= 0.999 else OrderStatus.PARTIAL
        order.status = status
        return IntentDispatchResult(order=order, fills=[fill], positions=[position], status=status)

    def _execute_fok(self, order: PaperOrder, book: OrderBook) -> IntentDispatchResult:
        available = book.depth_until(order.limit_price)
        if available < order.stake_usdc:
            return self._reject(order, "FOK_INSUFFICIENT_DEPTH", available_depth_usdc=available)
        filled_usdc, shares, fill_price = self._consume_asks(order, book)
        fill = PaperFill(
            paper_fill_id=new_id("pf"),
            paper_order_id=order.paper_order_id,
            signal_id=order.signal_id,
            token_id=order.token_id,
            side=order.side,
            raw_best_ask=book.best_ask,
            slippage_bps=0.0,
            fill_price=fill_price,
            stake_usdc=order.stake_usdc,
            shares=shares,
            depth_checked=True,
            available_depth_usdc=available,
            fill_ratio=1.0,
        )
        position = PaperPosition(
            paper_position_id=new_id("pp"),
            signal_id=order.signal_id,
            paper_order_id=order.paper_order_id,
            paper_fill_id=fill.paper_fill_id,
            strategy=order.strategy, asset=order.asset, timeframe=order.timeframe,
            market_id=order.market_id, market_slug=order.market_slug,
            token_id=order.token_id, side=order.side,
            entry_price=fill_price, shares=shares, stake_usdc=order.stake_usdc,
            signal_confidence=order.signal_confidence,
        )
        order.status = OrderStatus.FILLED
        return IntentDispatchResult(order=order, fills=[fill], positions=[position], status=OrderStatus.FILLED)

    def _consume_asks(self, order: PaperOrder, book: OrderBook) -> tuple[float, float, float]:
        remaining = order.stake_usdc
        filled_usdc = 0.0
        shares = 0.0
        for level in sorted(book.asks, key=lambda x: x.price):
            if level.price > order.limit_price:
                break
            available = level.price * level.size
            take = min(remaining, available)
            filled_usdc += take
            shares += take / level.price
            remaining -= take
            if remaining <= 0:
                break
        fill_price = filled_usdc / shares if shares > 0 else 0.0
        return filled_usdc, shares, fill_price

    def _preflight_fok(self, order: PaperOrder, book: OrderBook) -> tuple[bool, str | None, float | None]:
        if book.token_id != order.token_id:
            return False, "MALFORMED_ORDERBOOK", None
        registry_reason = self._registry_reject_reason(order.token_id, order.created_at)
        if registry_reason is not None:
            return False, registry_reason, None
        if self.registry is None and not book.is_fresh(
            self.max_book_staleness_ms, order.created_at
        ):
            return False, "STALE_ORDERBOOK", None
        if not book.asks or book.best_ask is None:
            return False, "MISSING_BEST_ASK", None
        if book.best_ask > order.limit_price:
            return False, "ASK_ABOVE_MAX_ENTRY", None
        if any(
            not isfinite(level.price)
            or level.price <= 0
            or not isfinite(level.size)
            or level.size <= 0
            for level in book.asks
        ):
            return False, "MALFORMED_ORDERBOOK", None
        available = book.depth_until(order.limit_price)
        if available < order.stake_usdc:
            return False, "FOK_INSUFFICIENT_DEPTH", available
        return True, None, available

    def _reject(self, order: PaperOrder, reason: str, available_depth_usdc: float | None = None) -> IntentDispatchResult:
        order.status = OrderStatus.REJECTED
        order.reject_reason = reason
        order.metrics.setdefault("fill_decision_accepted", False)
        order.metrics["fill_decision_reason"] = reason
        if available_depth_usdc is not None:
            order.metrics["available_depth_usdc"] = available_depth_usdc
        return IntentDispatchResult(order=order, status=OrderStatus.REJECTED, reject_reason=reason)


class PassiveGtdExecutor:
    def __init__(self, max_book_staleness_ms: int = 10000):
        self._store: dict[str, list[RestingOrder]] = defaultdict(list)
        self.max_book_staleness_ms = max_book_staleness_ms

    def enqueue(self, order: PaperOrder, signal: SignalCandidate) -> IntentDispatchResult:
        expiry_ts = signal.created_at.timestamp() + (signal.expiry_seconds or 300)
        resting = RestingOrder(
            order=order,
            signal_id=signal.signal_id,
            limit_price=order.limit_price,
            expiry_ts=expiry_ts,
            pair_id=signal.pair_id,
        )
        self._store[order.token_id].append(resting)
        order.status = OrderStatus.RESTING
        return IntentDispatchResult(order=order, status=OrderStatus.RESTING)

    def tick(self, books, wallet, risk_check=None) -> list[IntentDispatchResult]:
        now = time.time()
        now_dt = datetime.fromtimestamp(now, tz=timezone.utc)
        results: list[IntentDispatchResult] = []
        for token_id in list(self._store.keys()):
            book = books.get(token_id)
            surviving: list[RestingOrder] = []
            for resting in self._store[token_id]:
                if now >= resting.expiry_ts:
                    resting.order.status = OrderStatus.CANCELLED
                    resting.order.reject_reason = "GTD_EXPIRED"
                    results.append(IntentDispatchResult(
                        order=resting.order, status=OrderStatus.CANCELLED, reject_reason="GTD_EXPIRED"
                    ))
                    continue
                if book is not None and book.best_bid is not None and book.best_bid >= resting.limit_price:
                    if hasattr(books, "is_fill_eligible") and not books.is_fill_eligible(
                        token_id, self.max_book_staleness_ms, now_dt
                    ):
                        state = books.get_state(token_id)
                        reason = state.stale_reason if state else "NO_SNAPSHOT"
                        resting.order.status = OrderStatus.REJECTED
                        resting.order.reject_reason = reason or "STALE_ORDERBOOK"
                        results.append(IntentDispatchResult(
                            order=resting.order,
                            status=OrderStatus.REJECTED,
                            reject_reason=resting.order.reject_reason,
                        ))
                        continue
                    can_fill = wallet.can_afford(resting.order.stake_usdc)
                    if can_fill and risk_check is not None:
                        can_fill = risk_check(resting.order)
                    if can_fill:
                        fill = PaperFill(
                            paper_fill_id=new_id("pf"),
                            paper_order_id=resting.order.paper_order_id,
                            signal_id=resting.signal_id,
                            token_id=resting.order.token_id,
                            side=resting.order.side,
                            raw_best_ask=resting.limit_price,
                            slippage_bps=0.0,
                            fill_price=resting.limit_price,
                            stake_usdc=resting.order.stake_usdc,
                            shares=resting.order.stake_usdc / resting.limit_price,
                            depth_checked=False,
                            fill_ratio=1.0,
                        )
                        position = PaperPosition(
                            paper_position_id=new_id("pp"),
                            signal_id=resting.signal_id,
                            paper_order_id=resting.order.paper_order_id,
                            paper_fill_id=fill.paper_fill_id,
                            strategy=resting.order.strategy,
                            asset=resting.order.asset,
                            timeframe=resting.order.timeframe,
                            market_id=resting.order.market_id,
                            market_slug=resting.order.market_slug,
                            token_id=resting.order.token_id,
                            side=resting.order.side,
                            entry_price=resting.limit_price,
                            shares=resting.order.stake_usdc / resting.limit_price,
                            stake_usdc=resting.order.stake_usdc,
                            signal_confidence=resting.order.signal_confidence,
                        )
                        wallet.apply_fill(position)
                        resting.order.status = OrderStatus.FILLED
                        results.append(IntentDispatchResult(
                            order=resting.order, fills=[fill], positions=[position], status=OrderStatus.FILLED
                        ))
                    else:
                        resting.order.status = OrderStatus.CANCELLED
                        resting.order.reject_reason = "WALLET_INSUFFICIENT_CASH"
                        results.append(IntentDispatchResult(
                            order=resting.order, status=OrderStatus.CANCELLED, reject_reason="WALLET_INSUFFICIENT_CASH"
                        ))
                    continue
                surviving.append(resting)
            if surviving:
                self._store[token_id] = surviving
            else:
                del self._store[token_id]
        return results

    @property
    def resting_count(self) -> int:
        return sum(len(orders) for orders in self._store.values())


class MultiLegCoordinator:
    def __init__(self):
        self._pair_legs: dict[str, dict[str, bool]] = defaultdict(dict)  # pair_id -> {signal_id: filled}
        self._pending_fok: dict[str, tuple[SignalCandidate, PaperOrder, object]] = {}
        self._failed_pairs: set[str] = set()

    def register(self, signal: SignalCandidate) -> None:
        if signal.pair_id:
            leg_data = self._pair_legs[signal.pair_id]
            leg_data[signal.signal_id] = False

    def record_pending(self, signal: SignalCandidate, order: PaperOrder, book: object) -> None:
        if signal.pair_id and signal.hedge_leg is False:
            self._pending_fok[signal.signal_id] = (signal, order, book)

    def try_execute_fok_pair(
        self, hedge_signal: SignalCandidate, hedge_order: PaperOrder, hedge_book: OrderBook, executor: BestAskTakerExecutor
    ) -> IntentDispatchResult | None:
        pair_id = hedge_signal.pair_id
        if pair_id is None:
            return None

        # Find the pending first leg signal
        pending_key: str | None = None
        for sid, (sig, _order, _book) in self._pending_fok.items():
            if sig.pair_id == pair_id:
                pending_key = sid
                leg1_sig = sig
                leg1_order = _order
                leg1_book = _book
                break

        if pending_key is None:
            return None

        leg1_ok, leg1_reason, leg1_available = executor._preflight_fok(leg1_order, leg1_book)
        hedge_ok, hedge_reason, hedge_available = executor._preflight_fok(hedge_order, hedge_book)
        if not leg1_ok or not hedge_ok:
            reason = leg1_reason if not leg1_ok else hedge_reason
            result_order = leg1_order if not leg1_ok else hedge_order
            available = leg1_available if not leg1_ok else hedge_available
            result = executor._reject(result_order, reason or "FOK_PAIR_REJECTED", available_depth_usdc=available)
            if leg1_order.status != OrderStatus.REJECTED:
                executor._reject(leg1_order, "FOK_PAIR_REJECTED")
            if hedge_order.status != OrderStatus.REJECTED:
                executor._reject(hedge_order, "FOK_PAIR_REJECTED")
            self._pair_failed(pair_id, result)
            return result

        result1 = executor.execute(leg1_order, leg1_book, OrderIntent.TAKER_FOK)
        result2 = executor.execute(hedge_order, hedge_book, OrderIntent.TAKER_FOK)

        # Both filled — combine results
        combined = IntentDispatchResult(
            order=leg1_order,
            fills=result1.fills + result2.fills,
            positions=result1.positions + result2.positions,
            status=OrderStatus.FILLED,
        )
        self._pair_legs[pair_id][leg1_sig.signal_id] = True
        self._pair_legs[pair_id][hedge_signal.signal_id] = True
        del self._pending_fok[pending_key]
        return combined

    def cancel_pair(self, pair_id: str) -> list[str]:
        cancelled: list[str] = []
        for sid in list(self._pending_fok.keys()):
            sig, _order, _book = self._pending_fok[sid]
            if sig.pair_id == pair_id:
                cancelled.append(sid)
                del self._pending_fok[sid]
        self._pair_legs.pop(pair_id, None)
        return cancelled

    def any_leg_failed(self, pair_id: str) -> bool:
        return pair_id in self._failed_pairs

    def _pair_failed(self, pair_id: str, result: IntentDispatchResult) -> None:
        self._failed_pairs.add(pair_id)
        self.cancel_pair(pair_id)
