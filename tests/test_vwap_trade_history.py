from polysignal_lab.alpha.vwap_trade_history import TradeHistory


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
