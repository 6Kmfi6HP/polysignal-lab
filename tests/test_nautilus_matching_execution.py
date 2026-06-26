from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from polysignal_lab.alpha.types import NautilusOrderSpec
from polysignal_lab.domain.enums import OrderIntent, OrderStatus, Side
from polysignal_lab.domain.orderbook import BookLevel, OrderBook
from polysignal_lab.nautilus_runtime.matching import (
    MatchingAccuracySettings,
    NautilusFillEvent,
    NautilusMatchingOutcome,
    OwnedNautilusMatchingBoundary,
    NautilusMatchingPaperExecutionClient,
)
from polysignal_lab.paper.wallet import PaperWallet


def _spec(
    *,
    token_id: str = "token-up",
    price: float = 0.82,
    quantity: float = 3.0,
    intent: OrderIntent = OrderIntent.TAKER_IOC,
    max_entry_price: str = "0.84",
) -> NautilusOrderSpec:
    return NautilusOrderSpec(
        instrument_id=token_id,
        side=Side.UP,
        price=price,
        quantity=quantity,
        intent=intent,
        expiry_seconds=None,
        pair_id="pair-1",
        reduce_only=False,
        hedge_leg=False,
        tags={
            "strategy": "late_consensus",
            "asset": "BTC",
            "timeframe": "5m",
            "market_id": "btc-5m",
            "condition_id": "condition-btc-5m",
            "signal_id": "signal-1",
            "confidence": "0.71",
            "max_entry_price": max_entry_price,
            "entry_reference_price": "0.82",
        },
    )


def _book(*, token_id: str = "token-up", ask_price: float = 0.82, ask_size: float = 500.0) -> OrderBook:
    return OrderBook(
        token_id=token_id,
        bids=[BookLevel(price=0.80, size=100.0)],
        asks=[BookLevel(price=ask_price, size=ask_size)],
        received_at=datetime.now(UTC),
    )

class FakeNautilusBoundary:
    def __init__(self, outcomes: list[NautilusMatchingOutcome] | None = None) -> None:
        self.books: dict[str, OrderBook] = {}
        self.outcomes = list(outcomes or [])
        self.submitted_orders = []
        self.remaining_shares: dict[str, float] = {}

    def update_book(self, token_id: str, book: OrderBook) -> None:
        self.books[token_id] = book
        self.remaining_shares[token_id] = sum(level.size for level in book.asks)

    def submit_order(self, order, spec) -> NautilusMatchingOutcome:
        self.submitted_orders.append(order)
        if self.outcomes:
            return self.outcomes.pop(0)
        book = self.books[spec.instrument_id]
        best_ask = book.best_ask
        assert best_ask is not None
        if best_ask > order.limit_price:
            return NautilusMatchingOutcome(status=OrderStatus.REJECTED, reason="PRICE_ABOVE_LIMIT")
        available = self.remaining_shares.get(spec.instrument_id, 0.0)
        if spec.intent == OrderIntent.TAKER_FOK and available < spec.quantity:
            return NautilusMatchingOutcome(status=OrderStatus.REJECTED, reason="INSUFFICIENT_DEPTH")
        shares = min(spec.quantity, available)
        if shares <= 0:
            return NautilusMatchingOutcome(status=OrderStatus.REJECTED, reason="INSUFFICIENT_DEPTH")
        self.remaining_shares[spec.instrument_id] = available - shares
        return NautilusMatchingOutcome(
            status=OrderStatus.FILLED,
            fills=(
                NautilusFillEvent(
                    fill_price=best_ask,
                    shares=shares,
                    stake_usdc=best_ask * shares,
                    raw_best_ask=best_ask,
                    available_depth_usdc=best_ask * available,
                    fill_ratio=shares / spec.quantity,
                ),
            ),
        )


def test_accuracy_settings_match_spec_modes() -> None:
    fast_l1 = MatchingAccuracySettings.from_mode("fast_l1")
    depth_l2 = MatchingAccuracySettings.from_mode("depth_l2")
    queue_l2 = MatchingAccuracySettings.from_mode("queue_l2")

    assert fast_l1.book_type == "L1_MBP"
    assert fast_l1.liquidity_consumption is False
    assert depth_l2.book_type == "L2_MBP"
    assert depth_l2.liquidity_consumption is True
    assert depth_l2.queue_position is False
    assert queue_l2.queue_position is True


