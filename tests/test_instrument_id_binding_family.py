from __future__ import annotations

import pytest

pytest.importorskip("nautilus_trader")

from nautilus_trader.core.nautilus_pyo3 import InstrumentId as Pyo3InstrumentId
from nautilus_trader.model.identifiers import InstrumentId as CythonInstrumentId

from polysignal_lab.nautilus_runtime.native_order import _instrument_id
from polysignal_lab.nautilus_runtime.strategy.nautilus_objects import (
    _nautilus_instrument_id,
)

INSTRUMENT_TEXT = (
    "0xf2b4bb338aa66b421f55a4bfc0e99d555fa781ec2934e759a8f8cc6668c1874c"
    "-87899632447581826120701973675522904747721480403115091406246447876465306011165"
    ".POLYMARKET"
)


class _Instrument:
    def __init__(self, instrument_id: object) -> None:
        self.id = instrument_id


def test_cython_instrument_id_is_normalised_for_subscriptions() -> None:
    """
    Production symptom: `on_instrument` failed 40 times a minute with
    `TypeError: 'InstrumentId' object is not an instance of 'InstrumentId'` —
    nautilus_trader ships a Cython and a PyO3 class of the same name, and the
    runtime subscribes through the PyO3 API. Anything crossing that boundary
    must arrive as the PyO3 type.
    """
    cython_id = CythonInstrumentId.from_str(INSTRUMENT_TEXT)

    normalised = _nautilus_instrument_id(cython_id)

    assert isinstance(normalised, Pyo3InstrumentId)
    assert str(normalised) == INSTRUMENT_TEXT


def test_cython_instrument_id_is_normalised_for_order_submission() -> None:
    """The native OrderFactory boundary takes PyO3 types (see the 2026-07-20
    OrderSide/TimeInForce fix); the InstrumentId leg was left on Cython."""
    instrument = _Instrument(CythonInstrumentId.from_str(INSTRUMENT_TEXT))

    normalised = _instrument_id(instrument)

    assert isinstance(normalised, Pyo3InstrumentId)
    assert str(normalised) == INSTRUMENT_TEXT


@pytest.mark.parametrize(
    "normalise",
    [_nautilus_instrument_id, lambda value: _instrument_id(_Instrument(value))],
    ids=["subscriptions", "order_submission"],
)
def test_pyo3_instrument_id_passes_through(normalise) -> None:
    pyo3_id = Pyo3InstrumentId.from_str(INSTRUMENT_TEXT)

    assert normalise(pyo3_id) is pyo3_id


@pytest.mark.parametrize(
    "normalise",
    [_nautilus_instrument_id, lambda value: _instrument_id(_Instrument(value))],
    ids=["subscriptions", "order_submission"],
)
def test_string_instrument_id_is_parsed(normalise) -> None:
    normalised = normalise(INSTRUMENT_TEXT)

    assert isinstance(normalised, Pyo3InstrumentId)
    assert str(normalised) == INSTRUMENT_TEXT


def test_normalised_id_is_accepted_by_a_real_pyo3_api() -> None:
    """The regression only bites at a real PyO3 call, so assert against one."""
    from nautilus_trader.core.nautilus_pyo3 import (
        BookAction,
        BookOrder,
        OrderBookDelta,
        OrderSide,
        Price,
        Quantity,
    )

    order = BookOrder(OrderSide.BUY, Price.from_str("0.5"), Quantity.from_str("1"), 0)
    cython_id = CythonInstrumentId.from_str(INSTRUMENT_TEXT)

    with pytest.raises(TypeError):
        _ = OrderBookDelta(cython_id, BookAction.CLEAR, order, 0, 0, 0, 0)

    normalised = _nautilus_instrument_id(cython_id)
    assert isinstance(normalised, Pyo3InstrumentId)
    assert OrderBookDelta(normalised, BookAction.CLEAR, order, 0, 0, 0, 0) is not None


@pytest.mark.parametrize("bad", [None, "", "garbage", 42], ids=str)
def test_unusable_instrument_id_raises_at_the_boundary(bad: object) -> None:
    """
    Deliberate behaviour change: these used to pass through untouched and fail
    later inside a PyO3 call with an unreadable message. Rejecting them here
    names the bad value instead.
    """
    with pytest.raises(ValueError, match="invalid `InstrumentId` value"):
        _ = _nautilus_instrument_id(bad)
