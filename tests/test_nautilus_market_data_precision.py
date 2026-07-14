"""
Input: __future__, asyncio, decimal, pytest, nautilus optional
Output: regression tests for issue #13 price precision mismatch
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from nautilus_optional import require_nautilus


def _instrument(price_precision: int):
    from nautilus_trader.model.currencies import USDC_POS
    from nautilus_trader.model.enums import AssetClass
    from nautilus_trader.model.identifiers import InstrumentId, Symbol
    from nautilus_trader.model.instruments import BinaryOption
    from nautilus_trader.model.objects import Price, Quantity

    price_increment = Price(Decimal("1").scaleb(-price_precision), price_precision)
    size_increment = Quantity.from_str("0.000001")
    return BinaryOption(
        instrument_id=InstrumentId.from_str("0xabc-tokenup.POLYMARKET"),
        raw_symbol=Symbol("tokenup"),
        outcome="Up",
        description="issue13",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USDC_POS,
        price_increment=price_increment,
        price_precision=price_precision,
        size_increment=size_increment,
        size_precision=size_increment.precision,
        activation_ns=0,
        expiration_ns=4102444800000000000,
        max_quantity=None,
        min_quantity=None,
        maker_fee=Decimal("0"),
        taker_fee=Decimal("0"),
        ts_event=0,
        ts_init=0,
        info={},
    )


def _engine(instrument):
    from nautilus_trader.backtest.engine import OrderMatchingEngine
    from nautilus_trader.backtest.models.fee import MakerTakerFeeModel
    import nautilus_trader.backtest.models.fill as fill_models
    from nautilus_trader.cache.cache import Cache
    from nautilus_trader.common.component import MessageBus, TestClock
    from nautilus_trader.model.enums import AccountType, BookType, OmsType
    from nautilus_trader.model.identifiers import TraderId

    clock = TestClock()
    msgbus = MessageBus(trader_id=TraderId("TESTER-001"), clock=clock)
    cache = Cache()
    cache.add_instrument(instrument)
    return OrderMatchingEngine(
        instrument=instrument,
        raw_id=0,
        fill_model=fill_models.FillModel(),
        fee_model=MakerTakerFeeModel(),
        book_type=BookType.L2_MBP,
        oms_type=OmsType.NETTING,
        account_type=AccountType.CASH,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
    )


def _sandbox_client(loop: asyncio.AbstractEventLoop, instrument=None):
    from nautilus_trader.adapters.sandbox.config import SandboxExecutionClientConfig
    from nautilus_trader.cache.cache import Cache
    from nautilus_trader.common.component import LiveClock, MessageBus
    from nautilus_trader.model.identifiers import TraderId
    from nautilus_trader.portfolio.portfolio import Portfolio
    from polysignal_lab.nautilus_runtime.sandbox_precision_client import (
        PolySignalSandboxLiveExecClientFactory,
    )

    clock = LiveClock()
    msgbus = MessageBus(trader_id=TraderId("TESTER-001"), clock=clock)
    cache = Cache()
    if instrument is not None:
        cache.add_instrument(instrument)
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
    config = SandboxExecutionClientConfig(
        venue="POLYMARKET",
        starting_balances=["1000 pUSD"],
        base_currency="pUSD",
        oms_type="NETTING",
        account_type="CASH",
        book_type="L2_MBP",
        bar_execution=False,
        trade_execution=True,
    )
    client = PolySignalSandboxLiveExecClientFactory.create(
        loop=loop,
        name="POLYSIGNAL_PM_PAPER",
        config=config,
        portfolio=portfolio,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
    )
    return client, cache


def _mismatched_quote(instrument):
    from nautilus_trader.model.data import QuoteTick
    from nautilus_trader.model.objects import Price, Quantity

    return QuoteTick(
        instrument_id=instrument.id,
        bid_price=Price.from_str("0.45"),
        ask_price=Price.from_str("0.46"),
        bid_size=Quantity.from_str("10.000000"),
        ask_size=Quantity.from_str("10.000000"),
        ts_event=1,
        ts_init=1,
    )


def _mismatched_delta(instrument):
    from nautilus_trader.model.data import BookOrder, OrderBookDelta
    from nautilus_trader.model.enums import BookAction, OrderSide, RecordFlag
    from nautilus_trader.model.objects import Price, Quantity

    return OrderBookDelta(
        instrument_id=instrument.id,
        action=BookAction.UPDATE,
        order=BookOrder(
            side=OrderSide.BUY,
            price=Price.from_str("0.45"),
            size=Quantity.from_str("5.000000"),
            order_id=1,
        ),
        flags=RecordFlag.F_LAST,
        sequence=1,
        ts_event=1,
        ts_init=1,
    )


def test_mismatched_quote_and_delta_crash_matching_engine_without_normalization() -> None:
    require_nautilus()
    instrument = _instrument(3)
    engine = _engine(instrument)
    quote = _mismatched_quote(instrument)
    delta = _mismatched_delta(instrument)

    assert quote.bid_price.precision == 2
    assert delta.order.price.precision == 2

    with pytest.raises(RuntimeError, match="precision=2"):
        engine.process_quote_tick(quote)
    with pytest.raises(RuntimeError, match="precision=2"):
        engine.process_order_book_delta(delta)


def test_normalize_quote_and_delta_to_instrument_precision(caplog: pytest.LogCaptureFixture) -> None:
    require_nautilus()
    from polysignal_lab.nautilus_runtime.market_data_precision import (
        normalize_market_data_to_instrument,
    )

    instrument = _instrument(3)
    quote = _mismatched_quote(instrument)
    delta = _mismatched_delta(instrument)

    with caplog.at_level("WARNING", logger="polysignal_lab.nautilus.market_data_precision"):
        fixed_quote = normalize_market_data_to_instrument(quote, instrument)
        fixed_delta = normalize_market_data_to_instrument(delta, instrument)

    assert fixed_quote is not quote
    assert fixed_delta is not delta
    assert fixed_quote.bid_price.precision == 3
    assert fixed_quote.ask_price.precision == 3
    assert fixed_delta.order.price.precision == 3
    assert any("instrument.price_precision=3" in record.message for record in caplog.records)
    assert any("QuoteTick" in record.message for record in caplog.records)
    assert any("OrderBookDelta" in record.message for record in caplog.records)

    engine = _engine(instrument)
    engine.process_quote_tick(fixed_quote)
    engine.process_order_book_delta(fixed_delta)


def test_normalize_order_book_deltas_batch() -> None:
    require_nautilus()
    from nautilus_trader.model.data import OrderBookDeltas
    from polysignal_lab.nautilus_runtime.market_data_precision import (
        normalize_market_data_to_instrument,
    )

    instrument = _instrument(3)
    delta = _mismatched_delta(instrument)
    batch = OrderBookDeltas(instrument.id, [delta])
    fixed = normalize_market_data_to_instrument(batch, instrument)
    assert fixed is not batch
    assert all(item.order.price.precision == 3 for item in fixed.deltas if item.order is not None)

    engine = _engine(instrument)
    engine.process_order_book_deltas(fixed)


def test_normalize_is_noop_when_precision_matches() -> None:
    require_nautilus()
    from nautilus_trader.model.data import QuoteTick
    from polysignal_lab.nautilus_runtime.market_data_precision import (
        normalize_market_data_to_instrument,
    )

    instrument = _instrument(3)
    quote = QuoteTick(
        instrument_id=instrument.id,
        bid_price=instrument.make_price(0.45),
        ask_price=instrument.make_price(0.46),
        bid_size=instrument.make_qty(10.0),
        ask_size=instrument.make_qty(10.0),
        ts_event=1,
        ts_init=1,
    )
    assert normalize_market_data_to_instrument(quote, instrument) is quote


def test_precision_safe_sandbox_client_drops_market_data_on_cache_miss(
    caplog: pytest.LogCaptureFixture,
) -> None:
    require_nautilus()
    instrument = _instrument(3)
    quote = _mismatched_quote(instrument)

    with asyncio.Runner() as runner:
        client, _ = _sandbox_client(runner.get_loop())
        with caplog.at_level("ERROR", logger="polysignal_lab.nautilus.sandbox_precision"):
            client.on_data(quote)

    assert any("Dropping QuoteTick" in record.message for record in caplog.records)
    assert any("instrument missing from cache" in record.message for record in caplog.records)


def test_precision_safe_sandbox_client_forwards_non_market_data() -> None:
    require_nautilus()
    instrument = _instrument(3)

    with asyncio.Runner() as runner:
        client, _ = _sandbox_client(runner.get_loop())
        client.on_data(instrument)
        assert client.exchange.get_matching_engine(instrument.id) is not None


def test_live_node_uses_precision_safe_factory_for_real_sandbox() -> None:
    require_nautilus()
    from polysignal_lab.nautilus_runtime import live_node as live_node_mod
    from polysignal_lab.nautilus_runtime.sandbox_precision_client import (
        PolySignalSandboxLiveExecClientFactory,
    )

    class FakeSandbox:
        __module__ = "nautilus_trader.adapters.sandbox.factory"

    class FakeOther:
        __module__ = "tests.fake_sandbox"

    original = live_node_mod.SandboxLiveExecClientFactory
    try:
        live_node_mod.SandboxLiveExecClientFactory = FakeSandbox
        assert (
            live_node_mod._sandbox_exec_client_factory()
            is PolySignalSandboxLiveExecClientFactory
        )

        live_node_mod.SandboxLiveExecClientFactory = FakeOther
        assert live_node_mod._sandbox_exec_client_factory() is FakeOther
    finally:
        live_node_mod.SandboxLiveExecClientFactory = original


def test_precision_safe_factory_registers_and_receives_portfolio_from_real_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_nautilus()
    from types import SimpleNamespace

    from nautilus_trader.live.node import TradingNodeBuilder
    from polysignal_lab.nautilus_runtime.live_node import PAPER_EXEC_CLIENT_ID
    from polysignal_lab.nautilus_runtime.sandbox_precision_client import (
        PolySignalSandboxLiveExecClientFactory,
    )

    class RecordingLog:
        def __init__(self) -> None:
            self.errors: list[str] = []

        def error(self, message: str) -> None:
            self.errors.append(message)

        def info(self, _message: str) -> None:
            return None

    class RecordingExecEngine:
        def __init__(self) -> None:
            self.clients: list[object] = []

        def register_client(self, client: object) -> None:
            self.clients.append(client)

        def register_default_client(self, _client: object) -> None:
            return None

        def register_venue_routing(self, _client: object, _venue: object) -> None:
            return None

    captured: dict[str, object] = {}

    def create(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(
        PolySignalSandboxLiveExecClientFactory,
        "create",
        staticmethod(create),
    )
    builder = object.__new__(TradingNodeBuilder)
    builder._exec_factories = {}
    builder._log = RecordingLog()
    builder._exec_engine = RecordingExecEngine()
    builder._loop = object()
    builder._msgbus = object()
    builder._cache = object()
    builder._clock = object()
    builder._portfolio = object()

    builder.add_exec_client_factory(
        PAPER_EXEC_CLIENT_ID,
        PolySignalSandboxLiveExecClientFactory,
    )
    builder.build_exec_clients(
        {
            PAPER_EXEC_CLIENT_ID: SimpleNamespace(
                routing=SimpleNamespace(default=False, venues=frozenset()),
            )
        }
    )

    assert builder._log.errors == []
    assert PAPER_EXEC_CLIENT_ID in builder._exec_factories
    assert captured["portfolio"] is builder._portfolio
    assert builder._exec_engine.clients


def test_precision_safe_factory_returns_real_sandbox_execution_client() -> None:
    require_nautilus()
    from nautilus_trader.adapters.sandbox.execution import SandboxExecutionClient

    instrument = _instrument(3)
    with asyncio.Runner() as runner:
        client, cache = _sandbox_client(runner.get_loop(), instrument)

        assert isinstance(client, SandboxExecutionClient)
        assert cache.accounts()
        client.on_data(instrument)
        client.on_data(_mismatched_quote(instrument))
        client.on_data(_mismatched_delta(instrument))
