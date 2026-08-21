from __future__ import annotations
# pyright: reportAttributeAccessIssue=false, reportUnknownVariableType=false, reportUnknownMemberType=false

import subprocess
import sys
from decimal import Decimal
from pathlib import Path

from nautilus_trader.core import nautilus_pyo3 as pyo3

from polysignal_lab.nautilus_runtime._polymarket_common_compat import (
    make_price_at_precision,
    make_quantity_at_precision,
    price_increment_from_minimum_tick_size,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]

# The site issue69 failure: RAW Polymarket book strings carry 2 decimals
# ("0.42") while the instrument grid is 0.001 (price_precision=3). A delta
# built with the string's own precision is rejected by the engine/cache book:
# `Invalid delta order price precision 2, expected 3`.


def _instrument() -> object:
    increment = price_increment_from_minimum_tick_size("0.001")
    size_increment = pyo3.Quantity.from_str("0.000001")
    return pyo3.BinaryOption(
        instrument_id=pyo3.InstrumentId.from_str("cond-precision-token.POLYMARKET"),
        raw_symbol=pyo3.Symbol("precision-token"),
        asset_class=pyo3.AssetClass.ALTERNATIVE,
        currency=pyo3.Currency.from_str("USDC"),
        price_precision=increment.precision,
        size_precision=size_increment.precision,
        price_increment=increment,
        size_increment=size_increment,
        activation_ns=0,
        expiration_ns=10_000_000_000,
        ts_event=0,
        ts_init=0,
        outcome="UP",
    )


def _delta(
    instrument: object,
    *,
    price: object,
    size: object,
    sequence: int,
) -> object:
    order = pyo3.BookOrder(
        side=pyo3.OrderSide.BUY,
        price=price,
        size=size,
        order_id=sequence,
    )
    return pyo3.OrderBookDelta(
        instrument_id=instrument.id,
        action=pyo3.BookAction.ADD,
        order=order,
        flags=0,
        sequence=sequence,
        ts_event=1_000_000_000 + sequence,
        ts_init=1_000_000_000 + sequence,
    )


class _BookDeltaSubscriber(pyo3.Strategy):
    def __init__(self, instrument_id: object) -> None:
        super().__init__(
            pyo3.StrategyConfig(strategy_id=pyo3.StrategyId("PRECISION-SUB-001"))
        )
        self._instrument_id = instrument_id
        self.received: list[object] = []

    def on_start(self) -> None:
        self.subscribe_book_deltas(self._instrument_id, pyo3.BookType.L2_MBP)

    def on_book_deltas(self, deltas: object) -> None:
        self.received.append(deltas)


def _run_engine(*, deltas: list[object]) -> tuple[object, _BookDeltaSubscriber]:
    engine = pyo3.BacktestEngine(
        pyo3.BacktestEngineConfig(
            trader_id=pyo3.TraderId("PRECISION-TRADER-001"),
            bypass_logging=True,
        )
    )
    instrument = _instrument()
    engine.add_venue(
        venue=pyo3.Venue("POLYMARKET"),
        oms_type=pyo3.OmsType.NETTING,
        account_type=pyo3.AccountType.CASH,
        starting_balances=[pyo3.Money(100, pyo3.Currency.from_str("USDC"))],
        base_currency=pyo3.Currency.from_str("USDC"),
        book_type=pyo3.BookType.L2_MBP,
    )
    engine.add_instrument(instrument)
    subscriber = _BookDeltaSubscriber(instrument.id)
    engine.add_strategy(subscriber)
    engine.add_data(deltas)
    engine.run()
    return engine, subscriber


# --- site failure reproduction (raw string precision vs instrument grid) ---


