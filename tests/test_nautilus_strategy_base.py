from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

from polysignal_lab.alpha.types import (
    AlphaDecision,
    MarketView,
    NautilusOrderSpec,
    OrderIntentSpec,
)
from polysignal_lab.domain.enums import OrderIntent, Side
from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
from polysignal_lab.nautilus_bridge.market_registry import PolymarketMarketRegistry
from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
from polysignal_lab.nautilus_bridge.state import state_key
from polysignal_lab.nautilus_bridge.strategies.ptb_diff import PTBDiffNautilusStrategy
from polysignal_lab.nautilus_bridge.strategy_base import (
    PolySignalNautilusStrategy,
    is_nautilus_available,
)
from polysignal_lab.strategies.config import PTBDiffConfig, PTBTriggerConfig


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


def _assembler(view: object | None) -> MarketViewAssembler:
    return cast(MarketViewAssembler, cast(object, FakeAssembler(view)))


def _native_projections(
    registry: PolymarketMarketRegistry | None = None,
) -> dict[str, Any]:
    return {
        "registry": registry or PolymarketMarketRegistry(),
        "sidecar": ExternalDataSidecar(),
    }


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


def test_strategy_base_imports_without_nautilus_installed() -> None:
    assert isinstance(is_nautilus_available(), bool)


def test_strategy_base_returns_no_intents_when_view_not_ready() -> None:
    strategy = PolySignalNautilusStrategy(
        core=FakeCore([_decision()]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
    )

    assert strategy.evaluate_condition("condition-btc-5m") == []
    assert strategy.submitted_intents == []


def test_strategy_base_records_decision_order_intents() -> None:
    strategy = PolySignalNautilusStrategy(
        core=FakeCore([_decision()]),
        assembler=_assembler(object()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
    )

    intents = strategy.evaluate_condition("condition-btc-5m")

    assert intents == [
        OrderIntentSpec(
            intent=OrderIntent.PASSIVE_GTD, expiry_seconds=45, pair_id="pair-1"
        )
    ]
    assert strategy.submitted_intents == intents


def test_strategy_base_save_load_uses_versioned_bytes() -> None:
    strategy = PolySignalNautilusStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
    )
    strategy.accepted_state["condition-btc-5m"] = "accepted"

    state = strategy.on_save()
    restored = PolySignalNautilusStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
    )
    restored.on_load(state)

    assert set(state) == {state_key("ptb_diff")}
    assert restored.accepted_state == {"condition-btc-5m": "accepted"}


def test_ptb_nautilus_strategy_constructs_with_core_without_nautilus_dependency() -> (
    None
):
    config = PTBDiffConfig(
        triggers=[
            PTBTriggerConfig(
                name="test_up",
                side=Side.UP,
                min_diff_usd=80.0,
                max_token_price=0.92,
                min_token_price=0.80,
                min_seconds_to_close=0,
                max_seconds_to_close=120,
            )
        ]
    )

    strategy = PTBDiffNautilusStrategy(
        config=config, assembler=_assembler(None), condition_ids=("condition-btc-5m",)
    )

    assert strategy.strategy_name == "ptb_diff"


# ── Batch evaluation tests (nautilus runtime) ─────────────────────────────────


from polysignal_lab.domain.enums import OrderStatus  # noqa: E402
from polysignal_lab.domain.signal import SignalCandidate  # noqa: E402
from polysignal_lab.nautilus_runtime.decision_policy import (  # noqa: E402
    ApprovedDecision,
    DecisionPolicyActor,
)
from polysignal_lab.nautilus_runtime.execution_types import PaperExecutionResult  # noqa: E402
from polysignal_lab.nautilus_runtime.strategies.base import (  # noqa: E402
    PolySignalNautilusStrategy as RuntimeStrategy,
)


class _MockBook:
    best_ask: float | None = None
    ask_levels: tuple[tuple[float, float], ...] = ()


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


