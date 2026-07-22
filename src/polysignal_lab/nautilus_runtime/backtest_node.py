"""
Input: __future__, __future__.annotations, collections.abc, collections.abc.Sequence, polysignal_lab.config, polysignal_lab.config.Settings, polysignal_lab.config.load_settings, polysignal_lab.domain.market, polysignal_lab.domain.market.Market
Output: build_backtest_engine
Pos: Application code

🔄 Self-reference: When this file changes, update this header
"""


from __future__ import annotations

from collections.abc import Sequence

from polysignal_lab.config import Settings, load_settings
from polysignal_lab.domain.market import Market


def _recorded_clock_data(
    custom_data: tuple[object, ...], instrument_id: object
) -> list[object]:
    from nautilus_trader.core import nautilus_pyo3 as pyo3

    timestamps = sorted({int(getattr(item, "ts_init")) for item in custom_data})
    clock_data: list[object] = []
    for timestamp in timestamps:
        clock_data.append(
            pyo3.InstrumentStatus(
                instrument_id=instrument_id,  # pyright: ignore[reportArgumentType]
                action=pyo3.MarketStatusAction.NONE,
                ts_event=timestamp,
                ts_init=timestamp,
                reason=None,
                trading_event=None,
                is_trading=None,
                is_quoting=None,
                is_short_sell_restricted=None,
            )
        )
    return clock_data


def _add_backtest_data(
    engine: object,
    source: list[object],
    instruments: Sequence[object],
) -> None:
    from nautilus_trader.core import nautilus_pyo3 as pyo3

    native_data: list[object] = [
        item
        for item in source
        if isinstance(item, (pyo3.QuoteTick, pyo3.InstrumentClose))
    ]
    custom_data = tuple(item for item in source if item not in native_data)
    if custom_data:
        clock_source = native_data[0] if native_data else next(iter(instruments), None)
        if clock_source is not None:
            instrument_id = getattr(
                clock_source,
                "instrument_id",
                getattr(clock_source, "id", None),
            )
            if instrument_id is not None:
                native_data.extend(_recorded_clock_data(custom_data, instrument_id))
    if native_data:
        engine.add_data(native_data)  # pyright: ignore[reportAttributeAccessIssue]
    if not custom_data:
        return
    from polysignal_lab.nautilus_runtime.recorded_market_data import (
        RecordedCustomDataReplayActor,
    )

    engine.add_actor(  # pyright: ignore[reportAttributeAccessIssue]
        RecordedCustomDataReplayActor(custom_data)
    )


def build_backtest_engine(
    settings: Settings | None = None,
    *,
    instruments: Sequence[object] = (),
    quotes: Sequence[object] = (),
    data: Sequence[object] | None = None,
    markets: Sequence[Market] = (),
    condition_ids: Sequence[str] = (),
) -> object:
    if settings is None:
        settings = load_settings()
    from nautilus_trader.core import nautilus_pyo3 as pyo3

    runtime = settings.runtime.nautilus
    engine = pyo3.BacktestEngine(
        config=pyo3.BacktestEngineConfig(
            trader_id=pyo3.TraderId(runtime.trader_id),
            bypass_logging=True,
        )
    )
    currency = pyo3.Currency.from_str("USDC")
    engine.add_venue(
        venue=pyo3.Venue("POLYMARKET"),
        oms_type=pyo3.OmsType.NETTING,
        account_type=pyo3.AccountType.CASH,
        starting_balances=[
            pyo3.Money(runtime.backtest.starting_balance_usdc, currency)
        ],
        base_currency=currency,
        book_type=getattr(pyo3.BookType, runtime.sandbox_book_type),
    )
    for instrument in instruments:
        engine.add_instrument(instrument)
    source = list(data if data is not None else quotes)
    _add_backtest_data(engine, source, instruments)
    from polysignal_lab.nautilus_runtime.runtime_registration import (
        register_runtime_components,
    )

    register_runtime_components(
        engine,
        settings,
        markets=markets,
        condition_ids=condition_ids,
    )
    return engine
