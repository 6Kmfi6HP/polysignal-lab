"""
Input: __future__, __future__.annotations, types, types.SimpleNamespace, polysignal_lab.app.scheduler_reporting, polysignal_lab.app.scheduler_reporting._report_equity_inputs
Output: test_report_equity_inputs_prefers_nautilus_cache_over_shadow_wallet, test_report_equity_inputs_keeps_portfolio_equity_equal_to_starting_equity, test_report_equity_inputs_keeps_zero_portfolio_equity, test_report_equity_inputs_uses_nautilus_account_balance_when_portfolio_equity_missing, test_report_equity_inputs_uses_account_balance_for_non_numeric_portfolio_equity, test_report_equity_inputs_requires_nautilus_cache, test_report_equity_inputs_ignores_shadow_wallet_without_cache
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""






from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from polysignal_lab.app.scheduler_reporting import _report_equity_inputs


def _settings(starting_balance: float = 1_000.0) -> SimpleNamespace:
    return SimpleNamespace(
        paper_trading=SimpleNamespace(starting_balance_usdc=starting_balance),
    )


def test_report_equity_inputs_prefers_nautilus_cache_over_shadow_wallet() -> None:
    ts = datetime.now(UTC)
    cache = SimpleNamespace(
        account=lambda: SimpleNamespace(
            id="A-1",
            balances=[SimpleNamespace(currency="USDC", total=2_222.0)],
        ),
        positions=lambda: [
            SimpleNamespace(
                id="P-1", instrument_id="I", signed_qty=10, avg_px_open=0.5,
                realized_pnl=0.0, is_closed=False, ts_event=ts,
            ),
            SimpleNamespace(
                id="P-2", instrument_id="I", signed_qty=10, avg_px_open=0.5,
                realized_pnl=0.0, is_closed=True, ts_event=ts,
            ),
            SimpleNamespace(
                id="P-3", instrument_id="I", signed_qty=10, avg_px_open=0.5,
                realized_pnl=0.0, is_closed=False, ts_event=ts,
            ),
        ],
    )
    portfolio = SimpleNamespace(id="PF-1", equity=1_234.5)
    scheduler = SimpleNamespace(
        settings=_settings(),
        nautilus_cache=cache,
        nautilus_portfolio=portfolio,
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 1_234.5, 2)


def test_report_equity_inputs_keeps_portfolio_equity_equal_to_starting_equity() -> None:
    cache = SimpleNamespace(
        account=lambda: SimpleNamespace(
            id="A-1",
            balances=[SimpleNamespace(currency="USDC", total=987.65)],
        ),
        positions=lambda: [],
    )
    portfolio = SimpleNamespace(id="PF-1", equity=1_000.0)
    scheduler = SimpleNamespace(
        settings=_settings(),
        nautilus_cache=cache,
        nautilus_portfolio=portfolio,
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 1_000.0, 0)


def test_report_equity_inputs_keeps_zero_portfolio_equity() -> None:
    cache = SimpleNamespace(
        account=lambda: SimpleNamespace(
            id="A-1",
            balances=[SimpleNamespace(currency="USDC", total=987.65)],
        ),
        positions=lambda: [],
    )
    portfolio = SimpleNamespace(id="PF-1", equity=0.0)
    scheduler = SimpleNamespace(
        settings=_settings(),
        nautilus_cache=cache,
        nautilus_portfolio=portfolio,
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 0.0, 0)


def test_report_equity_inputs_uses_nautilus_account_balance_when_portfolio_equity_missing() -> None:
    ts = datetime.now(UTC)
    cache = SimpleNamespace(
        account=lambda: SimpleNamespace(
            id="A-1",
            balances=[
                SimpleNamespace(currency="BTC", total=99.0),
                SimpleNamespace(currency="USDC", total=987.65),
            ],
        ),
        positions=lambda: [
            SimpleNamespace(
                id="P-1", instrument_id="I", signed_qty=10, avg_px_open=0.5,
                realized_pnl=0.0, is_closed=False, ts_event=ts,
            ),
        ],
    )
    scheduler = SimpleNamespace(
        settings=_settings(),
        nautilus_cache=cache,
        # No nautilus_portfolio — falls through to account balance
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 987.65, 1)


def test_report_equity_inputs_uses_account_balance_for_non_numeric_portfolio_equity() -> None:
    cache = SimpleNamespace(
        account=lambda: SimpleNamespace(
            id="A-1",
            balances=[SimpleNamespace(currency="USDC", total=987.65)],
        ),
        positions=lambda: [],
    )
    scheduler = SimpleNamespace(
        settings=_settings(),
        nautilus_cache=cache,
        # No nautilus_portfolio — falls through to account balance
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 987.65, 0)


def test_report_equity_inputs_requires_nautilus_cache() -> None:
    scheduler = SimpleNamespace(
        settings=_settings(),
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 1_000.0, 0)


def test_report_equity_inputs_ignores_shadow_wallet_without_cache() -> None:
    scheduler = SimpleNamespace(
        settings=_settings(),
        wallet=SimpleNamespace(starting_balance=1_000.0, equity=1_025.0, open_position_count=3),
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 1_000.0, 0)