def test_runtime_strategy_evaluate_all_conditions_clears_tracking_and_captures_results() -> (
    None
):
    submitted: list[NautilusOrderSpec] = []

    def submitter(spec: NautilusOrderSpec) -> PaperExecutionResult:
        submitted.append(spec)
        return PaperExecutionResult(status=OrderStatus.FILLED)

    strategy = RuntimeStrategy(
        core=FakeCore([_decision()]),
        assembler=_assembler(_MockView()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        submitter=submitter,
    )
    strategy.submitted_specs.append(cast(NautilusOrderSpec, object()))

    batch = strategy.evaluate_all_conditions()

    assert batch.strategy == "ptb_diff"
    assert len(batch.submitted_specs) == 1
    assert len(batch.execution_results) == 1
    assert batch.execution_results[0].status == OrderStatus.FILLED
    assert submitted == list(batch.submitted_specs)


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

    strategy = RuntimeStrategy(
        core=FakeCore([decision]),
        assembler=_assembler(View()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        fixed_stake_usdc=10.0,
    )

    specs = strategy.evaluate_condition("condition-btc-5m")

    assert len(specs) == 1
    assert specs[0].intent == OrderIntent.TAKER_FOK
    assert specs[0].quantity == 20.0
    assert len(strategy.rejected_decisions) == 0


def test_native_strategy_records_rejection_when_order_mapping_fails() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class Book:
        best_ask: float | None = 0.50
        ask_levels: tuple[tuple[float, float], ...] = ((0.50, 1.0),)

    class View(_MockView):
        def book_for(self, side: Side) -> _BookViewLike:
            _ = side
            return Book()

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

def test_runtime_native_strategy_type_uses_nautilus_subscribe_data_for_custom_data() -> (
    None
):
    from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_runtime.native_strategy import (
        runtime_native_strategy_type,
    )

    class FakeBase:
        def __init__(self, *, config: object) -> None:
            self.config = config
            self.custom_subscriptions = []

        def subscribe_order_book_deltas(
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

    strategy_type = runtime_native_strategy_type(FakeBase, lambda: "cfg")

    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token.POLYMARKET", "up-token", Side.UP),
            down=InstrumentTokenMeta("down-token.POLYMARKET", "down-token", Side.DOWN),
        )
    )

    strategy = strategy_type(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        registry=registry,
        sidecar=ExternalDataSidecar(),
    )

    strategy.on_start()

    assert cast(list[object], getattr(strategy, "custom_subscriptions")) != []


def test_runtime_native_strategy_type_subscribes_custom_data_on_msgbus() -> None:
    from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_runtime.market_data import (
        PolySignalMarketMetaData,
        PolySignalMarketUniverseData,
        PolySignalPriceToBeatData,
        PolySignalSpotData,
    )
    from polysignal_lab.nautilus_runtime.native_strategy import (
        runtime_native_strategy_type,
    )

    class FakeMsgBus:
        def __init__(self) -> None:
            self.calls: list[tuple[object, Callable[[object], object]]] = []

        def subscribe(
            self, *, topic: object, handler: Callable[[object], object]
        ) -> None:
            self.calls.append((topic, handler))

    class FakeTopicCache:
        def get_custom_data_topic(
            self, data_type: object, instrument_id: object
        ) -> object:
            _ = instrument_id
            return data_type

    class FakeBase:
        def __init__(self, *, config: object) -> None:
            self.config = config
            self.custom_subscriptions = []
            self._msgbus = FakeMsgBus()
            self._topic_cache = FakeTopicCache()

        def subscribe_order_book_deltas(
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

        def handle_data(self, data: object) -> None:
            _ = cast(_DataHandler, cast(object, self)).on_data(data)

    strategy_type = runtime_native_strategy_type(FakeBase, lambda: "cfg")

    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token.POLYMARKET", "up-token", Side.UP),
            down=InstrumentTokenMeta("down-token.POLYMARKET", "down-token", Side.DOWN),
        )
    )

    sidecar = ExternalDataSidecar()
    strategy = strategy_type(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        registry=registry,
        sidecar=sidecar,
    )

    strategy.on_start()

    assert cast(list[object], getattr(strategy, "custom_subscriptions")) == []
    msgbus_calls = cast(FakeMsgBus, getattr(strategy, "_msgbus")).calls
    assert len(msgbus_calls) == 4
    assert {getattr(topic, "type", topic) for topic, _handler in msgbus_calls} == {
        PolySignalSpotData,
        PolySignalPriceToBeatData,
        PolySignalMarketMetaData,
        PolySignalMarketUniverseData,
    }

    _topic, handler = msgbus_calls[0]
    handler(
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

    spot = sidecar.spot_for("BTC")
    assert spot is not None
    assert spot.price == 100000.0


def test_runtime_strategy_evaluate_all_conditions_uses_override_condition_ids() -> None:
    class RecordingAssembler(FakeAssembler):
        def __init__(self) -> None:
            super().__init__(object())
            self.seen: list[str] = []

        def build(
            self,
            condition_id: str,
            *,
            created_at: datetime | None = None,
        ) -> MarketView | None:
            _ = created_at
            self.seen.append(condition_id)
            return self.view

    assembler = RecordingAssembler()
    strategy = RuntimeStrategy(
        core=FakeCore([]),
        assembler=cast(MarketViewAssembler, cast(object, assembler)),
        condition_ids=("old",),
        strategy_name="ptb_diff",
    )

    batch = strategy.evaluate_all_conditions(("new",))

    assert assembler.seen == ["new"]
    assert batch.submitted_specs == ()


def test_native_strategy_generates_signal_from_on_data_callback() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.order_factory = FakeOrderFactoryForNative()
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


def test_native_strategy_constructor_requires_injected_projections() -> None:
    import pytest

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    with pytest.raises(
        RuntimeError,
        match="requires injected registry, sidecar, and assembler projections",
    ):
        PolySignalNativeStrategy(
            core=FakeCore([]),
            assembler=_assembler(None),
            condition_ids=(),
            strategy_name="ptb_diff",
        )


def test_native_strategy_constructor_requires_injected_assembler() -> None:
    import pytest

    from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
    from polysignal_lab.nautilus_bridge.market_registry import PolymarketMarketRegistry
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    with pytest.raises(
        RuntimeError,
        match="requires injected registry, sidecar, and assembler projections",
    ):
        PolySignalNativeStrategy(
            core=FakeCore([]),
            assembler=cast(Any, None),
            condition_ids=(),
            strategy_name="ptb_diff",
            registry=PolymarketMarketRegistry(),
            sidecar=ExternalDataSidecar(),
        )


def test_native_strategy_on_start_subscribes_all_custom_data_with_injected_projections() -> (
    None
):
    from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
    from polysignal_lab.nautilus_bridge.market_registry import PolymarketMarketRegistry
    from polysignal_lab.nautilus_runtime.market_data import (
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

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=(),
        strategy_name="ptb_diff",
        registry=PolymarketMarketRegistry(),
        sidecar=ExternalDataSidecar(),
    )

    strategy.on_start()

    assert PolySignalMarketMetaData in strategy.custom_subscriptions
    assert PolySignalMarketUniverseData in strategy.custom_subscriptions
    assert PolySignalSpotData in strategy.custom_subscriptions
    assert PolySignalPriceToBeatData in strategy.custom_subscriptions


def test_native_strategy_on_start_sets_evaluation_heartbeat() -> None:
    from datetime import UTC, datetime, timedelta

    from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
    from polysignal_lab.nautilus_bridge.market_registry import PolymarketMarketRegistry
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
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.custom_subscriptions: list[object] = []
            self.evaluated: list[str] = []
            self.clock = FakeClock()

        def subscribe_data(self, data_type):
            self.custom_subscriptions.append(data_type)

        def evaluate_condition(self, condition_id: str) -> None:
            self.evaluated.append(condition_id)

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m", "condition-btc-retired"),
        strategy_name="ptb_diff",
        registry=PolymarketMarketRegistry(),
        sidecar=ExternalDataSidecar(),
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
        assembler=_assembler(object()),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
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
        **_native_projections(),
        progress_callback=progress_events.append,
    )

    strategy.on_start()

    assert "start" in progress_events

def test_native_strategy_constructor_without_registry_fails_clearly() -> None:
    import pytest

    from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    with pytest.raises(
        RuntimeError,
        match="requires injected registry, sidecar, and assembler projections",
    ):
        PolySignalNativeStrategy(
            core=FakeCore([]),
            assembler=_assembler(None),
            condition_ids=(),
            strategy_name="ptb_diff",
            sidecar=ExternalDataSidecar(),
            instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
        )


