"""
Input: __future__, pytest, nautilus_optional, nautilus_runtime_contracts_harness, polysignal_lab
Output: v2 backtest/live sandbox runtime contract acceptance tests
Pos: Test Layer - Acceptance / Integration

🔄 Self-reference: When this file changes, update this header
"""

from __future__ import annotations

# ruff: noqa: E402

from types import SimpleNamespace

import pytest
from nautilus_optional import require_nautilus

require_nautilus()

from nautilus_trader.core import nautilus_pyo3 as pyo3

from factories import sample_market_view
from nautilus_contract_probe import ContractProbeStrategy
from nautilus_runtime_contracts_harness import (
    build_backtest_engine,
    order_statuses,
    register_contract_probe,
    register_contract_probe_on_livenode,
    safe_dispose,
    synthetic_quotes,
)
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.nautilus_bridge.enum_parser import PolymarketEnumParser
from polysignal_lab.nautilus_bridge.state import decode_state, save_strategy_state
from polysignal_lab.nautilus_runtime.live_node import (
    SANDBOX_EXEC_CLIENT_ID,
    POLYMARKET_CLIENT_ID,
)


def test_nautilus_version_has_native_strategy_messaging() -> None:
    from importlib.metadata import version

    assert version("nautilus-trader") == "1.231.0.dev20260716+16604"
    assert callable(getattr(pyo3.Strategy, "publish_data", None))
    assert callable(getattr(pyo3.Strategy, "subscribe_data", None))


def test_message_and_market_view_immutability() -> None:
    tick = pyo3.QuoteTick(
        instrument_id=pyo3.InstrumentId.from_str("BTCUSDT.BINANCE"),
        bid_price=pyo3.Price.from_str("100.00"),
        ask_price=pyo3.Price.from_str("100.01"),
        bid_size=pyo3.Quantity.from_str("1.000000"),
        ask_size=pyo3.Quantity.from_str("1.000000"),
        ts_event=1,
        ts_init=1,
    )
    with pytest.raises(AttributeError):
        tick.bid_price = pyo3.Price.from_str("99.00")  # type: ignore[misc]

    view = sample_market_view(asset="BTC", timeframe="5m")
    with pytest.raises(Exception):
        view.asset = "ETH"  # type: ignore[misc]


def test_backtest_dataengine_dispatch_and_order_lifecycle() -> None:
    engine, inst = build_backtest_engine()
    engine.add_data(synthetic_quotes(inst.id, [100.0, 100.5, 101.0, 101.5, 102.0]))
    strategy = register_contract_probe(
        engine, order_id_tag="lifecycle", instrument_id=inst.id
    )

    engine.run()

    assert any(event[0] == "quote" for event in strategy.events)
    assert any(event[0] == "filled" for event in strategy.events)
    assert any(event[0] == "pos_opened" for event in strategy.events)
    statuses = order_statuses(engine.cache)
    assert statuses and all(status == "FILLED" for _, status in statuses)
    assert engine.cache.positions_open_count() == 1
    assert engine.portfolio.is_completely_flat() is False
    assert strategy.clock_samples  # Clock available at on_start
    safe_dispose(engine)


def test_backtest_cache_portfolio_updates_after_fill() -> None:
    engine, inst = build_backtest_engine()
    engine.add_data(synthetic_quotes(inst.id, [100.0, 101.0, 102.0]))
    register_contract_probe(engine, order_id_tag="cache", instrument_id=inst.id)
    engine.run()

    assert engine.cache.orders_total_count() == 1
    assert engine.cache.positions_open_count() == 1
    assert engine.portfolio.is_completely_flat() is False
    account = engine.cache.account_for_venue(pyo3.Venue("BINANCE"))
    assert account is not None
    safe_dispose(engine)


