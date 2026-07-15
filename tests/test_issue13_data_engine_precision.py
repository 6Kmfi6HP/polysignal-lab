"""
Input: __future__, asyncio, decimal, sys, nautilus optional
Output: DataEngine queue regression for issue #13 trade tick precision drift
Pos: Test Layer - Integration tests

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

import asyncio
import sys
from decimal import Decimal

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
        description="issue13-data-engine",
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


def _trade_tick(instrument):
    from nautilus_trader.model.data import TradeTick
    from nautilus_trader.model.enums import AggressorSide
    from nautilus_trader.model.identifiers import TradeId
    from nautilus_trader.model.objects import Price, Quantity

    return TradeTick(
        instrument_id=instrument.id,
        price=Price.from_str("0.45"),
        size=Quantity.from_str("5.000000"),
        aggressor_side=AggressorSide.BUYER,
        trade_id=TradeId("issue13-trade"),
        ts_event=1,
        ts_init=1,
    )


async def _replay_precision_refresh(loop: asyncio.AbstractEventLoop) -> None:
    from nautilus_trader.adapters.sandbox.config import SandboxExecutionClientConfig
    from nautilus_trader.cache.cache import Cache
    from nautilus_trader.common.component import LiveClock, MessageBus
    from nautilus_trader.live.data_engine import LiveDataEngine, LiveDataEngineConfig
    from nautilus_trader.model.identifiers import TraderId
    from nautilus_trader.portfolio.portfolio import Portfolio

    from polysignal_lab.nautilus_runtime.sandbox_precision_client import (
        PolySignalSandboxLiveExecClientFactory,
    )

    processed_trade = asyncio.Event()

    class RethrowingLiveDataEngine(LiveDataEngine):
        def _handle_data(self, data) -> None:
            super()._handle_data(data)
            if type(data).__name__ == "TradeTick":
                processed_trade.set()

        def _handle_queue_exception(self, e: Exception, queue_name: str) -> None:
            if queue_name == "Data":
                processed_trade.set()
            raise e

    clock = LiveClock()
    msgbus = MessageBus(trader_id=TraderId("TESTER-001"), clock=clock)
    cache = Cache()
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
    client = PolySignalSandboxLiveExecClientFactory.create(
        loop=loop,
        name="POLYSIGNAL_PM_PAPER",
        config=SandboxExecutionClientConfig(
            venue="POLYMARKET",
            starting_balances=["1000 pUSD"],
            base_currency="pUSD",
            oms_type="NETTING",
            account_type="CASH",
            book_type="L2_MBP",
            bar_execution=False,
            trade_execution=True,
        ),
        portfolio=portfolio,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
    )
    engine = RethrowingLiveDataEngine(
        loop=loop,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        config=LiveDataEngineConfig(graceful_shutdown_on_exception=True),
    )
    old_instrument = _instrument(2)
    refreshed_instrument = _instrument(3)
    original_tick = _trade_tick(old_instrument)

    assert original_tick.price.precision == 2

    data_topic = f"data.*.{client.venue}.*"
    client.connect()
    assert msgbus.is_subscribed(data_topic, client.on_data)
    engine.start()
    queue_tasks = (
        engine.get_cmd_queue_task(),
        engine.get_req_queue_task(),
        engine.get_res_queue_task(),
        engine.get_data_queue_task(),
    )
    assert all(task is not None for task in queue_tasks)

    try:
        engine.process(old_instrument)
        engine.process(refreshed_instrument)
        engine.process(original_tick)

        await asyncio.wait_for(processed_trade.wait(), timeout=2.0)
        data_queue_task = engine.get_data_queue_task()
        assert data_queue_task is not None
        if data_queue_task.done():
            await data_queue_task

        matching_engine = client.exchange.get_matching_engine(old_instrument.id)
        assert matching_engine is not None
        assert cache.instrument(old_instrument.id).price_precision == 3
        assert matching_engine.instrument.price_precision == 3
        assert client.test_clock.timestamp_ns() == original_tick.ts_init
        assert original_tick.price.precision == 2
    finally:
        active_error = sys.exception()
        engine.stop()
        queue_results = await asyncio.gather(
            *(task for task in queue_tasks if task is not None),
            return_exceptions=True,
        )
        try:
            msgbus.unsubscribe(data_topic, client.on_data)
        finally:
            client.disconnect()
        if active_error is None:
            assert all(task is not None and task.done() for task in queue_tasks)
            assert not msgbus.is_subscribed(data_topic, client.on_data)
            assert client.is_connected is False
            for result in queue_results:
                if isinstance(result, BaseException):
                    raise result


def test_trade_tick_is_aligned_after_instrument_precision_refresh() -> None:
    require_nautilus()

    with asyncio.Runner() as runner:
        runner.run(_replay_precision_refresh(runner.get_loop()))