def test_native_strategy_bounds_rejected_decisions_to_prevent_memory_leak() -> None:
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
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
        **_native_projections(),
    )

    for _ in range(2000):
        strategy.submitted_orders.append("order")
    # With unbounded list this will have 2000 entries, with bounded maxlen <= 1000
    assert len(strategy.submitted_orders) <= 1000


def test_native_strategy_on_start_subscribes_built_in_market_data_by_instrument() -> (
    None
):
    from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
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

    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token.POLYMARKET", "up-token", Side.UP),
            down=InstrumentTokenMeta("down-token.POLYMARKET", "down-token", Side.DOWN),
        )
    )

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        registry=registry,
        sidecar=ExternalDataSidecar(),
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
    assert strategy.instrument_requests == [
        "up-token.POLYMARKET",
        "down-token.POLYMARKET",
    ]
    assert cast(_CustomDataStrategy, cast(object, strategy)).custom_subscriptions != []


def test_native_strategy_coalesces_wire_subscriptions_across_strategy_instances() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
    from polysignal_lab.nautilus_runtime.book_data import NautilusBookDataProvider
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
    from polysignal_lab.nautilus_runtime.market_data import PolySignalMarketUniverseData

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
            seen.append((self.label, condition_id))

    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token.POLYMARKET", "up-token", Side.UP),
            down=InstrumentTokenMeta("down-token.POLYMARKET", "down-token", Side.DOWN),
        )
    )
    books = NautilusBookDataProvider()
    assembler = MarketViewAssembler(
        registry=registry,
        books=books,
        sidecar=ExternalDataSidecar(),
    )
    first = FakeNativeStrategy(
        label="first",
        core=FakeCore([]),
        assembler=assembler,
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        registry=registry,
        sidecar=ExternalDataSidecar(),
    )
    second = FakeNativeStrategy(
        label="second",
        core=FakeCore([]),
        assembler=assembler,
        condition_ids=("condition-btc-5m",),
        strategy_name="late_consensus",
        registry=registry,
        sidecar=ExternalDataSidecar(),
    )

    first.on_start()
    second.on_start()

    assert first.instrument_requests == ["up-token.POLYMARKET", "down-token.POLYMARKET"]
    assert second.instrument_requests == []
    assert first.book_subscriptions == ["up-token.POLYMARKET", "down-token.POLYMARKET"]
    assert first.trade_subscriptions == ["up-token.POLYMARKET", "down-token.POLYMARKET"]
    assert second.book_subscriptions == []
    assert second.trade_subscriptions == []

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
    assert seen == [
        ("first", "condition-btc-5m"),
        ("second", "condition-btc-5m"),
    ]

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

    assert first.book_unsubscriptions == []
    assert first.trade_unsubscriptions == []
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
    assert seen == [("second", "condition-btc-5m")]

    second.on_data(exited)

    assert first.book_unsubscriptions == ["up-token.POLYMARKET", "down-token.POLYMARKET"]
    assert first.trade_unsubscriptions == ["up-token.POLYMARKET", "down-token.POLYMARKET"]
    assert second.book_unsubscriptions == []
    assert second.trade_unsubscriptions == []


def test_native_strategy_universe_update_subscribes_entered_market_once() -> None:
    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_runtime.instrument_mapping import (
        polymarket_instrument_id,
    )
    from polysignal_lab.nautilus_runtime.market_data import (
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

    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a.POLYMARKET", "up-a", Side.UP),
            down=InstrumentTokenMeta("down-a.POLYMARKET", "down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        registry=registry,
        sidecar=ExternalDataSidecar(),
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

    assert (
        strategy.instrument_requests.count(
            polymarket_instrument_id("condition-b", "up-b")
        )
        == 1
    )
    assert (
        strategy.instrument_requests.count(
            polymarket_instrument_id("condition-b", "down-b")
        )
        == 1
    )

    assert (
        strategy.book_subscriptions.count(
            polymarket_instrument_id("condition-b", "up-b")
        )
        == 1
    )
    assert (
        strategy.trade_subscriptions.count(
            polymarket_instrument_id("condition-b", "down-b")
        )
        == 1
    )


def test_native_strategy_universe_update_recovers_still_active_missing_subscription() -> (
    None
):
    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_runtime.market_data import PolySignalMarketUniverseData
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

    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a.POLYMARKET", "up-a", Side.UP),
            down=InstrumentTokenMeta("down-a.POLYMARKET", "down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        registry=registry,
        sidecar=ExternalDataSidecar(),
    )

    strategy.on_start()
    strategy._subscription_state.wire_condition_ids.clear()
    strategy._subscription_state.wire_instrument_ids.clear()

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
    assert strategy._subscription_state.wire_instrument_ids == {
        "down-a.POLYMARKET",
        "up-a.POLYMARKET",
    }



def test_native_strategy_universe_update_re_requests_unconfirmed_wired_market() -> (
    None
):
    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_runtime.market_data import PolySignalMarketUniverseData
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

    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a.POLYMARKET", "up-a", Side.UP),
            down=InstrumentTokenMeta("down-a.POLYMARKET", "down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        registry=registry,
        sidecar=ExternalDataSidecar(),
    )

    strategy.on_start()
    strategy.instrument_requests.clear()

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

    assert strategy.instrument_requests == [
        "up-a.POLYMARKET",
        "down-a.POLYMARKET",
    ]
    assert strategy.book_subscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]
    assert strategy.trade_subscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]



