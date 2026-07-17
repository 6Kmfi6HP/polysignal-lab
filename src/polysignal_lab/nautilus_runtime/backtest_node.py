from __future__ import annotations

from collections.abc import Sequence

from polysignal_lab.config import Settings, load_settings
from polysignal_lab.domain.market import Market


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
    if source:
        engine.add_data(source)
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
