"""
Input: __future__, __future__.annotations, sys, collections.abc, collections.abc.Callable, collections.abc.Mapping, datetime, datetime.UTC, datetime.datetime, datetime.timedelta
Output: test_native_strategy_on_save_load_delegates_to_core_via_encode_decode, test_native_strategy_on_save_persists_only_core_state, test_native_strategy_on_load_restores_core_without_runtime_order_truth, test_runtime_strategy_fok_depth_counts_asks_through_max_entry, test_native_strategy_records_rejection_when_order_mapping_fails, test_native_strategy_blocks_duplicate_in_flight_signal_submission, test_static_native_strategy_uses_nautilus_subscribe_data_for_custom_data, test_static_native_strategy_does_not_bypass_custom_data_lifecycle, test_native_strategy_generates_signal_from_on_data_callback, test_native_strategy_requires_shared_policy, test_native_strategy_constructor_requires_injected_projections
Pos: Test Layer - Unit/Integration tests

🔄 Self-reference: When this file changes, update this header
"""







from __future__ import annotations

import sys

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from importlib import import_module
from types import ModuleType, SimpleNamespace
from typing import Any, Protocol, cast

from polysignal_lab.alpha.types import (
    AlphaDecision,
    MarketView,
    OrderIntentSpec,
)
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_runtime.order_plan import NautilusOrderSpec
from polysignal_lab.nautilus_runtime.custom_data_state import StrategyCustomDataState
from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalPriceToBeatData, PolySignalSpotData

from polysignal_lab.nautilus_bridge.state import decode_state, state_key


class _FloatLike:
    def __init__(self, value: float) -> None:
        self.value = value

    def __float__(self) -> float:
        return self.value

    def __str__(self) -> str:
        return str(self.value)


class FakeAssembler:
    def __init__(self, view: object | None):
        self.view = cast(MarketView | None, view)

    def build(
        self,
        condition_id: str,
        *,
        created_at: datetime | None = None,
    ) -> MarketView | None:
        _ = condition_id, created_at
        return self.view


class FakeCore:
    def __init__(self, decisions: list[AlphaDecision]):
        self.decisions = decisions

    def evaluate(self, view: MarketView) -> list[AlphaDecision]:
        _ = view
        return self.decisions


class _NoopClock:
    def set_timer(self, name: object, interval: object, *, callback: object) -> None:
        _ = name, interval, callback