def test_native_strategy_ptb_update_re_requests_unconfirmed_wired_market() -> None:
    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_runtime.market_data import PolySignalPriceToBeatData
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

    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a.POLYMARKET", "up-a", Side.UP),
            down=InstrumentTokenMeta("down-a.POLYMARKET", "down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        registry=registry,
        sidecar=ExternalDataSidecar(),
    )

    strategy.on_start()
    strategy.instrument_requests.clear()
    stale = datetime.now(UTC) - timedelta(seconds=11)
    strategy._market_data_subscription_group._requested_instruments.update(
        {
            "up-a.POLYMARKET": stale,
            "down-a.POLYMARKET": stale,
        }
    )

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
    from polysignal_lab.nautilus_bridge.market_registry import PolymarketMarketRegistry
    from polysignal_lab.nautilus_runtime.market_data import (
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
        registry=PolymarketMarketRegistry(),
        instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
        sidecar=ExternalDataSidecar(),
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
    assert strategy._subscription_state.wire_instrument_ids == {
        "down-b.POLYMARKET",
        "up-b.POLYMARKET",
    }

def test_native_strategy_defers_market_subscription_until_instrument_cached() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_runtime.market_data import PolySignalMarketUniverseData
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

    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a.POLYMARKET", "up-a", Side.UP),
            down=InstrumentTokenMeta("down-a.POLYMARKET", "down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=(),
        strategy_name="ptb_diff",
        registry=registry,
        sidecar=ExternalDataSidecar(),
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

    assert strategy.instrument_requests == ["up-a.POLYMARKET", "down-a.POLYMARKET"]
    assert strategy.book_subscriptions == []
    assert strategy.trade_subscriptions == []
    assert strategy._subscription_state.pending_subscribe_condition_ids == {"condition-a"}

    strategy.cache.loaded.update({"up-a.POLYMARKET", "down-a.POLYMARKET"})
    strategy._subscribe_market_conditions(("condition-a",))

    assert strategy.book_subscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]
    assert strategy.trade_subscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]
    assert strategy._subscription_state.pending_subscribe_condition_ids == set()



def test_native_strategy_active_market_without_subscribe_hooks_marks_pending_subscribe() -> (
    None
):
    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_runtime.market_data import PolySignalMarketUniverseData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a.POLYMARKET", "up-a", Side.UP),
            down=InstrumentTokenMeta("down-a.POLYMARKET", "down-a", Side.DOWN),
        )
    )
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=(),
        strategy_name="ptb_diff",
        registry=registry,
        sidecar=ExternalDataSidecar(),
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

    assert strategy._subscription_state.wire_condition_ids == set()
    assert strategy._subscription_state.wire_instrument_ids == set()
    assert strategy._subscription_state.pending_subscribe_condition_ids == {
        "condition-a"
    }


def test_native_strategy_exited_market_is_gated_even_if_late_tick_arrives() -> None:
    from polysignal_lab.nautilus_runtime.market_data import PolySignalMarketUniverseData
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

    from polysignal_lab.nautilus_runtime.market_data import PolySignalMarketUniverseData
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
    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_runtime.market_data import PolySignalMarketUniverseData
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

    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a.POLYMARKET", "up-a", Side.UP),
            down=InstrumentTokenMeta("down-a.POLYMARKET", "down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        registry=registry,
        sidecar=ExternalDataSidecar(),
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
    assert strategy._subscription_state.wire_instrument_ids == set()
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
    assert strategy._subscription_state.wire_instrument_ids == {
        "down-a.POLYMARKET",
        "up-a.POLYMARKET",
    }


def test_native_strategy_exited_l1_market_unsubscribes_quote_ticks() -> None:
    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_runtime.market_data import PolySignalMarketUniverseData
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

    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a.POLYMARKET", "up-a", Side.UP),
            down=InstrumentTokenMeta("down-a.POLYMARKET", "down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        book_type="L1_MBP",
        registry=registry,
        sidecar=ExternalDataSidecar(),
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
    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_runtime.market_data import PolySignalMarketUniverseData
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

    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a.POLYMARKET", "up-a", Side.UP),
            down=InstrumentTokenMeta("down-a.POLYMARKET", "down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        registry=registry,
        sidecar=ExternalDataSidecar(),
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
    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_runtime.market_data import PolySignalMarketUniverseData
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

    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a.POLYMARKET", "up-a", Side.UP),
            down=InstrumentTokenMeta("down-a.POLYMARKET", "down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        registry=registry,
        unsubscribe_exited=False,
        sidecar=ExternalDataSidecar(),
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
    assert strategy._subscription_state.wire_instrument_ids == {
        "down-a.POLYMARKET",
        "up-a.POLYMARKET",
    }
    assert strategy._subscription_state.retained_wire_condition_ids == set()


def test_native_strategy_exited_market_without_unsubscribe_hooks_retains_wire_state() -> (
    None
):
    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_runtime.market_data import PolySignalMarketUniverseData
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

    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a.POLYMARKET", "up-a", Side.UP),
            down=InstrumentTokenMeta("down-a.POLYMARKET", "down-a", Side.DOWN),
        )
    )
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        registry=registry,
        sidecar=ExternalDataSidecar(),
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
    assert strategy._subscription_state.wire_condition_ids == {"condition-a"}
    assert strategy._subscription_state.wire_instrument_ids == {
        "down-a.POLYMARKET",
        "up-a.POLYMARKET",
    }
    assert strategy._subscription_state.retained_wire_condition_ids == {"condition-a"}

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

    assert strategy.book_subscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]
    assert strategy.trade_subscriptions == ["up-a.POLYMARKET", "down-a.POLYMARKET"]
    assert strategy._subscription_state.retained_wire_condition_ids == set()


def test_native_strategy_retained_wire_trade_tick_stays_gated() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_runtime.market_data import PolySignalMarketUniverseData
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

    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-updown-5m-a",
            market_slug="btc-updown-5m-a",
            condition_id="condition-a",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-a.POLYMARKET", "up-a", Side.UP),
            down=InstrumentTokenMeta("down-a.POLYMARKET", "down-a", Side.DOWN),
        )
    )

    view = _MockView()
    view.condition_id = "condition-a"
    strategy = FakeNativeStrategy(
        core=FakeCore([_decision()]),
        assembler=_assembler(view),
        condition_ids=("condition-a",),
        strategy_name="ptb_diff",
        registry=registry,
        sidecar=ExternalDataSidecar(),
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

    assert strategy._subscription_state.retained_wire_condition_ids == {"condition-a"}
    assert seen == []


def test_native_strategy_routes_spot_custom_data_to_matching_asset_conditions_only() -> (
    None
):
    from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_runtime.market_data import PolySignalSpotData
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    seen = []
    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token.POLYMARKET", "up-token", Side.UP),
            down=InstrumentTokenMeta("down-token.POLYMARKET", "down-token", Side.DOWN),
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
            up=InstrumentTokenMeta("eth-up.POLYMARKET", "eth-up", Side.UP),
            down=InstrumentTokenMeta("eth-down.POLYMARKET", "eth-down", Side.DOWN),
        )
    )

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

        def evaluate_condition(self, condition_id: str) -> None:
            seen.append(condition_id)

    sidecar = ExternalDataSidecar()
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m", "condition-eth-5m"),
        strategy_name="ptb_diff",
        registry=registry,
        sidecar=sidecar,
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
    assert sidecar.spot_for("BTC") is not None


