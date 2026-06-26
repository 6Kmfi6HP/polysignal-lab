from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
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


@dataclass(slots=True)
class _NautilusSession:
    loop: Any
    clock: Any
    msgbus: Any
    cache: Any
    portfolio: Any
    exec_engine: Any
    sandbox: Any
    order_factory: Any
    order_events: list[Any]
    components: dict[str, Any]



@dataclass(slots=True)
class _DirectNautilusSandbox:
    exchange: Any
    exec_client: Any

    def connect(self) -> None:
        starter = getattr(self.exec_client, "_start", None)
        if starter is not None:
            starter()

    def submit_order(self, command: Any) -> Any:
        return self.exec_client.submit_order(command)

    def on_data(self, data: Any) -> None:
        self.exchange.process_order_book_deltas(data)
        self.exchange.process(data.ts_init)

class OwnedNautilusMatchingBoundary:
    """Lazy boundary for the owned Nautilus sandbox matching path."""

    def __init__(self, settings: MatchingAccuracySettings) -> None:
        self.settings = settings
        self._books: dict[str, OrderBook] = {}
        self._instruments: dict[str, Any] = {}
        self._dirty_books: set[str] = set()
        self._published_books: set[str] = set()
        self._session: _NautilusSession | None = None
        self._sequence = 0

    def update_book(self, token_id: str, book: OrderBook) -> None:
        self._books[token_id] = book
        self._dirty_books.add(token_id)
        if self._session is not None and token_id in self._instruments:
            self._publish_book_to_nautilus(token_id, book)
            self._dirty_books.discard(token_id)
            self._published_books.add(token_id)

    def submit_order(self, order: PaperOrder, spec: NautilusOrderSpec) -> NautilusMatchingOutcome:
        book = self._books.get(order.token_id)
        if book is None:
            return NautilusMatchingOutcome(status=OrderStatus.REJECTED, reason="MISSING_ORDERBOOK")
        if book.best_ask is not None and book.best_ask > order.limit_price:
            return NautilusMatchingOutcome(status=OrderStatus.REJECTED, reason="PRICE_ABOVE_LIMIT")
        self._ensure_session()
        instrument = self._ensure_instrument(order, spec, book)
        if order.token_id in self._dirty_books or order.token_id not in self._published_books:
            self._publish_book_to_nautilus(order.token_id, book)
            self._dirty_books.discard(order.token_id)
            self._published_books.add(order.token_id)
        return self._submit_limit_order_through_nautilus(order, spec, instrument)

    def _ensure_session(self) -> None:
        if self._session is not None:
            return
        components = self._load_nautilus_components()
        loop = components["asyncio"].new_event_loop()
        clock = components["TestClock"]()
        if hasattr(clock, "set_time"):
            clock.set_time(0)
        trader_id = components["TraderId"]("POLYSIGNAL-001")
        msgbus = components["MessageBus"](trader_id, clock)
        cache = components["Cache"](database=None)
        portfolio = components["Portfolio"](msgbus=msgbus, cache=cache, clock=clock)
        exec_engine = components["ExecutionEngine"](msgbus=msgbus, cache=cache, clock=clock)
        order_events: list[Any] = []
        msgbus.subscribe("events.order.*", handler=order_events.append)
        exchange = components["SimulatedExchange"](
            venue=components["Venue"](components["DEFAULT_VENUE"]),
            oms_type=components["oms_type_from_str"]("NETTING"),
            account_type=components["account_type_from_str"]("CASH"),
            starting_balances=[components["Money"].from_str("100_000 USDC")],
            base_currency=components["Currency"].from_str("USDC"),
            default_leverage=Decimal(1),
            leverages={},
            modules=[],
            portfolio=portfolio,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            fill_model=components["FillModel"](),
            fee_model=components["MakerTakerFeeModel"](),
            latency_model=components["LatencyModel"](0),
            book_type=components["book_type_from_str"](self.settings.book_type),
            frozen_account=False,
            bar_execution=self.settings.bar_execution,
            trade_execution=self.settings.trade_execution,
            reject_stop_orders=True,
            support_gtd_orders=self.settings.support_gtd_orders,
            support_contingent_orders=self.settings.support_contingent_orders,
            use_position_ids=True,
            use_random_ids=False,
            use_reduce_only=self.settings.use_reduce_only,
            use_message_queue=False,
            liquidity_consumption=self.settings.liquidity_consumption,
            queue_position=self.settings.queue_position,
            price_protection_points=self.settings.price_protection_points,
        )
        exec_client = components["BacktestExecClient"](
            exchange=exchange,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
        )
        exchange.register_client(exec_client)
        exchange.initialize_account()
        exec_engine.register_client(exec_client)
        sandbox = _DirectNautilusSandbox(exchange=exchange, exec_client=exec_client)
        order_factory = components["OrderFactory"](
            trader_id=trader_id,
            strategy_id=components["StrategyId"]("S-001"),
            clock=clock,
            cache=cache,
        )
        sandbox.connect()
        self._session = _NautilusSession(
            loop=loop,
            clock=clock,
            msgbus=msgbus,
            cache=cache,
            portfolio=portfolio,
            exec_engine=exec_engine,
            sandbox=sandbox,
            order_factory=order_factory,
            order_events=order_events,
            components=components,
        )

    def _load_nautilus_components(self) -> dict[str, Any]:
        try:
            import asyncio

            from nautilus_trader.backtest.engine import SimulatedExchange
            from nautilus_trader.backtest.execution_client import BacktestExecClient
            from nautilus_trader.backtest.models import FillModel, LatencyModel, MakerTakerFeeModel
            from nautilus_trader.cache.cache import Cache
            from nautilus_trader.common.component import MessageBus, TestClock
            from nautilus_trader.common.factories import OrderFactory
            from nautilus_trader.execution.engine import ExecutionEngine
            from nautilus_trader.core.uuid import UUID4
            from nautilus_trader.execution.messages import SubmitOrder
            from nautilus_trader.model.data import BookOrder, OrderBookDelta, OrderBookDeltas
            from nautilus_trader.model.enums import (
                BookAction,
                OrderSide,
                TimeInForce,
                account_type_from_str,
                book_type_from_str,
                oms_type_from_str,
            )
            from nautilus_trader.model.identifiers import StrategyId, TraderId, Venue
            from nautilus_trader.model.objects import Currency, Money, Price, Quantity
            from nautilus_trader.portfolio.portfolio import Portfolio
        except Exception as exc:  # pragma: no cover - depends on optional Nautilus runtime
            raise NautilusMatchingUnavailable() from exc

        from polysignal_lab.nautilus_runtime.instrument_mapping import DEFAULT_VENUE

        return {
            "account_type_from_str": account_type_from_str,
            "asyncio": asyncio,
            "BacktestExecClient": BacktestExecClient,
            "BookAction": BookAction,
            "BookOrder": BookOrder,
            "book_type_from_str": book_type_from_str,
            "Cache": Cache,
            "Currency": Currency,
            "DEFAULT_VENUE": DEFAULT_VENUE,
            "ExecutionEngine": ExecutionEngine,
            "FillModel": FillModel,
            "LatencyModel": LatencyModel,
            "MakerTakerFeeModel": MakerTakerFeeModel,
            "MessageBus": MessageBus,
            "Money": Money,
            "oms_type_from_str": oms_type_from_str,
            "OrderBookDelta": OrderBookDelta,
            "OrderBookDeltas": OrderBookDeltas,
            "OrderFactory": OrderFactory,
            "OrderSide": OrderSide,
            "Portfolio": Portfolio,
            "Price": Price,
            "Quantity": Quantity,
            "SimulatedExchange": SimulatedExchange,
            "StrategyId": StrategyId,
            "SubmitOrder": SubmitOrder,
            "UUID4": UUID4,
            "TestClock": TestClock,
            "TimeInForce": TimeInForce,
            "TraderId": TraderId,
            "Venue": Venue,
        }

    def _ensure_instrument(self, order: PaperOrder, spec: NautilusOrderSpec, book: OrderBook) -> Any:
        if order.token_id in self._instruments:
            return self._instruments[order.token_id]
        session = self._require_session()
        from polysignal_lab.nautilus_bridge.market_registry import (
            InstrumentTokenMeta,
            MarketPairMeta,
        )
        from polysignal_lab.nautilus_runtime.instrument_mapping import (
            build_binary_option,
            instrument_id_for_token,
        )

        current = InstrumentTokenMeta(
            instrument_id=instrument_id_for_token(order.token_id),
            token_id=order.token_id,
            side=order.side,
        )
        other_side = order.side.opposite
        other = InstrumentTokenMeta(
            instrument_id=instrument_id_for_token(f"{order.token_id}-{other_side.value.lower()}"),
            token_id=f"{order.token_id}-{other_side.value.lower()}",
            side=other_side,
        )
        pair = MarketPairMeta(
            market_id=order.market_id,
            market_slug=order.market_slug,
            condition_id=str(order.metrics.get("condition_id", "")),
            asset=order.asset,
            timeframe=order.timeframe,
            start_ts=None,
            end_ts=None,
            up=current if order.side == Side.UP else other,
            down=current if order.side == Side.DOWN else other,
        )
        token = pair.up if order.side == Side.UP else pair.down
        instrument = build_binary_option(
            pair,
            token,
            tick_size=book.tick_size,
            min_order_size=book.min_order_size,
            ts_init_ns=session.clock.timestamp_ns(),
        )
        session.cache.add_instrument(instrument)
        if instrument.id not in session.sandbox.exchange.instruments:
            session.sandbox.exchange.add_instrument(instrument)
        self._instruments[order.token_id] = instrument
        return instrument

    def _publish_book_to_nautilus(self, token_id: str, book: OrderBook) -> None:
        session = self._require_session()
        instrument = self._instruments[token_id]
        components = session.components
        ts = _datetime_to_unix_ns(book.received_at)
        self._sequence += 1
        deltas = [
            components["OrderBookDelta"].clear(instrument.id, self._sequence, ts, ts),
        ]
        order_id = 1
        for level in sorted(book.bids, key=lambda value: value.price, reverse=True):
            if level.price <= 0 or level.size <= 0:
                continue
            self._sequence += 1
            deltas.append(
                components["OrderBookDelta"](
                    instrument_id=instrument.id,
                    action=components["BookAction"].ADD,
                    order=components["BookOrder"](
                        components["OrderSide"].BUY,
                        components["Price"].from_str(_decimal_str(level.price)),
                        components["Quantity"].from_str(_decimal_str(level.size)),
                        order_id,
                    ),
                    flags=0,
                    sequence=self._sequence,
                    ts_event=ts,
                    ts_init=ts,
                )
            )
            order_id += 1
        for level in sorted(book.asks, key=lambda value: value.price):
            if level.price <= 0 or level.size <= 0:
                continue
            self._sequence += 1
            deltas.append(
                components["OrderBookDelta"](
                    instrument_id=instrument.id,
                    action=components["BookAction"].ADD,
                    order=components["BookOrder"](
                        components["OrderSide"].SELL,
                        components["Price"].from_str(_decimal_str(level.price)),
                        components["Quantity"].from_str(_decimal_str(level.size)),
                        order_id,
                    ),
                    flags=0,
                    sequence=self._sequence,
                    ts_event=ts,
                    ts_init=ts,
                )
            )
            order_id += 1
        session.sandbox.on_data(components["OrderBookDeltas"](instrument.id, deltas))

    def _submit_limit_order_through_nautilus(
        self,
        order: PaperOrder,
        spec: NautilusOrderSpec,
        instrument: Any,
    ) -> NautilusMatchingOutcome:
        session = self._require_session()
        components = session.components
        time_in_force = (
            components["TimeInForce"].FOK
            if spec.intent == OrderIntent.TAKER_FOK
            else components["TimeInForce"].IOC
        )
        nautilus_order = session.order_factory.limit(
            instrument_id=instrument.id,
            order_side=components["OrderSide"].BUY,
            quantity=components["Quantity"].from_str(_decimal_str(spec.quantity)),
            price=components["Price"].from_str(_decimal_str(order.limit_price)),
            time_in_force=time_in_force,
            reduce_only=order.reduce_only,
            tags=[f"paper_order_id={order.paper_order_id}"],
        )
        start_index = len(session.order_events)
        command = components["SubmitOrder"](
            trader_id=nautilus_order.trader_id,
            strategy_id=nautilus_order.strategy_id,
            order=nautilus_order,
            command_id=components["UUID4"](),
            ts_init=session.clock.timestamp_ns(),
        )
        session.sandbox.submit_order(command)
        events = [
            event
            for event in session.order_events[start_index:]
            if _identifier_value(getattr(event, "client_order_id", None))
            == _identifier_value(nautilus_order.client_order_id)
        ]
        return self._outcome_from_nautilus_events(order, events)

    def _outcome_from_nautilus_events(
        self,
        order: PaperOrder,
        events: list[Any],
    ) -> NautilusMatchingOutcome:
        rejected = next((event for event in events if type(event).__name__ == "OrderRejected"), None)
        if rejected is not None:
            return NautilusMatchingOutcome(
                status=OrderStatus.REJECTED,
                reason=str(getattr(rejected, "reason", "MATCHING_REJECTED")),
            )
        fills = [event for event in events if type(event).__name__ == "OrderFilled"]
        if not fills:
            return NautilusMatchingOutcome(status=OrderStatus.REJECTED, reason="INSUFFICIENT_DEPTH")
        book = self._books.get(order.token_id)
        raw_best_ask = book.best_ask if book is not None and book.best_ask is not None else None
        available_depth_usdc = (
            _available_depth_usdc(book, order.limit_price) if book is not None else None
        )
        fill_events: list[NautilusFillEvent] = []
        for fill in fills:
            fill_price = float(fill.last_px)
            shares = float(fill.last_qty)
            fill_events.append(
                NautilusFillEvent(
                    fill_price=fill_price,
                    shares=shares,
                    stake_usdc=fill_price * shares,
                    raw_best_ask=raw_best_ask or fill_price,
                    available_depth_usdc=available_depth_usdc,
                    fill_ratio=shares / (order.shares or shares),
                    fill_id=_identifier_value(getattr(fill, "trade_id", None)),
                    position_id=_identifier_value(getattr(fill, "position_id", None)),
                )
            )
        filled_shares = sum(event.shares for event in fill_events)
        status = (
            OrderStatus.FILLED
            if order.shares is None or filled_shares >= order.shares
            else OrderStatus.PARTIAL
        )
        return NautilusMatchingOutcome(status=status, fills=tuple(fill_events))

    def _require_session(self) -> _NautilusSession:
        if self._session is None:
            raise NautilusMatchingUnavailable()
        return self._session

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
        seen_fill_ids: set[str] = set()
        for event in outcome.fills:
            if event.fill_id is not None:
                if event.fill_id in self._mirrored_fill_ids or event.fill_id in seen_fill_ids:
                    continue
                seen_fill_ids.add(event.fill_id)
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

        if not positions:
            order.status = outcome.status
            return PaperExecutionResult(
                order=order,
                status=outcome.status,
                reason=outcome.reason,
            )

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




def _decimal_str(value: float) -> str:
    return format(Decimal(str(value)).normalize(), "f")


def _identifier_value(value: Any) -> str | None:
    if value is None:
        return None
    raw = getattr(value, "value", None)
    return str(raw if raw is not None else value)


def _datetime_to_unix_ns(value: datetime) -> int:
    dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    delta = dt.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000


def _available_depth_usdc(book: OrderBook, limit_price: float) -> float:
    return sum(level.price * level.size for level in book.asks if level.price <= limit_price)


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