class StatefulFakeCore(FakeCore):
    def __init__(
        self,
        decisions: list[AlphaDecision],
        *,
        state: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(decisions)
        self.state: dict[str, object] = dict(
            state or {"alpha_marker": 42, "trades": {"condition-btc-5m": []}}
        )
        self.loaded_payload: dict[str, object] | None = None
        self.save_calls = 0

    def save_state(self) -> Mapping[str, object]:
        self.save_calls += 1
        return dict(self.state)

    def load_state(self, payload: Mapping[str, object]) -> None:
        self.loaded_payload = dict(payload)
        self.state = dict(payload)


def _assembler(view: object | None) -> MarketViewAssembler:
    return cast(MarketViewAssembler, cast(object, FakeAssembler(view)))


def _test_instrument_id(_condition_id: str, token_id: str) -> str:
    return f"{token_id}.POLYMARKET"


def _test_market_catalog() -> MarketCatalog:
    return MarketCatalog(instrument_id_resolver=_test_instrument_id)


def _native_projections(
    registry: MarketCatalog | None = None,
) -> dict[str, Any]:
    return {
        "registry": registry or _test_market_catalog(),
    }


def _minimal_native_strategy(
    *,
    core: object,
    strategy_name: str = "ptb_diff",
) -> object:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    return PolySignalNativeStrategy(
        core=core,
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name=strategy_name,
        policy=RuntimeFakePolicy(),
        **_native_projections(),
    )


def _load_static_native_strategy(
    monkeypatch,
    strategy_base: type[object],
    strategy_config: object,
) -> type[Any]:
    runtime_module_name = "polysignal_lab.nautilus_runtime.native_strategy"
    missing = object()
    previous_runtime_module = sys.modules.get(runtime_module_name, missing)
    _ = sys.modules.pop(runtime_module_name, None)

    nautilus_module = ModuleType("nautilus_trader")
    common_module = ModuleType("nautilus_trader.common")
    actor_module = ModuleType("nautilus_trader.common.actor")
    config_module = ModuleType("nautilus_trader.config")
    strategy_module = ModuleType("nautilus_trader.trading.strategy")
    trading_module = ModuleType("nautilus_trader.trading")

    class FakeActor:
        def __init__(self, *, config: object) -> None:
            self.actor_config = config

    actor_module.Actor = FakeActor
    config_module.ActorConfig = lambda: "actor-config"
    config_module.StrategyConfig = lambda: strategy_config
    strategy_module.Strategy = strategy_base

    nautilus_module.common = common_module
    nautilus_module.config = config_module
    nautilus_module.trading = trading_module
    common_module.actor = actor_module
    trading_module.strategy = strategy_module

    monkeypatch.setitem(sys.modules, "nautilus_trader", nautilus_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.common", common_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.common.actor", actor_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.config", config_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.trading", trading_module)
    monkeypatch.setitem(sys.modules, "nautilus_trader.trading.strategy", strategy_module)

    try:
        module = import_module(runtime_module_name)
        return cast(type[Any], module.PolySignalNativeStrategy)
    finally:
        if previous_runtime_module is missing:
            _ = sys.modules.pop(runtime_module_name, None)
        else:
            sys.modules[runtime_module_name] = previous_runtime_module



class _BookViewLike(Protocol):
    best_ask: float | None
    ask_levels: tuple[tuple[float, float], ...]


class _DataHandler(Protocol):
    def on_data(self, data: object) -> object: ...


class _CustomDataStrategy(Protocol):
    custom_subscriptions: list[object]

    def on_data(self, data: object) -> object: ...


class _ObservedOrder(Protocol):
    client_order_id: str | None
    metrics: Mapping[str, object]


class _ObservedFill(Protocol):
    market_id: str
    side: Side
    shares: float
    trade_id: str | None
    last_px: float


def _decision() -> AlphaDecision:
    return AlphaDecision(
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        token_id="up-token",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.82,
        max_entry_price=0.92,
        seconds_to_close=60,
        data_freshness_ms=20,
        reason_codes=("PTB_DIFF_THRESHOLD_OK",),
        metrics={"diff_usd": 120.0},
        order_intent=OrderIntentSpec(
            intent=OrderIntent.PASSIVE_GTD, expiry_seconds=45, pair_id="pair-1"
        ),
        hedge_leg=False,
    )


def test_native_strategy_on_save_load_delegates_to_core_via_encode_decode() -> None:
    core = StatefulFakeCore([])
    strategy = _minimal_native_strategy(core=core, strategy_name="ptb_diff")

    state = strategy.on_save()
    restored_core = StatefulFakeCore([])
    restored = _minimal_native_strategy(core=restored_core, strategy_name="ptb_diff")
    restored.on_load(state)

    assert core.save_calls == 1
    assert set(state) == {state_key("ptb_diff")}
    assert decode_state("ptb_diff", state) == {
        "alpha_marker": 42,
        "trades": {"condition-btc-5m": []},
    }
    assert restored_core.loaded_payload == {
        "alpha_marker": 42,
        "trades": {"condition-btc-5m": []},
    }
    assert restored_core.state == restored_core.loaded_payload


def test_native_strategy_on_save_persists_only_core_state() -> None:
    from polysignal_lab.nautilus_runtime.decision_policy import RejectedDecision

    core = StatefulFakeCore([])
    strategy = _minimal_native_strategy(core=core, strategy_name="vwap_momentum")
    strategy._metrics_tracker._approved_signal_metrics["client-1"] = {
        "dedupe_key": "dedupe-1",
        "level_price": 0.82,
    }
    strategy._pipeline_state.submitted_signal_keys.add("dedupe-1")
    strategy.submitted_orders.append(SimpleNamespace(client_order_id="client-1"))
    strategy.rejected_decisions.append(
        RejectedDecision(reason_code="TEST", detail={}, candidate=None)
    )

    payload = decode_state("vwap_momentum", strategy.on_save())

    assert payload == dict(core.save_state())
    assert "submitted_orders" not in payload
    assert "approved_signal_metrics" not in payload
    assert "submitted_signal_keys" not in payload
    assert "rejected_decisions" not in payload
    assert "fill_state" not in payload
    assert "accepted_state" not in payload


def test_native_strategy_on_load_restores_core_without_runtime_order_truth() -> None:
    from polysignal_lab.nautilus_runtime.decision_policy import RejectedDecision

    core = StatefulFakeCore([])
    strategy = _minimal_native_strategy(core=core, strategy_name="ptb_diff")
    strategy._metrics_tracker._approved_signal_metrics["client-1"] = {"dedupe_key": "dedupe-1"}
    strategy._pipeline_state.submitted_signal_keys.add("dedupe-1")
    strategy.submitted_orders.append(SimpleNamespace(client_order_id="client-1"))
    strategy.rejected_decisions.append(
        RejectedDecision(reason_code="TEST", detail={}, candidate=None)
    )

    state = strategy.on_save()

    restored_core = StatefulFakeCore([])
    restored = _minimal_native_strategy(core=restored_core, strategy_name="ptb_diff")
    restored._metrics_tracker._approved_signal_metrics["preexisting"] = {"dedupe_key": "keep-me"}
    restored.on_load(state)

    assert restored_core.loaded_payload == {
        "alpha_marker": 42,
        "trades": {"condition-btc-5m": []},
    }
    assert restored._metrics_tracker._approved_signal_metrics == {"preexisting": {"dedupe_key": "keep-me"}}
    assert len(restored.submitted_orders) == 0
    assert restored._pipeline_state.submitted_signal_keys == set()
    assert len(restored.rejected_decisions) == 0


# ── Batch evaluation tests (nautilus runtime) ─────────────────────────────────


from polysignal_lab.domain.signal import SignalCandidate  # noqa: E402
from polysignal_lab.nautilus_runtime.decision_policy import (  # noqa: E402
    ApprovedDecision,
    DecisionPolicyActor,
)
from polysignal_lab.nautilus_runtime.native_strategy import (  # noqa: E402
    PolySignalNativeStrategy,
)


class _MockBook:
    best_ask: float | None = 0.82
    ask_levels: tuple[tuple[float, float], ...] = ((0.82, 50.0),)


class _MockView:
    condition_id: str = "condition-btc-5m"

    def book_for(self, side: Side) -> _BookViewLike:
        _ = side
        return _MockBook()

    @property
    def created_at(self) -> datetime:
        return datetime.now(UTC)


class RuntimeFakePolicy(DecisionPolicyActor):
    def evaluate(self, decision: AlphaDecision, view: MarketView) -> ApprovedDecision:
        _ = view
        candidate = SignalCandidate.build(
            strategy=decision.strategy,
            asset=decision.asset,
            timeframe=decision.timeframe,
            market_id=decision.market_id,
            market_slug=decision.market_slug,
            condition_id=decision.condition_id,
            token_id=decision.token_id,
            side=decision.side,
            confidence=decision.confidence,
            entry_reference_price=decision.entry_reference_price,
            max_entry_price=decision.max_entry_price,
            seconds_to_close=decision.seconds_to_close,
            data_freshness_ms=decision.data_freshness_ms,
            reason_codes=list(decision.reason_codes),
            metrics=dict(decision.metrics),
            order_intent=decision.order_intent.intent
            if decision.order_intent
            else None,
            expiry_seconds=decision.order_intent.expiry_seconds
            if decision.order_intent
            else None,
            pair_id=decision.order_intent.pair_id if decision.order_intent else None,
            hedge_leg=decision.hedge_leg,
        )
        return ApprovedDecision(signal=candidate)




def test_runtime_strategy_fok_depth_counts_asks_through_max_entry() -> None:
    decision = AlphaDecision(
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        token_id="up-token",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.50,
        max_entry_price=0.52,
        seconds_to_close=60,
        data_freshness_ms=20,
        reason_codes=("TEST",),
        metrics={},
        order_intent=OrderIntentSpec(intent=OrderIntent.TAKER_FOK, pair_id="pair-1"),
        hedge_leg=False,
    )

    class Book:
        best_ask: float | None = 0.50
        ask_levels: tuple[tuple[float, float], ...] = (
            (0.50, 10.0),
            (0.52, 10.0),
            (0.53, 100.0),
        )

    class View(_MockView):
        def book_for(self, side: Side) -> _BookViewLike:
            _ = side
            return Book()

    from polysignal_lab.nautilus_runtime.order_mapping import order_spec_from_decision

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.submitted = []

        def submit_order(self, order):
            self.submitted.append(order)

    class SpecCapturingStrategy(FakeNativeStrategy):
        def _submit_approved(self, approved, *, view):
            book = view.book_for(approved.signal.side)
            spec = order_spec_from_decision(
                approved,
                fixed_stake_usdc=self.fixed_stake_usdc,
                best_ask=book.best_ask,
            )
            self.submitted_specs.append(spec)
            return SimpleNamespace(client_order_id="captured")

    strategy = SpecCapturingStrategy(
        core=FakeCore([decision]),
        assembler=_assembler(View()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        fixed_stake_usdc=10.0,
        instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
        **_native_projections(),
    )

    strategy.evaluate_condition("condition-btc-5m")

    assert len(strategy.submitted_specs) == 1
    assert strategy.submitted_specs[0].intent == OrderIntent.TAKER_FOK
    assert strategy.submitted_specs[0].quantity == 20.0
    assert len(strategy.rejected_decisions) == 0


def test_native_strategy_records_rejection_when_order_mapping_fails() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class Book:
        best_ask: float | None = 0.55
        ask_levels: tuple[tuple[float, float], ...] = ((0.55, 100.0),)

    class View(_MockView):
        def book_for(self, side: Side) -> _BookViewLike:
            _ = side
            return Book()

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.submitted = []

        def submit_order(self, order):
            self.submitted.append(order)

    decision = AlphaDecision(
        strategy="ptb_diff",
        asset="BTC",
        timeframe="5m",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        token_id="up-token",
        side=Side.UP,
        confidence=0.8,
        entry_reference_price=0.50,
        max_entry_price=0.52,
        seconds_to_close=60,
        data_freshness_ms=20,
        reason_codes=("TEST",),
        metrics={},
        order_intent=OrderIntentSpec(intent=OrderIntent.TAKER_FOK, pair_id="pair-1"),
        hedge_leg=False,
    )

    strategy = FakeNativeStrategy(
        core=FakeCore([decision]),
        assembler=_assembler(View()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        fixed_stake_usdc=10.0,
        instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
        **_native_projections(),
    )

    strategy.evaluate_condition("condition-btc-5m")

    assert len(strategy.submitted_orders) == 0
    assert len(strategy.rejected_decisions) != 0


def test_native_strategy_blocks_duplicate_in_flight_signal_submission() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class View(_MockView):
        pass

    class ReenteringCore(FakeCore):
        def on_order_filled(self, event):
            _ = event
            return [_decision()]

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.submitted: list[str] = []

        def _submit_approved(self, approved, *, view):
            _ = view
            self.submitted.append(approved.signal.dedupe_key)
            return SimpleNamespace(
                id=f"order-{len(self.submitted)}",
                tags={"signal_id": approved.signal.signal_id},
            )

    strategy = FakeNativeStrategy(
        core=ReenteringCore([_decision()]),
        assembler=_assembler(View()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        fixed_stake_usdc=10.0,
        **_native_projections(),
    )

    strategy.evaluate_condition("condition-btc-5m")
    strategy.evaluate_condition("condition-btc-5m")

    assert strategy.submitted == ["BTC:5m:btc-5m:UP:ptb_diff"]
    assert [rejected.reason_code for rejected in strategy.rejected_decisions] == [
        "DUPLICATE_IN_FLIGHT_SIGNAL"
    ]

    strategy.on_order_filled(
        SimpleNamespace(order_id="order-1", fill_price=0.5, shares=1.0, tags={})
    )
    strategy.evaluate_condition("condition-btc-5m")
    assert strategy.submitted == [
        "BTC:5m:btc-5m:UP:ptb_diff",
        "BTC:5m:btc-5m:UP:ptb_diff",
    ]

def test_static_native_strategy_uses_nautilus_subscribe_data_for_custom_data(
    monkeypatch,
) -> None:
    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
        MarketCatalog,
    )

    class FakeBase:
        def __init__(self, *, config: object) -> None:
            self.config = config
            self.custom_subscriptions = []
            self.clock = _NoopClock()

        def subscribe_order_book_deltas(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = instrument_id, args, kwargs

        def subscribe_quote_ticks(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = instrument_id, args, kwargs

        def subscribe_trade_ticks(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = instrument_id, args, kwargs

        def subscribe_data(
            self, data_type: object, *args: object, **kwargs: object
        ) -> None:
            self.custom_subscriptions.append(data_type)

    strategy_type = _load_static_native_strategy(monkeypatch, FakeBase, "cfg")

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token", Side.UP),
            down=InstrumentTokenMeta("down-token", Side.DOWN),
        )
    )

    strategy = strategy_type(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        registry=registry,
    )

    strategy.on_start()

    assert cast(list[object], getattr(strategy, "custom_subscriptions")) != []


def test_static_native_strategy_does_not_bypass_custom_data_lifecycle(monkeypatch) -> None:
    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import (
        PolySignalMarketMetaData,
        PolySignalMarketUniverseData,
        PolySignalPriceToBeatData,
        PolySignalSpotData,
    )

    class FakeMsgBus:
        def __init__(self) -> None:
            self.calls: list[tuple[object, Callable[[object], object]]] = []

        def subscribe(
            self, *, topic: object, handler: Callable[[object], object]
        ) -> None:
            self.calls.append((topic, handler))

    class FakeBase:
        def __init__(self, *, config: object) -> None:
            self.config = config
            self.custom_subscriptions = []
            self._msgbus = FakeMsgBus()
            self.clock = _NoopClock()

        def subscribe_order_book_deltas(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = instrument_id, args, kwargs

        def subscribe_quote_ticks(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = instrument_id, args, kwargs

        def subscribe_trade_ticks(
            self, instrument_id: object, *args: object, **kwargs: object
        ) -> None:
            _ = instrument_id, args, kwargs

        def subscribe_data(
            self, data_type: object, *args: object, **kwargs: object
        ) -> None:
            self.custom_subscriptions.append(data_type)

    strategy_type = _load_static_native_strategy(monkeypatch, FakeBase, "cfg")

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token", Side.UP),
            down=InstrumentTokenMeta("down-token", Side.DOWN),
        )
    )

    strategy = strategy_type(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        registry=registry,
    )

    strategy.on_start()

    assert cast(FakeMsgBus, getattr(strategy, "_msgbus")).calls == []
    custom_subscriptions = cast(list[object], getattr(strategy, "custom_subscriptions"))
    assert {getattr(data_type, "type", data_type) for data_type in custom_subscriptions} == {
        PolySignalSpotData,
        PolySignalPriceToBeatData,
        PolySignalMarketMetaData,
        PolySignalMarketUniverseData,
    }

    strategy.on_data(
        PolySignalSpotData(
            asset="BTC",
            symbol="BTCUSD",
            price=100000.0,
            source="polymarket_rtds",
            freshness_ms=5,
            ts_event=1,
            ts_init=1,
        )
    )

    spot = strategy.custom_data.spot_for("BTC")
    assert spot is not None
    assert spot.price == 100000.0




def test_native_strategy_generates_signal_from_on_data_callback() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        @property
        def order_factory(self) -> FakeOrderFactoryForNative:
            return FakeOrderFactoryForNative()

        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.submitted = []
            self.subscriptions = []

        def submit_order(self, order: object) -> None:
            self.submitted.append(order)

        def subscribe_data(self, data_type: object) -> None:
            self.subscriptions.append(data_type)

    class FakeOrderFactoryForNative:
        def limit(self, **kwargs: object) -> dict[str, object]:
            return dict(kwargs)

    class DataEvent:
        condition_id = "condition-btc-5m"

    strategy = FakeNativeStrategy(
        core=FakeCore([_decision()]),
        assembler=_assembler(_MockView()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        fixed_stake_usdc=10.0,
        instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
        **_native_projections(),
    )

    _ = cast(_DataHandler, cast(object, strategy)).on_data(DataEvent())

    assert len(strategy.submitted) == 1
    assert str(strategy.submitted[0]["instrument_id"]) == "up-token.POLYMARKET"
    assert (
        getattr(
            strategy.submitted[0]["time_in_force"],
            "name",
            strategy.submitted[0]["time_in_force"],
        )
        == "GTD"
    )
    assert len(strategy.submitted_specs) == 0
    assert len(strategy.execution_results) == 0


def test_native_strategy_requires_shared_policy() -> None:
    import pytest

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    with pytest.raises(TypeError, match="policy"):
        PolySignalNativeStrategy(
            core=FakeCore([]),
            assembler=_assembler(None),
            condition_ids=(),
            strategy_name="ptb_diff",
            registry=_test_market_catalog(),
        )


def test_native_strategy_constructor_requires_injected_projections() -> None:
    import pytest

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    with pytest.raises(
        RuntimeError,
        match="requires injected registry and assembler projections",
    ):
        PolySignalNativeStrategy(
            core=FakeCore([]),
            assembler=_assembler(None),
            condition_ids=(),
            strategy_name="ptb_diff",
            policy=RuntimeFakePolicy(),
        )


def test_native_strategy_constructor_requires_injected_assembler() -> None:
    import pytest

    from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    with pytest.raises(
        RuntimeError,
        match="requires injected registry and assembler projections",
    ):
        PolySignalNativeStrategy(
            core=FakeCore([]),
            assembler=cast(Any, None),
            condition_ids=(),
            strategy_name="ptb_diff",
            policy=RuntimeFakePolicy(),
            registry=_test_market_catalog(),
        )


def test_native_strategy_on_start_subscribes_all_custom_data_with_injected_projections() -> (
    None
):
    from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
    from polysignal_lab.nautilus_runtime.custom_data_types import (
        PolySignalMarketMetaData,
        PolySignalMarketUniverseData,
        PolySignalPriceToBeatData,
        PolySignalSpotData,
    )
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.custom_subscriptions: list[object] = []

        def subscribe_data(self, data_type):
            self.custom_subscriptions.append(getattr(data_type, "type", data_type))

        def _start_evaluation_heartbeat(self) -> None:
            return None

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=(),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        registry=_test_market_catalog(),
    )

    strategy.on_start()

    assert PolySignalMarketMetaData in strategy.custom_subscriptions
    assert PolySignalMarketUniverseData in strategy.custom_subscriptions
    assert PolySignalSpotData in strategy.custom_subscriptions
    assert PolySignalPriceToBeatData in strategy.custom_subscriptions


def test_native_strategy_on_start_sets_evaluation_heartbeat() -> None:
    from datetime import UTC, datetime, timedelta

    from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
    from polysignal_lab.nautilus_runtime.native_strategy import (
        EVALUATION_HEARTBEAT_TIMER_NAME,
        PolySignalNativeStrategy,
    )

    class FakeClock:
        def __init__(self) -> None:
            self.timer = None
            self.canceled: list[str] = []

        def set_timer(self, name, interval, *, callback):
            self.timer = (name, interval, callback)

        def cancel_timer(self, name):
            self.canceled.append(name)

    class FakeNativeStrategy(PolySignalNativeStrategy):
        @property
        def clock(self) -> FakeClock:
            return self.fake_clock

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.custom_subscriptions: list[object] = []
            self.evaluated: list[str] = []
            self.fake_clock = FakeClock()

        def subscribe_data(self, data_type):
            self.custom_subscriptions.append(data_type)

        def evaluate_condition(self, condition_id: str) -> None:
            self.evaluated.append(condition_id)

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m", "condition-btc-retired"),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        registry=_test_market_catalog(),
    )
    strategy._active_condition_ids = {"condition-btc-5m"}

    strategy.on_start()

    assert strategy.clock.timer is not None
    name, interval, callback = strategy.clock.timer
    assert name == EVALUATION_HEARTBEAT_TIMER_NAME
    assert interval == timedelta(seconds=10)

    callback(object())

    assert strategy.evaluated == ["condition-btc-5m"]
    strategy._last_market_data_evaluation_at["condition-btc-5m"] = datetime.now(UTC)
    callback(object())

    assert strategy.evaluated == ["condition-btc-5m"]

    strategy.on_stop()

    assert strategy.clock.canceled == [EVALUATION_HEARTBEAT_TIMER_NAME]

def test_native_strategy_reports_progress_on_internal_evaluation_heartbeat() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    progress_events: list[str] = []
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(_MockView()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        **_native_projections(),
        progress_callback=progress_events.append,
    )

    strategy._on_evaluation_heartbeat(object())

    assert progress_events == ["evaluation_heartbeat"]


def test_native_strategy_reports_progress_on_start_without_market_data() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    progress_events: list[str] = []
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        **_native_projections(),
        progress_callback=progress_events.append,
    )

    strategy.on_start()

    assert "start" in progress_events


def test_native_strategy_drops_unknown_project_owned_data_with_metric() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    observed: list[tuple[str, object]] = []
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        **_native_projections(),
    )
    strategy.progress_callback = lambda phase: observed.append((phase, None))

    strategy.on_data(object())

    assert ("dropped_frame", None) in observed


def test_malformed_project_owned_data_does_not_poison_later_valid_market_metadata() -> None:
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketMetaData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        **_native_projections(),
    )

    strategy.on_data(object())
    strategy.on_data(
        PolySignalMarketMetaData(
            market_id="market-1",
            market_slug="btc-updown-5m-market-1",
            condition_id="condition-1",
            asset="BTC",
            timeframe="5m",
            start_ts_ns=1,
            end_ts_ns=2,
            up_token_id="up-1",
            down_token_id="down-1",
            ts_event=11,
            ts_init=12,
        )
    )

    assert strategy.registry.by_condition("condition-1") is not None