def test_native_strategy_routes_ptb_custom_data_to_matching_active_condition_only() -> (
    None
):
    from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
    from polysignal_lab.nautilus_bridge.market_registry import PolymarketMarketRegistry
    from polysignal_lab.nautilus_runtime.market_data import PolySignalPriceToBeatData
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
    sidecar = ExternalDataSidecar()
    strategy = PolySignalNativeStrategy(
        core=FakeCore([]),
        assembler=cast(MarketViewAssembler, cast(object, assembler)),
        condition_ids=("condition-active",),
        strategy_name="ptb_diff",
        registry=PolymarketMarketRegistry(),
        sidecar=sidecar,
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
    active_ptb = sidecar.ptb_for("condition-active")
    inactive_ptb = sidecar.ptb_for("condition-inactive")
    assert active_ptb is not None
    assert active_ptb.value == 99950.0
    assert inactive_ptb is not None
    assert inactive_ptb.value == 100050.0


def test_native_strategy_order_book_callback_updates_shared_books_and_submits() -> None:
    from types import SimpleNamespace

    from polysignal_lab.alpha.types import SpotView
    from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
    from polysignal_lab.nautilus_runtime.book_data import NautilusBookDataProvider
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeLevel:
        def __init__(self, price: float, size: float) -> None:
            self.price = price
            self.size = size

    class FakeOrderBook:
        def __init__(self, bids, asks) -> None:
            self.bids = bids
            self.asks = asks
            self.last_trade_price = asks[0].price if asks else None
            self.last_trade_size = asks[0].size if asks else None
            self.last_trade_timestamp = None
            self.received_at = datetime.now(UTC)

    class FakeCache:
        def __init__(self) -> None:
            self.books = {
                "up-token.POLYMARKET": FakeOrderBook(
                    bids=[FakeLevel(0.49, 20.0)],
                    asks=[FakeLevel(0.50, 20.0), FakeLevel(0.52, 20.0)],
                ),
                "down-token.POLYMARKET": FakeOrderBook(
                    bids=[FakeLevel(0.48, 20.0)],
                    asks=[FakeLevel(0.51, 20.0), FakeLevel(0.53, 20.0)],
                ),
            }

        def order_book(self, instrument_id):
            return self.books[instrument_id]

    class FakeOrderFactoryForNative:
        def limit(self, **kwargs):
            return kwargs

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.order_factory = FakeOrderFactoryForNative()
            self.cache = FakeCache()
            self.submitted = []

        def submit_order(self, order):
            self.submitted.append(order)

    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token.POLYMARKET", "up-token", Side.UP),
            down=InstrumentTokenMeta("down-token.POLYMARKET", "down-token", Side.DOWN),
        )
    )
    sidecar = ExternalDataSidecar()
    sidecar.update_spot(
        SpotView(
            asset="BTC",
            symbol="BTCUSD",
            price=100000.0,
            source="polymarket_rtds",
            freshness_ms=10,
        )
    )
    sidecar.update_price_to_beat(
        condition_id="condition-btc-5m",
        value=99950.0,
        source="anchor",
        verified=True,
        from_anchor_service=True,
        anchor_source="chainlink",
        anchor_lag_ms=5,
    )
    assembler = MarketViewAssembler(
        registry=registry,
        books=NautilusBookDataProvider(),
        sidecar=sidecar,
    )

    strategy = FakeNativeStrategy(
        core=FakeCore([_decision()]),
        assembler=assembler,
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        policy=RuntimeFakePolicy(),
        fixed_stake_usdc=10.0,
        instrument_id_resolver=lambda token_id: f"{token_id}.POLYMARKET",
        registry=registry,
        sidecar=sidecar,
    )

    strategy.on_order_book_deltas(
        SimpleNamespace(instrument_id="down-token.POLYMARKET")
    )
    strategy.on_order_book_deltas(SimpleNamespace(instrument_id="up-token.POLYMARKET"))

    assert len(strategy.submitted) == 1
    assert str(strategy.submitted[0]["instrument_id"]) == "up-token.POLYMARKET"


def test_native_strategy_trade_tick_callback_updates_shared_trade_history() -> None:
    from types import SimpleNamespace

    from polysignal_lab.alpha.types import SpotView
    from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
    from polysignal_lab.nautilus_runtime.book_data import NautilusBookDataProvider
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

        def order_book(self, instrument_id):
            return self.books[instrument_id]

    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token.POLYMARKET", "up-token", Side.UP),
            down=InstrumentTokenMeta("down-token.POLYMARKET", "down-token", Side.DOWN),
        )
    )
    sidecar = ExternalDataSidecar()
    sidecar.update_spot(
        SpotView(
            asset="BTC",
            symbol="BTCUSD",
            price=100000.0,
            source="polymarket_rtds",
            freshness_ms=10,
        )
    )
    sidecar.update_price_to_beat(
        condition_id="condition-btc-5m",
        value=99950.0,
        source="anchor",
        verified=True,
        from_anchor_service=True,
        anchor_source="chainlink",
        anchor_lag_ms=5,
    )
    books = NautilusBookDataProvider()
    assembler = MarketViewAssembler(
        registry=registry,
        books=books,
        sidecar=sidecar,
    )

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.cache = FakeCache()
            self.evaluated: list[str] = []

        def evaluate_condition(self, condition_id: str) -> None:
            self.evaluated.append(condition_id)
            super().evaluate_condition(condition_id)

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=assembler,
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        registry=registry,
        sidecar=sidecar,
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
    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
    from polysignal_lab.strategies.config import OneCentBuyConfig

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

    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token.POLYMARKET", "up-token", Side.UP),
            down=InstrumentTokenMeta("down-token.POLYMARKET", "down-token", Side.DOWN),
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
        sidecar=ExternalDataSidecar(),
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