def test_matching_client_constructs_without_credentials() -> None:
    client = NautilusMatchingPaperExecutionClient(
        wallet=PaperWallet(),
        accuracy_mode="depth_l2",
    )

    assert client.paper_engine == "nautilus_matching"
    assert client.accuracy_mode == "depth_l2"


def test_submit_without_book_rejects() -> None:
    client = NautilusMatchingPaperExecutionClient(wallet=PaperWallet())

    result = client.submit_spec(_spec())

    assert result.status == OrderStatus.REJECTED
    assert result.reason == "MISSING_ORDERBOOK"


def test_unsupported_side_rejects_before_paper_order_construction() -> None:
    client = NautilusMatchingPaperExecutionClient(wallet=PaperWallet())
    spec = replace(_spec(), side="SIDEWAYS")  # type: ignore[arg-type]

    result = client.submit_spec(spec)

    assert result.status == OrderStatus.REJECTED
    assert result.reason == "UNSUPPORTED_SIDE"
    assert result.order is None

def test_update_book_rejects_stale_book_before_matching() -> None:
    client = NautilusMatchingPaperExecutionClient(
        wallet=PaperWallet(),
        max_book_staleness_ms=1_000,
    )
    stale_book = OrderBook(
        token_id="token-up",
        bids=[BookLevel(price=0.80, size=10.0)],
        asks=[BookLevel(price=0.83, size=10.0)],
        received_at=datetime.now(UTC) - timedelta(seconds=2),
    )

    client.update_book("token-up", stale_book)
    result = client.submit_spec(_spec())

    assert result.status == OrderStatus.REJECTED
    assert result.reason == "STALE_ORDERBOOK"


def test_update_trade_records_recent_trade_for_queue_mode() -> None:
    client = NautilusMatchingPaperExecutionClient(
        wallet=PaperWallet(),
        accuracy_mode="queue_l2",
    )
    ts_event = datetime.now(UTC)

    client.update_trade("token-up", price=0.84, size=2.5, side="BUY", ts_event=ts_event)
    trades = client.recent_trades_for("token-up")

    assert len(trades) == 1
    assert trades[0].price == 0.84
    assert trades[0].size == 2.5
    assert trades[0].side == "BUY"
    assert trades[0].ts_event == ts_event


def test_submit_spec_mirrors_nautilus_fill_event_without_local_repricing() -> None:
    boundary = FakeNautilusBoundary(
        [
            NautilusMatchingOutcome(
                status=OrderStatus.FILLED,
                fills=(
                    NautilusFillEvent(
                        fill_price=0.81,
                        shares=7.0,
                        stake_usdc=5.67,
                        raw_best_ask=0.82,
                        available_depth_usdc=8.2,
                        fill_ratio=0.7,
                    ),
                ),
            )
        ]
    )
    client = NautilusMatchingPaperExecutionClient(
        wallet=PaperWallet(),
        matching_boundary=boundary,
    )
    client.update_book("token-up", _book(ask_price=0.82, ask_size=500.0))

    result = client.submit_spec(_spec(quantity=10.0, max_entry_price="0.83"))

    assert boundary.submitted_orders
    assert result.status == OrderStatus.FILLED
    assert result.fills[0].fill_price == 0.81
    assert result.fills[0].shares == 7.0
    assert result.positions[0].stake_usdc == 5.67
    assert result.positions[0].paper_position_id in client.wallet.open_positions