def test_native_strategy_unknown_quote_tick_instrument_is_dropped_with_metric() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    phases: list[str] = []
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        **_native_projections(),
    )
    strategy.progress_callback = phases.append

    strategy.on_quote_tick(
        SimpleNamespace(
            instrument_id="unknown.POLYMARKET",
            bid_price=0.1,
            ask_price=0.2,
        )
    )

    assert "dropped_frame" in phases


def test_native_strategy_partial_market_data_mappings_are_dropped_without_evaluation() -> None:
    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
        MarketCatalog,
    )
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class MissingInstrumentCatalog(MarketCatalog):
        def instrument_id_for_token(self, token_id: str) -> str | None:
            _ = token_id
            return None

    cases: tuple[tuple[str, Callable[[PolySignalNativeStrategy, object], None], object], ...] = (
        (
            "quote_tick",
            lambda strategy, data: strategy.on_quote_tick(data),
            SimpleNamespace(
                instrument_id="up-token.POLYMARKET",
                bid_price=0.1,
                ask_price=0.2,
            ),
        ),
        (
            "order_book",
            lambda strategy, data: strategy.on_order_book(data),
            SimpleNamespace(instrument_id="up-token.POLYMARKET", bids=[], asks=[]),
        ),
        (
            "order_book_deltas",
            lambda strategy, data: strategy.on_order_book_deltas(data),
            SimpleNamespace(instrument_id="up-token.POLYMARKET"),
        ),
        (
            "trade_tick",
            lambda strategy, data: strategy.on_trade_tick(data),
            SimpleNamespace(
                instrument_id="up-token.POLYMARKET",
                price=0.2,
                size=3.0,
                aggressor_side="BUY",
            ),
        ),
    )

    for registry in (MissingInstrumentCatalog(),):
        registry.register(
            MarketPairMeta(
                market_id="btc-5m",
                market_slug="btc-updown-5m",
                condition_id="condition-btc-5m",
                asset="BTC",
                timeframe="5m",
                start_ts=None,
                end_ts=None,
                up=InstrumentTokenMeta("up-token", Side.UP),
                down=InstrumentTokenMeta("down-token", Side.DOWN),
            )
        )
        for name, handle, data in cases:
            phases: list[str] = []
            evaluated: list[str] = []
            strategy = PolySignalNativeStrategy(
                core=FakeCore([]),
                assembler=_assembler(None),
                condition_ids=("condition-btc-5m",),
                strategy_name="ptb_diff",
                policy=RuntimeFakePolicy(),
                **_native_projections(registry),
                progress_callback=phases.append,
            )
            def record_evaluation(condition_id: str) -> None:
                evaluated.append(condition_id)

            strategy.evaluate_condition = record_evaluation  # type: ignore[method-assign]

            handle(strategy, data)

            assert "dropped_frame" in phases, name
            assert "market_data_evaluation" not in phases, name
            assert evaluated == [], name


def test_native_strategy_unknown_market_data_instruments_are_dropped_with_metric() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    cases = (
        (
            "order_book",
            lambda strategy, data: strategy.on_order_book(data),
            SimpleNamespace(instrument_id="unknown-book.POLYMARKET", bids=[], asks=[]),
        ),
        (
            "order_book_deltas",
            lambda strategy, data: strategy.on_order_book_deltas(data),
            SimpleNamespace(instrument_id="unknown-deltas.POLYMARKET"),
        ),
        (
            "trade_tick",
            lambda strategy, data: strategy.on_trade_tick(data),
            SimpleNamespace(
                instrument_id="unknown-trade.POLYMARKET",
                price=0.2,
                size=3.0,
                aggressor_side="BUY",
            ),
        ),
    )

    for name, handle, data in cases:
        phases: list[str] = []
        strategy = PolySignalNativeStrategy(
            core=FakeCore([]),
            assembler=_assembler(None),
            condition_ids=("condition-btc-5m",),
            strategy_name="ptb_diff",
            policy=RuntimeFakePolicy(),
            **_native_projections(),
            progress_callback=phases.append,
        )

        handle(strategy, data)

        assert "dropped_frame" in phases, name


def test_native_strategy_drops_unknown_project_owned_data_with_condition_id() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class UnknownProjectData:
        condition_id = "condition-btc-5m"

    observed: list[tuple[str, object]] = []
    calls: list[str] = []
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        **_native_projections(),
    )
    strategy.progress_callback = lambda phase: observed.append((phase, None))
    strategy.evaluate_condition = lambda condition_id: calls.append(condition_id)  # type: ignore[method-assign]

    strategy.on_data(UnknownProjectData())

    assert ("dropped_frame", None) in observed
    assert calls == []


def test_native_strategy_readiness_gate_skips_missing_required_market_view_inputs() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    calls: list[object] = []
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        **_native_projections(),
    )
    strategy.core.evaluate = lambda view: calls.append(view) or []  # type: ignore[method-assign]
    strategy.assembler.build = lambda _condition_id: SimpleNamespace(
        condition_id="condition-btc-5m",
        up_book=None,
        down_book=None,
        spot=None,
        price_to_beat=None,
    )
    phases: list[str] = []
    strategy.progress_callback = phases.append

    strategy.evaluate_condition("condition-btc-5m")

    assert calls == []
    assert "readiness_miss" in phases


def test_native_strategy_routes_decisions_through_policy_actor_decide() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    decision = _decision()
    approved_decision = RuntimeFakePolicy().evaluate(decision, _MockView())
    submitted: list[object] = []
    decided: list[tuple[AlphaDecision, object]] = []

    class ActorPolicy:
        def decide(self, decision: AlphaDecision, view: object) -> object:
            decided.append((decision, view))
            return approved_decision

    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=ActorPolicy(),
        **_native_projections(),
    )
    strategy._submit_approved = lambda approved, *, view: submitted.append((approved, view))  # type: ignore[method-assign]
    view = _MockView()

    strategy._handle_decision(decision, view)

    assert decided == [(decision, view)]
    assert submitted == [(approved_decision, view)]


def test_cache_market_data_provider_uses_nautilus_order_book_methods_and_ts_last() -> None:
    from polysignal_lab.nautilus_runtime.cache_market_data import (
        NautilusCacheMarketDataProvider,
    )

    class Level:
        def __init__(self, price: float, size: float) -> None:
            self.price = price
            self.size = size

    class NautilusLikeOrderBook:
        ts_last = 1_800_000_000_000_000_000

        def bids(self) -> list[Level]:
            return [Level(0.49, 10.0)]

        def asks(self) -> list[Level]:
            return [Level(0.51, 20.0), Level(0.52, 10.0)]

    class Cache:
        def order_book(self, instrument_id: object) -> NautilusLikeOrderBook:
            assert instrument_id == "up-token.POLYMARKET"
            return NautilusLikeOrderBook()

        def trade_ticks(self, instrument_id: object) -> list[object]:
            _ = instrument_id
            return []

    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token", Side.UP),
            down=InstrumentTokenMeta("down-token", Side.DOWN),
        )
    )
    provider = NautilusCacheMarketDataProvider(cast(Any, Cache()), catalog=registry)

    book = provider.book_for_token("up-token")

    assert book is not None
    assert book.best_bid == 0.49
    assert book.best_ask == 0.51
    assert book.ask_levels == ((0.51, 20.0), (0.52, 10.0))
    assert book.received_at == datetime.fromtimestamp(1_800_000_000, UTC)
    assert book.freshness_ms is not None


def test_cache_market_data_provider_treats_missing_trade_ticks_as_empty() -> None:
    from polysignal_lab.nautilus_runtime.cache_market_data import (
        NautilusCacheMarketDataProvider,
    )

    class Cache:
        def order_book(self, instrument_id: object) -> object | None:
            _ = instrument_id
            return None

        def trade_ticks(self, instrument_id: object) -> object:
            _ = instrument_id
            raise LookupError("no cached trades")

    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token", Side.UP),
            down=InstrumentTokenMeta("down-token", Side.DOWN),
        )
    )
    provider = NautilusCacheMarketDataProvider(cast(Any, Cache()), catalog=registry)

    assert provider.trades_for_token("up-token") == ()


def test_cache_market_data_provider_treats_absent_trade_ticks_api_as_empty() -> None:
    from polysignal_lab.nautilus_runtime.cache_market_data import (
        NautilusCacheMarketDataProvider,
    )

    class Cache:
        def order_book(self, instrument_id: object) -> object | None:
            _ = instrument_id
            return None

    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token", Side.UP),
            down=InstrumentTokenMeta("down-token", Side.DOWN),
        )
    )
    provider = NautilusCacheMarketDataProvider(cast(Any, Cache()), catalog=registry)

    assert provider.trades_for_token("up-token") == ()


def test_native_strategy_resolved_instrument_allows_cache_without_instrument_api() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class Cache:
        pass

    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
        **_native_projections(),
    )
    strategy.cache = Cache()

    assert strategy._resolved_instrument("up-token") == "up-token.POLYMARKET"


def test_native_strategy_does_not_submit_when_approved_decision_view_lacks_book() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    decision = _decision()
    approved_decision = RuntimeFakePolicy().evaluate(decision, _MockView())
    submitted: list[object] = []
    phases: list[str] = []
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        **_native_projections(),
        progress_callback=phases.append,
    )
    strategy.policy.decide = lambda decision, view: approved_decision  # type: ignore[method-assign]
    strategy._submit_approved = lambda approved, *, view: submitted.append((approved, view))  # type: ignore[method-assign]
    view = SimpleNamespace(
        book_for=lambda _side: (_ for _ in ()).throw(
            ValueError("Quote maps must not be empty")
        )
    )

    strategy._handle_decision(decision, view)

    assert submitted == []
    assert "readiness_miss" in phases


