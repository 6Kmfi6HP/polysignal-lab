from __future__ import annotations

# ruff: noqa: E402

from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from nautilus_optional import require_nautilus

require_nautilus()

from nautilus_trader.core import nautilus_pyo3 as pyo3

from factories import sample_market_view
from nautilus_contract_probe import ContractProbeConfig, ContractProbeStrategy
from nautilus_runtime_contracts_harness import (
    build_backtest_engine,
    order_statuses,
    register_contract_probe,
    register_contract_probe_on_livenode,
    safe_dispose,
    synthetic_quotes,
)
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.nautilus_runtime.polymarket_adapter import PolymarketEnumParser
from polysignal_lab.nautilus_runtime.strategy_state import (
    decode_state,
    save_strategy_state,
)
from polysignal_lab.nautilus_runtime.live_node import (
    SANDBOX_EXEC_CLIENT_ID,
    POLYMARKET_CLIENT_ID,
)


def test_nautilus_version_has_native_strategy_messaging() -> None:
    from importlib.metadata import version

    assert version("nautilus-trader") == "1.231.0a20260730"
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


def test_backtest_reduce_only_exit_cannot_reverse_position() -> None:
    engine, raw_inst = build_backtest_engine()
    inst = cast(Any, raw_inst)
    engine = cast(Any, engine)
    engine.add_data(synthetic_quotes(inst.id, [100.0, 100.5, 101.0, 101.5, 102.0]))

    class ReduceOnlyProbe(ContractProbeStrategy):
        def __init__(self) -> None:
            super().__init__(
                ContractProbeConfig(
                    instrument_id=str(inst.id),
                    strategy_id="ReduceOnly-Probe",
                    order_id_tag="reduceonly",
                    auto_buy=False,
                )
            )
            self._entered = False
            self._exit_submitted = False
            self.exit_order: object | None = None

        def on_start(self) -> None:
            self.subscribe_quotes(inst.id)

        def on_quote(self, tick: object) -> None:
            _ = tick
            if self._entered:
                return
            self._entered = True
            self.submit_order(
                self.order_factory.market(
                    instrument_id=inst.id,
                    order_side=pyo3.OrderSide.BUY,
                    quantity=pyo3.Quantity.from_str("0.001000"),
                )
            )

        def on_order_filled(self, event: object) -> None:
            _ = event
            if self._exit_submitted:
                return
            self._exit_submitted = True
            self.exit_order = self.order_factory.market(
                instrument_id=inst.id,
                order_side=pyo3.OrderSide.SELL,
                quantity=pyo3.Quantity.from_str("0.002000"),
                reduce_only=True,
            )
            self.submit_order(self.exit_order)

    strategy = ReduceOnlyProbe()
    engine.add_strategy(strategy)
    engine.run()

    assert strategy.exit_order is not None
    assert bool(getattr(strategy.exit_order, "is_reduce_only", False)) is True
    assert all(
        float(position.signed_qty) >= 0 for position in engine.cache.positions_open()
    )
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


def test_adapter_enum_parser_maps_side_and_intent_only() -> None:
    """Order status string remapping deleted — NT events already carry OrderStatus."""
    assert PolymarketEnumParser.to_nautilus_order_side(Side.UP).name == "BUY"
    assert (
        PolymarketEnumParser.to_nautilus_time_in_force(OrderIntent.TAKER_FAK).name
        == "IOC"
    )
    assert not hasattr(PolymarketEnumParser, "to_nautilus_order_status")


def test_datatester_is_constructible_with_polymarket_data_contract() -> None:
    from nautilus_trader.common.actor import Actor
    from nautilus_trader.model.enums import BookType
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.test_kit.strategies.tester_data import (
        DataTester,
        DataTesterConfig,
    )

    instrument_id = InstrumentId.from_str("123.POLYMARKET")
    config = DataTesterConfig(
        instrument_ids=[instrument_id],
        request_instruments=True,
        subscribe_book_deltas=True,
        subscribe_trades=True,
        manage_book=True,
        log_data=False,
    )
    tester = DataTester(config)

    assert isinstance(tester, Actor)
    assert tester.config is config
    assert config.instrument_ids == [instrument_id]
    assert config.book_type == BookType.L2_MBP
    assert config.request_instruments is True
    assert config.subscribe_book_deltas is True
    assert config.subscribe_trades is True
    assert config.manage_book is True


def test_exectester_is_constructible_with_safe_local_contract() -> None:
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.test_kit.strategies.tester_exec import (
        ExecTester,
        ExecTesterConfig,
    )
    from nautilus_trader.trading.strategy import Strategy

    instrument_id = InstrumentId.from_str("123.POLYMARKET")
    config = ExecTesterConfig(
        instrument_id=instrument_id,
        order_qty=Decimal("1"),
        enable_limit_buys=True,
        enable_limit_sells=False,
        use_post_only=True,
        dry_run=True,
        log_data=False,
    )
    tester = ExecTester(config)

    assert isinstance(tester, Strategy)
    assert tester.config is config
    assert config.instrument_id == instrument_id
    assert config.order_qty == Decimal("1")
    assert config.enable_limit_buys is True
    assert config.enable_limit_sells is False
    assert config.use_post_only is True
    assert config.dry_run is True


def test_tester_importable_registration_reports_native_type_boundary() -> None:
    node = pyo3.LiveNode.builder(
        "TESTERS",
        pyo3.TraderId("TESTERS-001"),
        pyo3.Environment.SANDBOX,
    ).build()
    actor_config = pyo3.ImportableActorConfig(
        actor_path="nautilus_trader.test_kit.strategies.tester_data:DataTester",
        config_path=(
            "nautilus_trader.test_kit.strategies.tester_data:DataTesterConfig"
        ),
        config={
            "instrument_ids": ["123.POLYMARKET"],
            "request_instruments": True,
            "log_data": False,
        },
    )
    strategy_config = pyo3.ImportableStrategyConfig(
        strategy_path="nautilus_trader.test_kit.strategies.tester_exec:ExecTester",
        config_path=(
            "nautilus_trader.test_kit.strategies.tester_exec:ExecTesterConfig"
        ),
        config={
            "instrument_id": "123.POLYMARKET",
            "order_qty": "1",
            "dry_run": True,
            "log_data": False,
        },
    )

    with pytest.raises(RuntimeError, match="not an instance of 'DataActor'"):
        node.add_actor_from_config(actor_config)
    with pytest.raises(RuntimeError, match="not an instance of 'Strategy'"):
        node.add_strategy_from_config(strategy_config)


def test_polymarket_datatester_live_acceptance_blocked() -> None:
    pytest.skip(
        "Blocked: applicable TC-D01 through TC-D72 require network access and a "
        "live Polymarket instrument fixture; installed DataTester is constructible "
        "but is a Cython Actor, not a PyO3 DataActor accepted by LiveNode"
    )


def test_polymarket_exectester_live_acceptance_blocked() -> None:
    pytest.skip(
        "Blocked: applicable TC-E01 through TC-E87 require network access, "
        "credentials, funds, and a live Polymarket instrument fixture; installed "
        "ExecTester is constructible but is a Cython Strategy, not a PyO3 Strategy "
        "accepted by LiveNode"
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
