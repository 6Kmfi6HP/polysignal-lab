from __future__ import annotations

import time
from collections.abc import Callable, Sequence

from nautilus_trader.core import nautilus_pyo3 as pyo3
from nautilus_trader.test_kit.rust.instruments_pyo3 import TestInstrumentProviderPyo3

from nautilus_contract_probe import ContractProbeConfig, ContractProbeStrategy

VENUE_NAME = "BINANCE"
# 2.0 backtest risk engine enforces NOTIONAL_BELOW_MINIMUM (min 10 USDT);
# 0.001 BTC (~0.1 USDT at ~$100k) would be denied. ~1 BTC clears it at any
# realistic BTC price.
DEFAULT_QTY = "1.000000"


def default_instrument() -> object:
    return TestInstrumentProviderPyo3.btcusdt_binance()


def synthetic_quotes(
    instrument_id: object,
    prices: Sequence[float],
    *,
    size: str = "10.000000",
    start_ns: int = 1_000_000_000,
    step_ns: int = 1_000_000_000,
) -> list[object]:
    quotes: list[object] = []
    for index, px in enumerate(prices):
        ts = start_ns + index * step_ns
        quotes.append(
            pyo3.QuoteTick(
                instrument_id=instrument_id,
                bid_price=pyo3.Price.from_str(f"{px:.2f}"),
                ask_price=pyo3.Price.from_str(f"{px + 0.01:.2f}"),
                bid_size=pyo3.Quantity.from_str(size),
                ask_size=pyo3.Quantity.from_str(size),
                ts_event=ts,
                ts_init=ts,
            )
        )
    return quotes


def build_backtest_engine(
    *,
    trader_id: str = "CONTRACT-001",
    instrument: object | None = None,
    quotes: Sequence[object] | None = None,
) -> tuple[object, object]:
    """Return (engine, instrument) with venue + optional quote data loaded."""
    inst = instrument or default_instrument()
    engine = pyo3.BacktestEngine(
        config=pyo3.BacktestEngineConfig(
            trader_id=pyo3.TraderId(trader_id),
            bypass_logging=True,
        )
    )
    engine.add_venue(
        venue=pyo3.Venue(VENUE_NAME),
        oms_type=pyo3.OmsType.NETTING,
        account_type=pyo3.AccountType.MARGIN,
        starting_balances=[pyo3.Money(10_000, pyo3.Currency.from_str("USDT"))],
        base_currency=pyo3.Currency.from_str("USDT"),
        book_type=pyo3.BookType.L1_MBP,
    )
    engine.add_instrument(inst)
    if quotes:
        engine.add_data(list(quotes))
    return engine, inst


def register_contract_probe(
    engine: object,
    *,
    order_id_tag: str,
    instrument_id: object,
    quantity: str = DEFAULT_QTY,
    auto_buy: bool = True,
    auto_close_after_quotes: int = 0,
    workflow_marker: str = "",
) -> ContractProbeStrategy:
    strategy = ContractProbeStrategy(
        ContractProbeConfig(
            instrument_id=str(instrument_id),
            quantity=quantity,
            auto_buy=auto_buy,
            auto_close_after_quotes=auto_close_after_quotes,
            workflow_marker=workflow_marker,
            strategy_id=f"PolySignal-{order_id_tag}",
            order_id_tag=order_id_tag,
        )
    )
    engine.add_strategy(strategy)
    return strategy


def register_contract_probe_on_livenode(
    node: object,
    *,
    order_id_tag: str,
    instrument_id: object,
    quantity: str = DEFAULT_QTY,
    auto_buy: bool = False,
    workflow_marker: str = "",
) -> ContractProbeConfig:
    from dataclasses import asdict

    config = ContractProbeConfig(
        instrument_id=str(instrument_id),
        quantity=quantity,
        auto_buy=auto_buy,
        workflow_marker=workflow_marker,
        strategy_id=f"PolySignal-{order_id_tag}",
        order_id_tag=order_id_tag,
    )
    node.add_strategy_from_config(
        pyo3.ImportableStrategyConfig(
            strategy_path=f"{ContractProbeStrategy.__module__}:{ContractProbeStrategy.__qualname__}",
            config_path=f"{ContractProbeConfig.__module__}:{ContractProbeConfig.__qualname__}",
            config=asdict(config),
        )
    )
    return config


def wait_until(
    condition: Callable[[], bool],
    *,
    timeout: float = 2.0,
    poll: float = 0.01,
) -> None:
    """Poll until condition is true (event-condition wait; no fixed sleep)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(poll)
    raise TimeoutError(f"condition not met within {timeout}s")


def run_node(node: object, *, duration: float = 0.5) -> bool:
    """Start a 2.0 LiveNode on the caller's event loop, run briefly, stop it.

    2.0 removed ``start()`` and requires the node's loop on the current thread
    (msgbus uses thread-local storage; running from a spawned thread panics in
    pyo3). ``run_async`` runs on the caller's loop and must be stopped via the
    node handle. Returns whether the node reported running while active.
    """
    import asyncio

    handle = node.handle()

    async def _main() -> bool:
        run_task = asyncio.create_task(node.run_async())
        async def _stopper() -> None:
            await asyncio.sleep(duration)
            handle.stop()

        stopper = asyncio.create_task(_stopper())
        # Sample running state while the node is active; require 10 consecutive
        # True samples so a transient false negative cannot mask a good start.
        sampled: list[bool] = []
        for _ in range(50):
            await asyncio.sleep(0.01)
            sampled.append(bool(node.is_running))
            if len(sampled) >= 10 and all(sampled[-10:]):
                break
        try:
            await run_task
        finally:
            await stopper
        return bool(sampled) and all(sampled[-10:])

    return asyncio.run(_main())


def stop_node(node: object) -> None:
    node.stop()


def order_statuses(cache: object) -> list[tuple[str, str]]:
    orders = cache.orders() if callable(getattr(cache, "orders", None)) else ()
    return [
        (str(getattr(order, "client_order_id", "")), str(getattr(order, "status", "")))
        for order in orders
    ]


def safe_dispose(engine: object) -> None:
    dispose = getattr(engine, "dispose", None)
    if not callable(dispose):
        return
    try:
        dispose()
    except Exception:
        pass