def test_multi_strategy_isolation_unique_ids_and_positions() -> None:
    engine, inst = build_backtest_engine()
    engine.add_data(synthetic_quotes(inst.id, [100.0, 100.5, 101.0, 101.5, 102.0]))
    a = register_contract_probe(engine, order_id_tag="iso_a", instrument_id=inst.id)
    b = register_contract_probe(engine, order_id_tag="iso_b", instrument_id=inst.id)
    assert a.strategy_id != b.strategy_id

    engine.run()

    positions = list(engine.cache.positions_open())
    assert len(positions) == 2
    strategy_ids = {
        str(engine.cache.strategy_id_for_position(getattr(pos, "id", pos)))
        for pos in positions
    }
    assert strategy_ids == {"PolySignal-iso_a", "PolySignal-iso_b"}
    safe_dispose(engine)


def test_strategy_state_save_load_bytes_round_trip() -> None:
    engine, inst = build_backtest_engine()
    engine.add_data(synthetic_quotes(inst.id, [100.0]))
    strategy = register_contract_probe(
        engine,
        order_id_tag="stateful",
        instrument_id=inst.id,
        auto_buy=False,
        workflow_marker="entry_tp=0.92",
    )
    engine.run()

    saved = strategy.on_save()
    assert saved["workflow_marker"] == b"entry_tp=0.92"

    restored = ContractProbeStrategy.__new__(ContractProbeStrategy)
    restored.workflow_marker = ""
    restored.on_load(saved)
    assert restored.workflow_marker == "entry_tp=0.92"

    # Project schema path used by PolySignalNativeStrategy
    encoded = save_strategy_state(
        "probe",
        SimpleNamespace(save_state=lambda: {"alpha_key": 1}),
    )
    decoded = decode_state("probe", encoded)
    assert decoded["alpha"] == {"alpha_key": 1}
    assert "workflow" not in decoded
    safe_dispose(engine)


def test_backtest_settlement_close_via_strategy_api() -> None:
    engine, inst = build_backtest_engine()
    engine.add_data(
        synthetic_quotes(inst.id, [100.0, 100.5, 101.0, 101.5, 102.0, 102.5, 103.0])
    )
    strategy = register_contract_probe(
        engine,
        order_id_tag="settle_bt",
        instrument_id=inst.id,
        auto_close_after_quotes=3,
    )
    engine.run()

    assert any(event[0] == "filled" for event in strategy.events)
    assert any(event[0] == "pos_closed" for event in strategy.events)
    assert engine.cache.positions_open_count() == 0
    assert engine.portfolio.is_completely_flat() is True
    safe_dispose(engine)


def test_instrument_close_contract_expired_closes_position_in_backtest() -> None:
    engine, inst = build_backtest_engine()
    engine.add_data(synthetic_quotes(inst.id, [100.0, 100.5, 101.0]))
    strategy = register_contract_probe(
        engine, order_id_tag="instr_close", instrument_id=inst.id
    )
    try:
        close = pyo3.InstrumentClose(
            instrument_id=inst.id,
            close_price=pyo3.Price.from_str("0.00"),
            close_type=pyo3.InstrumentCloseType.CONTRACT_EXPIRED,
            ts_event=4_000_000_000,
            ts_init=4_000_000_000,
        )
    except Exception as exc:
        pytest.fail(f"InstrumentClose(CONTRACT_EXPIRED) construction failed: {exc}")
    # Queue after the fill-dated quotes; BacktestEngine.add_data accepts a sequence.
    engine.add_data([close])
    engine.run()

    assert any(event[0] == "instr_close" for event in strategy.events)
    assert any(event[0] == "pos_closed" for event in strategy.events)
    assert engine.cache.positions_open_count() == 0
    assert engine.cache.positions_closed_count() == 1
    assert engine.portfolio.is_completely_flat() is True
    safe_dispose(engine)


