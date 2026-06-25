from __future__ import annotations

from types import SimpleNamespace

from polysignal_lab.nautilus_runtime.node import build_trading_node, build_control, run_nautilus_cli


def test_build_trading_node_returns_component_dict() -> None:
    """build_trading_node returns all required components."""
    node = build_trading_node()

    assert "registry" in node
    assert "sidecar" in node
    assert "assembler" in node
    assert "group_assembler" in node
    assert "wallet" in node
    assert "paper_client" in node
    assert "policy" in node
    assert "position_policy" in node
    assert "settlement_actor" in node
    assert "observability" in node
    assert "strategies" in node
    assert "strategy_names" in node


def test_build_trading_node_strategies_is_list() -> None:
    """Strategy wrappers are a list."""
    node = build_trading_node()
    assert isinstance(node["strategies"], list)


def test_build_control_adapts_policy() -> None:
    from polysignal_lab.nautilus_runtime.decision_policy import DecisionPolicyActor

    policy = DecisionPolicyActor()
    ctrl = build_control(policy)

    assert ctrl.is_strategy_enabled("vwap_momentum")
    ctrl.set_strategy_enabled("vwap_momentum", enabled=False)
    assert not ctrl.is_strategy_enabled("vwap_momentum")


def test_run_nautilus_cli_prints_ready() -> None:
    """run_nautilus_cli completes without error."""
    run_nautilus_cli()
    # If we reach here, no exception was raised