def test_replayed_fill_id_is_not_returned_or_applied_twice() -> None:
    fill = NautilusFillEvent(
        fill_price=0.82,
        shares=4.0,
        stake_usdc=3.28,
        raw_best_ask=0.82,
        available_depth_usdc=8.2,
        fill_ratio=1.0,
        fill_id="nautilus-fill-1",
        position_id="nautilus-position-1",
    )
    boundary = FakeNautilusBoundary(
        [
            NautilusMatchingOutcome(status=OrderStatus.FILLED, fills=(fill,)),
            NautilusMatchingOutcome(status=OrderStatus.FILLED, fills=(fill,)),
        ]
    )
    wallet = PaperWallet(starting_balance=100.0)
    client = NautilusMatchingPaperExecutionClient(wallet=wallet, matching_boundary=boundary)
    client.update_book("token-up", _book())

    first = client.submit_spec(_spec(quantity=4.0, max_entry_price="0.83"))
    cash_after_first = wallet.cash_balance

    second = client.submit_spec(_spec(quantity=4.0, max_entry_price="0.83"))

    assert first.status == OrderStatus.FILLED
    assert len(first.fills) == 1
    assert len(first.positions) == 1
    assert second.status == OrderStatus.FILLED
    assert second.fills == []
    assert second.positions == []
    assert wallet.cash_balance == cash_after_first
    assert list(wallet.open_positions) == ["nautilus-position-1"]


def test_owned_boundary_stores_books_and_delegates_to_nautilus_path() -> None:
    class ContractBoundary(OwnedNautilusMatchingBoundary):
        def __init__(self) -> None:
            super().__init__(MatchingAccuracySettings.from_mode("depth_l2"))
            self.ensured = False
            self.instruments: list[str] = []
            self.published: list[str] = []
            self.submitted: list[str] = []

        def _ensure_session(self) -> None:
            self.ensured = True

        def _ensure_instrument(self, order, spec, book):
            self.instruments.append(order.token_id)
            return object()

        def _publish_book_to_nautilus(self, token_id: str, book: OrderBook) -> None:
            self.published.append(token_id)

        def _submit_limit_order_through_nautilus(self, order, spec, instrument):
            self.submitted.append(order.paper_order_id)
            return NautilusMatchingOutcome(
                status=OrderStatus.FILLED,
                fills=(
                    NautilusFillEvent(
                        fill_price=0.82,
                        shares=2.0,
                        stake_usdc=1.64,
                        raw_best_ask=0.82,
                    ),
                ),
            )

    boundary = ContractBoundary()
    book = _book()
    boundary.update_book("token-up", book)
    order = NautilusMatchingPaperExecutionClient()._paper_order_from_spec(
        _spec(quantity=2.0, max_entry_price="0.83")
    )

    outcome = boundary.submit_order(order, _spec(quantity=2.0, max_entry_price="0.83"))

    assert boundary._books["token-up"] is book
    assert boundary.ensured is True
    assert boundary.instruments == ["token-up"]
    assert boundary.published == ["token-up"]
    assert boundary.submitted == [order.paper_order_id]
    assert outcome.status == OrderStatus.FILLED
def test_taker_fills_at_book_price_not_slippage_model() -> None:
    client = NautilusMatchingPaperExecutionClient(
        wallet=PaperWallet(),
        matching_boundary=FakeNautilusBoundary(),
    )
    client.update_book("token-up", _book(ask_price=0.82, ask_size=500.0))

    result = client.submit_spec(_spec(quantity=10.0, max_entry_price="0.83"))

    assert result.status == OrderStatus.FILLED
    assert result.fills[0].fill_price == 0.82
    assert result.order is not None
    assert result.order.limit_price == 0.83
    assert result.order.reference_price == 0.82
    assert result.positions[0].paper_position_id in client.wallet.open_positions


def test_best_ask_above_max_entry_is_rejected() -> None:
    client = NautilusMatchingPaperExecutionClient(
        wallet=PaperWallet(),
        matching_boundary=FakeNautilusBoundary(),
    )
    client.update_book("token-up", _book(ask_price=0.84, ask_size=500.0))

    result = client.submit_spec(_spec(quantity=10.0, max_entry_price="0.83"))

    assert result.status == OrderStatus.REJECTED
    assert result.reason == "PRICE_ABOVE_LIMIT"


def test_fok_rejects_when_full_depth_unavailable() -> None:
    client = NautilusMatchingPaperExecutionClient(
        wallet=PaperWallet(),
        matching_boundary=FakeNautilusBoundary(),
    )
    client.update_book("token-up", _book(ask_price=0.82, ask_size=5.0))

    result = client.submit_spec(
        _spec(quantity=10.0, intent=OrderIntent.TAKER_FOK, max_entry_price="0.83")
    )

    assert result.status == OrderStatus.REJECTED
    assert result.reason == "INSUFFICIENT_DEPTH"