def test_native_strategy_on_order_denied_records_event_and_forgets_metrics() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class RecordingObservability:
        def __init__(self) -> None:
            self.orders: list[object] = []

        def record_nautilus_order_event(self, event: object) -> None:
            self.orders.append(event)

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
        observability=observability,
        **_native_projections(),
    )
    strategy._approved_signal_metrics["client-denied-1"] = {
        "signal_id": "sig-denied-1",
        "condition_id": "condition-btc-5m",
    }

    strategy.on_order_denied(
        SimpleNamespace(
            order_id="order-denied-1",
            client_order_id="client-denied-1",
            instrument_id="up-token.POLYMARKET",
            status="DENIED",
            reason="RISK_DENIED",
            tags=["strategy=ptb_diff", "condition_id=condition-btc-5m"],
            ts_event=datetime.now(UTC),
        )
    )

    assert len(observability.orders) == 1
    order = cast(_ObservedOrder, observability.orders[0])
    assert order.client_order_id == "client-denied-1"
    assert getattr(order, "status") == "DENIED"
    assert order.metrics["signal_id"] == "sig-denied-1"
    assert "client-denied-1" not in strategy._approved_signal_metrics

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

        def notify_nautilus_paper_fill(self, payload: dict[str, object]) -> None:
            _ = payload

        def mirror_nautilus_paper_fill(self, payload: dict[str, object]) -> None:
            _ = payload

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


def test_native_strategy_fill_notifies_telegram_with_fill_payload() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class RecordingObservability:
        def __init__(self) -> None:
            self.fills: list[object] = []
            self.mirrors: list[dict[str, object]] = []
            self.notifications: list[dict[str, object]] = []

        def record_decision(self, decision, accepted: bool) -> None:
            _ = decision, accepted

        def record_rejected_decision(self, rejected: object) -> None:
            _ = rejected

        def record_nautilus_order_event(self, event: object) -> None:
            _ = event

        def record_nautilus_fill_event(self, event: object) -> None:
            self.fills.append(event)

        def record_nautilus_position(self, position: object) -> None:
            _ = position

        def mirror_nautilus_paper_fill(self, payload: dict[str, object]) -> None:
            self.mirrors.append(payload)

        def notify_nautilus_paper_fill(self, payload: dict[str, object]) -> None:
            self.notifications.append(payload)

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.order_factory = object()

    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token.POLYMARKET", "up-token", Side.UP),
            down=InstrumentTokenMeta("down-token.POLYMARKET", "down-token", Side.DOWN),
        )
    )
    observability = RecordingObservability()
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        observability=observability,
        registry=registry,
        sidecar=ExternalDataSidecar(),
    )
    strategy._approved_signal_metrics["client-1"] = {
        "fav_price": 0.5,
        "signal_id": "sig-fill-1",
    }

    strategy.on_order_filled(
        SimpleNamespace(
            order_id="order-1",
            client_order_id="client-1",
            market_id="btc-5m",
            condition_id="condition-btc-5m",
            token_id="up-token",
            side=Side.UP,
            last_qty=_FloatLike(10.0),
            last_px=_FloatLike(0.0),
            trade_id="trade-1",
            liquidity_side="TAKER",
            tags=[
                "strategy=ptb_diff",
                "condition_id=condition-btc-5m",
            ],
            ts_event=datetime.now(UTC),
        )
    )

    assert len(observability.fills) == 1
    expected_payload = {
        "strategy": "ptb_diff",
        "asset": "BTC",
        "timeframe": "5m",
        "market_id": "btc-5m",
        "market_slug": "btc-updown-5m",
        "condition_id": "condition-btc-5m",
        "token_id": "up-token",
        "side": "UP",
        "fill_price": 0.5,
        "shares": 10.0,
        "stake_usdc": 5.0,
        "signal_id": "sig-fill-1",
        "order_id": "order-1",
        "client_order_id": "client-1",
        "paper_fill_id": "trade-1",
        "liquidity_side": "TAKER",
        "metrics": {"fav_price": 0.5, "signal_id": "sig-fill-1", "fill_price": 0.5},
    }
    assert observability.mirrors == [expected_payload]
    assert observability.notifications == [expected_payload]


def test_native_strategy_vwap_passive_fill_skips_telegram_notification() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class RecordingObservability:
        def __init__(self) -> None:
            self.fills: list[object] = []
            self.mirrors: list[dict[str, object]] = []
            self.notifications: list[dict[str, object]] = []

        def record_decision(self, decision, accepted: bool) -> None:
            _ = decision, accepted

        def record_rejected_decision(self, rejected: object) -> None:
            _ = rejected

        def record_nautilus_order_event(self, event: object) -> None:
            _ = event

        def record_nautilus_fill_event(self, event: object) -> None:
            self.fills.append(event)

        def record_nautilus_position(self, position: object) -> None:
            _ = position

        def mirror_nautilus_paper_fill(self, payload: dict[str, object]) -> None:
            self.mirrors.append(payload)

        def notify_nautilus_paper_fill(self, payload: dict[str, object]) -> None:
            self.notifications.append(payload)

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self.order_factory = object()

    observability = RecordingObservability()
    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="vwap_momentum",
        observability=observability,
        **_native_projections(),
    )

    strategy.on_order_filled(
        SimpleNamespace(
            order_id="order-1",
            client_order_id="client-1",
            market_id="btc-5m",
            condition_id="condition-btc-5m",
            token_id="up-token",
            side=Side.UP,
            last_qty=10.0,
            last_px=0.5,
            trade_id="trade-1",
            liquidity_side="TAKER",
            tags=[
                "strategy=vwap_momentum",
                "condition_id=condition-btc-5m",
                "order_intent=passive_gtd",
            ],
            ts_event=datetime.now(UTC),
        )
    )

    assert len(observability.fills) == 1
    assert observability.mirrors == [
        {
            "strategy": "vwap_momentum",
            "asset": "",
            "timeframe": "",
            "market_id": "btc-5m",
            "market_slug": "",
            "condition_id": "condition-btc-5m",
            "token_id": "up-token",
            "side": "UP",
            "fill_price": 0.5,
            "shares": 10.0,
            "stake_usdc": 5.0,
            "signal_id": "",
            "order_id": "order-1",
            "client_order_id": "client-1",
            "paper_fill_id": "trade-1",
            "liquidity_side": "TAKER",
            "metrics": {"fill_price": 0.5, "order_intent": "passive_gtd"},
        }
    ]
    assert observability.notifications == []


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


