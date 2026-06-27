from __future__ import annotations

from types import SimpleNamespace

import pytest

from polysignal_lab.nautilus_runtime.trading_node import (
    PAPER_EXEC_CLIENT_ID,
    assert_no_live_polymarket_execution,
    register_paper_factories,
)


class FakeNode:
    def __init__(self) -> None:
        self.data_factories = []
        self.exec_factories = []

    def add_data_client_factory(self, name, factory):
        self.data_factories.append((name, factory))

    def add_exec_client_factory(self, name, factory):
        self.exec_factories.append((name, factory))


def test_live_polymarket_execution_is_rejected() -> None:
    """Does NOT require nautilus_trader — tests pure Python logic."""
    config = SimpleNamespace(exec_clients={"POLYMARKET": object()})

    with pytest.raises(RuntimeError, match="live Polymarket execution"):
        assert_no_live_polymarket_execution(config)


@pytest.fixture
def nautilus() -> None:
    pytest.importorskip("nautilus_trader")


class TestWithNautilus:
    """Tests that require nautilus_trader."""

    def test_build_paper_trading_node_config_uses_polymarket_data_and_sandbox_exec(self, nautilus) -> None:
        from polysignal_lab.config import Settings
        from polysignal_lab.nautilus_runtime.trading_node import build_paper_trading_node_config

        settings = Settings()
        settings.paper_trading.starting_balance_usdc = 1234.0

        config = build_paper_trading_node_config(
            settings,
            instrument_config=SimpleNamespace(load_ids=frozenset({"up-token.POLYMARKET"})),
        )

        assert "POLYMARKET" in config.data_clients
        assert PAPER_EXEC_CLIENT_ID in config.exec_clients
        assert config.exec_clients[PAPER_EXEC_CLIENT_ID].venue == PAPER_EXEC_CLIENT_ID
        assert config.exec_clients[PAPER_EXEC_CLIENT_ID].account_type == "CASH"
        assert config.exec_clients[PAPER_EXEC_CLIENT_ID].oms_type == "NETTING"
        assert config.exec_clients[PAPER_EXEC_CLIENT_ID].starting_balances == ["1234.0 USDC"]
        assert "POLYMARKET" not in config.exec_clients

    def test_register_paper_factories_registers_data_and_sandbox_exec_only(self, nautilus) -> None:
        node = FakeNode()

        register_paper_factories(node)

        assert node.data_factories[0][0] == "POLYMARKET"
        assert node.exec_factories[0][0] == PAPER_EXEC_CLIENT_ID
        assert all(name != "POLYMARKET" for name, _factory in node.exec_factories)