def test_liquidity_consumption_prevents_reusing_same_level() -> None:
    client = NautilusMatchingPaperExecutionClient(
        wallet=PaperWallet(),
        matching_boundary=FakeNautilusBoundary(),
    )
    client.update_book("token-up", _book(ask_price=0.82, ask_size=12.0))

    first = client.submit_spec(_spec(quantity=10.0, max_entry_price="0.83"))
    second = client.submit_spec(_spec(quantity=10.0, max_entry_price="0.83"))

    assert first.status == OrderStatus.FILLED
    assert first.fills[0].shares == 10.0
    assert second.status == OrderStatus.FILLED
    assert second.fills[0].shares == 2.0



def test_owned_boundary_rejects_best_ask_above_limit_before_session() -> None:
    class Boundary(OwnedNautilusMatchingBoundary):
        def __init__(self) -> None:
            super().__init__(MatchingAccuracySettings.from_mode("depth_l2"))
            self.ensured = False
            self.submitted = False

        def _ensure_session(self) -> None:
            self.ensured = True

        def _ensure_instrument(self, order, spec, book):
            return object()

        def _publish_book_to_nautilus(self, token_id: str, book: OrderBook) -> None:
            return None

        def _submit_limit_order_through_nautilus(self, order, spec, instrument):
            self.submitted = True
            return NautilusMatchingOutcome(status=OrderStatus.FILLED)

    boundary = Boundary()
    boundary.update_book("token-up", _book(ask_price=0.84, ask_size=500.0))
    spec = _spec(quantity=10.0, max_entry_price="0.83")
    order = NautilusMatchingPaperExecutionClient()._paper_order_from_spec(spec)

    outcome = boundary.submit_order(order, spec)

    assert outcome.status == OrderStatus.REJECTED
    assert outcome.reason == "PRICE_ABOVE_LIMIT"
    assert boundary.ensured is False
    assert boundary.submitted is False


def test_owned_boundary_republishes_only_after_fresh_book_update() -> None:
    class FakeClock:
        def timestamp_ns(self) -> int:
            return 1

    class FakeOrderFactory:
        def limit(self, **kwargs):
            return SimpleNamespace(
                trader_id="trader",
                strategy_id="strategy",
                client_order_id="client-order-1",
            )

    class FakeTimeInForce:
        FOK = "FOK"
        IOC = "IOC"

    class FakeOrderSide:
        BUY = "BUY"

    class FakeQuantity:
        @staticmethod
        def from_str(value: str) -> str:
            return value

    class FakePrice:
        @staticmethod
        def from_str(value: str) -> str:
            return value

    class FakeSubmitOrder:
        def __init__(self, **kwargs) -> None:
            self.__dict__.update(kwargs)

    class Boundary(OwnedNautilusMatchingBoundary):
        def __init__(self) -> None:
            super().__init__(MatchingAccuracySettings.from_mode("depth_l2"))
            self.published: list[str] = []
            self.submitted: list[FakeSubmitOrder] = []

        def _ensure_session(self) -> None:
            self._session = SimpleNamespace(
                clock=FakeClock(),
                order_factory=FakeOrderFactory(),
                order_events=[],
                sandbox=SimpleNamespace(submit_order=self.submitted.append),
                components={
                    "OrderSide": FakeOrderSide,
                    "Price": FakePrice,
                    "Quantity": FakeQuantity,
                    "SubmitOrder": FakeSubmitOrder,
                    "TimeInForce": FakeTimeInForce,
                    "UUID4": lambda: "command-1",
                },
            )

        def _ensure_instrument(self, order, spec, book):
            instrument = SimpleNamespace(id="instrument-1")
            self._instruments[order.token_id] = instrument
            return instrument

        def _publish_book_to_nautilus(self, token_id: str, book: OrderBook) -> None:
            self.published.append(token_id)

    boundary = Boundary()
    boundary.update_book("token-up", _book(ask_price=0.82, ask_size=500.0))
    spec = _spec(quantity=10.0, max_entry_price="0.83")
    order = NautilusMatchingPaperExecutionClient()._paper_order_from_spec(spec)

    boundary.submit_order(order, spec)
    boundary.submit_order(order, spec)

    assert boundary.submitted
    assert boundary.published == ["token-up"]

    boundary.update_book("token-up", _book(ask_price=0.81, ask_size=500.0))
    boundary.submit_order(order, spec)

    assert boundary.published == ["token-up", "token-up"]


