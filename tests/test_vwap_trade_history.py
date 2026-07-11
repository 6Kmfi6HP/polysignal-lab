"""Unit tests for VWAP trade history."""

from __future__ import annotations

from polysignal_lab.alpha.vwap_trade_history import TradeHistory
from polysignal_lab.domain.trade import Trade


def test_trade_history_push_and_latest_price() -> None:
    history = TradeHistory()
    history.push("market:UP", 0.55, 1.0, 1000.0)

    assert history.latest_price("market:UP") == 0.55


def test_trade_history_duplicate_push_is_idempotent_for_storage() -> None:
    history = TradeHistory()
    key = "market:UP"

    history.push(key, 0.55, 1.0, 1000.0)
    history.push(key, 0.55, 1.0, 1000.0)

    assert len(history._trades[key]) == 2


def test_trade_history_remove_drops_matching_trade() -> None:
    history = TradeHistory()
    key = "market:UP"
    history.push(key, 0.55, 1.0, 1000.0)
    history.push(key, 0.60, 2.0, 1001.0)

    history.remove(key, 0.55, 1.0, 1000.0)

    assert history.latest_price(key) == 0.60
    assert key not in history._trades or len(history._trades[key]) == 1


def test_trade_history_trades_in_window_filters_by_timestamp() -> None:
    history = TradeHistory()
    key = "market:UP"
    history.push(key, 0.50, 1.0, 100.0)
    history.push(key, 0.55, 1.0, 200.0)

    trades = history.trades_in_window(key, window_sec=50.0, now=200.0)

    assert trades == [Trade(price=0.55, size=1.0, timestamp=200.0)]


def test_trade_history_vwap_computes_volume_weighted_average() -> None:
    history = TradeHistory()
    key = "market:UP"
    history.push(key, 0.50, 2.0, 100.0)
    history.push(key, 0.60, 1.0, 101.0)

    assert history.vwap(key, window_sec=10.0, now=101.0) == (0.50 * 2.0 + 0.60) / 3.0


def test_trade_history_snapshots_cannot_mutate_internal_state() -> None:
    history = TradeHistory()
    history.push("market", 0.5, 2.0, 1.0)

    snapshot = history.trades_for_key("market")
    all_snapshot = history.all_trades()
    history.push("market", 0.6, 3.0, 2.0)

    assert isinstance(snapshot, tuple)
    assert isinstance(all_snapshot["market"], tuple)
    assert snapshot == all_snapshot["market"]
    assert history.latest_price("market") == 0.6
    assert len(snapshot) == 1
