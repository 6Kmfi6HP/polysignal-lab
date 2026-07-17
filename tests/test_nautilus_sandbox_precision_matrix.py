"""Native PyO3 precision matrix for Polymarket-shaped instruments."""

from __future__ import annotations

from decimal import Decimal

import pytest
from nautilus_trader.core import nautilus_pyo3 as pyo3


def _instrument(*, min_quantity: str = "0.01") -> object:
    price_step = pyo3.Price.from_str("0.01")
    size_step = pyo3.Quantity.from_str("0.01")
    return pyo3.BinaryOption(
        instrument_id=pyo3.InstrumentId.from_str("precision-token.POLYMARKET"),
        raw_symbol=pyo3.Symbol("precision-token"),
        asset_class=pyo3.AssetClass.ALTERNATIVE,
        currency=pyo3.Currency.from_str("USDC"),
        price_precision=price_step.precision,
        size_precision=size_step.precision,
        price_increment=price_step,
        size_increment=size_step,
        activation_ns=0,
        expiration_ns=10_000_000_000,
        ts_event=0,
        ts_init=0,
        min_quantity=pyo3.Quantity.from_str(min_quantity),
        outcome="Yes",
    )


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


@pytest.mark.parametrize("kind", ["price", "quantity"])
def test_native_converters_preserve_valid_increment_boundaries(kind: str) -> None:
    instrument = _instrument()
    increment = (
        instrument.price_increment if kind == "price" else instrument.size_increment
    )
    maker = instrument.make_price if kind == "price" else instrument.make_qty
    value = _decimal(increment) * 7

    converted = maker(float(value))

    assert _decimal(converted) == value
    assert converted.precision == increment.precision


@pytest.mark.parametrize(
    ("kind", "increment_multiplier", "expected_multiplier"),
    [
        ("price", Decimal("7.5"), Decimal("8")),
        ("quantity", Decimal("7.5"), Decimal("8")),
        ("price", Decimal("7.1"), Decimal("7")),
        ("quantity", Decimal("7.1"), Decimal("7")),
    ],
)
def test_native_converters_quantize_half_and_excess_precision(
    kind: str,
    increment_multiplier: Decimal,
    expected_multiplier: Decimal,
) -> None:
    instrument = _instrument()
    increment = (
        instrument.price_increment if kind == "price" else instrument.size_increment
    )
    maker = instrument.make_price if kind == "price" else instrument.make_qty

    converted = maker(float(_decimal(increment) * increment_multiplier))

    assert _decimal(converted) == _decimal(increment) * expected_multiplier
    assert converted.precision == increment.precision


def test_native_quantity_converter_does_not_enforce_minimum() -> None:
    instrument = _instrument(min_quantity="0.05")
    below_minimum = _decimal(instrument.min_quantity) - _decimal(
        instrument.size_increment
    )

    converted = instrument.make_qty(float(below_minimum))

    assert _decimal(converted) == below_minimum
    assert converted < instrument.min_quantity


class _FillPrecisionStrategy(pyo3.Strategy):
    def __init__(self, instrument: object) -> None:
        super().__init__(
            pyo3.StrategyConfig(strategy_id=pyo3.StrategyId("PRECISION-001"))
        )
        self.instrument = instrument
        self.submitted = False
        self.fills: list[tuple[object, object]] = []

    def on_start(self) -> None:
        self.subscribe_quotes(self.instrument.id)

    def on_quote(self, tick: object) -> None:
        if self.submitted:
            return
        self.submitted = True
        self.submit_order(
            self.order_factory.limit(
                instrument_id=self.instrument.id,
                order_side=pyo3.OrderSide.BUY,
                quantity=self.instrument.make_qty(
                    float(str(self.instrument.size_increment))
                ),
                price=self.instrument.make_price(float(str(tick.ask_price))),
                time_in_force=pyo3.TimeInForce.GTC,
            )
        )

    def on_order_filled(self, event: object) -> None:
        self.fills.append((event.last_px, event.last_qty))


def test_engine_cache_and_fill_retain_instrument_precision() -> None:
    instrument = _instrument()
    engine = pyo3.BacktestEngine(
        pyo3.BacktestEngineConfig(
            trader_id=pyo3.TraderId("PRECISION-TRADER-001"),
            bypass_logging=True,
        )
    )
    engine.add_venue(
        venue=instrument.id.venue,
        oms_type=pyo3.OmsType.NETTING,
        account_type=pyo3.AccountType.CASH,
        starting_balances=[pyo3.Money(100, instrument.currency)],
        base_currency=instrument.currency,
        book_type=pyo3.BookType.L1_MBP,
    )
    engine.add_instrument(instrument)
    strategy = _FillPrecisionStrategy(instrument)
    engine.add_strategy(strategy)
    tick = _decimal(instrument.price_increment)
    size = _decimal(instrument.size_increment)
    engine.add_data(
        [
            pyo3.QuoteTick(
                instrument_id=instrument.id,
                bid_price=instrument.make_price(float(tick * 49)),
                ask_price=instrument.make_price(float(tick * 50)),
                bid_size=instrument.make_qty(float(size * 100)),
                ask_size=instrument.make_qty(float(size * 100)),
                ts_event=1_000_000_000,
                ts_init=1_000_000_000,
            )
        ]
    )

    try:
        engine.run()
        order = list(engine.cache.orders())[0]
        fill_price, fill_quantity = strategy.fills[0]
        assert fill_price.precision == instrument.price_precision
        assert fill_quantity.precision == instrument.size_precision
        assert order.price.precision == instrument.price_precision
        assert order.quantity.precision == instrument.size_precision
        assert order.filled_qty.precision == instrument.size_precision
    finally:
        engine.dispose()
