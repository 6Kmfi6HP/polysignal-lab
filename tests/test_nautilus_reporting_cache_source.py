from __future__ import annotations

from types import SimpleNamespace

from polysignal_lab.app.scheduler_reporting import _report_equity_inputs


def _settings(starting_balance: float = 1_000.0) -> SimpleNamespace:
    return SimpleNamespace(
        paper_trading=SimpleNamespace(starting_balance_usdc=starting_balance),
    )


def test_report_equity_inputs_prefers_nautilus_cache_reader_over_shadow_wallet() -> None:
    wallet = SimpleNamespace(
        starting_balance=999.0,
        equity=111.0,
        open_position_count=9,
    )
    cache_reader = SimpleNamespace(
        snapshot_portfolio_projection=lambda: {"equity": 1_234.5},
        read_account_projection=lambda: {
            "balances": [{"currency": "USDC", "total": 2_222.0}],
        },
        read_positions=lambda: [
            {"is_closed": False, "position_id": "P-1"},
            {"is_closed": True, "position_id": "P-2"},
            {"is_closed": False, "position_id": "P-3"},
        ],
    )
    scheduler = SimpleNamespace(
        settings=_settings(),
        wallet=wallet,
        nautilus_cache_reader=cache_reader,
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 1_234.5, 2)


def test_report_equity_inputs_keeps_portfolio_equity_equal_to_starting_equity() -> None:
    cache_reader = SimpleNamespace(
        snapshot_portfolio_projection=lambda: {"equity": 1_000.0},
        read_account_projection=lambda: {
            "balances": [{"currency": "USDC", "total": 987.65}],
        },
        read_positions=lambda: [],
    )
    scheduler = SimpleNamespace(
        settings=_settings(),
        wallet=SimpleNamespace(starting_balance=50.0, equity=50.0, open_position_count=50),
        nautilus_cache_reader=cache_reader,
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 1_000.0, 0)


def test_report_equity_inputs_keeps_zero_portfolio_equity() -> None:
    cache_reader = SimpleNamespace(
        snapshot_portfolio_projection=lambda: {"equity": 0.0},
        read_account_projection=lambda: {
            "balances": [{"currency": "USDC", "total": 987.65}],
        },
        read_positions=lambda: [],
    )
    scheduler = SimpleNamespace(
        settings=_settings(),
        wallet=SimpleNamespace(starting_balance=50.0, equity=50.0, open_position_count=50),
        nautilus_cache_reader=cache_reader,
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 0.0, 0)


def test_report_equity_inputs_uses_nautilus_account_balance_when_portfolio_equity_missing() -> None:
    cache_reader = SimpleNamespace(
        snapshot_portfolio_projection=lambda: {},
        read_account_projection=lambda: {
            "balances": [
                {"currency": "BTC", "total": 99.0},
                {"currency": "USDC", "total": 987.65},
            ],
        },
        read_positions=lambda: [{"is_closed": False, "position_id": "P-1"}],
    )
    scheduler = SimpleNamespace(
        settings=_settings(),
        wallet=SimpleNamespace(starting_balance=50.0, equity=50.0, open_position_count=50),
        nautilus_cache_reader=cache_reader,
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 987.65, 1)


def test_report_equity_inputs_uses_account_balance_for_non_numeric_portfolio_equity() -> None:
    cache_reader = SimpleNamespace(
        snapshot_portfolio_projection=lambda: {"equity": "bad"},
        read_account_projection=lambda: {
            "balances": [{"currency": "USDC", "total": 987.65}],
        },
        read_positions=lambda: [],
    )
    scheduler = SimpleNamespace(
        settings=_settings(),
        wallet=SimpleNamespace(starting_balance=50.0, equity=50.0, open_position_count=50),
        nautilus_cache_reader=cache_reader,
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 987.65, 0)


def test_report_equity_inputs_requires_nautilus_cache_reader() -> None:
    scheduler = SimpleNamespace(
        settings=_settings(),
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 1_000.0, 0)


def test_report_equity_inputs_ignores_shadow_wallet_without_cache_reader() -> None:
    scheduler = SimpleNamespace(
        settings=_settings(),
        wallet=SimpleNamespace(starting_balance=1_000.0, equity=1_025.0, open_position_count=3),
    )

    assert _report_equity_inputs(scheduler) == (1_000.0, 1_000.0, 0)