def test_raw_book_price_precision_mismatch_aborts_cache_boundary() -> None:
    """The exact live issue69 failure, exercised through the engine cache
    boundary in an isolated subprocess (the native book apply aborts the
    process on mismatched precision):
    `Invalid delta order price precision 2, expected 3`."""
    script = f"""
import sys
sys.path.insert(0, {str(_REPO_ROOT / "src")!r})
from polysignal_lab.nautilus_runtime.optional_imports import load_nautilus_module
from polysignal_lab.nautilus_runtime._polymarket_common_compat import (
    price_increment_from_minimum_tick_size,
)
pyo3 = load_nautilus_module("nautilus_trader.core.nautilus_pyo3")

instrument = pyo3.BinaryOption(
    instrument_id=pyo3.InstrumentId.from_str("cond-precision-tokta.POLYMARKET"),
    raw_symbol=pyo3.Symbol("precision-token"),
    asset_class=pyo3.AssetClass.ALTERNATIVE,
    currency=pyo3.Currency.from_str("USDC"),
    price_precision=3,
    size_precision=6,
    price_increment=price_increment_from_minimum_tick_size("0.001"),
    size_increment=pyo3.Quantity.from_str("0.000001"),
    activation_ns=0,
    expiration_ns=10_000_000_000,
    ts_event=0,
    ts_init=0,
    outcome="UP",
)
# RAW venue values: price string keeps its own 2-decimal precision.
order = pyo3.BookOrder(
    side=pyo3.OrderSide.BUY,
    price=pyo3.Price.from_str("0.42"),
    size=pyo3.Quantity.from_str("100"),
    order_id=1,
)
delta = pyo3.OrderBookDelta(
    instrument_id=instrument.id,
    action=pyo3.BookAction.ADD,
    order=order,
    flags=0,
    sequence=1,
    ts_event=1_000_000_000,
    ts_init=1_000_000_000,
)
engine = pyo3.BacktestEngine(
    pyo3.BacktestEngineConfig(trader_id=pyo3.TraderId("PRECISION-TRADER-001"), bypass_logging=True)
)
engine.add_venue(
    venue=pyo3.Venue("POLYMARKET"),
    oms_type=pyo3.OmsType.NETTING,
    account_type=pyo3.AccountType.CASH,
    starting_balances=[pyo3.Money(100, pyo3.Currency.from_str("USDC"))],
    base_currency=pyo3.Currency.from_str("USDC"),
    book_type=pyo3.BookType.L2_MBP,
)
engine.add_instrument(instrument)
engine.add_data([delta])
engine.run()
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=_REPO_ROOT,
    )
    assert result.returncode != 0, (
        "mismatched-precision delta must abort the engine boundary, "
        f"stderr={result.stderr[-2000:]}"
    )
    assert "Invalid delta order price precision 2, expected 3" in result.stderr


# --- normalized conversion applies cleanly at the same boundary ---


def test_normalized_polymarket_delta_applies_at_cache_boundary() -> None:
    """Project-side normalization (raw value + instrument precision) yields a
    delta the engine cache boundary accepts: no crash, subscriber receives the
    event, and the delta order price sits exactly on the instrument grid."""
    instrument = _instrument()
    price = make_price_at_precision("0.42", instrument.price_precision)
    size = make_quantity_at_precision("100", instrument.size_precision)
    assert price.precision == instrument.price_precision
    assert size.precision == instrument.size_precision

    engine, subscriber = _run_engine(
        deltas=[_delta(instrument, price=price, size=size, sequence=1)]
    )
    try:
        assert len(subscriber.received) == 1
        delta = subscriber.received[0]
        order = delta.deltas[0].order
        assert order.price.precision == instrument.price_precision
        assert order.size.precision == instrument.size_precision
        assert Decimal(str(order.price)) == Decimal("0.420")
        assert Decimal(str(order.size)) == Decimal("100")
    finally:
        engine.dispose()


def test_normalized_delta_matches_make_price_quantization() -> None:
    """The conversion helper and native `make_price` agree on the grid;
    neither helper keeps the raw string's own decimal places."""
    instrument = _instrument()
    raw = ["0.42", "0.420", "0.421", "1", "0.999", 0.5]
    for value in raw:
        converted = make_price_at_precision(value, instrument.price_precision)
        native = instrument.make_price(float(str(value)))
        assert converted.precision == native.precision == instrument.price_precision
        assert Decimal(str(converted)) == Decimal(str(native))