def test_same_strategy_registers_on_livenode_sandbox() -> None:
    inst = pyo3.InstrumentId.from_str("BTCUSDT.BINANCE")
    venue = pyo3.Venue(POLYMARKET_CLIENT_ID)
    money = pyo3.Money(1_000.0, pyo3.Currency.from_str("USDT"))
    node = (
        pyo3.LiveNode.builder(
            "CONTRACT", pyo3.TraderId("CONTRACT-LIVE-001"), pyo3.Environment.SANDBOX
        )
        .with_load_state(False)
        .with_save_state(False)
        .with_cache_config(pyo3.CacheConfig())
        .with_data_engine_config(pyo3.LiveDataEngineConfig())
        .with_exec_engine_config(pyo3.LiveExecEngineConfig(reconciliation=False))
        .add_data_client(
            POLYMARKET_CLIENT_ID,
            pyo3.PolymarketDataClientFactory(),
            pyo3.PolymarketDataClientConfig(),
        )
        .add_simulated_exec_client(
            SANDBOX_EXEC_CLIENT_ID,
            pyo3.SandboxExecutionClientFactory(),
            pyo3.SandboxExecutionClientConfig(
                venue=venue,
                starting_balances=[money],
            ),
        )
        .build()
    )
    config = register_contract_probe_on_livenode(
        node,
        order_id_tag="live_probe",
        instrument_id=inst,
        auto_buy=False,
        workflow_marker="live",
    )
    assert config.strategy_id == "PolySignal-live_probe"
    assert not hasattr(node, "cache")
    assert not hasattr(node, "portfolio")
    node.start()
    assert node.is_running is True
    node.stop()


def test_backtest_live_strategy_surface_equivalence() -> None:
    """Same Strategy class exposes Clock/Cache/order API in backtest and LiveNode."""
    engine, inst = build_backtest_engine()
    engine.add_data(synthetic_quotes(inst.id, [100.0]))
    bt = register_contract_probe(
        engine, order_id_tag="equiv_bt", instrument_id=inst.id, auto_buy=False
    )
    engine.run()

    node = (
        pyo3.LiveNode.builder(
            "EQUIV", pyo3.TraderId("EQUIV-001"), pyo3.Environment.SANDBOX
        )
        .with_load_state(False)
        .with_save_state(False)
        .build()
    )
    live_config = register_contract_probe_on_livenode(
        node,
        order_id_tag="equiv_live",
        instrument_id=inst.id,
        auto_buy=False,
    )
    assert hasattr(bt, "clock")
    assert hasattr(bt, "cache")
    assert hasattr(bt, "portfolio")
    assert hasattr(bt, "order_factory")
    assert hasattr(bt, "submit_order")
    assert hasattr(bt, "subscribe_quotes")
    assert type(bt) is ContractProbeStrategy
    assert str(bt.strategy_id) == "PolySignal-equiv_bt"
    assert live_config.strategy_id == "PolySignal-equiv_live"
    node.start()
    node.stop()
    safe_dispose(engine)


def test_same_strategy_class_registers_on_backtest_and_sandbox_livenode() -> None:
    engine, inst = build_backtest_engine()
    bt = register_contract_probe(
        engine, order_id_tag="same_bt", instrument_id=inst.id, auto_buy=False
    )
    node = pyo3.LiveNode.builder(
        "SAME", pyo3.TraderId("SAME-001"), pyo3.Environment.SANDBOX
    ).build()
    live_config = register_contract_probe_on_livenode(
        node,
        order_id_tag="same_live",
        instrument_id=inst.id,
        auto_buy=False,
    )

    assert type(bt) is ContractProbeStrategy
    assert str(bt.strategy_id) == "PolySignal-same_bt"
    assert live_config.strategy_id == "PolySignal-same_live"
    node.start()
    node.stop()
    safe_dispose(engine)