def test_owned_boundary_configures_exchange_with_accuracy_settings() -> None:
    captured: dict[str, object] = {}

    class FakeClock:
        def set_time(self, value: int) -> None:
            captured["clock_time"] = value

        def timestamp_ns(self) -> int:
            return 1

    class FakeMessageBus:
        def __init__(self, trader_id, clock) -> None:
            return None

        def subscribe(self, topic: str, handler) -> None:
            captured["subscription"] = topic

    class FakeCache:
        def __init__(self, database=None) -> None:
            return None

    class FakePortfolio:
        def __init__(self, **kwargs) -> None:
            return None

    class FakeExecutionEngine:
        def __init__(self, **kwargs) -> None:
            self.clients = []

        def register_client(self, client) -> None:
            self.clients.append(client)

    class FakeOrderFactory:
        def __init__(self, **kwargs) -> None:
            return None

    class FakeModel:
        def __init__(self, *args, **kwargs) -> None:
            return None

    class FakeValue:
        @staticmethod
        def from_str(value: str) -> str:
            return value

    class FakeSimulatedExchange:
        def __init__(self, **kwargs) -> None:
            captured["exchange_kwargs"] = kwargs
            self.instruments = {}

        def register_client(self, client) -> None:
            captured["exchange_client"] = client

        def initialize_account(self) -> None:
            captured["account_initialized"] = True

    class FakeBacktestExecClient:
        def __init__(self, **kwargs) -> None:
            captured["exec_client_kwargs"] = kwargs
            self.started = False

        def _start(self) -> None:
            self.started = True
            captured["exec_client_started"] = True

    class FakeSandboxExecutionClientConfig:
        def __init__(self, **kwargs) -> None:
            captured["sandbox_config_kwargs"] = kwargs

    class FakeSandboxExecutionClient:
        def __init__(self, **kwargs) -> None:
            self.exchange = SimpleNamespace(instruments={})

        def connect(self) -> None:
            captured["sandbox_connected"] = True

    class Boundary(OwnedNautilusMatchingBoundary):
        def _load_nautilus_components(self) -> dict[str, object]:
            return {
                "asyncio": SimpleNamespace(new_event_loop=lambda: object()),
                "account_type_from_str": lambda value: f"account:{value}",
                "BacktestExecClient": FakeBacktestExecClient,
                "book_type_from_str": lambda value: f"book:{value}",
                "Cache": FakeCache,
                "Currency": FakeValue,
                "DEFAULT_VENUE": "POLYSIGNAL_PM_PAPER",
                "ExecutionEngine": FakeExecutionEngine,
                "FillModel": FakeModel,
                "LatencyModel": FakeModel,
                "MakerTakerFeeModel": FakeModel,
                "MessageBus": FakeMessageBus,
                "Money": FakeValue,
                "oms_type_from_str": lambda value: f"oms:{value}",
                "OrderFactory": FakeOrderFactory,
                "Portfolio": FakePortfolio,
                "SandboxExecutionClient": FakeSandboxExecutionClient,
                "SandboxExecutionClientConfig": FakeSandboxExecutionClientConfig,
                "SimulatedExchange": FakeSimulatedExchange,
                "StrategyId": str,
                "TestClock": FakeClock,
                "TraderId": str,
                "Venue": str,
            }

    settings = MatchingAccuracySettings.from_mode("queue_l2")
    boundary = Boundary(settings)

    boundary._ensure_session()

    exchange_kwargs = captured["exchange_kwargs"]
    assert exchange_kwargs["liquidity_consumption"] is True
    assert exchange_kwargs["queue_position"] is True
    assert exchange_kwargs["price_protection_points"] == settings.price_protection_points