def test_native_strategy_l1_prefers_quote_ticks_and_trade_ticks() -> None:
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

        def subscribe_order_book_deltas(self, **kwargs):
            self.subscribed_deltas.append(kwargs)

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        book_type="L1_MBP",
        **_native_projections(),
    )

    strategy._subscribe_market_instrument("up-token.POLYMARKET")

    assert strategy.subscribed_quotes == ["up-token.POLYMARKET"]
    assert strategy.subscribed_trades == ["up-token.POLYMARKET"]
    assert strategy.subscribed_deltas == []


def test_native_strategy_l1_uses_interval_book_when_quote_ticks_unavailable() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.cache = SimpleNamespace(instrument=lambda instrument_id: object())
            self.subscribed_interval_books: list[dict[str, object]] = []
            self.subscribed_trades: list[str] = []
            self.subscribed_deltas: list[str] = []

        def subscribe_order_book_at_interval(self, **kwargs):
            self.subscribed_interval_books.append(kwargs)

        def subscribe_trade_ticks(self, instrument_id):
            self.subscribed_trades.append(str(instrument_id))

        def subscribe_order_book_deltas(self, **kwargs):
            self.subscribed_deltas.append(kwargs)

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        book_type="L1_MBP",
        **_native_projections(),
    )

    strategy._subscribe_market_instrument("up-token.POLYMARKET")

    assert strategy.subscribed_interval_books == [
        {"instrument_id": "up-token.POLYMARKET", "interval_ms": 1000}
    ]
    assert strategy.subscribed_trades == ["up-token.POLYMARKET"]
    assert strategy.subscribed_deltas == []


def test_native_strategy_l1_raw_delta_fallback_is_visible() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    phases: list[str] = []

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.cache = SimpleNamespace(instrument=lambda instrument_id: object())
            self.subscribed_deltas: list[dict[str, object]] = []
            self.subscribed_trades: list[str] = []

        def subscribe_order_book_deltas(self, **kwargs):
            self.subscribed_deltas.append(kwargs)

        def subscribe_trade_ticks(self, instrument_id):
            self.subscribed_trades.append(str(instrument_id))

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        book_type="L1_MBP",
        progress_callback=phases.append,
        **_native_projections(),
    )

    strategy._subscribe_market_instrument("up-token.POLYMARKET")

    assert strategy.subscribed_deltas == [
        {"instrument_id": "up-token.POLYMARKET", "book_type": "L1_MBP"}
    ]
    assert strategy.subscribed_trades == ["up-token.POLYMARKET"]
    assert "l1_raw_delta_fallback" in phases


def test_native_strategy_l2_keeps_order_book_deltas_and_trade_ticks() -> None:
    from types import SimpleNamespace

    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.cache = SimpleNamespace(instrument=lambda instrument_id: object())
            self.subscribed_quotes: list[str] = []
            self.subscribed_trades: list[str] = []
            self.subscribed_deltas: list[dict[str, object]] = []

        def subscribe_quote_ticks(self, instrument_id):
            self.subscribed_quotes.append(str(instrument_id))

        def subscribe_trade_ticks(self, instrument_id):
            self.subscribed_trades.append(str(instrument_id))

        def subscribe_order_book_deltas(self, **kwargs):
            self.subscribed_deltas.append(kwargs)

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=_assembler(None),
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        book_type="L2_MBP",
        **_native_projections(),
    )

    strategy._subscribe_market_instrument("up-token.POLYMARKET")

    assert strategy.subscribed_quotes == []
    assert strategy.subscribed_deltas == [
        {"instrument_id": "up-token.POLYMARKET", "book_type": "L2_MBP"}
    ]
    assert strategy.subscribed_trades == ["up-token.POLYMARKET"]


def test_native_strategy_quote_tick_updates_token_book_and_evaluates() -> None:
    from types import SimpleNamespace
    from datetime import UTC, datetime
    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
    from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
    from polysignal_lab.nautilus_runtime.book_data import NautilusBookDataProvider
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token.POLYMARKET", "up-token", Side.UP),
            down=InstrumentTokenMeta("down-token.POLYMARKET", "down-token", Side.DOWN),
        )
    )
    books = NautilusBookDataProvider()
    assembler = MarketViewAssembler(
        registry=registry,
        books=books,
        sidecar=ExternalDataSidecar(),
    )

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.evaluated: list[str] = []

        def evaluate_condition(self, condition_id: str) -> None:
            self.evaluated.append(condition_id)
            super().evaluate_condition(condition_id)

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=assembler,
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        registry=registry,
        sidecar=ExternalDataSidecar(),
    )

    strategy.on_quote_tick(
        SimpleNamespace(
            instrument_id="up-token.POLYMARKET",
            bid_price=0.49,
            ask_price=0.51,
            bid_size=12.0,
            ask_size=13.0,
            ts_event=datetime.now(UTC),
        )
    )

    book = books.book_for_token("up-token")
    assert book is not None
    assert book.best_bid == 0.49
    assert book.best_ask == 0.51
    assert book.last_trade_price is None
    assert book.last_trade_size is None
    assert strategy.evaluated == ["condition-btc-5m"]


def test_native_strategy_order_book_snapshot_updates_token_book_and_evaluates() -> None:
    from types import SimpleNamespace
    from datetime import UTC, datetime
    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
        PolymarketMarketRegistry,
    )
    from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
    from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
    from polysignal_lab.nautilus_runtime.book_data import NautilusBookDataProvider
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy

    class FakeLevel:
        def __init__(self, price: float, size: float) -> None:
            self.price = price
            self.size = size

    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-5m",
            market_slug="btc-updown-5m",
            condition_id="condition-btc-5m",
            asset="BTC",
            timeframe="5m",
            start_ts=None,
            end_ts=None,
            up=InstrumentTokenMeta("up-token.POLYMARKET", "up-token", Side.UP),
            down=InstrumentTokenMeta("down-token.POLYMARKET", "down-token", Side.DOWN),
        )
    )
    books = NautilusBookDataProvider()
    assembler = MarketViewAssembler(
        registry=registry,
        books=books,
        sidecar=ExternalDataSidecar(),
    )

    class FakeNativeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.evaluated: list[str] = []

        def evaluate_condition(self, condition_id: str) -> None:
            self.evaluated.append(condition_id)
            super().evaluate_condition(condition_id)

    strategy = FakeNativeStrategy(
        core=FakeCore([]),
        assembler=assembler,
        condition_ids=("condition-btc-5m",),
        strategy_name="ptb_diff",
        registry=registry,
        sidecar=ExternalDataSidecar(),
    )

    strategy.on_order_book(
        SimpleNamespace(
            instrument_id="down-token.POLYMARKET",
            bids=[FakeLevel(0.47, 10.0)],
            asks=[FakeLevel(0.53, 11.0)],
            last_trade_price=0.52,
            last_trade_size=3.0,
            last_trade_timestamp=None,
            received_at=datetime.now(UTC),
        )
    )

    book = books.book_for_token("down-token")
    assert book is not None
    assert book.best_bid == 0.47
    assert book.best_ask == 0.53
    assert book.last_trade_price == 0.52
    assert book.last_trade_size == 3.0
    assert strategy.evaluated == ["condition-btc-5m"]