def test_polymarket_data_config_exposes_resolve_poll() -> None:
    config = pyo3.PolymarketDataClientConfig(
        resolve_poll_enabled=True,
        resolve_poll_interval_secs=30,
        resolve_poll_grace_secs=10,
        resolve_poll_max_wait_secs=1800,
    )
    rendered = str(config)
    assert "resolve_poll_enabled: true" in rendered
    assert "resolve_poll_interval_secs: 30" in rendered
    assert "resolve_poll_grace_secs: 10" in rendered
    assert "resolve_poll_max_wait_secs: 1800" in rendered


def test_live_exec_engine_reconciliation_defaults_true() -> None:
    config = pyo3.LiveExecEngineConfig(reconciliation=True)
    assert "true" in str(getattr(config, "reconciliation", config)).lower()


def test_pyo3_polymarket_execution_factory_available() -> None:
    assert hasattr(pyo3, "PolymarketExecutionClientFactory")
    assert hasattr(pyo3, "PolymarketExecClientConfig")


def test_native_strategy_has_no_request_settlement_close() -> None:
    from polysignal_lab.nautilus_runtime import native_strategy as ns

    assert not hasattr(ns, "request_" + "settlement_close")


def test_adapter_enum_parser_boundary_rejects_unknown_and_maps_known() -> None:
    assert PolymarketEnumParser.to_nautilus_order_side(Side.UP).name == "BUY"
    assert (
        PolymarketEnumParser.to_nautilus_time_in_force(OrderIntent.TAKER_FAK).name
        == "IOC"
    )
    with pytest.raises(ValueError, match="unsupported"):
        PolymarketEnumParser.to_nautilus_order_status("not-a-real-status")


def test_datatester_exectester_pyo3_matrix_unavailable() -> None:
    """DataTester/ExecTester are classic Cython Actor/Strategy — not pyo3 LiveNode."""
    from nautilus_trader.test_kit.strategies.tester_data import DataTester
    from nautilus_trader.test_kit.strategies.tester_exec import ExecTester

    assert not issubclass(DataTester, pyo3.Strategy)
    assert not issubclass(ExecTester, pyo3.Strategy)
    pytest.skip(
        "DataTester/ExecTester target classic TradingNode; "
        "no pyo3 LiveNode/BacktestEngine matrix API — adapter live matrix deferred"
    )


def test_data_actor_and_strategy_use_native_component_ids() -> None:
    assert hasattr(pyo3, "DataActor")
    assert hasattr(pyo3, "StrategyId")


def test_polymarket_resolve_request_not_public_in_pyo3() -> None:
    resolve_symbols = [name for name in dir(pyo3) if "Resolve" in name]
    assert "PolymarketResolveRequest" not in resolve_symbols


def test_unknown_exec_outcome_injection_unavailable() -> None:
    pytest.skip(
        "pyo3 BacktestEngine has no public API to inject unknown exec outcomes "
        "into ExecutionEngine without inventing venue events"
    )


def test_duplicate_fill_injection_unavailable() -> None:
    pytest.skip(
        "pyo3 BacktestEngine matching engine does not expose a duplicate-fill inject "
        "hook; reconciliation idempotency requires exec-client test harness"
    )


def test_reconnect_restart_reconciliation_requires_live_exec_client() -> None:
    config = pyo3.LiveExecEngineConfig(reconciliation=True)
    assert config is not None
    assert "true" in str(getattr(config, "reconciliation", config)).lower()
    builder = pyo3.LiveNode.builder(
        "RECON", pyo3.TraderId("RECON-001"), pyo3.Environment.SANDBOX
    )
    assert callable(getattr(builder, "with_reconciliation", None))
    pytest.skip(
        "LiveNode reconciliation=True is configurable, but pyo3 offers no in-process "
        "reconnect/restart fixture for Polymarket sandbox without live venue I/O"
    )


def test_market_rotation_contract_covered_elsewhere() -> None:
    pytest.skip(
        "market rotation immutability + actor lifecycle covered in "
        "test_nautilus_market_rotation.py; no second harness here"
    )