def _real_market_view_with_empty_quote_depth() -> MarketView:
    from polysignal_lab.alpha.types import FreshnessView, SideBookView, SpotView

    now = datetime.now(UTC)
    return MarketView(
        view_id="view-empty-depth",
        market_id="btc-5m",
        market_slug="btc-updown-5m",
        condition_id="condition-btc-5m",
        asset="BTC",
        timeframe="5m",
        start_ts=None,
        end_ts=None,
        created_at=now,
        seconds_to_close=60,
        up=SideBookView(
            token_id="up-token",
            best_bid=None,
            best_ask=None,
            spread=None,
            freshness_ms=10,
            ask_levels=(),
        ),
        down=SideBookView(
            token_id="down-token",
            best_bid=None,
            best_ask=None,
            spread=None,
            freshness_ms=10,
            ask_levels=(),
        ),
        spot=SpotView(
            asset="BTC",
            symbol="BTCUSD",
            price=100_000.0,
            source="test",
            freshness_ms=10,
        ),
        price_to_beat=None,
        up_trades=(),
        down_trades=(),
        metrics={},
        freshness=FreshnessView(up_book_ms=10, down_book_ms=10, spot_ms=10, max_ms=10),
    )


def test_native_strategy_readiness_gate_skips_real_market_view_with_empty_quote_depth() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    calls: list[object] = []
    phases: list[str] = []
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(_real_market_view_with_empty_quote_depth()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        progress_callback=phases.append,
        **_native_projections(),
    )
    strategy.core.evaluate = lambda view: calls.append(view) or []  # type: ignore[method-assign]

    strategy.evaluate_condition("condition-btc-5m")

    assert calls == []
    assert "readiness_miss" in phases


def test_native_strategy_constructor_without_registry_fails_clearly() -> None:
    import pytest

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    with pytest.raises(
        RuntimeError,
        match="requires injected registry and assembler projections",
    ):
        PolySignalNativeStrategy(
            core=FakeCore([]),
            assembler=_assembler(None),
            condition_ids=(),
            strategy_name="ptb_diff",
            policy=RuntimeFakePolicy(),
            instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
        )


def test_native_strategy_bounds_rejected_decisions_to_prevent_memory_leak() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        **_native_projections(),
    )

    for _ in range(2000):
        strategy.rejected_decisions.append("rejected")
    # With unbounded list this will have 2000 entries, with bounded maxlen <= 1000
    assert len(strategy.rejected_decisions) <= 1000


def test_native_strategy_bounds_submitted_orders_to_prevent_memory_leak() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        **_native_projections(),
    )

    for _ in range(2000):
        strategy.submitted_orders.append("order")
    # With unbounded list this will have 2000 entries, with bounded maxlen <= 1000
    assert len(strategy.submitted_orders) <= 1000


def test_native_strategy_on_start_subscribes_built_in_market_data_by_instrument() -> (
    None
):
    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
        MarketCatalog,
    )
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.book_subscriptions = []
            self.trade_subscriptions = []
            self.custom_subscriptions = []
            self.instrument_requests = []

        def request_instrument(self, instrument_id, *args, **kwargs):
            _ = args, kwargs
            self.instrument_requests.append(str(instrument_id))

        def subscribe_order_book_deltas(self, instrument_id, *args, **kwargs):
            self.book_subscriptions.append(instrument_id)

        def subscribe_trade_ticks(self, instrument_id, *args, **kwargs):
            self.trade_subscriptions.append(instrument_id)

        def subscribe_data(self, data_type, *args, **kwargs):
            self.custom_subscriptions.append(data_type)

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token", Side.UP),
            down=InstrumentTokenMeta("down-token", Side.DOWN),
        )
    )

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        registry=registry,
    )

    strategy.on_start()

    assert [str(value) for value in strategy.book_subscriptions] == [
        "up-token.POLYMARKET",
        "down-token.POLYMARKET",
    ]
    assert [str(value) for value in strategy.trade_subscriptions] == [
        "up-token.POLYMARKET",
        "down-token.POLYMARKET",
    ]
    assert cast(_CustomDataStrategy, cast(object, strategy)).custom_subscriptions != []


def test_native_strategy_subscribes_market_data_per_strategy_instance() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
        MarketCatalog,
    )
    from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler

    from polysignal_lab.nautilus_runtime.cache_market_data import NautilusCacheMarketDataProvider
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData

    seen: list[tuple[str, str]] = []

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, *, label: str, **kwargs):
            super().__init__(**kwargs)
            self.label = label
            self.book_subscriptions: list[str] = []
            self.trade_subscriptions: list[str] = []
            self.instrument_requests: list[str] = []
            self.book_unsubscriptions: list[str] = []
            self.trade_unsubscriptions: list[str] = []

        def request_instrument(self, instrument_id, *args, **kwargs):
            _ = args, kwargs
            self.instrument_requests.append(str(instrument_id))

        def subscribe_order_book_deltas(self, instrument_id, *args, **kwargs):
            _ = args, kwargs
            self.book_subscriptions.append(str(instrument_id))

        def subscribe_trade_ticks(self, instrument_id, *args, **kwargs):
            _ = args, kwargs
            self.trade_subscriptions.append(str(instrument_id))

        def unsubscribe_order_book_deltas(self, instrument_id, *args, **kwargs):
            _ = args, kwargs
            self.book_unsubscriptions.append(str(instrument_id))

        def unsubscribe_trade_ticks(self, instrument_id, *args, **kwargs):
            _ = args, kwargs
            self.trade_unsubscriptions.append(str(instrument_id))

        def evaluate_condition(self, condition_id: str) -> None:
            if condition_id not in self._active_condition_ids:
                return
            seen.append((self.label, condition_id))

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token", Side.UP),
            down=InstrumentTokenMeta("down-token", Side.DOWN),
        )
    )
    cache = SimpleNamespace(
        trade_ticks=lambda instrument_id: (
            [
                SimpleNamespace(
                    price=0.51,
                    size=7.0,
                    aggressor_side="BUYER",
                    ts_event=datetime.now(UTC),
                )
            ]
            if str(instrument_id) == "up-token.POLYMARKET"
            else []
        )
    )
    books = NautilusCacheMarketDataProvider(cache, catalog=registry)
    assembler = MarketViewAssembler(
        catalog=registry,
        books=books,
        custom_data=StrategyCustomDataState(),
    )
    first = FakeNativeStrategy(
        label="first",
        core=FakeCore([]),
        assembler=assembler,
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        registry=registry,
    )
    second = FakeNativeStrategy(
        label="second",
        core=FakeCore([]),
        assembler=assembler,
        condition_ids=("condition-btc-5m",),
        strategy_name="late_consensus",
        policy=RuntimeFakePolicy(),
        registry=registry,
    )

    first.on_start()
    second.on_start()

    assert first.book_subscriptions == ["up-token.POLYMARKET", "down-token.POLYMARKET"]
    assert first.trade_subscriptions == ["up-token.POLYMARKET", "down-token.POLYMARKET"]
    assert second.book_subscriptions == ["up-token.POLYMARKET", "down-token.POLYMARKET"]
    assert second.trade_subscriptions == ["up-token.POLYMARKET", "down-token.POLYMARKET"]

    first.on_trade_tick(
        SimpleNamespace(
            instrument_id="up-token.POLYMARKET",
            price=0.51,
            size=7.0,
            aggressor_side="BUYER",
            ts_event=datetime.now(UTC),
        )
    )

    assert [(trade.price, trade.size) for trade in books.trades_for_token("up-token")] == [
        (0.51, 7.0)
    ]
    assert seen == [("first", "condition-btc-5m")]

    exited = PolySignalMarketUniverseData(
        epoch=2,
        active_condition_ids=(),
        entered_condition_ids=(),
        exited_condition_ids=("condition-btc-5m",),
        condition_to_up_token={},
        condition_to_down_token={},
        condition_to_asset={},
        condition_to_timeframe={},
        ts_event=1,
        ts_init=1,
    )
    first.on_data(exited)

    assert first.book_unsubscriptions == ["up-token.POLYMARKET", "down-token.POLYMARKET"]
    assert first.trade_unsubscriptions == ["up-token.POLYMARKET", "down-token.POLYMARKET"]
    assert second.book_unsubscriptions == []
    assert second.trade_unsubscriptions == []

    seen.clear()
    first.on_trade_tick(
        SimpleNamespace(
            instrument_id="up-token.POLYMARKET",
            price=0.52,
            size=3.0,
            aggressor_side="BUYER",
            ts_event=datetime.now(UTC),
        )
    )
    assert seen == []

    second.on_data(exited)

    assert second.book_unsubscriptions == ["up-token.POLYMARKET", "down-token.POLYMARKET"]
    assert second.trade_unsubscriptions == ["up-token.POLYMARKET", "down-token.POLYMARKET"]


def test_native_strategy_universe_update_subscribes_entered_market_once() -> None:
    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import (
        PolySignalMarketMetaData,
        PolySignalMarketUniverseData,
    )
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.book_subscriptions = []
            self.trade_subscriptions = []
            self.instrument_requests = []

        def request_instrument(self, instrument_id, *args, **kwargs):
            _ = args, kwargs
            self.instrument_requests.append(str(instrument_id))

        def subscribe_order_book_deltas(self, instrument_id, *args, **kwargs):
            self.book_subscriptions.append(str(instrument_id))

        def subscribe_trade_ticks(self, instrument_id, *args, **kwargs):
            self.trade_subscriptions.append(str(instrument_id))

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        registry=registry,
    )

    strategy.on_data(
        PolySignalMarketMetaData(
            market_id="condition-b",
            market_slug="btc-updown-5m-b",
            condition_id="condition-b",
            asset="BTC",
            timeframe="5m",
            start_ts_ns=1,
            end_ts_ns=2,
            up_token_id="up-b",
            down_token_id="down-b",
            ts_event=1,
            ts_init=1,
        )
    )
    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=2,
            active_condition_ids=("condition-a", "condition-b"),
            entered_condition_ids=("condition-b",),
            exited_condition_ids=(),
            condition_to_up_token={"condition-a": "up-a", "condition-b": "up-b"},
            condition_to_down_token={"condition-a": "down-a", "condition-b": "down-b"},
            condition_to_asset={"condition-a": "BTC", "condition-b": "BTC"},
            condition_to_timeframe={"condition-a": "5m", "condition-b": "5m"},
            ts_event=1,
            ts_init=1,
        )
    )
    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=2,
            active_condition_ids=("condition-a", "condition-b"),
            entered_condition_ids=("condition-b",),
            exited_condition_ids=(),
            condition_to_up_token={"condition-a": "up-a", "condition-b": "up-b"},
            condition_to_down_token={"condition-a": "down-a", "condition-b": "down-b"},
            condition_to_asset={"condition-a": "BTC", "condition-b": "BTC"},
            condition_to_timeframe={"condition-a": "5m", "condition-b": "5m"},
            ts_event=1,
            ts_init=1,
        )
    )

    assert strategy.book_subscriptions.count("up-b.POLYMARKET") == 1
    assert strategy.trade_subscriptions.count("down-b.POLYMARKET") == 1