def test_native_strategy_l1_projection_preserves_vwap_momentum_decision_inputs() -> None:
    from types import SimpleNamespace

    from polysignal_lab.alpha.types import SpotView
    from polysignal_lab.alpha.vwap_momentum_core import VWAPMomentumAlphaCore
    from polysignal_lab.nautilus_bridge.external_data import ExternalDataSidecar
    from polysignal_lab.nautilus_bridge.market_registry import (
        InstrumentTokenMeta,
        MarketPairMeta,
    )
    from polysignal_lab.nautilus_bridge.market_view_assembler import MarketViewAssembler
    from polysignal_lab.nautilus_runtime.book_data import NautilusBookDataProvider
    from polysignal_lab.nautilus_runtime.native_strategy import PolySignalNativeStrategy
    from polysignal_lab.strategies.config import VWAPMomentumConfig

    now = datetime.now(UTC)
    start_ts = now - timedelta(seconds=500)
    end_ts = now + timedelta(seconds=400)

    registry = PolymarketMarketRegistry()
    registry.register(
        MarketPairMeta(
            market_id="btc-15m",
            market_slug="btc-updown-15m",
            condition_id="condition-btc-15m",
            asset="BTC",
            timeframe="15m",
            start_ts=start_ts,
            end_ts=end_ts,
            up=InstrumentTokenMeta("up-token.POLYMARKET", "up-token", Side.UP),
            down=InstrumentTokenMeta("down-token.POLYMARKET", "down-token", Side.DOWN),
        )
    )

    sidecar = ExternalDataSidecar()
    sidecar.update_spot(
        SpotView(
            asset="BTC",
            symbol="BTCUSD",
            price=100000.0,
            source="polymarket_rtds",
            freshness_ms=10,
        )
    )
    sidecar.update_price_to_beat(
        condition_id="condition-btc-15m",
        value=99950.0,
        source="anchor",
        verified=True,
        from_anchor_service=True,
        anchor_source="chainlink",
        anchor_lag_ms=5,
    )

    books = NautilusBookDataProvider()
    assembler = MarketViewAssembler(
        registry=registry,
        books=books,
        sidecar=sidecar,
    )

    config = VWAPMomentumConfig(
        assets=["BTC"],
        timeframes=["15m"],
        min_price=0.35,
        max_price=0.85,
        min_elapsed_sec=45,
        no_entry_before_end_sec=20,
        vwap_window_sec=30,
        momentum_window_sec=60,
        min_deviation_pct=0.01,
        max_deviation_pct=1.0,
        min_momentum=0.01,
    )

    class FakeStrategy(PolySignalNativeStrategy):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.evaluated: list[str] = []

        def evaluate_condition(self, condition_id: str) -> None:
            self.evaluated.append(condition_id)

    strategy = FakeStrategy(
        core=FakeCore([]),
        assembler=assembler,
        condition_ids=("condition-btc-15m",),
        strategy_name="vwap_momentum",
        registry=registry,
        sidecar=sidecar,
    )

    # Feed L1 quote ticks for both tokens to establish the shared books
    strategy.on_quote_tick(
        SimpleNamespace(
            instrument_id="up-token.POLYMARKET",
            bid_price=0.48,
            ask_price=0.52,
            bid_size=10.0,
            ask_size=10.0,
            ts_event=now - timedelta(seconds=120),
        )
    )
    strategy.on_quote_tick(
        SimpleNamespace(
            instrument_id="down-token.POLYMARKET",
            bid_price=0.47,
            ask_price=0.53,
            bid_size=10.0,
            ask_size=11.0,
            ts_event=now - timedelta(seconds=120),
        )
    )

    # Feed L1 trade ticks for down-token to seed VWAP history
    # Trade within momentum band around now-60s
    strategy.on_trade_tick(
        SimpleNamespace(
            instrument_id="down-token.POLYMARKET",
            price=0.45,
            size=5.0,
            aggressor_side="SELLER",
            ts_event=now - timedelta(seconds=60),
        )
    )
    # Trade within VWAP window at now-25s
    strategy.on_trade_tick(
        SimpleNamespace(
            instrument_id="down-token.POLYMARKET",
            price=0.48,
            size=5.0,
            aggressor_side="BUYER",
            ts_event=now - timedelta(seconds=25),
        )
    )
    # Latest trade sets latest_price=0.55 for down-token
    strategy.on_trade_tick(
        SimpleNamespace(
            instrument_id="down-token.POLYMARKET",
            price=0.55,
            size=3.0,
            aggressor_side="BUYER",
            ts_event=now,
        )
    )

    # Verify the strategy routed all L1 ticks through evaluate_condition
    assert len(strategy.evaluated) == 5

    # Build the view from shared data fed via L1 callbacks
    view = assembler.build("condition-btc-15m", created_at=now)
    assert view is not None, "MarketView should be buildable after feeding L1 data"

    # Evaluate with a fresh VWAPMomentumAlphaCore so its TradeHistory
    # reflects only the data in this view (not any intermediate pushes
    # from the strategy's own evaluate_condition routing).
    fresh_core = VWAPMomentumAlphaCore(config)
    decisions = fresh_core.evaluate(view)

    assert len(decisions) > 0, (
        "VWAPMomentumAlphaCore should produce decisions from "
        "a MarketView assembled purely from L1 data"
    )

    decision = decisions[0]
    assert decision.strategy == "vwap_momentum"
    assert decision.condition_id == "condition-btc-15m"
    assert decision.token_id == "down-token"
    assert decision.side == Side.DOWN
    assert "VWAP_DEVIATION_OK" in decision.reason_codes
    assert "MOMENTUM_OK" in decision.reason_codes
