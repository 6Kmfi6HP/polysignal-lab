from __future__ import annotations
from types import SimpleNamespace
from typing import cast

from polysignal_lab.nautilus_runtime.cache_reader import NautilusCacheReader


def test_cache_reader_reads_orders_from_cache() -> None:
    o1 = SimpleNamespace(
        client_order_id="C-1", instrument_id="I", order_side="BUY",
        order_type="LIMIT", time_in_force="IOC", quantity=1, price=0.5, tags=[],
    )
    cache = SimpleNamespace(orders=lambda: [o1])

    reader = NautilusCacheReader(cache)
    rows = reader.read_orders()

    assert len(rows) == 1
    assert rows[0]["client_order_id"] == "C-1"


def test_cache_reader_reads_fills_from_cache() -> None:
    f1 = SimpleNamespace(
        client_order_id="C-1", instrument_id="I", trade_id="T-1",
        last_qty=5, last_px=0.5, liquidity_side="TAKER",
    )
    cache = SimpleNamespace(fills=lambda: [f1])

    reader = NautilusCacheReader(cache)
    rows = reader.read_fills()

    assert len(rows) == 1
    assert rows[0]["trade_id"] == "T-1"


def test_cache_reader_reads_positions_from_cache() -> None:
    p1 = SimpleNamespace(
        id="P-1", instrument_id="I", signed_qty=10, avg_px_open=0.5,
        realized_pnl=0.0, is_closed=False,
    )
    cache = SimpleNamespace(positions=lambda: [p1])

    reader = NautilusCacheReader(cache)
    rows = reader.read_positions()

    assert len(rows) == 1
    assert rows[0]["position_id"] == "P-1"


def test_cache_reader_reads_account_from_cache() -> None:
    acct = SimpleNamespace(id="A-1", balances=[SimpleNamespace(currency="USDC", total=1000.0)])
    cache = SimpleNamespace(account=lambda: acct)

    reader = NautilusCacheReader(cache)
    result = cast(SimpleNamespace | None, reader.read_account())

    assert result is not None
    assert result.id == "A-1"
    assert result.balances[0].currency == "USDC"


def test_cache_reader_snapshots_portfolio_from_cache() -> None:
    pf = SimpleNamespace(id="PF-1", equity=500.0)
    reader = NautilusCacheReader(SimpleNamespace(), portfolio=pf)
    result = cast(SimpleNamespace | None, reader.snapshot_portfolio())

    assert result is not None
    assert result.id == "PF-1"
    assert result.equity == 500.0


def test_cache_reader_snapshots_portfolio_from_cache_fallback() -> None:
    pf = SimpleNamespace(id="PF-1b", equity=550.0)
    cache = SimpleNamespace(portfolio=lambda: pf)

    reader = NautilusCacheReader(cache)
    result = cast(SimpleNamespace | None, reader.snapshot_portfolio())

    assert result is not None
    assert result.id == "PF-1b"
    assert result.equity == 550.0


def test_cache_reader_snapshots_portfolio_attribute() -> None:
    pf = SimpleNamespace(id="PF-2", equity=750.0)
    reader = NautilusCacheReader(SimpleNamespace(), portfolio=pf)
    result = cast(SimpleNamespace | None, reader.snapshot_portfolio())

    assert result is not None
    assert result.id == "PF-2"
    assert result.equity == 750.0


def test_cache_reader_empty_cache_returns_lists() -> None:
    cache = SimpleNamespace()
    reader = NautilusCacheReader(cache)

    assert reader.read_orders() == []
    assert reader.read_fills() == []
    assert reader.read_positions() == []
    assert reader.read_account() is None
    assert reader.snapshot_portfolio() is None


def test_cache_reader_respects_separate_portfolio_arg() -> None:
    """Portfolio argument overrides any portfolio on cache."""
    pf_explicit = SimpleNamespace(id="PF-EXPLICIT", equity=999.0)
    pf_on_cache = SimpleNamespace(id="PF-CACHE", equity=111.0)
    cache = SimpleNamespace(portfolio=lambda: pf_on_cache)

    reader = NautilusCacheReader(cache, portfolio=pf_explicit)
    result = cast(SimpleNamespace | None, reader.snapshot_portfolio())

    assert result is not None
    assert result.id == "PF-EXPLICIT"


def test_cache_reader_projects_account_and_portfolio_snapshots() -> None:
    acct = SimpleNamespace(
        id="A-1",
        balances=[SimpleNamespace(currency="USDC", total=1000.0)],
    )
    portfolio = SimpleNamespace(id="PF-1", equity=1012.5)
    reader = NautilusCacheReader(SimpleNamespace(account=lambda: acct), portfolio=portfolio)

    account = reader.read_account_projection()
    snapshot = reader.snapshot_portfolio_projection()

    assert account == {
        "account_id": "A-1",
        "balances": [{"currency": "USDC", "total": 1000.0}],
    }
    assert snapshot == {
        "portfolio_id": "PF-1",
        "equity": 1012.5,
    }