def test_native_strategy_universe_update_recovers_still_active_missing_subscription() -> (
    None
):
    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
        MarketCatalog,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.book_subscriptions = []
            self.trade_subscriptions = []

        def subscribe_order_book_deltas(self, instrument_id, *args, **kwargs):
            self.book_subscriptions.append(str(instrument_id))

        def subscribe_trade_ticks(self, instrument_id, *args, **kwargs):
            self.trade_subscriptions.append(str(instrument_id))

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        registry=registry,
    )

    strategy.on_start()
    strategy._subscription_state.wire_condition_ids.clear()

    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=2,
            active_condition_ids=("condition-a",),
            entered_condition_ids=(),
            exited_condition_ids=(),
            condition_to_up_token={"condition-a": "up-a"},
            condition_to_down_token={"condition-a": "down-a"},
            condition_to_asset={"condition-a": "BTC"},
            condition_to_timeframe={"condition-a": "5m"},
            ts_event=1,
            ts_init=1,
        )
    )

    assert strategy.book_subscriptions.count("up-a.POLYMARKET") == 2
    assert strategy.book_subscriptions.count("down-a.POLYMARKET") == 2
    assert strategy.trade_subscriptions.count("up-a.POLYMARKET") == 2
    assert strategy.trade_subscriptions.count("down-a.POLYMARKET") == 2
    assert strategy._subscription_state.wire_condition_ids == {"condition-a"}



def test_native_strategy_universe_update_skips_duplicate_wired_condition() -> (
    None
):
    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
        MarketCatalog,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.book_subscriptions = []
            self.trade_subscriptions = []

        def subscribe_order_book_deltas(self, instrument_id, *args, **kwargs):
            self.book_subscriptions.append(str(instrument_id))

        def subscribe_trade_ticks(self, instrument_id, *args, **kwargs):
            self.trade_subscriptions.append(str(instrument_id))

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        registry=registry,
    )

    strategy.on_start()
    initial_book_count = len(strategy.book_subscriptions)
    initial_trade_count = len(strategy.trade_subscriptions)

    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=2,
            active_condition_ids=("condition-a",),
            entered_condition_ids=(),
            exited_condition_ids=(),
            condition_to_up_token={"condition-a": "up-a"},
            condition_to_down_token={"condition-a": "down-a"},
            condition_to_asset={"condition-a": "BTC"},
            condition_to_timeframe={"condition-a": "5m"},
            ts_event=1,
            ts_init=1,
        )
    )

    assert len(strategy.book_subscriptions) == initial_book_count
    assert len(strategy.trade_subscriptions) == initial_trade_count



def test_native_strategy_ptb_update_re_requests_unconfirmed_wired_market() -> None:
    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
        MarketCatalog,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalPriceToBeatData
    from datetime import UTC, datetime, timedelta
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.instrument_requests = []
            self.book_subscriptions = []
            self.trade_subscriptions = []

        def request_instrument(self, instrument_id, *args, **kwargs):
            _ = args, kwargs
            self.instrument_requests.append(str(instrument_id))

        def subscribe_order_book_deltas(self, instrument_id, *args, **kwargs):
            self.book_subscriptions.append(str(instrument_id))

        def subscribe_trade_ticks(self, instrument_id, *args, **kwargs):
            self.trade_subscriptions.append(str(instrument_id))

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        registry=registry,
    )

    strategy.on_start()

    strategy.on_data(
        PolySignalPriceToBeatData(
            condition_id="condition-a",
            value=100000.0,
            source="anchor",
            verified=True,
            from_anchor_service=True,
            anchor_source="chainlink",
            anchor_lag_ms=0,
            ts_event=1,
            ts_init=1,
        )
    )

    assert strategy.instrument_requests == [
        "up-a.POLYMARKET",
        "down-a.POLYMARKET",
    ]
def test_native_strategy_active_market_without_metadata_stays_pending_until_metadata_arrives() -> (
    None
):
    from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
    from polysignal_lab.nautilus_runtime.custom_data_types import (
        PolySignalMarketMetaData,
        PolySignalMarketUniverseData,
    )
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.book_subscriptions = []
            self.trade_subscriptions = []

        def subscribe_order_book_deltas(self, instrument_id, *args, **kwargs):
            self.book_subscriptions.append(str(instrument_id))

        def subscribe_trade_ticks(self, instrument_id, *args, **kwargs):
            self.trade_subscriptions.append(str(instrument_id))

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=(),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        registry=_test_market_catalog(),
        instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
    )

    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=2,
            active_condition_ids=("condition-b",),
            entered_condition_ids=(),
            exited_condition_ids=(),
            condition_to_up_token={"condition-b": "up-b"},
            condition_to_down_token={"condition-b": "down-b"},
            condition_to_asset={"condition-b": "BTC"},
            condition_to_timeframe={"condition-b": "5m"},
            ts_event=1,
            ts_init=1,
        )
    )
    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=3,
            active_condition_ids=("condition-b",),
            entered_condition_ids=(),
            exited_condition_ids=(),
            condition_to_up_token={"condition-b": "up-b"},
            condition_to_down_token={"condition-b": "down-b"},
            condition_to_asset={"condition-b": "BTC"},
            condition_to_timeframe={"condition-b": "5m"},
            ts_event=1,
            ts_init=1,
        )
    )

    assert strategy.book_subscriptions == []
    assert strategy.trade_subscriptions == []
    assert strategy._subscription_state.pending_metadata_condition_ids == {
        "condition-b"
    }

    strategy.on_data(
        PolySignalMarketMetaData(
            market_id="condition-b",
            market_slug="btc-updown-5m-b",
            condition_id="condition-b",
            asset="BTC",
            timeframe="5m",
            start_ts_ns=1,
            end_ts_ns=2,
            up_token_id="up-b",
            down_token_id="down-b",
            ts_event=1,
            ts_init=1,
        )
    )

    assert strategy.book_subscriptions == ["up-b.POLYMARKET", "down-b.POLYMARKET"]
    assert strategy.trade_subscriptions == ["up-b.POLYMARKET", "down-b.POLYMARKET"]
    assert strategy._subscription_state.pending_metadata_condition_ids == set()
    assert strategy._subscription_state.wire_condition_ids == {"condition-b"}

def test_native_strategy_subscribes_market_data_without_cache_gate() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
        MarketCatalog,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeCache:
        def __init__(self) -> None:
            self.loaded: set[str] = set()

        def instrument(self, instrument_id):
            key = str(instrument_id)
            return SimpleNamespace(id=instrument_id) if key in self.loaded else None

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.cache = FakeCache()
            self.instrument_requests: list[str] = []
            self.book_subscriptions: list[str] = []
            self.trade_subscriptions: list[str] = []

        def request_instrument(self, instrument_id, *args, **kwargs):
            _ = args, kwargs
            self.instrument_requests.append(str(instrument_id))

        def subscribe_order_book_deltas(self, instrument_id, *args, **kwargs):
            _ = args, kwargs
            self.book_subscriptions.append(str(instrument_id))

        def subscribe_trade_ticks(self, instrument_id, *args, **kwargs):
            _ = args, kwargs
            self.trade_subscriptions.append(str(instrument_id))

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=(),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        registry=registry,
    )

    universe = PolySignalMarketUniverseData(
        epoch=2,
        active_condition_ids=("condition-a",),
        entered_condition_ids=(),
        exited_condition_ids=(),
        condition_to_up_token={"condition-a": "up-a"},
        condition_to_down_token={"condition-a": "down-a"},
        condition_to_asset={"condition-a": "BTC"},
        condition_to_timeframe={"condition-a": "5m"},
        ts_event=1,
        ts_init=1,
    )

    strategy.on_data(universe)

    assert strategy.instrument_requests == []
    assert strategy.book_subscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]
    assert strategy.trade_subscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]
    assert strategy._subscription_state.pending_subscribe_condition_ids == set()
    assert strategy._subscription_state.wire_condition_ids == {"condition-a"}



def test_native_strategy_active_market_without_subscribe_hooks_still_marks_wired() -> (
    None
):
    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
        MarketCatalog,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=(),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        registry=registry,
    )

    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=2,
            active_condition_ids=("condition-a",),
            entered_condition_ids=(),
            exited_condition_ids=(),
            condition_to_up_token={"condition-a": "up-a"},
            condition_to_down_token={"condition-a": "down-a"},
            condition_to_asset={"condition-a": "BTC"},
            condition_to_timeframe={"condition-a": "5m"},
            ts_event=1,
            ts_init=1,
        )
    )

    assert strategy._subscription_state.wire_condition_ids == {"condition-a"}
    assert strategy._subscription_state.pending_subscribe_condition_ids == set()


def test_native_strategy_exited_market_is_gated_even_if_late_tick_arrives() -> None:
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    seen: list[str] = []

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def _handle_decision(self, decision, view):
            _ = decision
            seen.append(view.condition_id)

    view = _MockView()
    view.condition_id = "condition-a"
    strategy = FakeNativeStrategy(
        core=FakeCore([_decision()]),
        assembler=_assembler(view),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        **_native_projections(),
    )
    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=3,
            active_condition_ids=("condition-b",),
            entered_condition_ids=("condition-b",),
            exited_condition_ids=("condition-a",),
            condition_to_up_token={"condition-b": "up-b"},
            condition_to_down_token={"condition-b": "down-b"},
            condition_to_asset={"condition-b": "BTC"},
            condition_to_timeframe={"condition-b": "5m"},
            ts_event=1,
            ts_init=1,
        )
    )

    strategy.evaluate_condition("condition-a")

    assert seen == []


def test_native_strategy_exited_market_fill_follow_up_is_gated() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class Book:
        best_ask: float | None = 0.50
        ask_levels: tuple[tuple[float, float], ...] = ((0.50, 20.0),)

    class View(_MockView):
        condition_id = "condition-a"

        def book_for(self, side: Side) -> _BookViewLike:
            _ = side
            return Book()

    class ExitedFollowUpCore:
        def __init__(self) -> None:
            self.fill_condition_ids: list[str] = []

        def evaluate(self, view: MarketView) -> list[AlphaDecision]:
            _ = view
            return []

        def on_order_filled(self, event: object) -> list[AlphaDecision]:
            self.fill_condition_ids.append(str(getattr(event, "condition_id")))
            return [
                AlphaDecision(
                    strategy="ptb_diff",
                    asset="BTC",
                    timeframe="5m",
                    market_id="btc-5m-a",
                    market_slug="btc-updown-5m-a",
                    condition_id="condition-a",
                    token_id="up-a",
                    side=Side.UP,
                    confidence=0.8,
                    entry_reference_price=0.50,
                    max_entry_price=0.52,
                    seconds_to_close=60,
                    data_freshness_ms=20,
                    reason_codes=("FOLLOW_UP",),
                    metrics={},
                    order_intent=OrderIntentSpec(
                        intent=OrderIntent.TAKER_FOK, pair_id="pair-condition-a"
                    ),
                    hedge_leg=False,
                )
            ]

    class FakeOrderFactory:
        def limit(self, **kwargs):
            return kwargs

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.order_factory = FakeOrderFactory()
            self.submitted = []

        def submit_order(self, order):
            self.submitted.append(order)

    core = ExitedFollowUpCore()
    strategy = FakeNativeStrategy(
        core=core,
        assembler=_assembler(View()),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        fixed_stake_usdc=10.0,
        instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
        **_native_projections(),
    )
    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=3,
            active_condition_ids=("condition-b",),
            entered_condition_ids=("condition-b",),
            exited_condition_ids=("condition-a",),
            condition_to_up_token={"condition-b": "up-b"},
            condition_to_down_token={"condition-b": "down-b"},
            condition_to_asset={"condition-b": "BTC"},
            condition_to_timeframe={"condition-b": "5m"},
            ts_event=1,
            ts_init=1,
        )
    )

    strategy.on_order_filled(
        SimpleNamespace(
            order_id="order-a-1",
            client_order_id="client-a-1",
            market_id="btc-5m-a",
            condition_id="condition-a",
            token_id="up-a",
            side=Side.UP,
            last_qty=10.0,
            last_px=0.5,
            trade_id="trade-a-1",
            liquidity_side="TAKER",
            tags=[
                "strategy=ptb_diff",
                "market_id=btc-5m-a",
                "condition_id=condition-a",
                "token_id=up-a",
            ],
            ts_event=datetime.now(UTC),
        )
    )

    assert core.fill_condition_ids == ["condition-a"]
    assert strategy.submitted == []
    assert len(strategy.submitted_orders) == 0


