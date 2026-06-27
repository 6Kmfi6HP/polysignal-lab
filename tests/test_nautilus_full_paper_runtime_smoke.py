from __future__ import annotations

from types import SimpleNamespace

from polysignal_lab.config import Settings


def test_full_paper_runtime_builds_node_without_live_execution(monkeypatch) -> None:
    import polysignal_lab.nautilus_runtime.node as node_mod

    built = {}

    class FakeTrader:
        def __init__(self) -> None:
            self.strategies = []
            self.cache = SimpleNamespace(orders=lambda: [], fills=lambda: [], positions=lambda: [])
            self.portfolio = SimpleNamespace(id="PF-SMOKE")

        def add_strategy(self, strategy):
            self.strategies.append(strategy)

    class FakeTradingNode:
        def __init__(self, config):
            self.config = config
            self.trader = FakeTrader()
            built["node"] = self

        def add_data_client_factory(self, name, factory):
            built.setdefault("data_factories", []).append(name)

        def add_exec_client_factory(self, name, factory):
            built.setdefault("exec_factories", []).append(name)

        def build(self):
            built["built"] = True

    monkeypatch.setattr(node_mod, "TradingNode", FakeTradingNode)
    monkeypatch.setattr(
        node_mod, "PolymarketInstrumentProviderConfig",
        lambda *, load_ids: SimpleNamespace(load_ids=load_ids),
    )
    monkeypatch.setattr(
        node_mod, "build_paper_trading_node_config",
        lambda settings, **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        node_mod, "register_paper_factories",
        lambda node: (
            node.add_data_client_factory("POLYMARKET", object()),
            node.add_exec_client_factory("POLYSIGNAL-SANDBOX", object()),
        ),
    )

    runtime = node_mod.build_trading_node(Settings(), condition_ids=("condition-btc-5m",))

    assert runtime["node"] is built["node"]
    assert "POLYMARKET" in built["data_factories"]
    assert "POLYMARKET" not in built["exec_factories"]
    assert built["built"] is True
    assert "cache_reader" in runtime
    from polysignal_lab.nautilus_runtime.cache_reader import NautilusCacheReader
    assert isinstance(runtime["cache_reader"], NautilusCacheReader)
    assert runtime["cache_reader"].read_orders() == []
    assert runtime["cache_reader"].read_fills() == []
    assert runtime["cache_reader"].read_positions() == []
    assert runtime["cache_reader"].snapshot_portfolio() is not None