def test_native_strategy_exited_market_unsubscribes_when_hooks_exist() -> None:
    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
        MarketCatalog,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.book_subscriptions = []
            self.trade_subscriptions = []
            self.book_unsubscriptions = []
            self.trade_unsubscriptions = []

        def subscribe_order_book_deltas(self, instrument_id, *args, **kwargs):
            self.book_subscriptions.append(str(instrument_id))

        def subscribe_trade_ticks(self, instrument_id, *args, **kwargs):
            self.trade_subscriptions.append(str(instrument_id))

        def unsubscribe_order_book_deltas(self, instrument_id, *args, **kwargs):
            self.book_unsubscriptions.append(str(instrument_id))

        def unsubscribe_trade_ticks(self, instrument_id, *args, **kwargs):
            self.trade_unsubscriptions.append(str(instrument_id))

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        registry=registry,
    )

    strategy.on_start()
    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=3,
            active_condition_ids=(),
            entered_condition_ids=(),
            exited_condition_ids=("condition-a",),
            condition_to_up_token={},
            condition_to_down_token={},
            condition_to_asset={},
            condition_to_timeframe={},
            ts_event=1,
            ts_init=1,
        )
    )

    assert strategy.book_subscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]
    assert strategy.trade_subscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]
    assert strategy.book_unsubscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]
    assert strategy.trade_unsubscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]
    assert strategy._subscription_state.wire_condition_ids == set()
    assert strategy._subscription_state.retained_wire_condition_ids == set()

    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=4,
            active_condition_ids=("condition-a",),
            entered_condition_ids=("condition-a",),
            exited_condition_ids=(),
            condition_to_up_token={"condition-a": "up-a"},
            condition_to_down_token={"condition-a": "down-a"},
            condition_to_asset={"condition-a": "BTC"},
            condition_to_timeframe={"condition-a": "5m"},
            ts_event=1,
            ts_init=1,
        )
    )

    assert strategy.book_subscriptions.count("up-a.POLYMARKET") == 2
    assert strategy.book_subscriptions.count("down-a.POLYMARKET") == 2
    assert strategy.trade_subscriptions.count("up-a.POLYMARKET") == 2
    assert strategy.trade_subscriptions.count("down-a.POLYMARKET") == 2
    assert strategy._subscription_state.wire_condition_ids == {"condition-a"}


def test_native_strategy_exited_l1_market_unsubscribes_quote_ticks() -> None:
    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
        MarketCatalog,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.quote_subscriptions = []
            self.trade_subscriptions = []
            self.quote_unsubscriptions = []
            self.trade_unsubscriptions = []

        def subscribe_quote_ticks(self, instrument_id, *args, **kwargs):
            self.quote_subscriptions.append(str(instrument_id))

        def subscribe_trade_ticks(self, instrument_id, *args, **kwargs):
            self.trade_subscriptions.append(str(instrument_id))

        def unsubscribe_quote_ticks(self, instrument_id, *args, **kwargs):
            self.quote_unsubscriptions.append(str(instrument_id))

        def unsubscribe_trade_ticks(self, instrument_id, *args, **kwargs):
            self.trade_unsubscriptions.append(str(instrument_id))

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        book_type="L1_MBP",
        registry=registry,
    )

    strategy.on_start()
    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=3,
            active_condition_ids=(),
            entered_condition_ids=(),
            exited_condition_ids=("condition-a",),
            condition_to_up_token={},
            condition_to_down_token={},
            condition_to_asset={},
            condition_to_timeframe={},
            ts_event=1,
            ts_init=1,
        )
    )

    assert strategy.quote_subscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]
    assert strategy.trade_subscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]
    assert strategy.quote_unsubscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]
    assert strategy.trade_unsubscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]


def test_native_strategy_exited_market_unsubscribes_without_book_type_kwarg() -> None:
    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
        MarketCatalog,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.book_unsubscriptions = []
            self.trade_unsubscriptions = []

        def subscribe_order_book_deltas(self, instrument_id, *args, **kwargs):
            _ = instrument_id, args, kwargs

        def subscribe_trade_ticks(self, instrument_id, *args, **kwargs):
            _ = instrument_id, args, kwargs

        def unsubscribe_order_book_deltas(self, instrument_id):
            self.book_unsubscriptions.append(str(instrument_id))

        def unsubscribe_trade_ticks(self, instrument_id):
            self.trade_unsubscriptions.append(str(instrument_id))

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        registry=registry,
    )

    strategy.on_start()
    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=3,
            active_condition_ids=(),
            entered_condition_ids=(),
            exited_condition_ids=("condition-a",),
            condition_to_up_token={},
            condition_to_down_token={},
            condition_to_asset={},
            condition_to_timeframe={},
            ts_event=1,
            ts_init=1,
        )
    )

    assert strategy.book_unsubscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]
    assert strategy.trade_unsubscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]


def test_native_strategy_exited_market_is_noop_when_unsubscribe_disabled() -> None:
    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
        MarketCatalog,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.book_unsubscriptions = []
            self.trade_unsubscriptions = []

        def subscribe_order_book_deltas(self, instrument_id, *args, **kwargs):
            _ = instrument_id

        def subscribe_trade_ticks(self, instrument_id, *args, **kwargs):
            _ = instrument_id

        def unsubscribe_order_book_deltas(self, instrument_id, *args, **kwargs):
            self.book_unsubscriptions.append(str(instrument_id))

        def unsubscribe_trade_ticks(self, instrument_id, *args, **kwargs):
            self.trade_unsubscriptions.append(str(instrument_id))

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        registry=registry,
        unsubscribe_exited=False,
    )

    strategy.on_start()
    strategy._subscription_state.pending_metadata_condition_ids.add("condition-a")
    strategy._subscription_state.pending_subscribe_condition_ids.add("condition-a")

    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=3,
            active_condition_ids=(),
            entered_condition_ids=(),
            exited_condition_ids=("condition-a",),
            condition_to_up_token={},
            condition_to_down_token={},
            condition_to_asset={},
            condition_to_timeframe={},
            ts_event=1,
            ts_init=1,
        )
    )

    assert strategy.book_unsubscriptions == []
    assert strategy.trade_unsubscriptions == []
    assert strategy._subscription_state.pending_metadata_condition_ids == set()
    assert strategy._subscription_state.pending_subscribe_condition_ids == set()
    assert strategy._subscription_state.wire_condition_ids == {"condition-a"}
    assert strategy._subscription_state.retained_wire_condition_ids == set()


def test_native_strategy_exited_market_without_unsubscribe_hooks_clears_wire_state() -> (
    None
):
    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
        MarketCatalog,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.book_subscriptions = []
            self.trade_subscriptions = []

        def subscribe_order_book_deltas(self, instrument_id, *args, **kwargs):
            self.book_subscriptions.append(str(instrument_id))

        def subscribe_trade_ticks(self, instrument_id, *args, **kwargs):
            self.trade_subscriptions.append(str(instrument_id))

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        registry=registry,
    )

    strategy.on_start()
    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=3,
            active_condition_ids=(),
            entered_condition_ids=(),
            exited_condition_ids=("condition-a",),
            condition_to_up_token={},
            condition_to_down_token={},
            condition_to_asset={},
            condition_to_timeframe={},
            ts_event=1,
            ts_init=1,
        )
    )

    assert strategy._active_condition_ids == set()
    assert strategy._subscription_state.wire_condition_ids == set()
    assert strategy._subscription_state.retained_wire_condition_ids == set()

    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=4,
            active_condition_ids=("condition-a",),
            entered_condition_ids=("condition-a",),
            exited_condition_ids=(),
            condition_to_up_token={"condition-a": "up-a"},
            condition_to_down_token={"condition-a": "down-a"},
            condition_to_asset={"condition-a": "BTC"},
            condition_to_timeframe={"condition-a": "5m"},
            ts_event=1,
            ts_init=1,
        )
    )

    assert strategy.book_subscriptions == [
        "up-a.POLYMARKET",
        "down-a.POLYMARKET",
        "up-a.POLYMARKET",
        "down-a.POLYMARKET",
    ]
    assert strategy.trade_subscriptions == [
        "up-a.POLYMARKET",
        "down-a.POLYMARKET",
        "up-a.POLYMARKET",
        "down-a.POLYMARKET",
    ]
    assert strategy._subscription_state.retained_wire_condition_ids == set()


def test_native_strategy_exited_market_trade_tick_stays_gated() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
        MarketCatalog,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    seen: list[str] = []

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def subscribe_order_book_deltas(self, instrument_id, *args, **kwargs):
            _ = instrument_id, args, kwargs

        def subscribe_trade_ticks(self, instrument_id, *args, **kwargs):
            _ = instrument_id, args, kwargs

        def _handle_decision(self, decision, view):
            _ = decision
            seen.append(view.condition_id)

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a", Side.UP),
            down=InstrumentTokenMeta("down-a", Side.DOWN),
        )
    )

    view = _MockView()
    view.condition_id = "condition-a"
    strategy = FakeNativeStrategy(
        core=FakeCore([_decision()]),
        assembler=_assembler(view),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        registry=registry,
    )

    strategy.on_start()
    strategy.on_data(
        PolySignalMarketUniverseData(
            epoch=3,
            active_condition_ids=(),
            entered_condition_ids=(),
            exited_condition_ids=("condition-a",),
            condition_to_up_token={},
            condition_to_down_token={},
            condition_to_asset={},
            condition_to_timeframe={},
            ts_event=1,
            ts_init=1,
        )
    )

    strategy.on_trade_tick(
        SimpleNamespace(
            instrument_id="up-a.POLYMARKET",
            price=0.51,
            size=7.0,
            aggressor_side="BUYER",
            ts_event=datetime.now(UTC),
        )
    )

    assert strategy._subscription_state.retained_wire_condition_ids == set()
    assert seen == []


def test_native_strategy_routes_spot_custom_data_to_matching_asset_conditions_only() -> (
    None
):
    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
        MarketCatalog,
    )
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalSpotData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    seen = []
    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token", Side.UP),
            down=InstrumentTokenMeta("down-token", Side.DOWN),
        )
    )
    registry.register(
        MarketPairMeta(
            market_id="eth-5m",
            market_slug="eth-updown-5m",
            condition_id="condition-eth-5m",
            asset="ETH",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("eth-up", Side.UP),
            down=InstrumentTokenMeta("eth-down", Side.DOWN),
        )
    )

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

        def evaluate_condition(self, condition_id: str) -> None:
            seen.append(condition_id)

    sidecar = StrategyCustomDataState()
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m", "condition-eth-5m"),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        registry=registry,
    )

    _ = cast(_DataHandler, cast(object, strategy)).on_data(
        PolySignalSpotData(
            asset="BTC",
            symbol="BTCUSD",
            price=100000.0,
            source="polymarket_rtds",
            freshness_ms=10,
            ts_event=1,
            ts_init=2,
        )
    )

    assert seen == ["condition-btc-5m"]
    assert strategy.custom_data.spot_for("BTC") is not None


def test_native_strategy_routes_ptb_custom_data_to_matching_active_condition_only() -> (
    None
):
    from polysignal_lab.nautilus_bridge.market_catalog import MarketCatalog
    from polysignal_lab.nautilus_runtime.custom_data_types import PolySignalPriceToBeatData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class RecordingAssembler(FakeAssembler):
        def __init__(self) -> None:
            super().__init__(None)
            self.seen: list[str] = []

        def build(
            self,
            condition_id: str,
            *,
            created_at: datetime | None = None,
        ) -> MarketView | None:
            _ = created_at
            self.seen.append(condition_id)
            return None

    assembler = RecordingAssembler()
    sidecar = StrategyCustomDataState()
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=cast(MarketViewAssembler, cast(object, assembler)),
        condition_ids=("condition-active",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        registry=_test_market_catalog(),
    )

    _ = cast(_DataHandler, cast(object, strategy)).on_data(
        PolySignalPriceToBeatData(
            condition_id="condition-active",
            value=99950.0,
            source="anchor",
            verified=True,
            from_anchor_service=True,
            anchor_source="chainlink",
            anchor_lag_ms=5,
            ts_event=1,
            ts_init=2,
        )
    )
    _ = cast(_DataHandler, cast(object, strategy)).on_data(
        PolySignalPriceToBeatData(
            condition_id="condition-inactive",
            value=100050.0,
            source="anchor",
            verified=True,
            from_anchor_service=True,
            anchor_source="chainlink",
            anchor_lag_ms=5,
            ts_event=3,
            ts_init=4,
        )
    )

    assert assembler.seen == ["condition-active"]
    active_ptb = strategy.custom_data.ptb_for("condition-active")
    inactive_ptb = strategy.custom_data.ptb_for("condition-inactive")
    assert active_ptb is not None
    assert active_ptb.value == 99950.0
    assert inactive_ptb is not None
    assert inactive_ptb.value == 100050.0




def test_native_strategy_trade_tick_callback_reads_cache_trades_without_shared_trade_history_write() -> None:
    from types import SimpleNamespace

    from polysignal_lab.alpha.types import SpotView
    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
        MarketCatalog,
    )
    from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler

    from polysignal_lab.nautilus_runtime.cache_market_data import NautilusCacheMarketDataProvider
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeLevel:
        def __init__(self, price: float, size: float) -> None:
            self.price = price
            self.size = size

    class FakeOrderBook:
        def __init__(self, bids, asks) -> None:
            self.bids = bids
            self.asks = asks
            self.last_trade_price = None
            self.last_trade_size = None
            self.last_trade_timestamp = None
            self.received_at = datetime.now(UTC)

    class FakeTrade:
        price = 0.51
        size = 7.0
        aggressor_side = "BUYER"
        ts_event = datetime.now(UTC)

    class FakeCache:
        def __init__(self) -> None:
            self.books = {
                "up-token.POLYMARKET": FakeOrderBook(
                    bids=[FakeLevel(0.49, 20.0)],
                    asks=[FakeLevel(0.50, 20.0)],
                ),
                "down-token.POLYMARKET": FakeOrderBook(
                    bids=[FakeLevel(0.48, 20.0)],
                    asks=[FakeLevel(0.51, 20.0)],
                ),
            }
            self.trades = {"up-token.POLYMARKET": [FakeTrade()]}

        def order_book(self, instrument_id):
            return self.books[instrument_id]

        def trade_ticks(self, instrument_id):
            return self.trades.get(str(instrument_id), [])

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token", Side.UP),
            down=InstrumentTokenMeta("down-token", Side.DOWN),
        )
    )
    sidecar = StrategyCustomDataState()
    sidecar.apply(
        PolySignalSpotData(
            asset="BTC",
            symbol="BTCUSD",
            price=100000.0,
            source="polymarket_rtds",
            freshness_ms=10,
            ts_event=0,
            ts_init=0,
        )
    )
    sidecar.apply(
        PolySignalPriceToBeatData(
            condition_id="condition-btc-5m",
            value=99950.0,
            source="anchor",
            verified=True,
            from_anchor_service=True,
            anchor_source="chainlink",
            anchor_lag_ms=5,
            ts_event=1_700_000_000_000_000_000,
            ts_init=1_700_000_000_000_000_000,
        )
    )
    fake_cache = FakeCache()
    books = NautilusCacheMarketDataProvider(fake_cache, catalog=registry)
    assembler = MarketViewAssembler(
        catalog=registry,
        books=books,
        custom_data=sidecar,
    )

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.cache = fake_cache
            self.evaluated: list[str] = []

        def evaluate_condition(self, condition_id: str) -> None:
            self.evaluated.append(condition_id)
            super().evaluate_condition(condition_id)

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=assembler,
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        registry=registry,
    )

    strategy.on_order_book_deltas(SimpleNamespace(instrument_id="up-token.POLYMARKET"))
    strategy.evaluated.clear()
    strategy.on_trade_tick(
        SimpleNamespace(
            instrument_id="up-token.POLYMARKET",
            price=0.51,
            size=7.0,
            aggressor_side="BUYER",
            ts_event=datetime.now(UTC),
        )
    )

    trades = books.trades_for_token("up-token")
    assert len(trades) == 1
    assert trades[0].price == 0.51
    assert strategy.evaluated == ["condition-btc-5m"]


def test_native_strategy_on_order_accepted_preserves_approved_signal_metrics() -> None:
    from types import SimpleNamespace

    from polysignal_lab.alpha.one_cent_buy_core import OneCentBuyAlphaCore
    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
        MarketCatalog,
    )
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
    from polysignal_lab.domain.strategy_config import OneCentBuyConfig

    class RecordingObservability:
        def __init__(self) -> None:
            self.decisions: list[tuple[str, bool]] = []
            self.rejections: list[object] = []
            self.orders: list[object] = []
            self.fills: list[object] = []
            self.positions: list[object] = []

        def record_decision(self, decision, accepted: bool) -> None:
            self.decisions.append((decision.strategy, accepted))

        def record_rejected_decision(self, rejected: object) -> None:
            self.rejections.append(rejected)

        def record_nautilus_order_event(self, event: object) -> None:
            self.orders.append(event)

        def record_nautilus_fill_event(self, event: object) -> None:
            self.fills.append(event)

        def record_nautilus_position(self, position: object) -> None:
            self.positions.append(position)

    class FakeOrderFactoryForNative:
        def limit(self, **kwargs):
            return kwargs

    class OneCentView:
        condition_id = "condition-btc-5m"
        market_id = "btc-5m"

        def __init__(self) -> None:
            now = datetime.now(UTC)
            self.created_at = now
            self.start_ts = now - timedelta(seconds=60)
            self.end_ts = now + timedelta(seconds=60)
            self.seconds_to_close = 60
            self.asset = "BTC"
            self.timeframe = "5m"
            self.market_slug = "btc-updown-5m"
            self.freshness = SimpleNamespace(max_ms=10)

        def book_for(self, side):
            if side == Side.DOWN:
                return SimpleNamespace(
                    token_id="down-token",
                    best_ask=0.01,
                    best_bid=0.01,
                    ask_levels=((0.01, 100.0),),
                )
            return SimpleNamespace(
                token_id="up-token",
                best_ask=0.05,
                best_bid=0.04,
                ask_levels=((0.05, 100.0),),
            )

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.order_factory = FakeOrderFactoryForNative()
            self.submitted = []

        def submit_order(self, order: object) -> None:
            self.submitted.append(order)

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token", Side.UP),
            down=InstrumentTokenMeta("down-token", Side.DOWN),
        )
    )
    observability = RecordingObservability()
    core = OneCentBuyAlphaCore(
        OneCentBuyConfig(entry_prices=(0.01,), shares_per_level=10)
    )
    strategy = FakeNativeStrategy(
        core=core,
        assembler=_assembler(OneCentView()),
        condition_ids=("condition-btc-5m",),
        strategy_name="one_cent_buy",
        policy=RuntimeFakePolicy(),
        fixed_stake_usdc=10.0,
        instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
        registry=registry,
        observability=observability,
    )

    strategy.evaluate_condition("condition-btc-5m")

    assert len(strategy.submitted) == 1
    submitted = strategy.submitted[0]
    accepted = SimpleNamespace(
        instrument_id="up-token.POLYMARKET",
        order_id="order-accepted-1",
        client_order_id="client-accepted-1",
        quantity=10.0,
        price=0.01,
        status="ACCEPTED",
        tags=submitted["tags"],
        ts_event=datetime.now(UTC),
    )

    strategy.on_order_accepted(accepted)

    assert ("btc-5m", 0.01) in core._submitted_levels
    assert observability.decisions == [("one_cent_buy", True)]
    assert len(observability.orders) == 1
    accepted_order = cast(_ObservedOrder, observability.orders[0])
    assert accepted_order.client_order_id == "client-accepted-1"
    assert accepted_order.metrics["level_price"] == 0.01
    assert observability.rejections == []

def test_native_strategy_attributes_inactive_registered_down_order_and_fill_from_catalog() -> (
    None
):
    from types import SimpleNamespace

    from polysignal_lab.nautilus_bridge.market_catalog import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy


    class CapturingCore(FakeCore):
        def __init__(self) -> None:
            super().__init__([])
            self.orders: list[object] = []
            self.fills: list[object] = []

        def on_order_submitted(self, event: object) -> None:
            self.orders.append(event)

        def on_order_filled(self, event: object) -> list[AlphaDecision]:
            self.fills.append(event)
            return []

    registry = _test_market_catalog()
    registry.register(
        MarketPairMeta(
            market_id="btc-exited-5m",
            market_slug="btc-exited-updown-5m",
            condition_id="condition-btc-exited-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-exited-token", Side.UP),
            down=InstrumentTokenMeta("down-exited-token", Side.DOWN),
        )
    )
    core = CapturingCore()
    strategy = PolySignalNativeStrategy(
        core=core,
        assembler=_assembler(None),
        condition_ids=(),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        registry=registry,
    )
    down_instrument_id = _test_instrument_id("condition-btc-exited-5m", "down-exited-token")
    event = SimpleNamespace(
        order_id="inactive-order-1",
        client_order_id="inactive-client-1",
        instrument_id=down_instrument_id,
        quantity=3.0,
        price=0.37,
        last_qty=3.0,
        last_px=0.37,
        trade_id="inactive-trade-1",
        liquidity_side="TAKER",
        tags=[],
        ts_event=datetime.now(UTC),
    )

    strategy.on_order_submitted(event)
    strategy.on_order_filled(event)

    assert len(core.orders) == 1
    order = core.orders[0]
    assert getattr(order, "market_id") == "btc-exited-5m"
    assert getattr(order, "condition_id") == "condition-btc-exited-5m"
    assert getattr(order, "token_id") == "down-exited-token"
    assert getattr(order, "side") is Side.DOWN
    assert len(core.fills) == 1
    fill = core.fills[0]
    assert getattr(fill, "market_id") == "btc-exited-5m"
    assert getattr(fill, "condition_id") == "condition-btc-exited-5m"
    assert getattr(fill, "token_id") == "down-exited-token"
    assert getattr(fill, "side") is Side.DOWN


def test_order_submitted_observability_failure_does_not_block_core_event() -> None:
    import sqlite3
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FailingObservability:
        def record_nautilus_order_event(self, event: object) -> None:
            _ = event
            raise sqlite3.OperationalError("database is locked")

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.order_factory = object()

    core_calls: list[object] = []
    phases: list[str] = []
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        observability=FailingObservability(),
        progress_callback=phases.append,
        **_native_projections(),
    )
    strategy.core.on_order_submitted = lambda event: core_calls.append(event)  # type: ignore[attr-defined]

    strategy.on_order_submitted(
        SimpleNamespace(
            order_id="order-1",
            client_order_id="C-001",
            instrument_id="up-token.POLYMARKET",
            status="SUBMITTED",
            tags=[],
            ts_event=datetime.now(UTC),
        )
    )

    assert len(core_calls) == 1
    assert "telemetry_side_effect_failed" in phases

def test_native_strategy_surfaces_approved_signal_to_observability() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class Book:
        best_ask: float | None = 0.82
        ask_levels: tuple[tuple[float, float], ...] = ((0.82, 50.0),)

    class View(_MockView):
        def book_for(self, side: Side) -> _BookViewLike:
            _ = side
            return Book()

    class RecordingObservability:
        def __init__(self) -> None:
            self.decisions: list[tuple[str, bool]] = []
            self.rejections: list[object] = []
            self.signals: list[object] = []
            self.published: list[tuple[object, float]] = []

        def record_decision(self, decision, accepted: bool) -> None:
            self.decisions.append((decision.strategy, accepted))

        def record_signal(self, signal: object) -> None:
            self.signals.append(signal)

        def notify_accepted_signal(self, signal: object, stake_usdc: float) -> None:
            self.published.append((signal, stake_usdc))

        def record_rejected_decision(self, rejected: object) -> None:
            self.rejections.append(rejected)

        def record_nautilus_order_event(self, event: object) -> None:
            _ = event

        def record_nautilus_fill_event(self, event: object) -> None:
            _ = event

        def record_nautilus_position(self, position: object) -> None:
            _ = position


    class FakeOrderFactory:
        def limit(self, **kwargs):
            return kwargs

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.order_factory = FakeOrderFactory()
            self.submitted: list[object] = []

        def submit_order(self, order: object) -> None:
            self.submitted.append(order)

    observability = RecordingObservability()
    strategy = FakeNativeStrategy(
        core=FakeCore([_decision()]),
        assembler=_assembler(View()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        fixed_stake_usdc=10.0,
        instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
        observability=observability,
        **_native_projections(),
    )

    strategy.evaluate_condition("condition-btc-5m")

    assert len(strategy.submitted) == 1
    assert len(observability.signals) == 1
    assert observability.decisions == [("ptb_diff", True)]
    assert len(observability.published) == 1
    published_signal, published_stake = observability.published[0]
    assert getattr(published_signal, "signal_id") == getattr(
        observability.signals[0], "signal_id"
    )
    assert published_stake == 10.0
    assert observability.rejections == []



def test_native_strategy_does_not_swallow_durable_signal_persistence_failure() -> None:
    import sqlite3

    import pytest

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class Book:
        best_ask: float | None = 0.82
        ask_levels: tuple[tuple[float, float], ...] = ((0.82, 50.0),)

    class View(_MockView):
        def book_for(self, side: Side) -> _BookViewLike:
            _ = side
            return Book()

    class FailingSignalObservability:
        def record_decision(self, decision, accepted: bool) -> None:
            _ = decision, accepted

        def record_signal(self, signal: object) -> None:
            _ = signal
            raise sqlite3.OperationalError("database is locked")

    class FakeOrderFactory:
        def limit(self, **kwargs):
            return kwargs

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.order_factory = FakeOrderFactory()

        def submit_order(self, order: object) -> None:
            _ = order

    strategy = FakeNativeStrategy(
        core=FakeCore([_decision()]),
        assembler=_assembler(View()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        fixed_stake_usdc=10.0,
        instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
        observability=FailingSignalObservability(),
        **_native_projections(),
    )

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        strategy.evaluate_condition("condition-btc-5m")


def test_native_strategy_rejection_persistence_failure_does_not_block_evaluate() -> None:
    import sqlite3

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FailingRejectedObservability:
        def record_decision(self, decision, accepted: bool) -> None:
            _ = decision, accepted

        def record_rejected_decision(self, rejected: object) -> None:
            _ = rejected
            raise sqlite3.OperationalError("database is locked")

    class RejectingPolicy(DecisionPolicyActor):
        def evaluate(self, decision: AlphaDecision, view: MarketView):
            _ = view
            return type("Rejected", (), {
                "reason_code": "TEST_REJECTED",
                "detail": {},
                "candidate": None,
            })()

    phases: list[str] = []
    strategy = PolySignalNativeStrategy(
        core=FakeCore([_decision()]),
        assembler=_assembler(_MockView()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RejectingPolicy(),
        observability=FailingRejectedObservability(),
        progress_callback=phases.append,
        **_native_projections(),
    )

    strategy.evaluate_condition("condition-btc-5m")

    assert "telemetry_side_effect_failed" in phases


def test_native_strategy_fill_and_position_callbacks_bridge_to_observability() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class RecordingObservability:
        def __init__(self) -> None:
            self.decisions: list[tuple[str, bool]] = []
            self.rejections: list[object] = []
            self.orders: list[object] = []
            self.fills: list[object] = []
            self.positions: list[object] = []

        def record_decision(self, decision, accepted: bool) -> None:
            self.decisions.append((decision.strategy, accepted))

        def record_rejected_decision(self, rejected: object) -> None:
            self.rejections.append(rejected)

        def record_nautilus_order_event(self, event: object) -> None:
            self.orders.append(event)

        def record_nautilus_fill_event(self, event: object) -> None:
            self.fills.append(event)

        def record_nautilus_position(self, position: object) -> None:
            self.positions.append(position)

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.order_factory = object()

    observability = RecordingObservability()
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        observability=observability,
        **_native_projections(),
    )

    fill = SimpleNamespace(
        order_id="order-1",
        client_order_id="order-1",
        market_id="btc-5m",
        condition_id="condition-btc-5m",
        token_id="up-token",
        side=Side.UP,
        last_qty=10.0,
        last_px=0.5,
        trade_id="trade-1",
        liquidity_side="TAKER",
        tags=["strategy=ptb_diff", "condition_id=condition-btc-5m"],
        ts_event=datetime.now(UTC),
    )
    opened = SimpleNamespace(
        id="pos-1",
        instrument_id="up-token.POLYMARKET",
        signed_qty=10.0,
        avg_px_open=0.5,
        realized_pnl=0.0,
        is_closed=False,
    )
    closed = SimpleNamespace(
        id="pos-1",
        instrument_id="up-token.POLYMARKET",
        signed_qty=0.0,
        avg_px_open=0.5,
        realized_pnl=1.0,
        is_closed=True,
    )

    strategy.on_order_filled(fill)
    strategy.on_position_opened(opened)
    strategy.on_position_closed(closed)

    assert len(observability.fills) == 1
    fill_event = cast(_ObservedFill, observability.fills[0])
    assert fill_event.trade_id == "trade-1"
    assert fill_event.last_px == 0.5
    assert observability.positions == [opened, closed]






def test_native_strategy_notifies_core_before_fill_handler() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class HedgeAwareCore:
        def __init__(self) -> None:
            self.events: list[tuple[str, str, Side, float]] = []

        def evaluate(self, view: MarketView) -> list[AlphaDecision]:
            return []

        def on_notify_fill(self, market_id: str, side: Side, shares: float) -> None:
            self.events.append(("notify", market_id, side, shares))

        def on_order_filled(self, event: object) -> list[AlphaDecision]:
            fill = cast(_ObservedFill, event)
            self.events.append(("filled", fill.market_id, fill.side, fill.shares))
            return []

    core = HedgeAwareCore()
    strategy = PolySignalNativeStrategy(
        core=core,
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="vwap_momentum",
        policy=RuntimeFakePolicy(),
        **_native_projections(),
    )

    strategy.on_order_filled(
        SimpleNamespace(
            order_id="order-1",
            client_order_id="order-1",
            market_id="btc-5m",
            condition_id="condition-btc-5m",
            token_id="up-token",
            side=Side.UP,
            last_qty=10.0,
            last_px=0.5,
            trade_id="trade-1",
            liquidity_side="TAKER",
            tags=["strategy=vwap_momentum", "condition_id=condition-btc-5m"],
            ts_event=datetime.now(UTC),
        )
    )

    assert core.events == [
        ("notify", "btc-5m", Side.UP, 10.0),
        ("filled", "btc-5m", Side.UP, 10.0),
    ]


# ── L1 subscription selection tests ──────────────────────────────────────────


def test_native_strategy_l1_subscribes_data_names_and_snapshot_request() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.cache = SimpleNamespace(instrument=lambda instrument_id: object())
            self.subscribed_quotes: list[str] = []
            self.subscribed_trades: list[str] = []
            self.subscribed_deltas: list[str] = []
            self.snapshot_requests: list[str] = []

        def subscribe_quote_ticks(self, instrument_id):
            self.subscribed_quotes.append(str(instrument_id))

        def subscribe_trade_ticks(self, instrument_id):
            self.subscribed_trades.append(str(instrument_id))

        def subscribe_order_book_deltas(self, instrument_id, *args, **kwargs):
            _ = args, kwargs
            self.subscribed_deltas.append(str(instrument_id))

        def request_order_book_snapshot(self, instrument_id):
            self.snapshot_requests.append(str(instrument_id))

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        book_type="L1_MBP",
        **_native_projections(),
    )

    strategy._subscribe_market_instrument("up-token.POLYMARKET")

    assert strategy.subscribed_quotes == ["up-token.POLYMARKET"]
    assert strategy.subscribed_trades == ["up-token.POLYMARKET"]
    assert strategy.subscribed_deltas == ["up-token.POLYMARKET"]
    assert strategy.snapshot_requests == ["up-token.POLYMARKET"]


def test_native_strategy_l1_skips_snapshot_when_hook_missing() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.cache = SimpleNamespace(instrument=lambda instrument_id: object())
            self.subscribed_quotes: list[str] = []
            self.subscribed_trades: list[str] = []
            self.subscribed_deltas: list[str] = []

        def subscribe_quote_ticks(self, instrument_id):
            self.subscribed_quotes.append(str(instrument_id))

        def subscribe_trade_ticks(self, instrument_id):
            self.subscribed_trades.append(str(instrument_id))

        def subscribe_order_book_deltas(self, instrument_id, *args, **kwargs):
            _ = args, kwargs
            self.subscribed_deltas.append(str(instrument_id))

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        book_type="L1_MBP",
        **_native_projections(),
    )

    strategy._subscribe_market_instrument("up-token.POLYMARKET")

    assert strategy.subscribed_quotes == ["up-token.POLYMARKET"]
    assert strategy.subscribed_trades == ["up-token.POLYMARKET"]
    assert strategy.subscribed_deltas == ["up-token.POLYMARKET"]


def test_native_strategy_l1_subscribes_all_data_names() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    phases: list[str] = []

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.cache = SimpleNamespace(instrument=lambda instrument_id: object())
            self.subscribed_deltas: list[str] = []
            self.subscribed_trades: list[str] = []

        def subscribe_order_book_deltas(self, instrument_id, *args, **kwargs):
            _ = args, kwargs
            self.subscribed_deltas.append(str(instrument_id))

        def subscribe_trade_ticks(self, instrument_id):
            self.subscribed_trades.append(str(instrument_id))

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        book_type="L1_MBP",
        progress_callback=phases.append,
        **_native_projections(),
    )

    strategy._subscribe_market_instrument("up-token.POLYMARKET")

    assert strategy.subscribed_deltas == ["up-token.POLYMARKET"]
    assert strategy.subscribed_trades == ["up-token.POLYMARKET"]
    assert "l1_raw_delta_fallback" not in phases


def test_native_strategy_l2_subscribes_all_data_names() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.cache = SimpleNamespace(instrument=lambda instrument_id: object())
            self.subscribed_quotes: list[str] = []
            self.subscribed_trades: list[str] = []
            self.subscribed_deltas: list[str] = []

        def subscribe_quote_ticks(self, instrument_id):
            self.subscribed_quotes.append(str(instrument_id))

        def subscribe_trade_ticks(self, instrument_id):
            self.subscribed_trades.append(str(instrument_id))

        def subscribe_order_book_deltas(self, instrument_id, *args, **kwargs):
            _ = args, kwargs
            self.subscribed_deltas.append(str(instrument_id))

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        book_type="L2_MBP",
        **_native_projections(),
    )

    strategy._subscribe_market_instrument("up-token.POLYMARKET")

    assert strategy.subscribed_quotes == ["up-token.POLYMARKET"]
    assert strategy.subscribed_deltas == ["up-token.POLYMARKET"]
    assert strategy.subscribed_trades == ["up-token.POLYMARKET"]


def test_native_strategy_does_not_define_custom_market_data_subscription_group() -> None:
    import inspect

    import polysignal_lab.nautilus_runtime.native_strategy as native_strategy

    source = inspect.getsource(native_strategy)

    assert "class _MarketDataSubscriptionGroup" not in source
    assert "_polysignal_market_data_subscription_group" not in source
    assert "_market_data_subscription_group" not in source
